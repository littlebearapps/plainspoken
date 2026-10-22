"""The golden set: labelled cases the judges and the claims checker are measured against (Phase 6 evals).

One TOML file per group (`evals/golden/J1.toml` … `J4.toml`, `JR.toml`, and `CL.toml` for the claims checker),
each `schema = 1`, `group = "<G>"` and `[[case]]` tables. A CL case is a short article plus its ledger claims
(`[[case.claim]]`), each with the verdict the checker should reach (`expect`) and why; `claims_ledger` builds the
ledger the checker reads, without them. `load` reads and type-checks the files (a malformed file raises GoldenError
naming the file, the case and the key); `validate` checks what the cases say (ids, rules, labels, provenance, JR
evidence, CL claims) and, with `require_counts`, that every group is big and balanced enough to measure;
`heldout_leaks` proves no case text is quoted in the files a model sees (rubrics, skills, guides, hooks, briefs).
Format: evals/golden/README.md."""
import hashlib
import os
import re
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from plainspoken import justify, pinning, schema
from plainspoken.doc import CONTENT_TYPES, split_lines
from plainspoken.registry import load_config

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = PLUGIN_ROOT / "evals" / "golden"
HELDOUT_ROOTS = ("data", "agents", "skills", "guides", "hooks", "output-styles", "templates", "evals/briefs")
SCHEMA = 1
JUDGE_GROUPS = ("J1", "J2", "J3", "J4", "JR")  # what `eval judges` measures
CLAIMS = "CL"  # the claims checker's group: `eval claims` measures it
GROUPS = (*JUDGE_GROUPS, CLAIMS)
LABELS = {**{g: ("fail", "pass") for g in JUDGE_GROUPS[:4]}, "JR": ("accept", "reject"), CLAIMS: ("fail", "pass")}
# What a CL case tests (its `rule`): a part of the claims rubric (data/rubrics/claims.md).
CL_RULES = ("opinion_label", "derivation", "entailment", "first_hand_scope", "quote", "brief", "aggregator")
CL_STATUSES = ("verified", "derived", "first_hand", "opinion_or_inference", "hypothetical")  # no removed/blocking
CL_KEYS = ("expect", "why")  # a CL claim's label keys: never in the ledger the checker reads
MAX_WHY = 240
STATUSES = ("confirmed", "endorsed", "provisional")
SOURCE_FOR_STATUS = {"confirmed": "owner", "endorsed": "owner-endorsed", "provisional": "constructed"}
ID_RE = re.compile(r"(J[1-4]|JR|CL)-[A-Za-z0-9_]+(-[A-Za-z0-9_]+)?-\d{3}")  # used with fullmatch
MAX_TEXT = 4000
MAX_ORIGIN = 160
MIN_CASES = 30
MIN_PER_LABEL = 10
CL_MIN_CASES = 10  # the claims set is smaller: each case is an article and a ledger, with several labelled claims
CL_MIN_CASES_PER_LABEL = 4  # cases whose checker result should be BLOCKED (fail) and PASS (pass)
CL_MIN_CLAIMS_PER_LABEL = 10  # labelled claims of each verdict
SHINGLE = 8

_CASE_KEYS = ("id", "rule", "label", "content_type", "source", "status", "origin", "text")
_JR_KEYS = ("kind", "reason", "evidence")
_CL_KEYS = ("id", "rule", "content_type", "source", "status", "origin", "text", "claim")  # label: from the claims
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
    claims: tuple[dict, ...] = field(default=(), hash=False)  # CL only: ledger claims, each with `expect` and `why`


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
    if group == CLAIMS:
        return [_cl_case(item, n, name) for n, item in enumerate(items, 1)]
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


def _cl_case(item: object, n: int, name: str) -> GoldenCase:
    """One CL case: the shared keys, then `[[case.claim]]` tables. Its label is `fail` when any claim's `expect`
    is `fail` (the checker should return BLOCKED), else `pass`; what each claim says is `validate`'s job."""
    if not isinstance(item, dict):
        raise GoldenError(f"{name}: case #{n}: not a table")
    where = f"{name}: {_case_name(item, n)}"
    for key in sorted(set(item) - set(_CL_KEYS)):
        why = "CL cases take their label from their claims' expect" if key == "label" else "unknown key"
        raise GoldenError(f"{where}: {key}: {why}")
    for key in _CL_KEYS:
        if key not in item:
            raise GoldenError(f"{where}: {key}: missing key")
        if key != "claim" and not isinstance(item[key], str):
            raise GoldenError(f"{where}: {key}: must be a string")
    claims = item["claim"]
    if not isinstance(claims, list) or not all(isinstance(c, dict) for c in claims):
        raise GoldenError(f"{where}: claim: must be an array of tables ([[case.claim]])")
    label = "fail" if any(c.get("expect") == "fail" for c in claims) else "pass"
    return GoldenCase(id=item["id"], group=CLAIMS, rule=item["rule"], label=label, text=item["text"],
                      content_type=item["content_type"], source=item["source"], status=item["status"],
                      origin=item["origin"], file=name, claims=tuple(dict(c) for c in claims))


def text_sha256(text: str) -> str:
    """`sha256:<hex>` of a text's UTF-8 bytes: a CL case's article or ledger, as `claims.article_hash` hashes a file."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def claims_ledger(case: GoldenCase) -> dict:
    """The claim ledger a CL case's checker reads: the fixed top-level fields of a complete, fresh ledger for
    `posts/article.md` (its `source_content_hash` is the case text's), and the case's claims without their label
    keys (`expect`, `why`). No id, label or origin of the case is in it."""
    return {"schema_version": 1, "article_id": "ARTICLE", "article_slug": "article", "source_file": "posts/article.md",
            "source_content_hash": text_sha256(case.text), "checked_at": "2026-10-01T09:00:00+10:00",
            "checked_by": "claims skill", "coverage_status": "complete",
            "claims": [{k: v for k, v in c.items() if k not in CL_KEYS} for c in case.claims]}


def _cl_problems(c: GoldenCase) -> list[str]:
    """What's wrong with a CL case's claims: each has `expect` (fail or pass) and a one-line `why`, a unique id, a
    status the checker can be scored on, and text the article really says; the ledger they make is schema-valid;
    a derivation names claims of this case."""
    out = []
    if c.rule not in CL_RULES:
        out.append(f"rule {c.rule!r} must be one of {', '.join(CL_RULES)}")
    if not c.claims:
        out.append("needs at least one [[case.claim]]")
    article = pinning.normalise_text(c.text)
    ids = [cl.get("claim_id") for cl in c.claims]
    for i, cl in enumerate(c.claims, 1):
        cid = cl.get("claim_id") if isinstance(cl.get("claim_id"), str) else f"claim #{i}"
        if cl.get("expect") not in LABELS[CLAIMS]:
            out.append(f"{cid}: expect {cl.get('expect')!r} must be fail or pass")
        why = cl.get("why")
        if not isinstance(why, str) or not why.strip() or len(why) > MAX_WHY or "\n" in why:
            out.append(f"{cid}: why must be one line of 1–{MAX_WHY} characters")
        if cl.get("claim_id") in ids[:i - 1]:
            out.append(f"{cid}: duplicate claim_id")
        if cl.get("status") not in CL_STATUSES:
            out.append(f"{cid}: status {cl.get('status')!r} must be one of {', '.join(CL_STATUSES)}")
        text = cl.get("text")
        if isinstance(text, str) and pinning.normalise_text(text) not in article:
            out.append(f"{cid}: its text isn't in the article word for word")
        derivation = cl.get("derivation")
        inputs = derivation.get("inputs") if isinstance(derivation, dict) else None
        for name in inputs if isinstance(inputs, list) else []:
            if name not in ids or name == cl.get("claim_id"):
                out.append(f"{cid}: derivation input {name!r} isn't another claim of this case")
    out += [f"ledger: {m}" for m in schema.validate(claims_ledger(c), schema.load("claim-ledger"))]
    return out


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
    if c.group == CLAIMS:
        out += _cl_problems(c)
    elif rule is None:
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
        if g == CLAIMS:
            row.update({f"claims {lab}": sum(cl.get("expect") == lab for c in mine for cl in c.claims)
                        for lab in LABELS[g]})
        out[g] = row
    return out


def count_line(group: str, row: dict) -> str:
    n = row["cases"]
    keys = (*LABELS[group], *STATUSES, *([f"claims {lab}" for lab in LABELS[group]] if group == CLAIMS else []))
    return f"{group} {n} case{'' if n == 1 else 's'}: " + " · ".join(f"{k} {row[k]}" for k in keys)


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
            if g == CLAIMS:
                problems += _cl_count_problems(row)
                continue
            if row is None:
                problems.append(f"{g}: no cases (need at least {MIN_CASES}, {MIN_PER_LABEL} of each label)")
                continue
            if row["cases"] < MIN_CASES:
                problems.append(f"{g}: {row['cases']} cases (need at least {MIN_CASES})")
            for lab in LABELS[g]:
                if row[lab] < MIN_PER_LABEL:
                    problems.append(f"{g}: {row[lab]} {lab} cases (need at least {MIN_PER_LABEL})")
    return problems


def _cl_count_problems(row: dict | None) -> list[str]:
    """CL needs CL_MIN_CASES cases, CL_MIN_CASES_PER_LABEL of each case label and CL_MIN_CLAIMS_PER_LABEL labelled
    claims of each verdict: a checker that blocks everything, or nothing, can't score well on it."""
    if row is None:
        return [f"{CLAIMS}: no cases (need at least {CL_MIN_CASES}, {CL_MIN_CLAIMS_PER_LABEL} claims of each verdict)"]
    out = []
    if row["cases"] < CL_MIN_CASES:
        out.append(f"{CLAIMS}: {row['cases']} cases (need at least {CL_MIN_CASES})")
    for lab in LABELS[CLAIMS]:
        if row[lab] < CL_MIN_CASES_PER_LABEL:
            out.append(f"{CLAIMS}: {row[lab]} {lab} cases (need at least {CL_MIN_CASES_PER_LABEL})")
        if row[f"claims {lab}"] < CL_MIN_CLAIMS_PER_LABEL:
            out.append(f"{CLAIMS}: {row[f'claims {lab}']} {lab} claims (need at least {CL_MIN_CLAIMS_PER_LABEL})")
    return out


def _cl_strings(case: GoldenCase) -> list[str]:
    """A CL case's held-out prose beyond its text: each claim's text, why, notes, pinned passages, derivation
    method and first-hand scope."""
    out: list[str] = []
    for cl in case.claims:
        out += [cl.get(k) for k in ("text", "why", "notes")]
        binding, derivation, scope = cl.get("binding"), cl.get("derivation"), cl.get("first_hand_scope")
        if isinstance(binding, dict):
            out.append(binding.get("passage"))
            extras = binding.get("additional_passages")
            out += [e.get("passage") for e in extras if isinstance(e, dict)] if isinstance(extras, list) else []
        out.append(derivation.get("method") if isinstance(derivation, dict) else None)
        out.append(scope.get("scope") if isinstance(scope, dict) else None)
    return [x for x in out if isinstance(x, str)]


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
    """`<path>: <case id>: …` for every file under `roots` that shares a SHINGLE-word run with a case's text, a
    JR case's reason or a CL case's claim prose (`_cl_strings`), in case-folded words with punctuation and spacing
    ignored. A text shorter than SHINGLE words leaks when all of it appears. Missing roots and binary files are
    skipped; a folder or file that can't be read is a problem line of its own, never an exception."""
    index: dict[tuple[str, ...], list[str]] = {}
    for c in cases:
        for part in (c.text, c.reason or "", *_cl_strings(c)):
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
