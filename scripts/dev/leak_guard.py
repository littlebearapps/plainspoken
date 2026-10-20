"""Fail if any file contains a private or client term from the denylist.

The denylist has two parts. ``data/leak-denylist.txt`` (tracked) keeps format comments and generic patterns that
name nothing. The private list, with the names, lives outside the repo, in the file named by
``PLAINSPOKEN_LEAK_LIST`` (locally ``~/.config/plainspoken/leak-denylist.txt``, mode 600; in CI the secret of the
same name, written to ``$RUNNER_TEMP``). Both use the same line formats. A hit from the private list is labelled
``private#<line>`` (its line in that file), never by the term, so a public CI log can't show it.

On the owner's repo CI fails when the private list isn't configured; a fork, a pull request from a fork or a
local run skips it with one notice line and exits by the rest.

A name can also be stored as a keyed hash, ``hmac:<words>:<hex>`` (HMAC-SHA256 of the normalised name), so it
never sits anywhere in plaintext and nobody without the key can confirm a guessed name. The key comes from
``PLAINSPOKEN_LEAK_KEY`` (the CI secret) or an untracked, git-ignored ``.leak-guard-key`` at the root. Older
``sha256:<words>:<hex>`` lines are unkeyed; they still match.

Without the key the keyed entries can't be checked, so the guard never reports green: a local run ends on a
``SKIPPED (no key)`` line (exit 0, or 1 if the rest found a hit). CI on the owner's repo fails instead; a fork's
CI, or a pull request from a fork, skips and says so. With no keyed entries in either list no key is needed. A
wrong key fails the ``hmac-key-check:`` line, which either list may carry.

Git-ignored files (local eval output) aren't scanned: they can't be committed by accident.

    python3 -m scripts.dev.leak_guard [ROOT]           # scan (default: .)
    python3 -m scripts.dev.leak_guard --hash "Name"    # the hmac: line for a new name (needs the key)
    python3 -m scripts.dev.leak_guard --convert "Name" # replace Name's old sha256: line (either list) with hmac:
    python3 -m scripts.dev.leak_guard --convert -      # the same, the name read from stdin (no echo at a terminal)
    python3 -m scripts.dev.leak_guard --key-check      # the hmac-key-check: line for this key

A TERM of ``-`` reads the name from stdin, so it stays out of shell history and ``ps``.

Rotating the key means re-hashing every name with the new key and replacing the key-check line.
"""
from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ALLOW_PATHS = ("data/leak-denylist.txt", ".github/CODEOWNERS")
ALLOW_PREFIXES = ("tests/fixtures/leak/", ".git/")
ALLOW_MARKER = "leak-guard: allow"
OWNER_REPO = "littlebearapps/plainspoken"
KEY_ENV = "PLAINSPOKEN_LEAK_KEY"
LIST_ENV = "PLAINSPOKEN_LEAK_LIST"
REPO_LIST = "data/leak-denylist.txt"
PRIVATE_WHERE = "the private list"
KEY_FILE = ".leak-guard-key"
KEY_CHECK_TEXT = "plainspoken leak guard key check"
USAGE = f"""usage: python3 -m scripts.dev.leak_guard [ROOT]
       python3 -m scripts.dev.leak_guard --hash "Some Name"
       python3 -m scripts.dev.leak_guard --convert "Some Name"
       python3 -m scripts.dev.leak_guard --key-check

Scan ROOT (default .) for terms in {REPO_LIST} and the private list (the file named by {LIST_ENV}).
Keyed entries need the key in {KEY_ENV} or {KEY_FILE}.
  --hash TERM     print the hmac: denylist line for TERM (needs the key)
  --convert TERM  replace TERM's old sha256: line with its hmac: line, in place, in either list (needs the key)
  TERM -          --hash and --convert read the term from stdin (no echo at a terminal), keeping it out
                  of shell history and ps: e.g. --convert -
  --key-check     print the hmac-key-check: line for the key
  -h, --help      show this help"""
# A word keeps internal . - ' & (so a domain, a hyphenated name or O'Brien is one token); edge punctuation is dropped.
TOKEN_RE = re.compile(r"[^\W_]+(?:[.\-'’&][^\W_]+)*")
_PIECE_RE = re.compile(r"[^\W_]+")
_HASHED_RE = re.compile(r"(sha256|hmac):([1-9][0-9]*):([0-9a-f]{64})")
_KEY_CHECK_RE = re.compile(r"hmac-key-check:([0-9a-f]{64})")


class GuardError(ValueError):
    """The guard couldn't check (unreadable list, key or file): never a green result."""


@dataclass(frozen=True)
class Term:
    label: str
    pattern: re.Pattern[str]
    origin: str = "repo"  # "repo" (the tracked list) or "private"
    index: int = 0  # the entry's line in its list


@dataclass(frozen=True)
class HashedTerm:
    label: str
    words: int
    digest: str
    keyed: bool = False
    origin: str = "repo"
    index: int = 0


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    term: str


@dataclass(frozen=True)
class Denylist:
    terms: list[Term | HashedTerm]
    key_check: str | None
    private_missing: str | None = None  # why the private list wasn't loaded; None when it was


def normalise(term: str) -> str:
    return " ".join(term.replace("’", "'").casefold().split())


def _digest(norm: str, key: bytes | None = None) -> str:
    if key is None:
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()
    return hmac.new(key, norm.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_line(term: str, key: bytes | None = None) -> str:
    """The denylist line for term: ``hmac:`` with a key, the old unkeyed ``sha256:`` without."""
    norm = normalise(term)
    return f"{'sha256' if key is None else 'hmac'}:{len(norm.split())}:{_digest(norm, key)}"


def key_check_line(key: bytes) -> str:
    return f"hmac-key-check:{_digest(KEY_CHECK_TEXT, key)}"


def _parse(lines: list[str], origin: str, where: str) -> tuple[list[Term | HashedTerm], str | None]:
    """Terms and key-check digest from one list. A private entry's label is ``private#<line>``, and no error
    quotes a line, so nothing from the private list reaches a log."""
    private = origin == "private"
    terms: list[Term | HashedTerm] = []
    key_check: str | None = None
    for lineno, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        label = f"private#{lineno}" if private else s
        if s.startswith("hmac-key-check:"):
            m = _KEY_CHECK_RE.fullmatch(s)
            if not m or key_check is not None:
                raise GuardError(f"{where}:{lineno}: malformed or repeated hmac-key-check: line")
            key_check = m.group(1)
        elif s.startswith(("sha256:", "hmac:")):
            m = _HASHED_RE.fullmatch(s)
            if not m:
                raise GuardError(f"{where}:{lineno}: malformed {s.split(':', 1)[0]}: line")
            kind, words, digest = m.groups()
            terms.append(HashedTerm(label if private else f"{kind}:{digest[:12]}", int(words), digest,
                                    kind == "hmac", origin, lineno))
        elif s.startswith("regex:"):
            try:
                terms.append(Term(label, re.compile(s[len("regex:"):]), origin, lineno))
            except re.error as e:
                # re.error's text can quote the pattern (a group name, an escape), so a private line gets only
                # the position.
                detail = f"at position {e.pos}" if private else str(e)
                raise GuardError(f"{where}:{lineno}: bad regex ({detail})") from e
        else:
            pat = r"\s+".join(map(re.escape, s.split()))
            terms.append(Term(label, re.compile(pat, re.IGNORECASE), origin, lineno))
    return terms, key_check


def _private_path(env: Mapping[str, str]) -> Path | None:
    value = env.get(LIST_ENV, "").strip()
    return Path(value).expanduser() if value else None


def _read_private(env: Mapping[str, str]) -> tuple[list[str] | None, str | None]:
    """(the private list's lines, None), or (None, why it isn't configured). Never names the file's path."""
    path = _private_path(env)
    if path is None:
        return None, f"{LIST_ENV} is not set"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return None, f"can't read the file {LIST_ENV} names ({type(e).__name__})"
    lines = text.splitlines()
    # CI writes an empty file when the secret is missing; a list of only comments checks nothing either.
    if not any(s.strip() and not s.strip().startswith("#") for s in lines):
        return None, f"the file {LIST_ENV} names has no entries"
    return lines, None


def load_denylist(root: str, env: Mapping[str, str] | None = None) -> Denylist:
    """The tracked list plus the private list (the file in PLAINSPOKEN_LEAK_LIST, when it's configured)."""
    env = os.environ if env is None else env
    path = Path(root) / REPO_LIST
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise GuardError(f"can't read {REPO_LIST} ({type(e).__name__})") from e
    terms, key_check = _parse(lines, "repo", "leak-denylist.txt")
    private_lines, private_missing = _read_private(env)
    if private_lines is not None:
        private_terms, private_check = _parse(private_lines, "private", PRIVATE_WHERE)
        terms += private_terms
        if key_check is not None and private_check is not None and key_check != private_check:
            raise GuardError(f"{REPO_LIST} and {PRIVATE_WHERE} carry different hmac-key-check: lines")
        key_check = key_check or private_check
    if key_check is None and any(isinstance(t, HashedTerm) and t.keyed for t in terms):
        # Without the check a wrong key matches nothing and the run would look clean.
        raise GuardError("the denylist has hmac: entries but neither list has an hmac-key-check: line, so no key "
                         "can be verified")
    return Denylist(terms, key_check, private_missing)


def load_terms(root: str, env: Mapping[str, str] | None = None) -> list[Term | HashedTerm]:
    return load_denylist(root, env).terms


def load_key(root: str, env: Mapping[str, str]) -> bytes | None:
    """The key from the environment (an empty value, as CI gives for a missing secret, counts as none), else the
    untracked key file. None when neither has one; GuardError when the file is there but unusable."""
    value = env.get(KEY_ENV, "").strip()
    if value:
        return value.encode("utf-8")
    path = Path(root) / KEY_FILE
    if not path.exists():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as e:
        raise GuardError(f"can't read {KEY_FILE} ({type(e).__name__})") from e
    if not value:
        raise GuardError(f"{KEY_FILE} is empty")
    return value.encode("utf-8")


def _pr_head_repo(event_path: str | None) -> str | None:
    if not event_path:
        return None
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        return event["pull_request"]["head"]["repo"]["full_name"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def missing_secret_reason(env: Mapping[str, str], secret: str, local_hint: str) -> str | None:
    """None when a missing secret must fail (CI on the owner's repo); otherwise why skipping is all right."""
    if env.get("GITHUB_ACTIONS") != "true":
        return f"a local run; {local_hint}"
    repo = env.get("GITHUB_REPOSITORY", "")
    if repo != OWNER_REPO:
        return f"CI on a fork ({repo or 'unknown repo'}) has no {secret} secret"
    if env.get("GITHUB_EVENT_NAME", "").startswith("pull_request"):
        head = _pr_head_repo(env.get("GITHUB_EVENT_PATH"))
        if head is not None and head != repo:
            return f"a pull request from a fork ({head}) gets no {secret} secret"
    return None


def missing_key_reason(env: Mapping[str, str]) -> str | None:
    return missing_secret_reason(env, KEY_ENV, f"set {KEY_ENV} or put the key in {KEY_FILE}")


def missing_list_reason(env: Mapping[str, str]) -> str | None:
    return missing_secret_reason(env, LIST_ENV, f"set {LIST_ENV} to the private list's path")


def _spans(token: str, from_start: bool, to_end: bool) -> set[str]:
    """Casefolded runs of a token's alphanumeric pieces (a possessive's stem, a domain inside a host name).

    A run containing hyphens is also offered with them read as spaces, so a slug matches a multi-word name.
    """
    pieces = [(m.start(), m.end()) for m in _PIECE_RE.finditer(token)]
    starts = [0] if from_start else range(len(pieces))
    out: set[str] = set()
    for i in starts:
        ends = [len(pieces) - 1] if to_end else range(i, len(pieces))
        for j in ends:
            if j < i:
                continue
            run = token[pieces[i][0]:pieces[j][1]].replace("’", "'").casefold()
            out.add(run)
            if "-" in run:
                out.add(run.replace("-", " "))
    return out


def _hashed_matches(
    text: str, hashed: list[HashedTerm], key: bytes | None = None
) -> list[tuple[int, HashedTerm]]:
    """Return (offset of the first token, term) for every hashed term found in text. Keyed terms need the key."""
    hashed = [t for t in hashed if not t.keyed or key is not None]
    if not hashed:
        return []
    plain = {(t.words, t.digest): t for t in hashed if not t.keyed}
    keyed = {(t.words, t.digest): t for t in hashed if t.keyed}
    max_n = max(t.words for t in hashed)
    tokens = [(m.start(), m.group()) for m in TOKEN_RE.finditer(text)]
    found: dict[tuple[int, str], HashedTerm] = {}
    for i, (offset, first) in enumerate(tokens):
        for n in range(1, min(max_n, len(tokens) - i) + 1):
            if n == 1:
                candidates = _spans(first, False, False)
            else:
                middle = [w.replace("’", "'").casefold() for _, w in tokens[i + 1:i + n - 1]]
                lasts = _spans(tokens[i + n - 1][1], True, False)
                candidates = {" ".join([f, *middle, last]) for f in _spans(first, False, True) for last in lasts}
            for c in candidates:
                words = c.count(" ") + 1
                t = plain.get((words, _digest(c))) if plain else None
                if t is None and keyed:
                    t = keyed.get((words, _digest(c, key)))
                if t is not None:
                    found[(offset, t.digest)] = t
    return sorted(((off, t) for (off, _), t in found.items()), key=lambda x: (x[0], x[1].label))


def list_files(base: Path) -> tuple[list[Path], bool]:
    """(files to scan, whether git chose them). When base is the top of a git work tree that's tracked files plus
    untracked ones that aren't ignored; anywhere else (no repo, a subfolder, a folder an enclosing repo ignores)
    every file."""
    def run(*args: str) -> bytes:
        return subprocess.run(["git", "-C", str(base), *args], capture_output=True, check=True, timeout=120).stdout

    try:
        top = Path(run("rev-parse", "--show-toplevel").decode("utf-8", errors="surrogateescape").strip())
        if top.resolve() != base.resolve():
            raise subprocess.SubprocessError("not the top of a work tree")
        out = subprocess.run(
            ["git", "-C", str(base), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True, timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return sorted(p for p in base.rglob("*") if p.is_file()), False
    names = {n for n in out.decode("utf-8", errors="surrogateescape").split("\0") if n}
    return sorted(p for p in (base / n for n in names) if p.is_file()), True


def scan(root: str, terms: list[Term | HashedTerm], key: bytes | None = None) -> tuple[list[Hit], list[Hit]]:
    """Return (hits, suppressed). A suppressed hit has the allow marker on its start line.

    Keyed entries are checked only with the key. An unreadable file raises GuardError."""
    hashed = [t for t in terms if isinstance(t, HashedTerm)]
    terms = [t for t in terms if isinstance(t, Term)]
    base = Path(root)
    hits: list[Hit] = []
    suppressed: list[Hit] = []
    files = [(f, f.relative_to(base).as_posix()) for f in list_files(base)[0]]
    files = [(f, rel) for f, rel in files if not (rel in ALLOW_PATHS or rel.startswith(ALLOW_PREFIXES))]
    if not files:  # after the allow-list: a root it empties checked nothing, so it's never green
        raise GuardError(f"no files to scan under {root}")
    for f, rel in files:
        for t in terms:
            if t.pattern.search(rel):
                hits.append(Hit(rel, 0, t.label))
        for _, ht in _hashed_matches(rel, hashed, key):
            hits.append(Hit(rel, 0, ht.label))
        try:
            data = f.read_bytes()
        except OSError as e:
            raise GuardError(f"can't read {rel} ({type(e).__name__})") from e
        if b"\x00" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        matches = [(m.start(), t.label) for t in terms for m in t.pattern.finditer(text)]
        matches += [(off, ht.label) for off, ht in _hashed_matches(text, hashed, key)]
        for start, label in matches:
            n = text.count("\n", 0, start)
            hit = Hit(rel, n + 1, label)
            if n < len(lines) and ALLOW_MARKER in lines[n]:
                suppressed.append(hit)
            else:
                hits.append(hit)
    key = lambda h: (h.path, h.line, h.term)  # noqa: E731
    return sorted(hits, key=key), sorted(suppressed, key=key)


def _entries(n: int) -> str:
    return f"{n} keyed {'entry' if n == 1 else 'entries'}"


def main(root: str, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    try:
        if not Path(root).is_dir():
            raise GuardError(f"no such folder {root}")
        deny = load_denylist(root, env)
        key = load_key(root, env)
        if key is not None:
            _check_key(key, deny.key_check)
        hits, suppressed = scan(root, deny.terms, key)
    except GuardError as e:
        print(f"leak-guard: FAILED, nothing reported as clean: {e}")
        return 2
    for h in hits:
        print(f"{h.path}:{h.line}: denylisted term '{h.term}'")
    for h in suppressed:
        print(f"{h.path}:{h.line}: suppressed by {ALLOW_MARKER}")
    # Every part that wasn't checked gets its own line, so a skipped run never ends on a bare count.
    notes: list[tuple[bool, str]] = []  # (fails the run, line)
    if deny.private_missing is not None:
        reason = missing_list_reason(env)
        if reason is None:
            notes.append((True, f"FAILED (no private list): private leak list not configured "
                                f"({deny.private_missing}). Set the {LIST_ENV} secret on {OWNER_REPO}."))
        else:
            notes.append((False, f"SKIPPED (no private list): private leak list not configured, so its entries "
                                 f"weren't checked ({reason})."))
    n_keyed = sum(1 for t in deny.terms if isinstance(t, HashedTerm) and t.keyed)
    if key is None and n_keyed:
        reason = missing_key_reason(env)
        if reason is None:
            notes.append((True, f"FAILED (no key): {KEY_ENV} is empty, so {_entries(n_keyed)} weren't checked. "
                                f"Set the {KEY_ENV} secret on {OWNER_REPO}."))
        else:
            notes.append((False, f"SKIPPED (no key): {_entries(n_keyed)} not checked ({reason})."))
    counts = f"{len(hits)} hit(s), {len(suppressed)} suppressed"
    if not notes:
        print(f"leak-guard: {counts}")
        return 1 if hits else 0
    for i, (_, line) in enumerate(notes, 1):
        print(f"leak-guard: {line}" + (f" The rest: {counts}" if i == len(notes) else ""))
    return 1 if hits or any(fails for fails, _ in notes) else 0


def _check_key(key: bytes, key_check: str | None) -> None:
    if key_check is not None and not hmac.compare_digest(_digest(KEY_CHECK_TEXT, key), key_check):
        raise GuardError("the key fails the denylist's key check (hmac-key-check:): a wrong or old key")


def convert(root: str, term: str, key: bytes, env: Mapping[str, str] | None = None) -> tuple[str, int] | None:
    """Replace the sha256: line for term with its hmac: line, in place, in whichever list has it (the tracked one
    first). Return (which list, line number), or None."""
    env = os.environ if env is None else env
    _check_key(key, load_denylist(root, env).key_check)
    old = hash_line(term)
    lists = [(REPO_LIST, Path(root) / REPO_LIST)]
    private = _private_path(env)
    if private is not None:
        lists.append((PRIVATE_WHERE, private))
    for name, path in lists:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.strip() == old:
                lines[i] = line.replace(old, hash_line(term, key))
                path.write_text("".join(lines), encoding="utf-8")
                return name, i + 1
    return None


def _read_term() -> str:
    """The term for `-`: a terminal prompts without echo (getpass); a pipe gives its first line. Never printed."""
    if sys.stdin.isatty():
        try:
            return getpass.getpass("term (not echoed): ")
        except (EOFError, KeyboardInterrupt):
            return ""
    return (sys.stdin.readline() or "").rstrip("\r\n")


def cli(argv: list[str], env: Mapping[str, str] | None = None, key_root: str = ".") -> int:
    """key_root is the repo root that --hash, --key-check and --convert use (the working folder)."""
    env = os.environ if env is None else env
    if argv and argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    if argv and argv[0] in ("--hash", "--key-check", "--convert"):
        try:
            key = load_key(key_root, env)
            # --key-check skips the list's check: rotating the key needs the new key's line.
            if key is not None and argv[0] != "--key-check":
                # A keyed line made under an unverified key would never match: insist on the list's check line.
                key_check = load_denylist(key_root, env).key_check
                if key_check is None:
                    raise GuardError(f"neither {REPO_LIST} nor {PRIVATE_WHERE} ({LIST_ENV}) has an "
                                     "hmac-key-check: line to verify the key against")
                _check_key(key, key_check)
        except GuardError as e:
            print(f"leak-guard: FAILED: {e}")
            return 2
        if key is None:
            print(f"leak-guard: {argv[0]} needs the key (no key in {KEY_ENV} or {KEY_FILE})")
            return 2
        if argv[0] == "--key-check":
            print(key_check_line(key))
            return 0
        term = _read_term() if len(argv) >= 2 and argv[1] == "-" else (argv[1] if len(argv) >= 2 else "")
        if not term.strip():
            print(f'leak-guard: {argv[0]} needs a term, e.g. {argv[0]} "Some Name" (or {argv[0]} - to read '
                  f'it from stdin)')
            return 2
        norm = normalise(term)
        if " ".join(TOKEN_RE.findall(norm)) != norm:
            print(f"leak-guard: {argv[0]} term must be plain words (letters, digits and internal . - ' &)")
            return 2
        if argv[0] == "--hash":
            print(hash_line(term, key))
            return 0
        try:
            found = convert(key_root, term, key, env)
        except GuardError as e:
            print(f"leak-guard: FAILED: {e}")
            return 2
        except (OSError, UnicodeDecodeError) as e:
            # The OSError text names the file, which may be the private list's path.
            errno = f" errno {e.errno}" if isinstance(e, OSError) and e.errno else ""
            print(f"leak-guard: FAILED: can't update a denylist ({type(e).__name__}{errno})")
            return 2
        if found is None:
            print("leak-guard: no sha256: entry matches that term; nothing changed")
            return 1
        print(f"leak-guard: converted {found[0]} line {found[1]} to hmac:")
        return 0
    if argv and argv[0].startswith("-"):
        print(f"leak-guard: unknown option {argv[0]}\n{USAGE}")
        return 2
    return main(argv[0] if argv else ".", env)


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
