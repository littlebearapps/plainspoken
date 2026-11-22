"""Pre-existing judge verdicts (#200). A judge's fail is pre-existing when every quote in its evidence sits in a
sentence that hasn't changed since the judges last read the draft, and the round before didn't fail that rule on
any of those sentences: a late find on old text, not something the last fix did. `merge` marks the rule entry
`pre_existing`, and the check skill doesn't count a fix pass that only has those to fix.

`<key>.rounds.json` keeps the last two judged drafts (completed merges, each a different version): the draft's
sha256, a 16-hex hash per sentence (`sentdiff.units`, compared after `pinning.normalise_evidence`) and, for each rule
a judge failed, the sentences its evidence quoted (null when a quote couldn't be placed). It never holds the draft's
text. `meaning-diff --start` deletes it, so a run never compares with an earlier one's rounds.

The shortcut (#188): after judges who passed everything, with only lint-owned rules failing, a fix that only joins
two neighbouring sentences or splits one reruns the lint and JR and keeps the judges' verdicts. `shortcut` decides
it for `judge-input` and `merge` alike, from each round's `exact` hashes (the sentence as written, links and case
kept) and `lint_only`. A join keeps both sentences' words, joined by a comma, a semicolon, "and" or "but"; a split
is the same in reverse. Any other change, a second pair, or a round a judge failed means the judges read the draft.
A run takes it once: `shortcuts` lists the drafts that took it, and the next qualifying fix gets the judges, the
final judge pass the guard asks for. A carried merge saves no round, since no judge read that draft.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from plainspoken import pinning, report, sentdiff

_ELLIPSIS = "..."  # normalise_evidence turns "…" into this; a quote's fragments either side are matched alone
SHORTCUTS = 1  # #188: per run; the next qualifying fix gets the four judges
_JOINS = (", ", "; ", " and ", " but ", ", and ", ", but ", "; and ", "; but ")  # the rhythm rule's joins


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def fingerprint(text: str) -> dict:
    """The draft's sentences, normalised, with their hashes and where each sits in the sentences joined by spaces;
    `raw` and `exact` are each sentence as written (quotes straightened, spaces collapsed) and its hash."""
    raw = [pinning.normalise_text(u[0]) for u in sentdiff.units(text)]
    norms = [pinning.normalise_evidence(u) for u in raw]
    starts, pos = [], 0
    for n in norms:
        starts.append(pos)
        pos += len(n) + 1
    return {"norms": norms, "starts": starts, "joined": " ".join(norms),
            "hashes": [_h(n) for n in norms], "raw": raw, "exact": [_h(r) for r in raw]}


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


def _load(path: Path) -> tuple[list[dict], list[str]]:
    """(the saved rounds, oldest first; the drafts that took the shortcut). ([], []) for a missing or damaged file."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        slots = data["rounds"]
        cuts = data.get("shortcuts", [])
        if (isinstance(slots, list) and len(slots) <= 2
                and all(isinstance(s, dict) and isinstance(s.get("article_sha256"), str)
                        and isinstance(s.get("hashes"), list) and isinstance(s.get("seen"), dict) for s in slots)
                and isinstance(cuts, list) and all(isinstance(c, str) for c in cuts)):
            return slots, cuts
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return [], []


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _is_join(pair: list[str], new: str) -> bool:
    """Whether `new` is the two sentences hashed in `pair`, in order, in their own words: the first's full stop
    swapped for one of `_JOINS`, the second's first letter lowercased or not."""
    first, second = pair
    for sep in _JOINS:
        at = new.find(sep)
        while at > 0:
            head, tail = new[:at], new[at + len(sep):]
            if tail and _h(head + ".") == first and second in (_h(tail), _h(_cap(tail))):
                return True
            at = new.find(sep, at + 1)
    return False


def _is_split(old: str, pair: list[str]) -> bool:
    """Whether the two sentences in `pair` are the one hashed as `old`, split at one of `_JOINS`."""
    head, tail = pair
    if not head.endswith(".") or not tail:
        return False
    return any(_h(head[:-1] + sep + t) == old for sep in _JOINS for t in {tail, tail[:1].lower() + tail[1:]})


def _join_or_split(base: dict, fp: dict) -> str | None:
    """"join" or "split" when the draft is the base's sentences with one pair joined or one sentence split, the
    rest unchanged; "none" when no sentence changed; None for any other change."""
    found = []
    for tag, i1, i2, j1, j2 in sentdiff.opcodes(base["exact"], fp["exact"]):
        if tag == "equal":
            continue
        if tag == "replace" and (i2 - i1, j2 - j1) == (2, 1) and _is_join(base["exact"][i1:i2], fp["raw"][j1]):
            found.append("join")
        elif tag == "replace" and (i2 - i1, j2 - j1) == (1, 2) and _is_split(base["exact"][i1], fp["raw"][j1:j2]):
            found.append("split")
        else:
            return None
    return found[0] if len(found) == 1 else ("none" if not found else None)


def shortcut(text: str, sha: str, path: Path, judged: dict[str, dict | None], stamps: dict) -> dict:
    """#188: whether the judges' verdicts on the last judged draft carry to this one. `judged` is each judge
    group's saved file, `stamps` the profile_sha256 and ruleset_version they must carry. Returns `base` (the
    judged draft's sha256 to carry from, or None), `why` (one line) and `second` (only the once-a-run cap said
    no)."""
    slots, cuts = _load(path)
    no = {"base": None, "second": False}
    if not slots:
        return {**no, "why": "no judged draft in this run"}
    base = slots[-1]
    if base["article_sha256"] == sha:
        return {**no, "why": "the judges read this draft"}
    if base.get("lint_only") is not True or not isinstance(base.get("exact"), list):
        return {**no, "why": "the judges' last round failed a rule, or a lint BLOCK on a rule a judge owns"}
    for g, j in sorted(judged.items()):
        verdicts = j.get("verdicts") if isinstance(j, dict) else None
        if (not isinstance(verdicts, list) or j.get("article_sha256") != base["article_sha256"]
                or any(j.get(k) != v for k, v in stamps.items())
                or not all(isinstance(v, dict) and v.get("verdict") == "pass" for v in verdicts)):
            return {**no, "why": f"{g}'s file isn't an all-pass verdict on the last judged draft"}
    change = _join_or_split(base, fingerprint(text))
    if change is None:
        return {**no, "why": "the fix changed more than one join or split of two sentences"}
    if len(set(cuts) - {sha}) >= SHORTCUTS:
        return {"base": None, "second": True,
                "why": "this run took the shortcut once already, so the judges read this draft"}
    what = {"join": "joined two sentences", "split": "split one sentence", "none": "changed no sentence"}[change]
    return {"base": base["article_sha256"], "second": False,
            "why": f"since the judges passed everything, the only change {what}"}


def mark(rules: dict, text: str, sha: str, path: Path, *, complete: bool, carried: bool = False) -> list[str]:
    """Set `pre_existing: true` on each judge entry in `rules` (merge's `rules_out`) that's pre-existing against the
    last judged draft other than this one, and return those rule ids, sorted. A complete merge saves this round
    (replacing an earlier save of the same draft), keeping the one before it; an INCOMPLETE one saves nothing. A
    `carried` merge (#188) saves no round but adds this draft to `shortcuts`."""
    fp = fingerprint(text)
    fails = _judge_fails(rules, fp)
    slots, cuts = _load(path)
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
    if carried:
        if sha not in cuts:
            report.write_atomic(path, json.dumps({"rounds": slots, "shortcuts": cuts + [sha]}) + "\n")
    elif complete:
        lint_only = all(e.get("source") == "lint" for e in rules.values() if e.get("verdict") == "fail")
        now = {"article_sha256": sha, "hashes": fp["hashes"], "exact": fp["exact"], "seen": fails,
               "lint_only": lint_only}
        report.write_atomic(path, json.dumps({"rounds": ([base] if base else []) + [now], "shortcuts": cuts}) + "\n")
    return marked
