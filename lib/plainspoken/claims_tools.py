"""The logic behind the `claims` CLI subcommands that build or combine things: `scaffold` (a fail-closed starter
ledger from the extracted candidates), `pin` (a ready-to-paste TOML binding fragment), `stamp` (the article's hash,
the time and `checked_by` written into the ledger, so no hash is copied by hand), and `status` (gaps computed, the
checker's record read, the report payload assembled).

Kept apart from claims.py, the ledger core, because it needs extraction.py and checker.py, and checker.py imports
claims.py.

The checker record (`<key>.claims-check.json`, written by `checker.record`) is read here and nowhere else. It's
current only when its `article_sha256` and `ledger_sha256` (both `sha256:<hex>`, as `claims.article_hash`) match the
article and ledger on disk now, and its `rubric_sha256` and `matrix_sha256` match the rubric and configured matrix
(`checker.rubric_hash`, `checker.matrix_hash`). A missing record means the checker hasn't run; a malformed one counts
as INCOMPLETE.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
import tomllib
from pathlib import Path

from plainspoken import _util, checker, claims, extraction, integrity, pinning, schema, tomlw

__all__ = ["CHECKED_BY", "RESOLUTION", "NotReady", "default_id_prefix", "id_pattern", "location_kinds",
           "pin_fragment", "read_check", "scaffold", "scaffold_text", "source_suffixes", "stamp", "stamp_text",
           "status_report", "unreported", "display_path"]

CHECKED_BY = "plainspoken claims scaffold"
RESOLUTION = "unreviewed candidate from claims scaffold"
_SUFFIXES = re.compile(r"\\\.\(([a-z|]+)\)\$$")  # the `\.(md|mdx|…)$` that ends the source_file pattern
# extraction kind -> claim_type (each a value of the schema's claim_type enum; anything else is a `premise`)
_CLAIM_TYPES = {"statistic": "statistic", "currency": "price", "count": "count", "version": "version",
                "quote": "quotation", "comparative": "comparison", "causal": "causal",
                "platform_behaviour": "platform_behaviour", "multiplier": "statistic"}
_HIGH_PROMINENCE = ("tldr", "heading", "chart", "jsonld")
_SCAFFOLD_HEADER = (
    "# Scaffolded by `claims scaffold` from the deterministic candidates only: semantic and fresh-context coverage\n"
    "# haven't run. Every claim is `blocking` until a person or agent gives it a real status (verified, derived,\n"
    "# first_hand, opinion_or_inference, hypothetical or removed) with the fields that status needs.\n\n")
_BINDING_REMINDER = (
    "# Also set the five judgements the schema requires, each after reading the passage against the claim:\n"
    "# same_subject, same_geography, same_period, same_denominator, supports_strength (true or false).\n")


@functools.lru_cache(maxsize=1)
def _schema() -> dict:
    return schema.load("claim-ledger")


def location_kinds() -> tuple[str, ...]:
    """The schema's `locations[].kind` values."""
    return tuple(_schema()["$defs"]["claim"]["properties"]["locations"]["items"]["properties"]["kind"]["enum"])


def id_pattern() -> re.Pattern[str]:
    """The schema's `claim_id` pattern, compiled."""
    return re.compile(_schema()["$defs"]["claim"]["properties"]["claim_id"]["pattern"])


def source_suffixes() -> tuple[str, ...]:
    """The file types the schema's `source_file` pattern allows (`.md`, …). SchemaError when the pattern no longer
    ends in a `\\.(a|b|…)$` group this can read."""
    pattern = _schema()["properties"]["source_file"]["pattern"]
    m = _SUFFIXES.search(pattern)
    if not m:
        raise schema.SchemaError(f"can't read the file types from the source_file pattern {pattern!r}")
    return tuple(f".{s}" for s in m.group(1).split("|"))


def default_id_prefix(article: Path) -> str:
    """The article stem, upper-cased, each run of non-alphanumerics turned into one `-` (`ARTICLE` if nothing's
    left)."""
    return re.sub(r"[^A-Za-z0-9]+", "-", Path(article).stem.upper()).strip("-") or "ARTICLE"


def project_relative(path: Path, project_root: Path) -> str:
    """`path` relative to the project root, as POSIX. ValueError when it's outside the project."""
    resolved, root = Path(path).resolve(), Path(project_root).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"{path} isn't inside the project ({root}), so a ledger can't name it")
    return resolved.relative_to(root).as_posix()


_HEADING = re.compile(r"^#{1,6}[ \t]+(.*?)[ \t]*$")
_HEADING_ID = re.compile(r"[ \t]*\{#[^}]*\}$")  # a trailing `{#anchor}` id
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
BEFORE_HEADINGS = "before the first heading"


def _sections(text: str) -> list[tuple[int, str]]:
    """(line, heading text) of each markdown heading, in order: frontmatter and fenced code skipped, closing `#`s
    and a trailing `{#id}` dropped."""
    fm = integrity.FRONTMATTER.search(text)
    skip = text.count("\n", 0, fm.end()) + 1 if fm else 0
    out: list[tuple[int, str]] = []
    fence = ""
    for n, line in enumerate(text.splitlines(), start=1):
        if n <= skip:
            continue
        m = _FENCE.match(line)
        if m and (not fence or m.group(1).startswith(fence)):
            fence = "" if fence else m.group(1)[0] * 3
            continue
        h = None if fence else _HEADING.match(line)
        if h:
            title = _HEADING_ID.sub("", re.sub(r"[ \t]+#+$", "", h.group(1))).strip()
            if title:
                out.append((n, title))
    return out


def _anchor(sections: list[tuple[int, str]], line: int) -> str:
    """The heading of the section `line` sits in (a heading is its own section), or BEFORE_HEADINGS."""
    title = BEFORE_HEADINGS
    for n, heading in sections:
        if n > line:
            break
        title = heading
    return title


def _location(surface: str, line: int, sections: list[tuple[int, str]]) -> dict:
    if surface.startswith("frontmatter:"):
        return {"kind": "frontmatter", "field": surface.split(":", 1)[1]}
    return {"kind": surface if surface in location_kinds() else "body", "anchor": _anchor(sections, line)}


def _claim(n: int, prefix: str, c: dict, sections: list[tuple[int, str]]) -> dict:
    surface = c["surface"]
    high = surface.startswith("frontmatter:") or surface in _HIGH_PROMINENCE
    return {
        "claim_id": f"{prefix}-C{n:03d}",
        "text": c["text"],
        "locations": [_location(surface, c["line"], sections)],
        "claim_type": _CLAIM_TYPES.get(c["kind"], "premise"),
        "prominence": "high" if high else "medium",
        "status": "blocking",
        "resolution": RESOLUTION,
        "notes": f"{c['kind']} candidate {c['value']!r} ({surface}, line {c['line']})",
    }


def scaffold(article: Path, project_root: Path, *, id_prefix: str | None = None,
             platforms: tuple[str, ...] | None = None, checked_at: str | None = None) -> dict:
    """A ledger holding every extracted candidate as a `blocking` claim, `coverage_status = "unstarted"`.

    Raises ValueError for an article outside the project, a file type the schema's `source_file` doesn't allow, or
    an id prefix that doesn't make schema-valid claim ids; OSError / UnicodeDecodeError when the article can't be
    read."""
    article = Path(article)
    source_file = project_relative(article, project_root)
    suffixes = source_suffixes()
    if article.suffix.lower() not in suffixes:
        raise ValueError(f"{article}: a ledger's source_file must end in {', '.join(suffixes)}")
    prefix = default_id_prefix(article) if id_prefix is None else id_prefix
    if not id_pattern().match(f"{prefix}-C001"):
        raise ValueError(f"--id-prefix {prefix!r}: use letters and digits, joined by single - or _")
    text = article.read_text(encoding="utf-8")
    cands = extraction.extract_candidates(text, platforms)
    sections = _sections(text)
    return {
        "schema_version": 1,
        "article_id": prefix,
        "article_slug": article.stem,
        "source_file": source_file,
        "source_content_hash": claims.article_hash(article),
        "checked_at": checked_at or _util.now_iso(),
        "checked_by": CHECKED_BY,
        "coverage_status": "unstarted",
        "coverage_notes": (f"{len(cands)} deterministic candidate(s) scaffolded; semantic and fresh-context coverage "
                           "not run."),
        "claims": [_claim(n, prefix, c, sections) for n, c in enumerate(cands, start=1)],
    }


def scaffold_text(ledger: dict) -> str:
    """The scaffolded ledger as TOML, with a header comment saying what it is."""
    return _SCAFFOLD_HEADER + tomlw.dumps(ledger)


def pin_fragment(source_text: str, passage: str, *, retrieved_at: str, source_snapshot: str | None,
                 additional: bool = False, source_url: str | None = None, locator: str | None = None) -> str:
    """A `[claims.binding]` fragment (or, with `additional`, a `[[claims.binding.additional_passages]]` one) for a
    passage located verbatim in `source_text`. Raises ValueError on a refusal (pinning.binding_fields)."""
    fields = pinning.binding_fields(source_text, passage, retrieved_at=retrieved_at,
                                    source_snapshot=None if additional else source_snapshot)
    if not additional:
        return tomlw.dumps({"claims": {"binding": fields}}) + _BINDING_REMINDER
    if source_url is not None:
        fields["source_url"] = source_url
    if locator is not None:
        fields["locator"] = locator
    return tomlw.dumps({"claims": {"binding": {"additional_passages": [fields]}}})


class NotReady(Exception):
    """`stamp` refused: the ledger isn't finished (coverage not complete, or a gap open). Not a ValueError, because
    the CLI exits 1 for it, not 2 (bad input)."""


_STAMP_KEYS = ("source_content_hash", "checked_at", "checked_by")
_TOP_KEY = re.compile(r'^[ \t]*(["\']?)(source_content_hash|checked_at|checked_by)\1[ \t]*=')
_TABLE_LINE = re.compile(r"^[ \t]*\[")


def _stamp_toml(text: str, values: dict) -> str:
    lines = text.splitlines(keepends=True)
    end = next((i for i, ln in enumerate(lines) if _TABLE_LINE.match(ln)), len(lines))  # top-level keys end here
    done = set()
    for i in range(end):
        m = _TOP_KEY.match(lines[i])
        if m:
            lines[i] = tomlw.dumps({m.group(2): values[m.group(2)]})
            done.add(m.group(2))
    missing = "".join(tomlw.dumps({k: values[k]}) for k in _STAMP_KEYS if k not in done)
    at = end  # above the blank and comment lines that lead into the first table, so they stay with it
    while at > 0 and (not lines[at - 1].strip() or lines[at - 1].lstrip().startswith("#")):
        at -= 1
    if missing and at > 0 and not lines[at - 1].endswith("\n"):
        missing = "\n" + missing
    lines[at:at] = [missing]
    return "".join(lines)


def stamp_text(text: str, suffix: str, values: dict) -> str:
    """The ledger text with `values` (`source_content_hash`, `checked_at`, `checked_by`) set at its top level and
    everything else unchanged. TOML is edited in place, line by line, so comments and layout stay; a missing key is
    added before the first table. JSON is rewritten with the same keys in the same order. Raises ValueError when the
    result wouldn't read back as the same ledger with those three values (a value written over several lines)."""
    if suffix == ".json":
        data = claims.strict_json(text)
        if not isinstance(data, dict):
            raise ValueError("the ledger must be an object at the top level")
        return json.dumps({**data, **values}, indent=2, ensure_ascii=False) + "\n"
    before = tomllib.loads(text)
    out = _stamp_toml(text, values)
    try:
        after = tomllib.loads(out)
    except tomllib.TOMLDecodeError:
        after = None
    if after != {**before, **values}:
        raise ValueError("can't stamp it in place: put source_content_hash, checked_at and checked_by each on one "
                         "line at the top of the ledger, then run stamp again")
    return out


def stamp(article: Path, ledger_path: Path, project_root: Path, platforms: tuple[str, ...] | None,
          checked_by: str) -> tuple[str, dict]:
    """(new ledger text, the values written) for `claims stamp`. Writes nothing itself.

    Raises NotReady while `coverage_status` isn't `complete` or the article holds a value or quote the ledger
    doesn't (`claims gaps`): the hash says the ledger was checked against this text, so it waits until it was.
    Raises OSError / UnicodeDecodeError for an unreadable article, claims.LedgerError for an unreadable ledger, and
    ValueError for a ledger whose `source_file` is another article or one it can't edit in place."""
    article, ledger_path = Path(article), Path(ledger_path)
    raw = article.read_bytes()  # one read: the hash and the gaps are of the same text
    text = raw.decode("utf-8")
    values = {"source_content_hash": "sha256:" + hashlib.sha256(raw).hexdigest(), "checked_at": _util.now_iso(),
              "checked_by": checked_by}
    ledger = claims.load_ledger(ledger_path)
    own = project_relative(article, project_root)
    if ledger.get("source_file") != own:
        raise ValueError(f"{ledger_path} is the ledger for {ledger.get('source_file')!r}, not {own}")
    if ledger.get("coverage_status") != "complete":
        raise NotReady(f"coverage_status is {ledger.get('coverage_status')!r}: finish steps 2 to 4 (every claim "
                       "reviewed, every verified claim pinned, no gaps), set it to \"complete\", then stamp")
    gaps = extraction.value_gaps(text, ledger, platforms)
    if gaps:
        shown = ", ".join(g["value"] for g in gaps[:5]) + (" …" if len(gaps) > 5 else "")
        raise NotReady(f"{len(gaps)} value(s) or quote(s) in the article aren't in the ledger ({shown}): run "
                       "`claims gaps` and give each one a claim or an exclusion, then stamp")
    return stamp_text(ledger_path.read_text(encoding="utf-8"), ledger_path.suffix.lower(), values), values


def read_check(path: Path, article_sha: str | None, ledger_sha: str | None, rubric_sha: str | None = None,
               matrix_sha: str | None = None) -> tuple[dict | None, str | None]:
    """(check, note) from the checker record at `path`, for `claims.status`.

    No file: (None, None). A malformed file (not JSON, not an object, `result` / `article_sha256` / `ledger_sha256`
    missing or not text): ({"result": "INCOMPLETE", "current": False}, "checker record unreadable: …"). Otherwise
    `current` says whether all four bound hashes match now (article, ledger, rubric, matrix: a record with no
    `rubric_sha256` or `matrix_sha256` is never current), and `warnings` counts the record's warning findings. A
    record that isn't current notes `checker result stale`, `… (rubric changed)` or `… (matrix changed)`, the first
    that applies."""
    path = Path(path)
    if not path.exists():
        return None, None
    unreadable = {"result": "INCOMPLETE", "current": False}, f"checker record unreadable: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return unreadable
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str)
                                             for k in ("result", "article_sha256", "ledger_sha256")):
        return unreadable
    if not (article_sha is not None and ledger_sha is not None
            and data["article_sha256"] == article_sha and data["ledger_sha256"] == ledger_sha):
        note = "checker result stale"
    elif rubric_sha is None or data.get("rubric_sha256") != rubric_sha:
        note = "checker result stale (rubric changed)"
    elif matrix_sha is None or data.get("matrix_sha256") != matrix_sha:
        note = "checker result stale (matrix changed)"
    else:
        note = None
    findings = data.get("findings")
    warnings = sum(isinstance(f, dict) and f.get("severity") == "warning"
                   for f in (findings if isinstance(findings, list) else []))
    return {"result": data["result"], "current": note is None, "warnings": warnings}, note


def status_report(article: Path, ledger: Path, project_root: Path, check_path: Path,
                  platforms: tuple[str, ...] | None) -> dict:
    """`claims.status` with the gaps computed and the checker record read, plus what the report file records.

    Raises OSError / UnicodeDecodeError when the article can't be read, and ValueError for a configured matrix
    that isn't there (bad input). A missing or broken ledger isn't an error here: it makes the status INCOMPLETE,
    with the reason."""
    article, ledger = Path(article), Path(ledger)
    text = article.read_text(encoding="utf-8")
    try:
        loaded: dict | claims.LedgerError = claims.load_ledger(ledger)
        gaps = extraction.value_gaps(text, loaded, platforms)
    except claims.LedgerError as e:
        loaded, gaps = e, None  # status() reports the unreadable ledger
    check, note = read_check(check_path, claims.hash_or_none(article), claims.hash_or_none(ledger),
                             checker.rubric_hash(), checker.matrix_hash(project_root))
    result = claims.status(article, ledger, project_root, gaps=gaps, check=check, loaded=loaded)
    if note:
        result["reasons"] = [note if r == "checker not run" else r for r in result["reasons"]]
    elif result["status"] == "PASS":  # only then: an INCOMPLETE ending "checker: PASS" reads as a mixed signal
        n = check["warnings"]
        result["reasons"].append(f"checker: PASS ({n} warning{'' if n == 1 else 's'})")
    return {**result, "article": display_path(article, project_root),
            "ledger": display_path(ledger, project_root), "gaps": gaps, "check": check}


def unreported(article: Path, ledger: Path | None, project_root: Path, error: BaseException) -> dict:
    """The INCOMPLETE `<key>.claims.json` payload written when `claims status` can't report (a configured matrix
    that isn't there, an unreadable article, an ambiguous ledger), so an earlier PASS never outlives the error.
    Same keys as `status_report`."""
    first = (str(error).splitlines() or [""])[0]
    return {"status": "INCOMPLETE", "reasons": [f"can't report: {type(error).__name__}: {first}"],
            "article_sha256": claims.hash_or_none(article),
            "ledger_sha256": None if ledger is None else claims.hash_or_none(ledger), "counts": {},
            "article": display_path(article, project_root),
            "ledger": None if ledger is None else display_path(ledger, project_root), "gaps": None, "check": None}


def display_path(path: Path, project_root: Path) -> str:
    """`path` project-relative when it's inside the project, else as given."""
    try:
        return project_relative(path, project_root)
    except (ValueError, OSError, RuntimeError):
        return str(path)
