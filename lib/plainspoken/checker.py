"""The isolated claims checker's CLI side: its input block, and recording its reply.

The `claims-checker` agent is read-only and is never told who wrote the article, so the CLI does the bookkeeping:

  * `checker_input` names the files the agent reads (article, ledger, rubric, the host's regulated-claims matrix or
    "none") and the hashes it checks against (`matrix_sha256` is the matrix file's hash, or "none"). It refuses a
    stale ledger: the checker never runs on one.
  * `parse_reply` accepts one JSON object, bare or in exactly one fenced block. Prose outside the block is allowed
    and recorded (`reply_had_prose`). Anything ambiguous (two blocks, a competing object in the prose, a duplicated
    key) or malformed is a ValueError, never a PASS.
  * The reply copies `article_sha256`, `ledger_sha256` and `matrix_sha256` from its input block; `record` refuses a
    reply whose hashes are missing or aren't current (StaleReply), so an old reply is never bound to new text or a
    new matrix.
  * `verify` checks every finding's `evidence` verbatim against the article and the ledger's pinned passages, after
    `pinning.normalise_evidence` (quotes, whitespace, markdown link syntax and case, nothing else). Substring
    matching defeats ellipsis stitching on its own: "A … B" is found only where the text really says it. An unfound
    quote keeps its finding, marked `evidence_verified: false`: the checker is additive
    only, so nothing it says is dropped, and an unverified blocking finding still blocks until a person dismisses it.
  * `record` writes `<key>.claims-check.json`, bound to the article, ledger, rubric and matrix hashes, which
    `claims_tools.read_check` reads for `claims status`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from plainspoken import _util, claims, config, pinning, report

__all__ = ["RUBRIC", "ReplyError", "StaleLedger", "StaleReply", "check_reply_hashes", "checker_input",
           "ledger_passages", "matrix_hash", "parse_reply", "record", "reply_object", "rubric_hash", "verify",
           "verbatim"]

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = ROOT / "data" / "rubrics" / "claims.md"
RESULTS = ("PASS", "BLOCKED")
SEVERITIES = ("blocking", "warning")
_FENCE_LINE = re.compile(r"^[ \t]*```", re.M)
_FENCE = re.compile(r"^[ \t]*```([^\n]*)\n(.*?)\n[ \t]*```[ \t]*$", re.M | re.S)
_REPLY_KEYS = ('"result"', '"findings"')  # in prose outside the fence: a second, competing object
_HASH_IN_TEXT = re.compile(r'"(article_sha256|ledger_sha256|matrix_sha256)"\s*:\s*"([^"\n]*)"')
MIN_EVIDENCE_WORDS = 3  # one or two common words are found almost anywhere, so they show nothing


class StaleLedger(Exception):
    """The ledger's `source_content_hash` doesn't match the article: refuse, never bind a check to it. Not a
    ValueError, because the CLI exits 1 for it (INCOMPLETE), not 2 (bad input)."""


class StaleReply(Exception):
    """The reply's `article_sha256` / `ledger_sha256` are missing or aren't the current hashes: the checker read
    another version. Refused with nothing written (exit 1), never bound to the current hashes."""


class ReplyError(ValueError):
    """The checker's reply couldn't be parsed or verified. `record` has written an INCOMPLETE record by then."""


def _fresh_hashes(article: Path, ledger_path: Path) -> tuple[dict, str, str]:
    """(ledger, article_sha256, ledger_sha256). Raises OSError for an unreadable article, claims.LedgerError for an
    unreadable ledger, StaleLedger when the ledger was checked against another version of the article."""
    article_sha = claims.article_hash(article)
    ledger = claims.load_ledger(ledger_path)
    if ledger.get("source_content_hash") != article_sha:
        raise StaleLedger(f"stale ledger: {ledger_path} was checked against another version of {article} "
                          "(source_content_hash doesn't match). Re-verify the changed claims, refresh the hash, "
                          "then run the checker.")
    return ledger, article_sha, claims.article_hash(ledger_path)


def _matrix_path(project_root: Path) -> Path | None:
    """The configured regulated-claims matrix, resolved, or None when none is configured. ValueError when it's
    configured but isn't there (or the config is malformed)."""
    value = config.claims_settings(project_root)["regulated_matrix"]
    if value is None:
        return None
    path = Path(value) if Path(value).is_absolute() else Path(project_root) / value
    if not path.is_file():
        raise ValueError(f"[claims] regulated_matrix {value} not found (looked for {path})")
    return path.resolve()


def rubric_hash() -> str:
    """`sha256:<hex>` of the rubric file's bytes."""
    return claims.article_hash(RUBRIC)


def matrix_hash(project_root: Path) -> str:
    """`sha256:<hex>` of the configured matrix file's bytes, or the literal "none" when none is configured.
    ValueError / OSError as `_matrix_path`, or when the file can't be read."""
    path = _matrix_path(project_root)
    return "none" if path is None else claims.article_hash(path)


def checker_input(article: Path, ledger_path: Path, project_root: Path) -> dict:
    """The agent's input block. Raises StaleLedger, or OSError / ValueError for bad input (an unreadable article
    or ledger, a malformed config, a configured matrix that isn't there)."""
    _, article_sha, ledger_sha = _fresh_hashes(article, ledger_path)
    matrix = _matrix_path(project_root)
    return {"article": str(Path(article).resolve()), "ledger": str(Path(ledger_path).resolve()),
            "rubric": str(RUBRIC), "regulated_matrix": "none" if matrix is None else str(matrix),
            "article_sha256": article_sha, "ledger_sha256": ledger_sha, "matrix_sha256": matrix_hash(project_root)}


# --- the reply -----------------------------------------------------------------------------------------------------

def parse_reply(text: str) -> dict:
    """The reply's JSON object, with `reply_had_prose` added.

    Accepted: a bare object, or exactly one fenced block (```` ```json ```` or untagged) with optional prose around
    it. ValueError when the reply is ambiguous or malformed: more than one fenced block (tagged or not), an unclosed
    fence, a fence tagged as something else, prose outside the fence that holds `"result"` or `"findings"` (a
    competing object), no object, invalid JSON, a duplicated key, no `findings` list (or a finding that isn't an
    object), or a `result` other than PASS or BLOCKED."""
    data, had_prose = reply_object(text, _REPLY_KEYS)
    if data.get("result") not in RESULTS:
        raise ValueError(f"the reply's result is {data.get('result')!r}, not PASS or BLOCKED")
    findings = data.get("findings")
    if not isinstance(findings, list):
        raise ValueError("the reply has no findings list")
    for i, f in enumerate(findings, start=1):
        if not isinstance(f, dict):
            raise ValueError(f"finding {i} isn't an object")
    data["reply_had_prose"] = had_prose
    return data


def reply_object(text: str, reply_keys: tuple[str, ...]) -> tuple[dict, bool]:
    """(the one JSON object in an agent's reply, whether it had prose outside its fenced block). Shared by every
    isolated checker's reply. ValueError for more than one fenced block, an unclosed or wrongly tagged fence, prose
    that holds one of `reply_keys` (quoted JSON keys: a competing object), no object, invalid JSON or a duplicated
    key."""
    markers = len(_FENCE_LINE.findall(text))
    had_prose = False
    if markers:
        blocks = list(_FENCE.finditer(text))
        if markers != 2 or len(blocks) != 1:
            raise ValueError(f"the reply has {markers} code-fence lines; send exactly one ```json block")
        block = blocks[0]
        if block.group(1).strip().lower() not in ("", "json"):
            raise ValueError(f"the reply's fenced block is tagged {block.group(1).strip()!r}, not json")
        body = block.group(2)
        prose = (text[:block.start()] + text[block.end():]).strip()
        if any(k in prose for k in reply_keys):
            raise ValueError("the prose outside the ```json block holds another reply object; send exactly one")
        had_prose = bool(prose)
    else:
        body = text.strip()
        if not body.startswith("{"):
            raise ValueError("the reply holds no JSON object (bare, or in one ```json block)")
    try:
        data = claims.strict_json(body)
    except (ValueError, RecursionError) as e:
        why = f"{e.msg} (at line {e.lineno}, column {e.colno})" if isinstance(e, json.JSONDecodeError) else str(e)
        raise ValueError(f"the reply isn't valid JSON: {why}") from None
    if not isinstance(data, dict):
        raise ValueError("the reply's JSON isn't an object")
    return data, had_prose


def ledger_passages(ledger: object) -> list[str]:
    """Every pinned passage in the ledger: each `binding.passage` and `binding.additional_passages[].passage`.
    Anything malformed is skipped (the ledger validator reports it)."""
    out: list[str] = []
    items = ledger.get("claims") if isinstance(ledger, dict) else None
    for claim in items if isinstance(items, list) else []:
        binding = claim.get("binding") if isinstance(claim, dict) else None
        if not isinstance(binding, dict):
            continue
        if isinstance(binding.get("passage"), str):
            out.append(binding["passage"])
        extras = binding.get("additional_passages")
        for item in extras if isinstance(extras, list) else []:
            if isinstance(item, dict) and isinstance(item.get("passage"), str):
                out.append(item["passage"])
    return out


def verbatim(evidence: object, corpus: list[str]) -> bool:
    """Whether `evidence` is at least MIN_EVIDENCE_WORDS words and, once normalised, is in one of the `corpus` texts
    (each already `pinning.normalise_evidence`d)."""
    if not isinstance(evidence, str):
        return False
    needle = pinning.normalise_evidence(evidence)
    return len(needle.split()) >= MIN_EVIDENCE_WORDS and any(needle in text for text in corpus)


def verify(reply: dict, article_text: str, ledger: dict) -> dict:
    """`{"result", "reply_result", "findings", "blocking", "warnings", "unverified_evidence", "reply_had_prose"}`.

    Each finding is kept as given, plus `evidence_verified`: its evidence is at least MIN_EVIDENCE_WORDS words and
    found verbatim (`pinning.normalise_evidence`) in the article or a pinned passage. `result` is BLOCKED when any
    finding is blocking (verified or not), PASS only when there's no blocking finding, the reply said PASS and every
    quote verified, and INCOMPLETE otherwise. ValueError for a finding whose severity isn't `blocking` or `warning`."""
    corpus = [pinning.normalise_evidence(article_text)] + [pinning.normalise_evidence(p)
                                                            for p in ledger_passages(ledger)]
    findings: list[dict] = []
    for i, f in enumerate(reply["findings"], start=1):
        if not isinstance(f, dict):
            raise ValueError(f"finding {i} isn't an object")
        if f.get("severity") not in SEVERITIES:
            raise ValueError(f"finding {i}: severity {f.get('severity')!r} isn't blocking or warning")
        findings.append({**f, "evidence_verified": verbatim(f.get("evidence"), corpus)})
    blocking = sum(f["severity"] == "blocking" for f in findings)
    unverified = sum(not f["evidence_verified"] for f in findings)
    if blocking:
        result = "BLOCKED"
    elif reply.get("result") == "PASS" and not unverified:
        result = "PASS"
    else:
        result = "INCOMPLETE"
    return {"result": result, "reply_result": reply.get("result"), "findings": findings, "blocking": blocking,
            "warnings": len(findings) - blocking, "unverified_evidence": unverified,
            "reply_had_prose": bool(reply.get("reply_had_prose"))}


# --- the record ----------------------------------------------------------------------------------------------------

def _write_atomic(path: Path, payload: dict) -> None:
    report.write_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def check_reply_hashes(reply: dict, article_sha: str, ledger_sha: str, matrix_sha: str) -> None:
    """StaleReply unless the reply's `article_sha256`, `ledger_sha256` and `matrix_sha256` (copied from the input
    block) are the current hashes: a reply to another version of the article, ledger or matrix is never bound to
    this one."""
    for key, now in (("article_sha256", article_sha), ("ledger_sha256", ledger_sha), ("matrix_sha256", matrix_sha)):
        said = reply.get(key)
        if said is None:
            raise StaleReply(f"stale reply: it carries no {key}, so it can't show which version it checked. "
                             "Run `claims checker-input` and the checker again.")
        if said != now:
            raise StaleReply(f"stale reply: its {key} is {str(said)[:80]!r}, not the current {now}. The checker "
                             "read another version: run `claims checker-input` and the checker again.")


def _stale_hashes_in(text: str, current: dict[str, str]) -> bool:
    """Whether a reply that couldn't be parsed names an `article_sha256`, `ledger_sha256` or `matrix_sha256` other
    than the current one: it answered another version, so it says nothing about this one."""
    return any(current[key] != value for key, value in _HASH_IN_TEXT.findall(text))


def _record_of(base: dict, *, result: str, reply_result: object, blocking: int, warnings: int, unverified: int,
               had_prose: object, findings: list, error: str | None) -> dict:
    """Every record has the same keys; a rejected reply has `reply_error` set and the counts at 0."""
    return {**base, "result": result, "recorded_at": _util.now_iso(), "reply_result": reply_result,
            "reply_error": error, "blocking": blocking, "warnings": warnings, "unverified_evidence": unverified,
            "reply_had_prose": had_prose, "findings": findings}


def record(article: Path, ledger_path: Path, reply_text: str, check_path: Path, display: dict,
           project_root: Path) -> dict:
    """Verify the reply and write the check record to `check_path`; returns the record.

    Writes nothing, and leaves any earlier record as it is, for a stale ledger (StaleLedger) or a reply bound to
    other hashes (StaleReply), even one that can't be parsed but names another article, ledger or matrix hash. A
    reply that can't be parsed or verified is a ReplyError, but first an INCOMPLETE record is written for the
    current hashes, so an earlier PASS for this version can't outlive a broken re-run.
    OSError / ValueError (claims.LedgerError) for an unreadable article or ledger, or a configured matrix that
    isn't there, with nothing written. `display` holds the `article` and `ledger` names to record; `project_root`
    finds the configured matrix."""
    ledger, article_sha, ledger_sha = _fresh_hashes(article, ledger_path)
    matrix_sha = matrix_hash(project_root)
    base = {**display, "article_sha256": article_sha, "ledger_sha256": ledger_sha, "rubric_sha256": rubric_hash(),
            "matrix_sha256": matrix_sha}
    article_text = Path(article).read_text(encoding="utf-8")

    def rejected(e: ValueError) -> ReplyError:
        _write_atomic(check_path, _record_of(base, result="INCOMPLETE", reply_result=None, blocking=0, warnings=0,
                                             unverified=0, had_prose=None, findings=[], error=str(e)))
        return ReplyError(str(e))

    try:
        reply = parse_reply(reply_text)
    except ValueError as e:
        current = {"article_sha256": article_sha, "ledger_sha256": ledger_sha, "matrix_sha256": matrix_sha}
        if _stale_hashes_in(reply_text, current):  # an old, broken reply never replaces a current record
            raise StaleReply(f"stale reply: it couldn't be read ({e}), and it names hashes other than the current "
                             "ones, so it answered another version. Run `claims checker-input` and the checker "
                             "again.") from None
        raise rejected(e) from None
    check_reply_hashes(reply, article_sha, ledger_sha, matrix_sha)
    try:
        checked = verify(reply, article_text, ledger)
    except ValueError as e:
        raise rejected(e) from None
    rec = _record_of(base, result=checked["result"], reply_result=checked["reply_result"],
                     blocking=checked["blocking"], warnings=checked["warnings"],
                     unverified=checked["unverified_evidence"], had_prose=checked["reply_had_prose"],
                     findings=checked["findings"], error=None)
    _write_atomic(check_path, rec)
    return rec
