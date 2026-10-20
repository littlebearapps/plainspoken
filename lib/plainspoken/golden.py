"""The golden set: labelled cases the judges are measured against (Phase 6 evals).

One TOML file per group (`evals/golden/J1.toml` … `J4.toml`, `JR.toml`), each `schema = 1`, `group = "<G>"` and
`[[case]]` tables. `load` reads and type-checks the files (a malformed file raises GoldenError naming the file, the
case and the key); `validate` checks what the cases say (ids, rules, labels, provenance, JR evidence) and, with
`require_counts`, that every group is big and balanced enough to measure; `heldout_leaks` proves no case text is
quoted in the files a model sees (rubrics, skills, guides, hooks, briefs). Format: evals/golden/README.md."""
import os
import re
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from plainspoken import justify
from plainspoken.doc import CONTENT_TYPES, split_lines
from plainspoken.registry import load_config

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = PLUGIN_ROOT / "evals" / "golden"
HELDOUT_ROOTS = ("data", "agents", "skills", "guides", "hooks", "output-styles", "templates", "evals/briefs")
SCHEMA = 1
GROUPS = ("J1", "J2", "J3", "J4", "JR")
LABELS = {**{g: ("fail", "pass") for g in GROUPS[:4]}, "JR": ("accept", "reject")}
STATUSES = ("confirmed", "endorsed", "provisional")
SOURCE_FOR_STATUS = {"confirmed": "owner", "endorsed": "owner-endorsed", "provisional": "constructed"}
ID_RE = re.compile(r"(J[1-4]|JR)-[A-Za-z0-9_]+(-[A-Za-z0-9_]+)?-\d{3}")  # used with fullmatch
MAX_TEXT = 4000
MAX_ORIGIN = 160
MIN_CASES = 30
MIN_PER_LABEL = 10
SHINGLE = 8

_CASE_KEYS = ("id", "rule", "label", "content_type", "source", "status", "origin", "text")
_JR_KEYS = ("kind", "reason", "evidence")
_WORD = re.compile(r"\w+")


class GoldenError(ValueError):
    """A golden file that can't be read as the format: names the file, the case and the key."""


@dataclass(frozen=True)
class GoldenCase:
    """One labelled case. Hashable: `evidence` (dicts) stays out of the hash, so a JR case can key a dict or sit
    in a set like any other."""
    id: str
    group: str
    rule: str
    label: str
    text: str
    content_type: str
    source: str
    status: str
    origin: str
    kind: str | None = None
    reason: str | None = None
    evidence: tuple[dict, ...] = field(default=(), hash=False)
    file: str = ""  # the file name the case came from, for problem lines


def _case_name(item: dict, n: int) -> str:
    cid = item.get("id")
    return cid if isinstance(cid, str) and cid else f"case #{n}"


def _load_file(path: Path) -> list[GoldenCase]:
    name = path.name
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise GoldenError(f"{name}: can't read: {(str(e).splitlines() or [type(e).__name__])[0]}") from None
    if type(raw.get("schema")) is not int or raw["schema"] != SCHEMA:  # `true == 1`, so check the type first
        raise GoldenError(f"{name}: schema must be {SCHEMA}, got {raw.get('schema')!r}")
    group = raw.get("group")
    if group not in GROUPS:
        raise GoldenError(f"{name}: group must be one of {', '.join(GROUPS)}, got {group!r}")
    extra = sorted(set(raw) - {"schema", "group", "case"})
    if extra:
        raise GoldenError(f"{name}: unknown top-level key(s) {', '.join(extra)}")
    items = raw.get("case", [])
    if not isinstance(items, list):
        raise GoldenError(f"{name}: 'case' must be an array of tables ([[case]])")
    allowed = set(_CASE_KEYS) | (set(_JR_KEYS) if group == "JR" else set())
    required = _CASE_KEYS + (_JR_KEYS if group == "JR" else ())
    cases = []
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise GoldenError(f"{name}: case #{n}: not a table")
        where = f"{name}: {_case_name(item, n)}"
        for key in sorted(set(item) - allowed):
            why = "only JR cases carry it" if key in _JR_KEYS else "unknown key"
            raise GoldenError(f"{where}: {key}: {why}")
        for key in required:
            if key not in item:
                raise GoldenError(f"{where}: {key}: missing key")
            if key != "evidence" and not isinstance(item[key], str):
                raise GoldenError(f"{where}: {key}: must be a string")
        evidence: tuple[dict, ...] = ()
        if group == "JR":
            ev = item["evidence"]
            if not isinstance(ev, list):
                raise GoldenError(f"{where}: evidence: must be an array of {{line, quote}} tables")
            for e in ev:
                if (not isinstance(e, dict) or set(e) != {"line", "quote"} or type(e["line"]) is not int
                        or not isinstance(e["quote"], str)):
                    raise GoldenError(f"{where}: evidence: each item is {{line = <integer>, quote = \"…\"}}")
            evidence = tuple(dict(e) for e in ev)
        cases.append(GoldenCase(id=item["id"], group=group, rule=item["rule"], label=item["label"],
                                text=item["text"], content_type=item["content_type"], source=item["source"],
                                status=item["status"], origin=item["origin"], kind=item.get("kind"),
                                reason=item.get("reason"), evidence=evidence, file=name))
    return cases


def load(dir: Path) -> list[GoldenCase]:
    """Every case in `dir/*.toml`, files in name order. Raises GoldenError for a missing folder, no files, or a
    file that isn't the format (what the cases say is `validate`'s job)."""
    d = Path(dir)
    if not d.is_dir():
        raise GoldenError(f"{d}: no such folder")
    files = sorted(d.glob("*.toml"))
    if not files:
        raise GoldenError(f"{d}: no golden files (*.toml)")
    return [c for f in files for c in _load_file(f)]


def _case_problems(c: GoldenCase, rules: dict) -> list[str]:
    out = []
    if not ID_RE.fullmatch(c.id):
        out.append("id must look like <group>-<rule>[-<tag>]-NNN")
    elif c.id.split("-", 1)[0] != c.group:
        out.append(f"id prefix doesn't match group {c.group}")
    rule = rules.get(c.rule)
    if rule is None:
        out.append(f"rule {c.rule!r} isn't in the ruleset")
    elif c.group != "JR" and rule.group != c.group:
        out.append(f"rule {c.rule} belongs to {rule.group or 'no judge group'}, not {c.group}")
    if c.label not in LABELS[c.group]:
        out.append(f"label {c.label!r} must be {' or '.join(LABELS[c.group])} in {c.group}")
    if c.content_type not in CONTENT_TYPES:
        out.append(f"content_type {c.content_type!r} must be one of {', '.join(CONTENT_TYPES)}")
    if c.status not in STATUSES:
        out.append(f"status {c.status!r} must be one of {', '.join(STATUSES)}")
    elif c.source != SOURCE_FOR_STATUS[c.status]:
        out.append(f"status {c.status} needs source = \"{SOURCE_FOR_STATUS[c.status]}\", got {c.source!r}")
    if not c.origin.strip() or len(c.origin) > MAX_ORIGIN or "\n" in c.origin:
        out.append(f"origin must be one line of 1–{MAX_ORIGIN} characters")
    if not c.text.strip() or len(c.text) > MAX_TEXT:
        out.append(f"text must be 1–{MAX_TEXT} characters (got {len(c.text)})")
    if c.group == "JR":
        if c.kind not in justify.KINDS:
            out.append(f"kind {c.kind!r} must be one of {', '.join(justify.KINDS)}")
        if not (c.reason or "").strip():
            out.append("reason is empty")
        if not c.evidence:
            out.append("evidence needs at least one {line, quote}")
        lines = split_lines(c.text)  # numbered as the lint numbers them
        for e in c.evidence:
            line, quote = e["line"], e["quote"]
            if not 1 <= line <= len(lines):
                out.append(f"evidence line {line} is outside the text (1–{len(lines)})")
            elif not quote or quote not in lines[line - 1]:
                out.append(f"evidence quote {quote!r} isn't on line {line}")
    return out


def counts(cases: list[GoldenCase]) -> dict[str, dict]:
    """Per group, in GROUPS order (groups with no cases left out): cases, each label, each status."""
    out: dict[str, dict] = {}
    for g in GROUPS:
        mine = [c for c in cases if c.group == g]
        if not mine:
            continue
        row = {"cases": len(mine)}
        row.update({lab: sum(c.label == lab for c in mine) for lab in LABELS[g]})
        row.update({s: sum(c.status == s for c in mine) for s in STATUSES})
        out[g] = row
    return out


def count_line(group: str, row: dict) -> str:
    n = row["cases"]
    parts = [f"{k} {row[k]}" for k in (*LABELS[group], *STATUSES)]
    return f"{group} {n} case{'' if n == 1 else 's'}: " + " · ".join(parts)


def validate(cases: list[GoldenCase], *, require_counts: bool, cfg=None) -> list[str]:
    """Problem lines, `<file>: <case id>: <what>` (empty = valid). With `require_counts`, also every group needs
    at least MIN_CASES cases and MIN_PER_LABEL of each label."""
    rules = (cfg or load_config()).rules
    problems: list[str] = []
    first_seen: dict[str, str] = {}
    for c in cases:
        if c.id in first_seen:
            problems.append(f"{first_seen[c.id]}: {c.id}: duplicate id (also in {c.file})")
        else:
            first_seen[c.id] = c.file
        problems += [f"{c.file}: {c.id}: {p}" for p in _case_problems(c, rules)]
    if require_counts:
        have = counts(cases)
        for g in GROUPS:
            row = have.get(g)
            if row is None:
                problems.append(f"{g}: no cases (need at least {MIN_CASES}, {MIN_PER_LABEL} of each label)")
                continue
            if row["cases"] < MIN_CASES:
                problems.append(f"{g}: {row['cases']} cases (need at least {MIN_CASES})")
            for lab in LABELS[g]:
                if row[lab] < MIN_PER_LABEL:
                    problems.append(f"{g}: {row[lab]} {lab} cases (need at least {MIN_PER_LABEL})")
    return problems


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _shingles(text: str, size: int = SHINGLE) -> set[tuple[str, ...]]:
    w = _words(text)
    return {tuple(w[i:i + size]) for i in range(len(w) - size + 1)}


def _case_shingles(text: str) -> set[tuple[str, ...]]:
    """A case's SHINGLE-word runs; a text shorter than SHINGLE words is one run of all its words, so a short case
    quoted whole is still caught."""
    w = _words(text)
    return {tuple(w)} if 0 < len(w) < SHINGLE else _shingles(text)


def _unreadable(path: object, e: OSError) -> str:
    return f"{path}: can't read it ({e.strerror or type(e).__name__}), so the held-out check didn't cover it"


def _files(root: Path, problems: list[str]) -> Iterator[Path]:
    """The files under `root` (or `root` itself), in path order. A folder that can't be read is a problem line,
    never an exception: an unread folder would otherwise pass as clean."""
    try:
        if root.is_file():
            yield root
            return
        if not root.is_dir():
            return
    except OSError as e:
        problems.append(_unreadable(root, e))
        return
    found = []
    for folder, dirs, names in os.walk(root, onerror=lambda e: problems.append(_unreadable(e.filename, e))):
        dirs.sort()
        found += [Path(folder) / n for n in names]
    yield from sorted(found)


def _read_text(path: Path, problems: list[str]) -> str | None:
    try:
        data = path.read_bytes()
    except FileNotFoundError:  # gone since the walk, or a dangling link
        return None
    except OSError as e:
        problems.append(_unreadable(path, e))
        return None
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def heldout_roots(base: Path = PLUGIN_ROOT) -> list[Path]:
    return [base / r for r in HELDOUT_ROOTS]


def heldout_leaks(cases: list[GoldenCase], roots: list[Path]) -> list[str]:
    """`<path>: <case id>: …` for every file under `roots` that shares a SHINGLE-word run with a case's text or,
    for a JR case, its reason (case-folded words; punctuation and spacing ignored). A text or reason shorter than
    SHINGLE words leaks when all of it appears. Missing roots and binary files are skipped; a folder or file that
    can't be read is a problem line of its own, never an exception."""
    index: dict[tuple[str, ...], list[str]] = {}
    for c in cases:
        for part in (c.text, c.reason or ""):
            for s in _case_shingles(part):
                index.setdefault(s, []).append(c.id)
    if not index:
        return []
    sizes = sorted({len(s) for s in index})
    problems: list[str] = []
    for root in roots:
        for path in _files(Path(root), problems):
            text = _read_text(path, problems)
            if text is None:
                continue
            hit: list[str] = []
            for s in (s for size in sizes for s in _shingles(text, size)):
                for cid in index.get(s, ()):
                    if cid not in hit:
                        hit.append(cid)
            problems += [f"{path}: {cid}: quotes {SHINGLE}+ consecutive words (all of a shorter text) of a held-out "
                         "golden case" for cid in sorted(hit)]
    return problems
