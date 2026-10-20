"""The blind reader test (Phase 6 evals), part two: scoring the pairs `blind` built.

`score` reports per judge the share that found the person (and its complement, plainspoken judged human), the share
preferring plainspoken, the share picking A (position bias), each with a 95% Wilson interval, plus majority rows and
Fleiss' kappa. A reply that isn't the JSON asked for, and a blank or invalid rater answer, is an **error**: counted,
never a choice. A pair and order a judge has no reply or answer for is **missing**, kept apart from both; a majority
item no judge has answered is missing too, while a tie or no valid vote among the answers is an error. A reply whose
key isn't a pair and order of this build is left out and named in the warnings. No composite score."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from plainspoken import evalmetrics as em
from plainspoken.adapters.llm_panel import Reply, is_anthropic, sampling, sampling_line, transport_for, usd
from plainspoken.blind import CSV_FIELDS, ORDERS, SCHEMA, BlindError, parse_blind, read_key, read_pairs

TIER_MODEL = "tier-2 proxy"
TIER_RATER = "tier-1"
NON_ANTHROPIC = "non-Anthropic majority"
ALL_ANTHROPIC_WARNING = ("warning: every tier-2 judge is an Anthropic model. Judges favour their own family and "
                         "plainspoken's drafts are Claude-written, so tier 2 needs a model from another vendor: no "
                         "tier-2 line goes into the eval history.")
ERROR_MAX = 120
OFF_KEY_SHOWN = 3  # off-key reply keys named in the warning


def _to_text(letter: str, order: str) -> str:
    """The pair's own text ('a'/'b') shown as `letter` in `order`."""
    first = letter == "A"
    return ("a" if first else "b") if order == "ab" else ("b" if first else "a")


def _to_letter(text: str, order: str) -> str:
    return ("A" if text == "a" else "B") if order == "ab" else ("B" if text == "a" else "A")


def _rate(k: int, n: int) -> dict:
    lo, hi = em.wilson(k, n)
    return {"value": k / n if n else None, "k": k, "n": n, "ci": [lo, hi]}


def _flip(r: dict) -> dict:
    lo, hi = r["ci"]
    return {"value": None if r["value"] is None else 1 - r["value"], "k": r["n"] - r["k"], "n": r["n"],
            "ci": [1 - hi, 1 - lo]}


def _metrics(judgements: dict, key: dict, orders: tuple[str, ...]) -> dict:
    """`judgements`: (pair, order) → (human text, better text) or None (an error). An item of `key` × `orders`
    with no judgement at all is missing."""
    valid = {item: v for item, v in judgements.items() if v is not None}
    n = len(valid)
    found = sum(v[0] == key[item[0]]["human"] for item, v in valid.items())
    prefers = sum(v[1] != key[item[0]]["human"] for item, v in valid.items())
    picked_a = sum(_to_letter(v[0], item[1]) == "A" for item, v in valid.items())
    both = [p for p in {item[0] for item in valid} if all((p, o) in valid for o in ORDERS)]
    agree = sum(valid[(p, "ab")][0] == valid[(p, "ba")][0] for p in both)
    found_r = _rate(found, n)
    return {"n": n, "errors": len(judgements) - n, "missing": len(key) * len(orders) - len(judgements),
            "found_human": found_r, "plainspoken_judged_human": _flip(found_r),
            "prefers_plainspoken": _rate(prefers, n), "position_a": _rate(picked_a, n),
            "orders_agree": {"k": agree, "n": len(both)}}


def _model_judgements(replies: list[Reply], key: dict) -> tuple[dict, dict, dict, list[str]]:
    """Per model: judgements, error reasons and the replies' facts (asked for, answered as, every model id any reply
    reported); then the keys of replies that aren't a pair and order of this build."""
    latest: dict[str, Reply] = {}
    for r in replies:
        latest[r.key] = r
    judged: dict[str, dict] = {}
    reasons: dict[str, Counter] = {}
    facts: dict[str, dict] = {}
    off_key: list[str] = []
    for r in latest.values():
        parts = r.key.split("|")
        if len(parts) != 3 or parts[0] not in key or parts[1] not in ORDERS:
            off_key.append(r.key)
            continue
        pair, order, name = parts
        judged.setdefault(name, {})
        reasons.setdefault(name, Counter())
        f = facts.setdefault(name, {"model_requested": r.model_requested, "reported": set(), "served": set()})
        f["served"].update(m for m in (r.model_reported or "").split("+") if m.strip())
        if r.error is not None:
            judged[name][(pair, order)] = None
            reasons[name][f"call failed: {r.error}"[:ERROR_MAX]] += 1
            continue
        got, why = parse_blind(r.text)
        if got is None:
            judged[name][(pair, order)] = None
            reasons[name][why[:ERROR_MAX]] += 1
            continue
        if r.model_reported:
            f["reported"].add(r.model_reported)
        judged[name][(pair, order)] = (_to_text(got["human"], order), _to_text(got["better"], order))
    return judged, reasons, facts, off_key


def _anthropic(fact: dict) -> bool:
    """Decided from the models that answered (`model_reported`; the CLI's aliases count), else, when no reply
    named one, from the model asked for."""
    served = fact["served"]
    return any(is_anthropic(m) for m in served) if served else is_anthropic(fact["model_requested"])


def _rater_judgements(path: Path, key: dict) -> tuple[dict, dict]:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise BlindError(f"{path}: no such answers file") from None
    except (OSError, UnicodeDecodeError) as e:
        raise BlindError(f"{path}: can't read it ({getattr(e, 'strerror', None) or type(e).__name__})") from None
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None or not set(CSV_FIELDS) <= {f.strip() for f in reader.fieldnames}:
        raise BlindError(f"{path}: needs the columns {','.join(CSV_FIELDS)}")
    judged: dict[str, dict] = {}
    reasons: dict[str, Counter] = {}
    for n, row in enumerate(reader, 2):
        row = {(k or "").strip(): (v or "").strip() if isinstance(v, str) else "" for k, v in row.items()}
        rater, pair, h, b = (row.get(k, "") for k in CSV_FIELDS)
        if not (rater or h or b):
            continue  # an unfilled template row
        if not rater:
            raise BlindError(f"{path}: row {n} has answers but no rater")
        if pair not in key:
            raise BlindError(f"{path}: row {n}: no pair {pair!r} in this build")
        mine = judged.setdefault(rater, {})
        reasons.setdefault(rater, Counter())
        if (pair, "ab") in mine:
            raise BlindError(f"{path}: row {n}: {rater} answered pair {pair} twice")
        bad = [f"{k} {v!r} isn't a or b" for k, v in (("human", h), ("better", b)) if v.lower() not in ("a", "b")]
        if bad:
            mine[(pair, "ab")] = None
            reasons[rater]["; ".join(bad)] += 1
            continue
        mine[(pair, "ab")] = (h.lower(), b.lower())  # the form prints each pair as stored: A is a
    return judged, reasons


def _majority(by_judge: dict[str, dict], key: dict, orders: tuple[str, ...]) -> dict:
    """One judgement per (pair, order): the majority of the judges' human and better choices; a tie or no valid
    vote is an error. An item no judge has answered is left out (missing)."""
    items = [(p, o) for p in key for o in orders]
    out = {}
    for item in items:
        if all(item not in j for j in by_judge.values()):
            continue
        votes = [j.get(item) for j in by_judge.values()]
        human = em.majority([v[0] if v else None for v in votes])
        better = em.majority([v[1] if v else None for v in votes])
        out[item] = None if human is None or better is None else (human, better)
    return out


def _kappa(by_judge: dict[str, dict], key: dict, orders: tuple[str, ...]) -> dict | None:
    if len(by_judge) < 2:
        return None
    table = []
    for p in key:
        for o in orders:
            votes = [j.get((p, o)) for j in by_judge.values()]
            if all(v is not None for v in votes):
                table.append([sum(v[0] == t for v in votes) for t in ("a", "b")])
    return {"value": em.fleiss_kappa(table) if table else None, "judges": len(by_judge), "items": len(table)}


def score(out: Path, replies: list[Reply] | None, human_csv: Path | None) -> dict:
    """The blind-test summary: per judge (panel model, tier-2 proxy; or rater, tier-1) `n` valid judgements,
    `errors`, `missing` (no reply or answer), `found_human`, `plainspoken_judged_human` (1 − found, interval
    flipped), `prefers_plainspoken`,
    `position_a` (share of human picks that were the text printed as A), each `{value, k, n, ci}`, and
    `orders_agree` (models: pairs whose two orders picked the same text). A model judges every pair in both orders,
    each its own judgement; a rater judges each pair once, as printed. Majority rows (each naming its `judges`) and
    Fleiss' kappa on the human choice per tier when it has 2 or more judges, plus a non-Anthropic majority when the
    panel mixes Anthropic and 2 or more other models (tier 2 means other vendors: judges favour their own family and
    the drafts are Claude-written). A model is Anthropic by the model that answered (`model_reported`; an alias
    such as `opus` counts), else by the one asked for. `warnings` says when every tier-2 judge is Anthropic and
    names replies whose key isn't a pair and order of this build. BlindError for a missing build or a bad answers
    file."""
    out = Path(out)
    read_pairs(out)
    key = read_key(out)
    judges_out: list[dict] = []
    majority: list[dict] = []
    kappa: dict[str, dict | None] = {}
    warnings: list[str] = []
    if replies:
        judged, reasons, facts, off_key = _model_judgements(list(replies), key)
        anthropic = {name: _anthropic(facts[name]) for name in judged}
        for name, js in judged.items():
            reported = sorted(facts[name]["reported"])
            judges_out.append({"name": name, "tier": TIER_MODEL, "kind": "model",
                               "model_requested": facts[name]["model_requested"], "anthropic": anthropic[name],
                               "model_reported": ", ".join(reported), **_metrics(js, key, ORDERS),
                               "error_reasons": dict(reasons[name].most_common())})
        if len(judged) >= 2:
            majority.append({"name": "panel majority", "tier": TIER_MODEL, "kind": "majority",
                             "judges": list(judged), **_metrics(_majority(judged, key, ORDERS), key, ORDERS)})
        others = {n: js for n, js in judged.items() if not anthropic[n]}
        if len(others) >= 2 and len(others) < len(judged):
            majority.append({"name": NON_ANTHROPIC, "tier": TIER_MODEL, "kind": "majority",
                             "judges": list(others), **_metrics(_majority(others, key, ORDERS), key, ORDERS)})
        if judged and not others:
            warnings.append(ALL_ANTHROPIC_WARNING)
        if off_key:
            shown = ", ".join(off_key[:OFF_KEY_SHOWN]) + (", …" if len(off_key) > OFF_KEY_SHOWN else "")
            warnings.append(f"warning: {len(off_key)} repl{'y' if len(off_key) == 1 else 'ies'} with a key that "
                            f"isn't a pair and order of this build, so not scored: {shown}")
        kappa[TIER_MODEL] = _kappa(judged, key, ORDERS)
    if human_csv is not None:
        judged, reasons = _rater_judgements(human_csv, key)
        for name, js in judged.items():
            row = _metrics(js, key, ("ab",))
            row.pop("orders_agree")
            judges_out.append({"name": name, "tier": TIER_RATER, "kind": "rater", **row,
                               "error_reasons": dict(reasons[name].most_common())})
        if len(judged) >= 2:
            row = _metrics(_majority(judged, key, ("ab",)), key, ("ab",))
            row.pop("orders_agree")
            majority.append({"name": "rater majority", "tier": TIER_RATER, "kind": "majority",
                             "judges": list(judged), **row})
        kappa[TIER_RATER] = _kappa(judged, key, ("ab",))
    return {"schema": SCHEMA, "pairs": len(key), "judges": judges_out, "majority": majority, "kappa": kappa,
            "warnings": warnings, "sampling": sampling(transport_for(r.billed) for r in replies or ())}


# ---------------------------------------------------------------- report

def _cell(r: dict) -> str:
    lo, hi = r["ci"]
    if r["value"] is None:
        return f"n/a [{lo:.2f}–{hi:.2f}] (0/0)"
    return f"{r['value']:.2f} [{lo:.2f}–{hi:.2f}] ({r['k']}/{r['n']})"


def render(summary: dict, *, title: str | None = None) -> str:
    """The markdown report: what the figures mean, a row per judge and majority, agreement and errors."""
    run = summary.get("run") or {}
    cost = summary.get("cost")
    lines = [f"# Blind reader test: {title or run.get('id', 'run')}", ""]
    for w in summary.get("warnings") or []:
        lines += [w, ""]
    lines.append(f"- {summary['pairs']} pair{'' if summary['pairs'] == 1 else 's'}. A panel model judges each pair "
                 "in both orders (A and B swapped), each its own judgement; a rater judges each pair once, as "
                 "printed on the form.")
    lines.append(f"- {TIER_MODEL}: the model panel stands in for readers. {TIER_RATER}: people.")
    if cost:
        lines.append(f"- Cost: US${usd(cost['billed_usd'])} billed (OpenRouter) · US${usd(cost['notional_usd'])} "
                     "notional (Claude subscription, nothing billed)")
    if sampling_line(summary.get("sampling") or {}):
        lines.append(sampling_line(summary["sampling"]))
    if run.get("scored"):
        lines.append(f"- Scored {run['scored']}")
    lines += ["", "*plainspoken judged human* is the share of judgements that took the plainspoken text for the "
              "person's: 0.50 means the judge couldn't tell them apart. *found the person* is its complement. "
              "*picked A* shows position bias (0.50 is none). Each figure has a 95% Wilson interval and the counts "
              "behind it. An error (a failed call, a reply that isn't the JSON asked for, a blank or invalid answer) "
              "is counted on its own, never as a choice; a missing judgement had no reply or answer at all. A majority "
              "error is a tie or no valid vote; a majority judgement is missing when no judge answered. There is no "
              "combined score.", "",
              "| judge | tier | asked for | answered as | plainspoken judged human [95% CI] | found the person "
              "[95% CI] | prefers plainspoken [95% CI] | picked A [95% CI] | orders agree | errors | missing | n |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for j in [*summary["judges"], *summary["majority"]]:
        agree = j.get("orders_agree")
        agree = f"{agree['k']}/{agree['n']}" if agree else "–"
        lines.append(f"| {j['name']} | {j['tier']} | {j.get('model_requested') or '–'} | "
                     f"{(j.get('model_reported') or 'not reported') if j['kind'] == 'model' else '–'} | "
                     f"{_cell(j['plainspoken_judged_human'])} | {_cell(j['found_human'])} | "
                     f"{_cell(j['prefers_plainspoken'])} | {_cell(j['position_a'])} | "
                     f"{agree} | {j['errors']} | {j.get('missing', 0)} | {j['n']} |")
    lines += ["", "## Agreement", ""]
    if not summary["kappa"]:
        lines.append("Nothing to compare.")
    for tier, k in summary["kappa"].items():
        if k is None:
            lines.append(f"- {tier}: one judge, so no agreement figure.")
        else:
            value = "n/a" if k["value"] is None else f"{k['value']:.2f}"
            lines.append(f"- {tier}: Fleiss' kappa {value} on the human choice ({k['judges']} judges, {k['items']} "
                         "judgements every judge answered).")
    lines += ["", "## Errors", ""]
    failed = [j for j in summary["judges"] if j.get("error_reasons")]
    if failed:
        lines += ["| judge | reason | count |", "|---|---|---|"]
        for j in failed:
            lines += [f"| {j['name']} | {why.replace('|', '/')} | {count} |"
                      for why, count in j["error_reasons"].items()]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"
