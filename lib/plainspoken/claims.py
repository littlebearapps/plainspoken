"""Claim ledgers: load (TOML or JSON), validate, find the ledger for an article, and report its status.

One ledger per article, `<ledger_dir>/<report key>.claims.toml` (or `.claims.json`; `ledger_path_for`), validated
against `data/schemas/claim-ledger.schema.json` plus the rules JSON Schema can't express:

  * claim ids are unique within the ledger;
  * `source_content_hash` matches the current article (a stale hash means every verification predates the
    current wording);
  * `blocking` claims, and sensitive first-hand claims the owner hasn't approved, are surfaced as `blocking`;
  * a `coverage_status` other than `complete` is surfaced (report the article as incomplete, never as passing);
  * a `human_signoff` whose wording no longer appears in the article is void (both sides through
    `pinning.normalise_text`: typographic quotes and whitespace only, so case still counts);
  * an aggregator source never supports a verified claim.

Findings are `{"severity": "error"|"blocking"|"warning", "claim_id": str|None, "message": str}`. No findings means
the ledger is valid and fresh, not that its claims are true. `status()` is the only thing that says PASS, and only
with the isolated checker's current PASS: the producer never awards its own pass.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from plainspoken import _util, config, pinning, schema

SUFFIXES = (".toml", ".json")


class LedgerError(ValueError):
    """A ledger that can't be read or parsed. The message names the file (and, for TOML, the line)."""


def article_hash(path: Path) -> str:
    """`sha256:<hex>` of the file's bytes: an article, a ledger, the rubric or the matrix (every claims-side hash)."""
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hash_or_none(path: Path) -> str | None:
    """`article_hash`, or None when the file can't be read (missing, unreadable, a NUL in the path)."""
    try:
        return article_hash(path)
    except (OSError, ValueError):  # ValueError: a NUL in the path
        return None


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} isn't valid JSON")


def no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    """A `json.loads` object_pairs_hook: a key repeated in one object is a ValueError, never last-one-wins."""
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def strict_json(text: str) -> object:
    """`json.loads` that refuses what a ledger or a checker reply must never hold: a key repeated in one object, and
    NaN / Infinity. Raises json.JSONDecodeError, ValueError or RecursionError."""
    return json.loads(text, object_pairs_hook=no_duplicates, parse_constant=_reject_constant)


def load_ledger(path: Path) -> dict:
    """Read a `.toml` (tomllib) or `.json` ledger. Raises LedgerError naming the file on anything else."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise LedgerError(f"{path}: unsupported ledger format {path.suffix or '(none)'!r}: "
                          "use .claims.toml or .claims.json")
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise LedgerError(f"{path}: no such ledger") from None
    except UnicodeDecodeError:
        raise LedgerError(f"{path}: not UTF-8 text") from None
    except OSError as e:
        raise LedgerError(f"{path}: can't read the ledger ({e.strerror or type(e).__name__})") from None
    except ValueError:  # e.g. a NUL in the path
        raise LedgerError(f"{_shown(path)}: not a usable ledger path") from None
    if suffix == ".toml":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:  # the message carries "(at line N, column M)"
            raise LedgerError(f"{path}: not valid TOML: {e}") from None
        except RecursionError:
            raise LedgerError(f"{path}: not valid TOML: nested too deeply") from None
    else:
        try:
            data = strict_json(text)
        except json.JSONDecodeError as e:
            raise LedgerError(f"{path}: not valid JSON: {e.msg} (at line {e.lineno}, column {e.colno})") from None
        except (ValueError, RecursionError) as e:
            raise LedgerError(f"{path}: not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise LedgerError(f"{path}: the ledger must be an object at the top level")
    return data


def _shown(path: object) -> str:
    """A path for a message: as text, with a NUL written `\\x00` (never a repr, never a raw NUL)."""
    return str(path).replace("\x00", "\\x00")


def _finding(severity: str, claim_id: object, message: str) -> dict:
    return {"severity": severity, "claim_id": claim_id if isinstance(claim_id, str) else None, "message": message}


def _claims(ledger: dict) -> list[dict]:
    items = ledger.get("claims")
    return [c for c in items if isinstance(c, dict)] if isinstance(items, list) else []


def _article_text(root: Path, src: str) -> tuple[Path, bytes | None]:
    art = Path(root) / src
    try:
        return art, art.read_bytes() if art.is_file() else None
    except OSError:
        return art, None


def validate_ledger(path: Path, project_root: Path) -> list[dict]:
    """Validate one ledger file; `project_root` resolves its `source_file`. Raises LedgerError when the ledger can't
    be read or parsed."""
    return validate(load_ledger(path), project_root)


def validate(ledger: dict, project_root: Path) -> list[dict]:
    """`validate_ledger` for a ledger already loaded (`load_ledger`)."""
    findings = [_finding("error", None, f"schema: {m}") for m in schema.validate(ledger, schema.load("claim-ledger"))]
    claims = _claims(ledger)

    seen: set[str] = set()
    for c in claims:
        cid = c.get("claim_id")
        if isinstance(cid, str) and cid in seen:
            findings.append(_finding("error", cid, f"duplicate claim_id {cid!r}"))
        if isinstance(cid, str):
            seen.add(cid)

    src = ledger.get("source_file")
    article_norm: str | None = None
    if isinstance(src, str) and "\x00" in src:
        findings.append(_finding("error", None, f"source_file contains a NUL character: {_shown(src)}"))
    if pinning.safe_relative(src):
        art, data = _article_text(project_root, src)
        if data is None:
            findings.append(_finding("error", None, f"source_file not found: {src}"))
        else:
            recorded = ledger.get("source_content_hash")
            actual = "sha256:" + hashlib.sha256(data).hexdigest()
            if isinstance(recorded, str) and recorded and recorded != actual:
                findings.append(_finding("error", None, (
                    "stale verification: source_content_hash doesn't match the current article "
                    f"({src} changed after this ledger was checked). Re-verify the affected claims and refresh "
                    "the hash; never keep a pass based on an earlier version.")))
            article_norm = pinning.normalise_text(data.decode("utf-8", errors="replace"))

    for c in claims:
        cid = c.get("claim_id")
        status = c.get("status")
        if status == "blocking":
            findings.append(_finding("blocking", cid, f"blocking claim unresolved: {str(c.get('text', ''))[:120]}"))
        scope = c.get("first_hand_scope")
        if (status != "removed" and isinstance(scope, dict) and scope.get("sensitive") is True
                and scope.get("approved_by_owner") is not True):  # removed is audit history: it never publishes
            findings.append(_finding("blocking", cid, (
                "sensitive first-hand claim: owner approval required before publication "
                "(set first_hand_scope.approved_by_owner = true once the owner has approved it)")))
        source = c.get("source")
        if status == "verified" and isinstance(source, dict) and source.get("source_tier") == "aggregator":
            findings.append(_finding("error", cid, (
                "aggregator source on a verified claim: an aggregator never supports a claim: trace to the origin "
                "or cut")))
        signoff = c.get("human_signoff")
        wording = signoff.get("wording") if isinstance(signoff, dict) else None
        if article_norm is not None and isinstance(wording, str) and wording.strip():
            if pinning.normalise_text(wording) not in article_norm:
                findings.append(_finding("error", cid, (
                    f"voided sign-off: the signed wording no longer appears in {src}. The approval was bound to "
                    "the exact wording: review and sign again, or remove the block.")))

    for c in claims:  # the schema subset has no anyOf, so "inputs or derived_from_external" is checked here
        derivation = c.get("derivation")
        if isinstance(derivation, dict) and "inputs" not in derivation and "derived_from_external" not in derivation:
            findings.append(_finding("error", c.get("claim_id"), (
                "a derivation needs inputs (claim ids) or derived_from_external (files or URLs)")))

    coverage = ledger.get("coverage_status")
    if coverage and coverage != "complete":
        findings.append(_finding("warning", None, (
            f"coverage_status={coverage}: report as incomplete, not passing")))
    return findings


def _ledger_file(ledger_dir: Path, name: str) -> Path:
    """`<name>.claims.toml`, or the `.claims.json` sibling when only that exists."""
    toml_path, json_path = ledger_dir / f"{name}.claims.toml", ledger_dir / f"{name}.claims.json"
    return json_path if not toml_path.exists() and json_path.exists() else toml_path


def _names_article(ledger: Path, article: Path, project_root: Path) -> bool | None:
    """Whether the ledger's `source_file` is `article`: None when that can't be told (the ledger can't be read, or
    its source_file is missing, unsafe or names no file)."""
    try:
        src = load_ledger(ledger).get("source_file")
    except LedgerError:
        return None
    if not pinning.safe_relative(src):
        return None
    try:
        named = Path(project_root) / src
        if not named.is_file():
            return None
        return named.resolve() == Path(article).resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def ledger_path_for(article: Path, project_root: Path) -> Path:
    """`<ledger_dir>/<key>.claims.toml`, or the `.claims.json` sibling when only that exists. `key` is the report
    key (`_util.path_key`: the stem plus 8 hex of the project-relative path), so two `index.md` files in different
    folders never share a ledger. `ledger_dir` is `[claims] ledger_dir` from the project config (default
    `.plainspoken/claims`), relative to `project_root`.

    A ledger named for the stem alone (`<stem>.claims.toml`, before v0.5.0) is still used when there's no keyed one
    and its `source_file` is this article; one naming another article belongs to that article. One whose
    `source_file` can't be matched to any file is ambiguous: LedgerError, naming the file to rename it to, never a
    silent pick."""
    root = Path(project_root)
    ledger_dir = root / config.claims_settings(root)["ledger_dir"]
    keyed = _ledger_file(ledger_dir, _util.path_key(article, root))
    if keyed.exists():
        return keyed
    old = _ledger_file(ledger_dir, Path(article).stem)
    if not old.exists():
        return keyed
    owner = _names_article(old, article, root)
    if owner is None:
        raise LedgerError(f"{old}: a ledger named for the stem alone whose source_file can't be matched to an "
                          f"article, so it may not be {Path(article).name}'s. Set its source_file to the article "
                          f"it records and rename it to that article's ledger name (`paths <article>` prints it; "
                          f"for this one it's {keyed.name})")
    return old if owner else keyed


def _derivation_reasons(ledger: dict) -> list[str]:
    """A `derived` claim (not removed) whose `derivation.inputs` names an id that isn't a live claim here. Files and
    URLs belong in `derivation.derived_from_external`, which is never read as claim ids."""
    claims_ = _claims(ledger)
    live = {c.get("claim_id") for c in claims_ if c.get("status") != "removed" and isinstance(c.get("claim_id"), str)}
    out = []
    for c in claims_:
        derivation = c.get("derivation")
        inputs = derivation.get("inputs") if isinstance(derivation, dict) else None
        if c.get("status") != "derived" or not isinstance(inputs, list):
            continue
        for name in inputs:
            if isinstance(name, str) and name not in live:
                out.append(f"{c.get('claim_id') or '-'} is derived from {name}, which isn't a live claim in this "
                           "ledger (absent or removed): re-derive it from live claims or re-verify it (a file or URL "
                           "goes in derivation.derived_from_external)")
    return out


def needs_owner(ledger: dict) -> list[str]:
    """`<id>: <text> (<why>)` for each live claim that waits on the owner: left `blocking`, a sensitive first-hand
    claim not yet approved, or one tagged with a `regulated_class`. A write report's "Needs the owner" is this list,
    so a phrase it asks the owner about is in the ledger, never only in prose (issue #45)."""
    out = []
    for c in _claims(ledger):
        if c.get("status") == "removed":
            continue
        scope = c.get("first_hand_scope")
        why = ["blocking"] if c.get("status") == "blocking" else []
        if isinstance(scope, dict) and scope.get("sensitive") is True and scope.get("approved_by_owner") is not True:
            why.append("owner approval")
        if isinstance(c.get("regulated_class"), str) and c["regulated_class"].strip():
            why.append(f"regulated: {c['regulated_class'].strip()}")
        if why:
            text = " ".join(str(c.get("text", "")).split())[:120]
            out.append(f"{c.get('claim_id') or '-'}: {text} ({', '.join(why)})")
    return out


def status(article: Path, ledger: Path, project_root: Path, gaps: list | None = None,
           check: dict | None = None, loaded: dict | LedgerError | None = None) -> dict:
    """PASS only when the ledger is valid, complete and fresh for this article, every live claim's pins recheck
    against their saved sources (`pinning.status_reasons`), every derivation names live claims, `gaps == []`, and the
    isolated checker's current record says PASS. Anything missing or unknown is INCOMPLETE; a blocking claim or a
    current BLOCKED checker record is BLOCKED, which wins over INCOMPLETE. Notes (`note: …`, last in `reasons`) never
    change the result. A pin's snapshot must live under `[claims] sources_dir` and never be the article; a malformed
    `[claims]` config raises config.ConfigError (the CLI's bad-input exit). `loaded` is the ledger as a caller
    already loaded it (or the LedgerError that gave), so the file is parsed once."""
    article, ledger = Path(article), Path(ledger)
    article_sha = hash_or_none(article)
    ledger_sha = hash_or_none(ledger)
    blocked: list[str] = []
    incomplete: list[str] = []
    notes: list[str] = []
    counts: dict[str, int] = {}

    if article_sha is None:
        incomplete.append(f"article unreadable: {article}")
    try:
        if isinstance(loaded, LedgerError):
            raise loaded
        data = load_ledger(ledger) if loaded is None else loaded
        findings = validate(data, project_root)
    except LedgerError as e:
        data, findings = None, []
        incomplete.append(f"ledger unreadable: {e}")

    if data is not None:
        for c in _claims(data):
            if isinstance(c.get("status"), str):
                counts[c["status"]] = counts.get(c["status"], 0) + 1
        for f in findings:
            if f["severity"] == "blocking":
                blocked.append(f"blocking: {f['message']}")
            elif f["severity"] == "error":
                incomplete.append(f"error: {f['message']}")
        if data.get("coverage_status") != "complete":
            incomplete.append(f"coverage_status is {data.get('coverage_status')!r}, not 'complete'")
        pin_incomplete, notes = pinning.status_reasons(data, Path(project_root), article=article)
        incomplete += pin_incomplete + _derivation_reasons(data)
        src = data.get("source_file")
        if pinning.safe_relative(src) and article_sha is not None:
            try:
                same = (Path(project_root) / src).resolve() == article.resolve()
            except (OSError, ValueError, RuntimeError):  # status never raises: an unresolvable path isn't a match
                same = False
            if not same:
                incomplete.append(f"ledger source_file is {src}, not this article")
            elif data.get("source_content_hash") != article_sha and not any(
                    f["message"].startswith("stale verification") for f in findings):
                incomplete.append("stale verification: the article changed after the ledger was checked")

    if gaps is None:
        incomplete.append("gaps not computed")
    elif gaps:
        incomplete.append(f"{len(gaps)} value(s) in the article aren't in the ledger")

    if not isinstance(check, dict) or check.get("current") is not True:
        incomplete.append("checker not run")
    elif check.get("result") == "BLOCKED":
        blocked.append("checker: BLOCKED")
    elif check.get("result") != "PASS":
        incomplete.append(f"checker result {check.get('result')!r}, not PASS")

    result = "BLOCKED" if blocked else "INCOMPLETE" if incomplete else "PASS"
    return {"status": result, "reasons": blocked + incomplete + notes, "article_sha256": article_sha,
            "ledger_sha256": ledger_sha, "counts": counts}
