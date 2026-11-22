"""Pre-existing judge verdicts (#200). A judge's fail is pre-existing when every quote in its evidence sits in a
sentence that hasn't changed since the judges last read the draft, and the round before didn't fail that rule on
any of those sentences: a late find on old text, not something the last fix did. `merge` marks the rule entry
`pre_existing`, and the check skill doesn't count a fix pass that only has those to fix.

`<key>.rounds.json` keeps the last two judged drafts (completed merges, each a different version): the draft's
sha256, a 16-hex hash per sentence (`sentdiff.units`, compared after `pinning.normalise_evidence`) and, for each rule
a judge failed, the sentences its evidence quoted (null when a quote couldn't be placed). It never holds the draft's
text. `meaning-diff --start` deletes it, so a run never compares with an earlier one's rounds.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from plainspoken import pinning, report, sentdiff

_ELLIPSIS = "..."  # normalise_evidence turns "…" into this; a quote's fragments either side are matched alone


def fingerprint(text: str) -> dict:
    """The draft's sentences, normalised, with their hashes and where each sits in the sentences joined by spaces."""
    norms = [pinning.normalise_evidence(u[0]) for u in sentdiff.units(text)]
    starts, pos = [], 0
    for n in norms:
        starts.append(pos)
        pos += len(n) + 1
    return {"norms": norms, "starts": starts, "joined": " ".join(norms),
            "hashes": [hashlib.sha256(n.encode("utf-8")).hexdigest()[:16] for n in norms]}


def quoted_units(quote: object, fp: dict) -> set[int] | None:
    """Every sentence index a quote touches, over every place each of its fragments appears; None when the quote is
    empty or a fragment isn't in the draft (it can't be placed, so it's never called pre-existing)."""
    frags = [f.strip() for f in pinning.normalise_evidence(quote).split(_ELLIPSIS)] if isinstance(quote, str) else []
    frags = [f for f in frags if f]
    if not frags:
        return None
    joined, starts, norms, out = fp["joined"], fp["starts"], fp["norms"], set()
    for frag in frags:
        at, found = joined.find(frag), False
        while at >= 0:
            found = True
            end = at + len(frag)
            out |= {i for i, s in enumerate(starts) if s < end and at < s + len(norms[i])}
            at = joined.find(frag, at + 1)
        if not found:
            return None
    return out


def _judge_fails(rules: dict, fp: dict) -> dict[str, list[int] | None]:
    """rule id → the sentences a judge's fail quoted (None when any quote can't be placed), for judge entries only."""
    out: dict[str, list[int] | None] = {}
    for rid, e in rules.items():
        if not str(e.get("source", "")).startswith("judge:") or e.get("judge_verdict") != "fail":
            continue
        units: set[int] | None = set()
        for item in e.get("evidence") or []:
            got = quoted_units(item.get("quote") if isinstance(item, dict) else None, fp)
            if got is None:
                units = None
                break
            units |= got
        out[rid] = sorted(units) if units else None
    return out


def _slots(path: Path) -> list[dict]:
    """The saved rounds, oldest first; [] for a missing or damaged file."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        slots = data["rounds"]
        if (isinstance(slots, list) and len(slots) <= 2
                and all(isinstance(s, dict) and isinstance(s.get("article_sha256"), str)
                        and isinstance(s.get("hashes"), list) and isinstance(s.get("seen"), dict) for s in slots)):
            return slots
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return []


def mark(rules: dict, text: str, sha: str, path: Path, *, complete: bool) -> list[str]:
    """Set `pre_existing: true` on each judge entry in `rules` (merge's `rules_out`) that's pre-existing against the
    last judged draft other than this one, and return those rule ids, sorted. A complete merge saves this round
    (replacing an earlier save of the same draft), keeping the one before it; an INCOMPLETE one saves nothing."""
    fp = fingerprint(text)
    fails = _judge_fails(rules, fp)
    slots = _slots(path)
    older = [s for s in slots if s["article_sha256"] != sha]
    base = older[-1] if older else None
    marked = []
    if base is not None:
        same = {}  # this draft's sentence index → the base's, for each sentence that didn't change
        for tag, i1, i2, j1, _ in sentdiff.opcodes(base["hashes"], fp["hashes"]):
            if tag == "equal":
                same.update({j1 + k: i1 + k for k in range(i2 - i1)})
        for rid, units in sorted(fails.items()):
            seen = base["seen"].get(rid, [])  # None: the round before failed it on a quote it couldn't place
            if (units and isinstance(seen, list) and all(j in same for j in units)
                    and not {same[j] for j in units} & set(seen)):
                rules[rid]["pre_existing"] = True
                marked.append(rid)
    if complete:
        now = {"article_sha256": sha, "hashes": fp["hashes"], "seen": fails}
        report.write_atomic(path, json.dumps({"rounds": ([base] if base else []) + [now]}) + "\n")
    return marked
