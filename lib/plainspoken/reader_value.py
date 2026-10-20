"""The reader-value contract: the defined benefit a piece promises its reader before drafting, and must deliver.

`load_contract(path)` reads a standalone `.toml` or `.json` contract, or (any other file) a markdown file holding a
`## Reader Value Contract` heading with exactly one fenced `toml`, `json` or `yaml` block in its section. A `yaml`
block is read with `frontmatter.load`, so anything that reader rejects (flow mappings, anchors, tabs…) is a
`ContractError` naming the file line: fail closed, never half-read.

`validate(contract, ctas, vague_phrases)` is the schema (`data/schemas/reader-value.schema.json`) plus the
three rules a schema can't express:

  * a CTA-shaped `promised_outcome`: a CTA phrase is in it and fewer than six words are left once every CTA phrase is
    removed. The sales CTA never counts as reader value;
  * a CTA-shaped `first_action`: any CTA phrase in it. The first useful action is the reader's own;
  * a vague `original_value`: the whole value is one of the vague phrases ("unique insights", "expert advice").

CTA phrases (`ctas`) are the shipped `data/claims.toml` `[reader_value] cta_phrases` plus the project's own
(`cta_phrases(cwd)` merges them); vague phrases are shipped only. Findings are `{"severity": "error", "message"}`.

The delivery gate (the producer never awards its own pass) mirrors the claims checker's CLI side:

  * `delivery_input` names the files the read-only `delivery-checker` agent reads (the draft, its contract, the
    rubric `data/rubrics/delivery.md`) and the hashes it copies back. It refuses a contract that doesn't validate
    (ContractNotReady) and a contract that is the draft itself.
  * `record_delivery` writes `<key>.delivery.json`, bound to the draft, contract and rubric hashes. The reply holds
    one verdict per item in DELIVERY_ITEMS; a `pass` needs evidence found verbatim in the draft. Module findings
    (`modules.check`) fail the gate. Only the isolated reviewer (`reviewer = "delivery-checker"`) can make the
    record's `result` PASS: a writer's own reading (`reviewer = "self-check"`) records its `reading`, and its
    `result` is FAIL or INCOMPLETE, never PASS.
  * `delivery_status` reads the record back: PASS only for a current record (all three hashes match the files on
    disk now) from the isolated reviewer that says PASS while the contract still validates; STALE when a hash moved;
    otherwise the record's FAIL or INCOMPLETE. A host reads the gate through it, never through `result` alone.
"""
from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from pathlib import Path

from plainspoken import _util, checker, claims, claims_data, modules, pinning, report, schema
from plainspoken.config import reader_value_settings
from plainspoken.frontmatter import FrontmatterError
from plainspoken.frontmatter import load as load_yaml

__all__ = ["DELIVERY_ITEMS", "DELIVERY_RUBRIC", "REVIEWERS", "TEMPLATE", "ContractError", "ContractNotReady",
           "DeliveryReplyError", "StaleDeliveryReply", "cta_phrases", "default_contract", "delivery_input",
           "delivery_rubric_hash", "delivery_status", "load_contract", "merge_phrases", "record_delivery", "shipped_cta_phrases",
           "shipped_vague_phrases", "validate"]

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "reader-value.toml"
DELIVERY_RUBRIC = ROOT / "data" / "rubrics" / "delivery.md"
# The delivery gate's items, in the rubric's order. `n/a` is a verdict only for the two that can have nothing to
# judge: a draft that asks the reader to do nothing has nothing to disclose, and a draft with no start-here module
# has no summary to match.
DELIVERY_ITEMS = ("outcome", "standalone_action", "disclosure", "success_and_stop", "not_a_pitch", "original_value",
                  "start_here")
_NA_ITEMS = ("disclosure", "start_here")
_VERDICTS = ("pass", "fail", "n/a")
REVIEWERS = ("delivery-checker", "self-check")
_REPLY_KEYS = ('"result"', '"items"')
_HASH_IN_TEXT = re.compile(r'"(article_sha256|contract_sha256)"\s*:\s*"([^"\n]*)"')
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CONTRACT_HEADING = re.compile(r"^Reader Value Contract(?:\s+#+)?$", re.I)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([^`\s]*)")
_LANGS = {"toml": "toml", "json": "json", "yaml": "yaml", "yml": "yaml"}
_YAML_LINE = re.compile(r"^line (\d+): ")
_TOML_LINE = re.compile(r"\bat line (\d+)")
_MIN_OUTCOME_WORDS = 6


class ContractError(ValueError):
    """A contract that can't be read. The message names the file (and the line, where there is one)."""


class ContractNotReady(Exception):
    """The contract reads but doesn't validate: the delivery gate can't run on it. Not a ValueError, because the CLI
    exits 1 for it (INCOMPLETE), not 2 (bad input)."""


class StaleDeliveryReply(Exception):
    """The reply's `article_sha256` / `contract_sha256` are missing or aren't the current hashes: the reviewer read
    another version. Refused with nothing written (exit 1)."""


class DeliveryReplyError(ValueError):
    """The reviewer's reply couldn't be parsed or verified. `record_delivery` has written an INCOMPLETE record."""


# --- phrases ----------------------------------------------------------------------------------------------------
def shipped_cta_phrases() -> tuple[str, ...]:
    """`data/claims.toml` `[reader_value] cta_phrases`."""
    return claims_data.string_list("reader_value", "cta_phrases")


def shipped_vague_phrases() -> tuple[str, ...]:
    """`data/claims.toml` `[reader_value] vague_phrases`."""
    return claims_data.string_list("reader_value", "vague_phrases")


def merge_phrases(base: Iterable[str], extra: Iterable[str]) -> tuple[str, ...]:
    """`base` then `extra`, stripped, dropping blanks and any phrase already present (compared case-insensitively)."""
    seen: set[str] = set()
    out: list[str] = []
    for phrase in (*base, *extra):
        phrase = " ".join(phrase.split())
        if phrase and phrase.casefold() not in seen:
            seen.add(phrase.casefold())
            out.append(phrase)
    return tuple(out)


def cta_phrases(cwd: Path) -> tuple[str, ...]:
    """The shipped CTA phrases plus the project's `[reader_value] cta_phrases`. A malformed config raises
    `ConfigError`."""
    return merge_phrases(shipped_cta_phrases(), reader_value_settings(cwd)["cta_phrases"])


def _pattern(phrases: Iterable[str]) -> re.Pattern[str] | None:
    parts = sorted({r"\s+".join(map(re.escape, p.split())) for p in phrases if p.split()}, key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.I) if parts else None


# --- validation -------------------------------------------------------------------------------------------------
def _error(message: str) -> dict:
    return {"severity": "error", "message": message}


def validate(contract: dict, ctas: tuple[str, ...], vague_phrases: tuple[str, ...]) -> list[dict]:
    """Schema errors, then the CTA and vague-value rules. `[]` when the contract is sound. `ctas` is the CTA phrase
    list (usually `cta_phrases(cwd)`)."""
    findings = [_error(f"schema: {e}") for e in schema.validate(contract, schema.load("reader-value"))]
    if not isinstance(contract, dict):
        return findings
    cta = _pattern(ctas)
    outcome = contract.get("promised_outcome")
    if cta and isinstance(outcome, str) and cta.search(outcome) \
            and len(cta.sub(" ", outcome).split()) < _MIN_OUTCOME_WORDS:
        findings.append(_error("promised_outcome is CTA-shaped: a call to action never counts as reader value. "
                               "Promise what the reader can do, know or decide after reading"))
    action = contract.get("first_action")
    action_text = " ".join(str(v) for v in action.values()) if isinstance(action, dict) else ""
    if cta and action_text and cta.search(action_text):
        findings.append(_error("first_action is CTA-shaped: the first useful action must be the reader's own, "
                               "not contacting or buying from the author"))
    value = contract.get("original_value")
    vague = {" ".join(p.split()).casefold() for p in vague_phrases}
    if isinstance(value, str) and " ".join(value.strip().rstrip(".").split()).casefold() in vague:
        findings.append(_error("original_value is vague filler: name the actual method, data or experience the "
                               "piece contributes"))
    return findings


# --- loading ----------------------------------------------------------------------------------------------------
def load_contract(path: Path) -> dict:
    """Read a contract from a `.toml` or `.json` file, or from the fenced block under `## Reader Value Contract` in
    any other (markdown) file. Unreadable files raise OSError or UnicodeDecodeError; a missing or malformed contract
    raises `ContractError`."""
    path = Path(path)
    text = path.read_text(encoding="utf-8").lstrip("\ufeff")
    suffix = path.suffix.lower()
    if suffix == ".toml":
        return _parse(path, "toml", text, 0)
    if suffix == ".json":
        return _parse(path, "json", text, 0)
    lang, body, offset = _markdown_block(path, text)
    return _parse(path, lang, body, offset)


def _parse(path: Path, lang: str, text: str, offset: int) -> dict:
    """Parse one contract body. `offset` is the file line before the body's first line (0 for a whole file)."""
    where = f"{path} (the {lang} block from line {offset + 1})" if offset else str(path)
    try:
        if lang == "toml":
            data = tomllib.loads(text)
        elif lang == "json":
            data = json.loads(text)
        else:
            data = load_yaml(text)
    except tomllib.TOMLDecodeError as e:  # its message says "(at line N, column M)" of the parsed text
        message = _TOML_LINE.sub(lambda m: f"at line {int(m.group(1)) + offset}", str(e))
        raise ContractError(f"{where}: not valid TOML ({message})") from None
    except json.JSONDecodeError as e:
        raise ContractError(f"{path}: line {e.lineno + offset}: not valid JSON ({e.msg})") from None
    except FrontmatterError as e:
        message = str(e)
        m = _YAML_LINE.match(message)
        if m:
            message = f"line {int(m.group(1)) + offset}: {message[m.end():]}"
        else:
            message = f"line {offset + 1}: {message}"
        raise ContractError(f"{path}: {message} (the YAML reader handles a plain subset only)") from None
    if not isinstance(data, dict):
        raise ContractError(f"{where}: the contract must be a table of fields, not {type(data).__name__}")
    return data


def _markdown_block(path: Path, text: str) -> tuple[str, str, int]:
    """(language, body, offset) for the one contract fence under `## Reader Value Contract`."""
    lines = text.replace("\r\n", "\n").split("\n")
    heading_at: list[int] = []
    fence: tuple[str, int] | None = None  # (marker, length) of the open code fence outside the contract section
    section: int | None = None  # level of the contract heading while scanning its section
    blocks: list[tuple[str, int, int | None]] = []  # (info, opening line index, closing line index)
    i = 0
    while i < len(lines):
        line = lines[i]
        f = _FENCE.match(line)
        if fence is not None:  # inside a code fence: nothing here is a heading
            if f and f.group(1)[0] == fence[0] and len(f.group(1)) >= fence[1] and not f.group(2):
                fence = None
            i += 1
            continue
        h = _HEADING.match(line)
        if h:
            level, title = len(h.group(1)), (h.group(2) or "").strip()
            if section is not None and level <= section:
                section = None
            if _CONTRACT_HEADING.match(title):
                heading_at.append(i)
                section = level
            i += 1
            continue
        if f:
            if section is not None:
                close = _closing_fence(lines, i, f.group(1))
                blocks.append((f.group(2).lower(), i, close))
                if close is None:
                    break
                i = close + 1
                continue
            fence = (f.group(1)[0], len(f.group(1)))
        i += 1
    if not heading_at:
        raise ContractError(f"no Reader Value Contract block in {path} (no '## Reader Value Contract' heading)")
    if len(heading_at) > 1:
        raise ContractError(f"{path}: more than one 'Reader Value Contract' heading "
                            f"(lines {', '.join(str(n + 1) for n in heading_at)})")
    contract = [b for b in blocks if b[0] in _LANGS]
    if not contract:
        other = f"; the fence at line {blocks[0][1] + 1} is {blocks[0][0] or 'untagged'}" if blocks else ""
        raise ContractError(f"no Reader Value Contract block in {path} (no ```toml, ```json or ```yaml fence under "
                            f"the heading at line {heading_at[0] + 1}{other})")
    if len(contract) > 1:
        raise ContractError(f"{path}: more than one contract block under 'Reader Value Contract' "
                            f"(lines {', '.join(str(b[1] + 1) for b in contract)})")
    info, start, end = contract[0]
    if end is None:
        raise ContractError(f"{path}: line {start + 1}: the contract's code fence is never closed")
    return _LANGS[info], "\n".join(lines[start + 1:end]), start + 1


def _closing_fence(lines: list[str], start: int, marker: str) -> int | None:
    for j in range(start + 1, len(lines)):
        f = _FENCE.match(lines[j])
        if f and f.group(1)[0] == marker[0] and len(f.group(1)) >= len(marker) and not f.group(2):
            return j
    return None


# --- the delivery gate ------------------------------------------------------------------------------------------
def default_contract(article: Path, project_root: Path) -> Path:
    """`.plainspoken/reader-value/<draft file name without its extension>.reader-value.toml` under the project."""
    return Path(project_root) / ".plainspoken" / "reader-value" / f"{Path(article).stem}.reader-value.toml"


def delivery_rubric_hash() -> str:
    """`sha256:<hex>` of the delivery rubric's bytes."""
    return claims.article_hash(DELIVERY_RUBRIC)


def _ready_contract(article: Path, contract: Path, project_root: Path) -> list[dict]:
    """The contract's validate findings (`[]` when it's sound). ValueError when the contract is the draft itself;
    ContractError / OSError when it can't be read; ConfigError for a malformed project config."""
    if Path(contract).resolve() == Path(article).resolve():
        raise ValueError(f"{contract} is the draft itself: the contract lives in its own file, never in the draft "
                         "that ships")
    return validate(load_contract(contract), cta_phrases(project_root), shipped_vague_phrases())


def _not_ready(contract: Path, findings: list[dict]) -> ContractNotReady:
    return ContractNotReady(f"the contract {contract} doesn't validate ({len(findings)} finding(s); first: "
                            f"{findings[0]['message']}). Run `reader-value validate` and fix it first.")


def delivery_input(article: Path, contract: Path, project_root: Path) -> dict:
    """The delivery-checker agent's input block. Raises ContractNotReady for a contract that doesn't validate, and
    OSError / ValueError for bad input (an unreadable draft or contract, a contract that is the draft)."""
    findings = _ready_contract(article, contract, project_root)
    if findings:
        raise _not_ready(contract, findings)
    return {"article": str(Path(article).resolve()), "contract": str(Path(contract).resolve()),
            "rubric": str(DELIVERY_RUBRIC), "article_sha256": claims.article_hash(article),
            "contract_sha256": claims.article_hash(contract)}


def _reply_items(reply: dict, has_start_here: bool) -> list[dict]:
    """The reply's items, checked for shape. ValueError for anything but exactly one well-formed item per name in
    DELIVERY_ITEMS."""
    items = reply.get("items")
    if not isinstance(items, list):
        raise ValueError("the reply has no items list")
    seen: dict[str, int] = {}
    for i, it in enumerate(items, start=1):
        if not isinstance(it, dict):
            raise ValueError(f"item {i} isn't an object")
        name, verdict = it.get("item"), it.get("verdict")
        if name not in DELIVERY_ITEMS:
            raise ValueError(f"item {i}: {name!r} isn't one of {', '.join(DELIVERY_ITEMS)}")
        if name in seen:
            raise ValueError(f"item {i}: {name!r} is already item {seen[name]}; give each item once")
        seen[name] = i
        if verdict not in _VERDICTS:
            raise ValueError(f"item {i} ({name}): verdict {verdict!r} isn't pass, fail or n/a")
        if verdict == "n/a" and name not in _NA_ITEMS:
            raise ValueError(f"item {i} ({name}): n/a is only for {' and '.join(_NA_ITEMS)}")
        if verdict == "n/a" and not (isinstance(it.get("why"), str) and it["why"].strip()):
            raise ValueError(f"item {i} ({name}): an n/a verdict needs its reason in `why`")
        if name == "start_here" and (verdict == "n/a") == has_start_here:
            raise ValueError(f"item {i} (start_here): the draft {'has' if has_start_here else 'has no'} start-here "
                             f"module, so the verdict is {'pass or fail' if has_start_here else 'n/a'}")
        evidence = it.get("evidence")
        if evidence is not None and not isinstance(evidence, str):
            raise ValueError(f"item {i} ({name}): evidence is text or null")
    missing = [name for name in DELIVERY_ITEMS if name not in seen]
    if missing:
        raise ValueError(f"the reply has no verdict for {', '.join(missing)}")
    return items


def _verify_items(items: list[dict], article_text: str) -> list[dict]:
    """Each item plus `evidence_verified`: True / False for quoted evidence (found verbatim in the draft, at least
    `checker.MIN_EVIDENCE_WORDS` words), False for a pass with nothing quoted, None for a fail or n/a with none."""
    corpus = [pinning.normalise_evidence(article_text)]
    out = []
    for it in items:
        evidence = it.get("evidence")
        if evidence is None:
            verified = False if it["verdict"] == "pass" else None
        else:
            verified = checker.verbatim(evidence, corpus)
        out.append({**it, "evidence_verified": verified})
    return out


def _reading(reply_result: object, items: list[dict], module_findings: list[dict]) -> str:
    """FAIL when an item fails or a module check finds anything; PASS when the reply says PASS, every item passes
    (or is a permitted n/a) and every quote verified; INCOMPLETE otherwise."""
    if module_findings or any(it["verdict"] == "fail" for it in items):
        return "FAIL"
    if reply_result == "PASS" and not any(it["evidence_verified"] is False for it in items):
        return "PASS"
    return "INCOMPLETE"


def record_delivery(article: Path, contract: Path, reply_text: str, record_path: Path, display: dict,
                    project_root: Path, reviewer: str = "delivery-checker") -> dict:
    """Verify a delivery reply and write the record to `record_path`; returns the record.

    `reviewer` is "delivery-checker" (the isolated agent's reply) or "self-check" (the writer's own reading,
    recorded but never a PASS). Writes nothing, and leaves any earlier record, for a reply bound to other hashes
    (StaleDeliveryReply), even one that can't be parsed but names another draft or contract hash. A reply that
    can't be parsed or verified writes an INCOMPLETE record, then raises DeliveryReplyError; a contract that no
    longer validates writes an INCOMPLETE record, then raises ContractNotReady. OSError / ValueError for bad input,
    with nothing written. `display` holds the `article` and `contract` names to record."""
    if reviewer not in REVIEWERS:
        raise ValueError(f"reviewer {reviewer!r} isn't one of {', '.join(REVIEWERS)}")
    findings = _ready_contract(article, contract, project_root)
    article_sha, contract_sha = claims.article_hash(article), claims.article_hash(contract)
    article_text = Path(article).read_text(encoding="utf-8")
    base = {**display, "article_sha256": article_sha, "contract_sha256": contract_sha,
            "rubric_sha256": delivery_rubric_hash(), "reviewer": reviewer}

    def write(result: str, *, reading: str | None, reply: dict | None, items: list, module_findings: list,
              error: str | None) -> dict:
        rec = {**base, "result": result, "reading": reading, "recorded_at": _util.now_iso(),
               "reply_result": reply.get("result") if reply else None, "reply_error": error,
               "failed": sum(it.get("verdict") == "fail" for it in items),
               "unverified_evidence": sum(it.get("evidence_verified") is False for it in items),
               "reply_had_prose": reply.get("reply_had_prose") if reply else None,
               "items": items, "module_findings": module_findings}
        report.write_atomic(record_path, json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
        return rec

    def rejected(e: Exception) -> DeliveryReplyError:
        write("INCOMPLETE", reading=None, reply=None, items=[], module_findings=[], error=str(e))
        return DeliveryReplyError(str(e))

    current = {"article_sha256": article_sha, "contract_sha256": contract_sha}
    try:
        data, had_prose = checker.reply_object(reply_text, _REPLY_KEYS)
    except ValueError as e:
        if any(current[k] != v for k, v in _HASH_IN_TEXT.findall(reply_text)):
            raise StaleDeliveryReply(f"stale reply: it couldn't be read ({e}), and it names hashes other than the "
                                     "current ones, so it answered another version. Run `reader-value "
                                     "deliver-input` and the reviewer again.") from None
        raise rejected(e) from None
    for key, now in current.items():
        said = data.get(key)
        if said != now:
            what = f"carries no {key}" if said is None else f"has {key} {str(said)[:80]!r}, not the current {now}"
            raise StaleDeliveryReply(f"stale reply: it {what}, so it read another version. Run `reader-value "
                                     "deliver-input` and the reviewer again.")
    if findings:
        not_ready = _not_ready(contract, findings)
        write("INCOMPLETE", reading=None, reply=None, items=[], module_findings=[], error=str(not_ready))
        raise not_ready
    data["reply_had_prose"] = had_prose
    module_findings = modules.check(article_text)
    try:
        if data.get("result") not in ("PASS", "FAIL"):
            raise ValueError(f"the reply's result is {data.get('result')!r}, not PASS or FAIL")
        items = _verify_items(_reply_items(data, modules.opens(article_text, "start-here")), article_text)
    except ValueError as e:
        raise rejected(e) from None
    reading = _reading(data.get("result"), items, module_findings)
    result = reading if reviewer == "delivery-checker" else ("FAIL" if reading == "FAIL" else "INCOMPLETE")
    return write(result, reading=reading, reply=data, items=items, module_findings=module_findings, error=None)


def delivery_status(article: Path, contract: Path, record_path: Path, project_root: Path) -> dict:
    """`{"status": PASS | FAIL | INCOMPLETE | STALE, "reasons": [...], "record": <the record or None>}` for the
    delivery record at `record_path`, read against the draft, contract and rubric on disk now. Writes nothing.

    PASS needs a readable record whose `article_sha256`, `contract_sha256` and `rubric_sha256` all match now, whose
    `reviewer` is "delivery-checker" and whose `result` is PASS, and a contract that still validates. A hash that moved
    is STALE (an old PASS never stands for new text). A self-check record is never PASS, whatever its `result` says.
    OSError / ValueError when the draft or contract can't be read (ContractError names the file)."""
    findings = _ready_contract(article, contract, project_root)
    now = {"article_sha256": claims.article_hash(article), "contract_sha256": claims.article_hash(contract),
           "rubric_sha256": delivery_rubric_hash()}
    path = Path(record_path)
    if not path.exists():
        return {"status": "INCOMPLETE", "reasons": [f"no delivery record at {path}: run deliver mode"],
                "record": None}
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        rec = None
    keys = ("result", "reviewer", *now)
    if not isinstance(rec, dict) or not all(isinstance(rec.get(k), str) for k in keys):
        return {"status": "INCOMPLETE", "reasons": [f"delivery record unreadable: {path}"], "record": None}
    moved = [what for key, what in (("article_sha256", "draft"), ("contract_sha256", "contract"),
                                    ("rubric_sha256", "rubric")) if rec[key] != now[key]]
    if moved:
        return {"status": "STALE", "reasons": [f"delivery record stale ({', '.join(moved)} changed since it was "
                                               "recorded): run deliver mode again"], "record": rec}
    reasons: list[str] = []
    if findings:
        reasons.append(str(_not_ready(contract, findings)))
    if rec["reviewer"] != "delivery-checker":
        reasons.append(f"reviewer is {rec['reviewer']!r}: a self-check is never a pass; only the isolated "
                       "delivery-checker's reply can pass the gate")
    result = rec["result"] if rec["result"] in ("PASS", "FAIL", "INCOMPLETE") else "INCOMPLETE"
    if result == "FAIL":
        return {"status": "FAIL", "reasons": reasons, "record": rec}
    if reasons or result != "PASS":
        if result != "PASS" and not reasons:
            reasons.append(f"the record says {rec['result']}")
        return {"status": "INCOMPLETE", "reasons": reasons, "record": rec}
    return {"status": "PASS", "reasons": [], "record": rec}
