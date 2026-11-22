"""Carrying a JR accept across a fix (#188).

A fix pass changes the article's hash, and the justification file and JR review are bound to that hash, so every
kept WARN used to need a fresh reason and a fresh JR call, even one the fix didn't touch. `<key>.carry.json` keeps,
for each rule JR accepted in this run, the kind and reason it accepted and a hash per evidence item it saw. `merge`
writes it, never the skill. A later draft's justification for that rule carries the accept, with no JR call, only
when all of these hold, else the rule goes to JR as before:

- the carry file was written under this profile, ruleset and content type;
- the rule is lint-owned (`source` `lint`): a judge's evidence can be recorded again for the same draft, the lint's
  can't (it's a function of the draft, the profile and the ruleset);
- its kind and reason are the ones JR accepted, character for character;
- every evidence item JR would see now is one it saw then: the same finding (line number aside) in the same text.

The text an item is bound to is its section as written (from its H2 heading to the next) for the rules whose lint
finding is about that section alone (`SECTION_RULES`), and the whole article for every other rule and for a finding
with no line, so those carry only when the article hasn't changed (a reason rewritten for another rule, say). A
reject is never carried, and a later reject of the same rule deletes its accept. `meaning-diff --start` deletes the
file, so a run never carries an earlier run's accept.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Rules whose lint findings are about text inside the H2 section holding the finding's line, verified per check:
# 7 (a run of sentences in one section), 7d and NR-2 (one section's sentences), 12e (a run of bullets, which a
# heading ends) and 13 (the heading itself). Count rules (2b, 4a2, 23, 25), 12d (a run of paragraphs across sections),
# 24 (every curly line), whole-article metrics and anything added later are bound to the whole article.
SECTION_RULES = frozenset({"7", "7d", "NR-2", "12e", "13"})
STAMPS = ("profile_sha256", "ruleset_version", "content_type")


def _h(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _section_text(doc, line: int) -> str:
    """The source lines of the H2 section holding `line`, as written; the whole text for a line outside the body."""
    lines = doc.lines
    if not isinstance(line, int) or isinstance(line, bool) or not 0 < line <= len(lines):
        return "\n".join(lines)
    starts = sorted({1, *(s.line for s in doc.sections if s.level == 2)})
    start = max(s for s in starts if s <= line)
    end = min([s for s in starts if s > line] or [len(lines) + 1])
    return "\n".join(lines[start - 1:end - 1])


def spans(rid: str, items: list, doc) -> list[str] | None:
    """One hash per evidence item: the finding with its line left out, and the text it's bound to. None when any item
    isn't a lint finding, so the rule can't carry."""
    out = []
    for f in items:
        if not isinstance(f, dict) or f.get("source", "lint") != "lint" or f.get("rule") != rid:
            return None
        text = _section_text(doc, f.get("line")) if rid in SECTION_RULES else "\n".join(doc.lines)
        out.append(_h(rid, str(f.get("severity")), str(f.get("excerpt")), str(f.get("message")), text))
    return out or None


def load(path: Path, stamps: dict) -> dict[str, dict]:
    """rule id → its carried accept, from a carry file written under `stamps`; {} for a missing, damaged or other
    file (nothing carries)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or any(data.get(k) != stamps.get(k) for k in STAMPS):
        return {}
    rules = data.get("rules")
    if not isinstance(rules, dict):
        return {}
    return {rid: r for rid, r in rules.items()
            if isinstance(r, dict) and all(isinstance(r.get(k), str) for k in ("kind", "reason", "review_reason"))
            and isinstance(r.get("spans"), list) and all(isinstance(s, str) for s in r["spans"])}


def matches(rid: str, entry: dict, record: dict[str, dict]) -> dict | None:
    """The carried accept for `rid` when every evidence span of its report entry is one JR saw; None otherwise. The
    caller still compares the kind and reason."""
    got = record.get(rid)
    now = entry.get("spans") if isinstance(entry, dict) and entry.get("source") == "lint" else None
    if got is None or not isinstance(now, list) or not now or not set(now) <= set(got["spans"]):
        return None
    return got


def decide(rules: dict, items: dict[str, dict], record: dict[str, dict]) -> dict[str, dict]:
    """rule id → carried accept, for each justification in `items` (rule id → item) whose kind and reason are the
    accepted ones and whose evidence JR saw (`matches`)."""
    out = {}
    for rid, it in sorted(items.items()):
        got = matches(rid, rules.get(rid, {}), record)
        if (got is not None and it.get("kind") == got["kind"] and isinstance(it.get("reason"), str)
                and it["reason"].strip() == got["reason"]):
            out[rid] = got
    return out


def updated(record: dict[str, dict], rules: dict, reviewed: dict[str, dict], sha: str) -> dict[str, dict]:
    """The carry file's rules after a JR review this merge validated: an accept of a lint-owned rule with spans is
    saved (replacing an earlier one), any other verdict deletes the rule's accept."""
    out = dict(record)
    for rid, v in reviewed.items():
        out.pop(rid, None)
        entry = rules.get(rid, {})
        if v["review"] == "accept" and entry.get("source") == "lint" and entry.get("spans"):
            out[rid] = {"kind": v["kind"], "reason": v["reason"], "review_reason": v["review_reason"],
                        "spans": list(entry["spans"]), "article_sha256": sha}
    return out


def payload(stamps: dict, rules: dict[str, dict]) -> str:
    return json.dumps({**{k: stamps.get(k) for k in STAMPS}, "rules": rules}, indent=2, ensure_ascii=False) + "\n"
