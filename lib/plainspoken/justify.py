"""Fix or justify (2026-09-29): WARN justifications and their JR review.

A WARN rule that still fails after the fix pass is resolved only by a justification in `<key>.justify.json`
that the isolated JR reviewer accepts in `<key>.JR.judge.json`. The justification file is bound to the
article's hash; the review is bound to the article's hash AND the justification file's hash, so editing either
after the review voids it. Only WARN rules can be justified."""
import hashlib
import json
from pathlib import Path

KINDS = ("voice", "quote", "load_bearing", "false_positive", "format", "metric")
MIN_REASON = 15


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict | None:
    """The JSON object at `path`, or None when it's missing, unreadable or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def validate_justify(data: dict) -> list[str]:
    """Shape errors in a justification file (empty list = valid)."""
    errors = []
    if not isinstance(data.get("article_sha256"), str):
        errors.append("justify: article_sha256 missing")
    items = data.get("items")
    if not isinstance(items, list):
        return errors + ["justify: items must be a list"]
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, dict) or not it.get("rule"):
            errors.append(f"justify: item without a rule: {it!r}")
            continue
        rid = str(it["rule"])
        if rid in seen:
            errors.append(f"justify: rule {rid} is justified twice")
        seen.add(rid)
        if it.get("kind") not in KINDS:
            errors.append(f"justify: rule {rid}: kind must be one of {', '.join(KINDS)}")
        reason = it.get("reason")
        if not isinstance(reason, str) or len(reason.strip()) < MIN_REASON:
            errors.append(f"justify: rule {rid}: reason must be a real sentence ({MIN_REASON}+ characters)")
        elif len(reason.strip().splitlines()) > 1:
            errors.append(f"justify: rule {rid}: reason must be one line")
    return errors


def validate_review(data: dict, rules: set[str]) -> list[str]:
    """Errors in a JR review: exactly one accept/reject verdict, with a reason, for each rule in `rules`."""
    verdicts = data.get("verdicts")
    if not isinstance(verdicts, list):
        return ["JR: no verdicts list"]
    errors, seen = [], set()
    for v in verdicts:
        rid = str(v.get("rule")) if isinstance(v, dict) else "?"
        ok = (isinstance(v, dict) and rid in rules and rid not in seen and v.get("verdict") in ("accept", "reject")
              and isinstance(v.get("reason"), str) and bool(v["reason"].strip()))
        if not ok:
            errors.append(f"JR: bad verdict entry for rule {rid}")
            continue
        seen.add(rid)
    errors += [f"JR: no verdict for rule {rid}" for rid in sorted(rules - seen)]
    return errors


def resolve(d: Path, key: str, sha: str, warns: list[str], stamps: dict | None = None) -> dict:
    """Which failing WARN rules (`warns`) an accepted justification resolves.

    With no failing WARN rule nothing is read. No justification file = nothing resolved (the article is
    UNRESOLVED; that's a content state, not a problem). A stale, unreadable or malformed justification file, or
    a missing, stale or malformed review, is a problem (→ INCOMPLETE: rerun the named step, don't edit the
    article). Justifications for rules not in `warns` (passing rules, BLOCK rules) are listed as unused.
    `stamps` (profile_sha256, ruleset_version) must match the review's, when given (merge always gives them)."""
    out: dict = {"accepted": set(), "justified": [], "unused": [], "problems": []}
    jpath = d / f"{key}.justify.json"
    if not warns or not jpath.exists():
        return out
    data = read_json(jpath)
    if data is None:
        out["problems"].append("justify: file unreadable or not a JSON object — rewrite it (`justify --template`)")
        return out
    if data.get("article_sha256") != sha:
        out["problems"].append("justify: written for an older version of the article — rewrite it "
                               "(`justify --template`) and rerun JR")
        return out
    errors = validate_justify(data)
    if errors:
        out["problems"] += errors
        return out
    items = {str(it["rule"]): it for it in data["items"]}
    relevant = {rid: it for rid, it in items.items() if rid in warns}
    out["unused"] = sorted(set(items) - set(relevant))
    if not relevant:
        return out
    review = read_json(d / f"{key}.JR.judge.json")
    if review is None:
        out["problems"].append("JR: review missing or not valid JSON — dispatch the JR judge "
                               "(`justify --review-input`)")
        return out
    if review.get("article_sha256") != sha or review.get("justify_sha256") != file_sha(jpath):
        out["problems"].append("JR: stale (the article or the justifications changed after the review) — rerun JR")
        return out
    if stamps and any(review.get(k) != v for k, v in stamps.items()):
        out["problems"].append("JR: reviewed under another profile or ruleset (stale) — rerun JR")
        return out
    errors = validate_review(review, set(relevant))
    if errors:
        out["problems"] += errors
        return out
    verdicts = {str(v["rule"]): v for v in review["verdicts"]}
    for rid in sorted(relevant):
        it, v = relevant[rid], verdicts[rid]
        out["justified"].append({"rule": rid, "kind": it["kind"], "reason": it["reason"].strip(),
                                 "review": v["verdict"], "review_reason": v["reason"].strip()})
        if v["verdict"] == "accept":
            out["accepted"].add(rid)
    return out


def template(report: dict, existing: dict | None = None) -> dict:
    """A justification skeleton with one item per failing WARN rule in the report (JR-accepted ones included, so
    a rewrite doesn't drop them). A rule's kind and reason carry over from `existing` only when that file was
    written for the report's version of the article; otherwise they're left blank for the writer."""
    sha = report["article_sha256"]
    kept: dict[str, dict] = {}
    items = existing.get("items") if isinstance(existing, dict) and existing.get("article_sha256") == sha else None
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and it.get("rule"):
            kept.setdefault(str(it["rule"]), it)

    def field(rid: str, key: str) -> str:
        value = kept.get(rid, {}).get(key, "")
        return value if isinstance(value, str) else ""

    return {"article_sha256": sha, "items": [{"rule": rid, "kind": field(rid, "kind"), "reason": field(rid, "reason")}
                                             for rid in report.get("warns", [])]}


def review_input(report: dict, data: dict, justify_sha: str) -> dict:
    """What the JR judge receives: each justification that covers a failing WARN rule, with that rule's evidence
    (judge evidence, else the lint's WARN findings)."""
    items = []
    for it in data["items"]:
        rid = str(it["rule"])
        if rid not in report.get("warns", []):
            continue
        entry = report.get("rules", {}).get(rid, {})
        evidence = entry.get("evidence") or [f for f in entry.get("findings", []) if f.get("severity") == "WARN"]
        items.append({"rule": rid, "kind": it["kind"], "reason": it["reason"], "evidence": evidence})
    return {"group": "JR", "article": report["article"], "article_sha256": report["article_sha256"],
            "justify_sha256": justify_sha, "items": items}
