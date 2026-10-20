"""Judge validation (Phase 6 evals): golden set × model panel → replies → metrics and a report.

`jobs` turns golden cases into one self-contained prompt per case and model (key `<case id>|<model name>`), for
`llm_panel.run_batch`. `score` reads the replies back against the labels: for each group, per model and for the
majority of all models and of the non-Anthropic models, the confusion counts and TPR, TNR and precision with 95%
Wilson intervals, on two splits: `all` cases and `human` (confirmed + endorsed labels). While the `all` split holds
a provisional case its figures are a proxy, and the report says so. `render` writes the markdown report and
`accept` applies the accept bar.

The positive label is `fail` for J1–J4 and `reject` for JR (the judge catches a bad justification). A reply whose
call failed, or that isn't the JSON asked for, is an **error**: counted, its reason tallied, never a label. A case
a model has no reply for (a run stopped early) is **missing**, kept apart from both. No composite score."""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from plainspoken import evalmetrics as em
from plainspoken import evalprompts
from plainspoken.adapters.llm_panel import (PanelModel, Reply, is_anthropic, sampling, sampling_line,
                                            transport_for, usd)
from plainspoken.golden import GROUPS, LABELS, GoldenCase

SCHEMA = 1
SPLITS = ("all", "human")
HUMAN = ("confirmed", "endorsed")
POSITIVE = {g: ("reject" if g == "JR" else "fail") for g in GROUPS}
MIN_RATE = 0.8
MAX_ERROR_RATE = 0.10
MAJORITY_ALL = "all models"
MAJORITY_NON = "non-Anthropic models"
ERROR_MAX = 120  # characters of a call error kept as a tally reason
_MISSING = object()


def job_key(case_id: str, model_name: str) -> str:
    return f"{case_id}|{model_name}"


def golden_sha256(dir: Path) -> str:
    """One hash over the golden files (`*.toml`, name order): a changed label or case gives a new hash."""
    h = hashlib.sha256()
    for f in sorted(Path(dir).glob("*.toml")):
        h.update(f.name.encode("utf-8") + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def prompt_for(case: GoldenCase, workdir: Path) -> str:
    return evalprompts.jr_prompt(case) if case.group == "JR" else evalprompts.judge_prompt(case, workdir)


def jobs(cases: list[GoldenCase], models: list[PanelModel], workdir: Path) -> list[tuple[str, PanelModel, str]]:
    """One job per case and model, in case order then model order. Every model gets the same prompt for a case. A
    model with `groups` set gets jobs only for those groups.
    `workdir` (a temp folder the caller removes) holds the temp files the lint reads for J prompts."""
    Path(workdir).mkdir(parents=True, exist_ok=True)
    out = []
    for c in cases:
        prompt = prompt_for(c, workdir)
        out += [(job_key(c.id, m.name), m, prompt) for m in models if m.groups is None or c.group in m.groups]
    return out


# ---------------------------------------------------------------- scoring

def costs(replies: Iterable[Reply]) -> dict:
    """Billed (OpenRouter) and notional (Claude subscription, nothing billed) US$, in total and per model."""
    billed = notional = 0.0
    per: dict[str, dict] = {}
    for r in replies:
        p = per.setdefault(r.name, {"calls": 0, "billed_usd": 0.0, "notional_usd": 0.0})
        p["calls"] += 1
        if r.billed:
            billed += r.cost_usd
            p["billed_usd"] += r.cost_usd
        else:
            notional += r.cost_usd
            p["notional_usd"] += r.cost_usd
    for p in per.values():
        p["billed_usd"], p["notional_usd"] = round(p["billed_usd"], 6), round(p["notional_usd"], 6)
    return {"billed_usd": round(billed, 6), "notional_usd": round(notional, 6), "models": per}


def _is_anthropic(info: dict) -> bool:
    return is_anthropic(info["model_requested"], info.get("vendor"))


def _model_infos(models: list[PanelModel] | None, replies: dict[str, Reply]) -> list[dict]:
    if models is not None:
        infos = [{"name": m.name, "vendor": m.vendor, "transport": m.transport, "model_requested": m.model,
                  "billed": m.billed, "groups": list(m.groups) if m.groups else None} for m in models]
    else:  # derived from the replies, in the order they first appear
        seen: dict[str, dict] = {}
        for r in replies.values():
            seen.setdefault(r.name, {"name": r.name, "vendor": None, "transport": None,
                                     "model_requested": r.model_requested, "billed": r.billed, "groups": None})
        infos = list(seen.values())
    for info in infos:
        mine = [r for r in replies.values() if r.name == info["name"]]
        reported = sorted({r.model_reported for r in mine if r.error is None and r.model_reported})
        # None: no reply at all ("not run"); "": replies came back but none named the model that answered
        info["model_reported"] = ", ".join(reported) if reported else (None if not mine else "")
        hosts: dict[str, int] = {}
        for r in mine:
            if r.error is None and r.provider:
                hosts[r.provider] = hosts.get(r.provider, 0) + 1
        info["providers"] = dict(sorted(hosts.items(), key=lambda kv: (-kv[1], kv[0])))
        info["anthropic"] = _is_anthropic(info)
    return infos


def _answer(case: GoldenCase, reply: Reply) -> tuple[str | None, str | None]:
    """(label, None) or (None, why it's an error)."""
    if reply.error is not None:
        return None, f"call failed: {reply.error}"[:ERROR_MAX]
    label, why = evalprompts.parse_judge(reply.text, case)
    return (label, None) if label is not None else (None, why or "unparseable reply")


def _row(pairs: list[tuple[str, str | None]], positive: str, missing: int = 0) -> dict:
    conf = em.confusion(pairs, positive)
    return {**conf, "missing": missing, "error_rate": conf["errors"] / conf["n"] if conf["n"] else None,
            **em.rates(conf)}


def _model_row(cases: list[GoldenCase], name: str, answers: dict, positive: str) -> dict:
    pairs, missing = [], 0
    for c in cases:
        a = answers[(c.id, name)]
        if a is _MISSING:
            missing += 1
        else:
            pairs.append((c.label, a))
    return _row(pairs, positive, missing)


def _vote(answers: dict, case_id: str, voters: list[str]) -> list[str | None]:
    return [None if answers[(case_id, n)] is _MISSING else answers[(case_id, n)] for n in voters]


def _kappa(cases: list[GoldenCase], names: list[str], answers: dict, labels: tuple[str, str]) -> dict | None:
    """Fleiss' kappa across every model, on the cases every model labelled; None with fewer than 2 models."""
    if len(names) < 2:
        return None
    table = []
    for c in cases:
        votes = _vote(answers, c.id, names)
        if all(v is not None for v in votes):
            table.append([sum(v == lab for v in votes) for lab in labels])
    return {"value": em.fleiss_kappa(table) if table else None, "models": len(names), "cases": len(table)}


def _split(cases: list[GoldenCase], names: list[str], non_anthropic: list[str], answers: dict,
           group: str) -> dict:
    positive = POSITIVE[group]
    labels = (positive, next(lab for lab in LABELS[group] if lab != positive))
    provisional = sum(c.status == "provisional" for c in cases)
    out = {"cases": len(cases), "labels": {lab: sum(c.label == lab for c in cases) for lab in labels},
           "provisional": provisional, "proxy": provisional > 0,
           "models": {n: _model_row(cases, n, answers, positive) for n in names}, "majority": {},
           "kappa": _kappa(cases, names, answers, labels)}
    for title, voters in ((MAJORITY_ALL, names), (MAJORITY_NON, non_anthropic)):
        if len(voters) >= 2:
            pairs, missing = [], 0
            for c in cases:
                if all(answers[(c.id, n)] is _MISSING for n in voters):
                    missing += 1  # no voter has a reply yet: missing, as on a model row, not a majority error
                else:
                    pairs.append((c.label, em.majority(_vote(answers, c.id, voters))))
            out["majority"][title] = _row(pairs, positive, missing)
    return out


def score(cases: list[GoldenCase], replies: dict[str, Reply], models: list[PanelModel] | None = None, *,
          calls: Iterable[Reply] | None = None) -> dict:
    """The metrics summary for `cases` against `replies` (key → newest reply, as `llm_panel.read_replies` gives).
    `models` names the run's models, in order (a model with no reply shows as not run); without it the models
    come from the replies. Replies for other cases are ignored. `cost` is `costs(calls)` when `calls` (every
    recorded call, retries included: `llm_panel.reply_lines`) is given, else the cost of the scored replies."""
    infos = _model_infos(models, replies)
    names = [i["name"] for i in infos]
    non_anthropic = [i["name"] for i in infos if not i["anthropic"]]
    judges = {i["name"]: i.get("groups") for i in infos}

    def judging(group: str, pool: list[str]) -> list[str]:
        return [n for n in pool if judges[n] is None or group in judges[n]]
    answers: dict[tuple[str, str], object] = {}
    errors: dict[str, Counter] = {n: Counter() for n in names}
    for c in cases:
        for n in judging(c.group, names):
            r = replies.get(job_key(c.id, n))
            if r is None:
                answers[(c.id, n)] = _MISSING
                continue
            label, why = _answer(c, r)
            answers[(c.id, n)] = label
            if why:
                errors[n][why] += 1
    groups: dict[str, dict] = {}
    rules: dict[str, dict] = {}
    for g in GROUPS:
        mine = [c for c in cases if c.group == g]
        if not mine:
            continue
        subsets = {"all": mine, "human": [c for c in mine if c.status in HUMAN]}
        groups[g] = {"positive": POSITIVE[g], "negative": next(lab for lab in LABELS[g] if lab != POSITIVE[g]),
                     "splits": {s: _split(subsets[s], judging(g, names), judging(g, non_anthropic), answers, g)
                                for s in SPLITS}}
        rules[g] = {}
        for rule in dict.fromkeys(c.rule for c in mine):
            rules[g][rule] = {s: {n: _model_row([c for c in subsets[s] if c.rule == rule], n, answers,
                                                POSITIVE[g]) for n in judging(g, names)} for s in SPLITS}
    if calls is None:
        ids = {c.id for c in cases}
        calls = [r for r in replies.values() if r.name in names and r.key.split("|", 1)[0] in ids]
    return {"schema": SCHEMA, "models": infos, "groups": groups, "rules": rules,
            "errors": {n: dict(errors[n].most_common()) for n in names if errors[n]}, "cost": costs(calls),
            "sampling": sampling(i["transport"] or transport_for(i["billed"]) for i in infos)}


# ---------------------------------------------------------------- accept bar

def accept(summary: dict, models: list[str] | None = None, min_rate: float = MIN_RATE,
           max_error_rate: float = MAX_ERROR_RATE) -> list[dict]:
    """The accept bar, per group and model: TPR >= min_rate and TNR >= min_rate on the `all` split, errors at most
    max_error_rate of the replies, and every case run. One `{group, model, ok, why}` per pair."""
    names = models if models is not None else [m["name"] for m in summary["models"]]
    limits = {m["name"]: m.get("groups") for m in summary["models"]}
    out = []
    eps = 1e-12
    for g, grp in summary["groups"].items():
        rows = grp["splits"]["all"]["models"]
        for name in names:
            if limits.get(name) is not None and g not in limits[name]:
                out.append({"group": g, "model": name, "ok": True,
                            "why": f"doesn't judge {g} (its panel entry lists {', '.join(limits[name])})"})
                continue
            row = rows.get(name)
            why: list[str] = []
            if row is None:
                why.append("not in this run")
            elif row["n"] == 0:
                why.append("not run")
            else:
                if row["missing"]:
                    why.append(f"{row['missing']} case{'' if row['missing'] == 1 else 's'} not run")
                for key, label, short in (("tpr", grp["positive"], "TPR"), ("tnr", grp["negative"], "TNR")):
                    v = row[key]["value"]
                    if v is None:
                        why.append(f"no {label} cases answered, so no {short}")
                    elif v < min_rate - eps:
                        why.append(f"{short} {v:.2f} < {min_rate:g}")
                if row["error_rate"] is not None and row["error_rate"] > max_error_rate + eps:
                    why.append(f"errors {row['errors']}/{row['n']} ({row['error_rate']:.0%}) > {max_error_rate:.0%}")
            out.append({"group": g, "model": name, "ok": not why, "why": "; ".join(why) or "meets the bar"})
    return out


# ---------------------------------------------------------------- report

def _rate(r: dict) -> str:
    lo, hi = r["ci"]
    if r["value"] is None:
        return f"n/a [{lo:.2f}–{hi:.2f}] (0/0)"
    return f"{r['value']:.2f} [{lo:.2f}–{hi:.2f}] ({r['k']}/{r['n']})"


def _row_cells(title: str, row: dict) -> str:
    return (f"| {title} | {_rate(row['tpr'])} | {_rate(row['tnr'])} | {_rate(row['precision'])} | {row['errors']} | "
            f"{row['missing']} | {row['n']} |")


def _split_title(name: str, split: dict) -> str:
    labels = " · ".join(f"{k} {v}" for k, v in split["labels"].items())
    head = "all cases" if name == "all" else "human labels (confirmed + endorsed)"
    title = f"### {head}: {split['cases']} case{'' if split['cases'] == 1 else 's'} ({labels})"
    if split["proxy"]:
        title += f" · provisional labels: proxy ({split['provisional']} provisional)"
    return title


def render(summary: dict, *, min_rate: float = MIN_RATE, models: list[str] | None = None) -> str:
    """The markdown report: run facts and cost, the models and the ids that answered, the accept bar, then per
    group and split the rates with their intervals, the majority rows and agreement, per rule, and the errors."""
    run = summary.get("run") or {}
    cost = summary["cost"]
    lines = [f"# Judge validation: {run.get('id', 'run')}", ""]
    lines.append(f"- Run started {run.get('started') or 'unknown'} · scored {run.get('scored') or 'unknown'}")
    if run.get("golden_sha256"):
        filters = run.get("filters") or {}
        lines.append(f"- Golden set: {run.get('golden_cases', '?')} cases, sha256 {run['golden_sha256'][:12]}… · "
                     f"group {', '.join(filters.get('group') or []) or 'all'} · "
                     f"status {', '.join(filters.get('status') or []) or 'all'}")
    lines.append(f"- Cost: US${usd(cost['billed_usd'])} billed (OpenRouter) · US${usd(cost['notional_usd'])} "
                 "notional (Claude subscription, nothing billed)")
    if sampling_line(summary.get("sampling") or {}):
        lines.append(sampling_line(summary["sampling"]))
    if run.get("stopped"):
        lines.append(f"- Stopped early: {run['stopped']}")
    lines += ["", "Rates are point estimates with a 95% Wilson interval and the counts behind them. An error (a call "
              "that failed, or a reply that isn't the JSON asked for) is counted on its own, never as a pass or a "
              "fail; a missing case had no reply (the run stopped). A majority error is a tie or no valid vote. "
              "There is no combined score.", "", "## Models", "",
              "| model | vendor | asked for | answered as | served by | calls | billed US$ | notional US$ |",
              "|---|---|---|---|---|---|---|---|"]
    per = cost.get("models", {})
    for m in summary["models"]:
        reported = m["model_reported"]
        shown = "not run" if reported is None else (reported or "not reported")
        c = per.get(m["name"], {"calls": 0, "billed_usd": 0.0, "notional_usd": 0.0})
        hosts = m.get("providers") or {}
        served = ", ".join(f"{h} {n}" for h, n in hosts.items()) if hosts else "not reported"
        lines.append(f"| {m['name']} | {m.get('vendor') or '?'} | {m['model_requested']} | {shown} | {served} | "
                     f"{c['calls']} | "
                     f"{usd(c['billed_usd'])} | {usd(c['notional_usd'])} |")
    lines += ["", "## Accept bar", "",
              f"TPR ≥ {min_rate:g} and TNR ≥ {min_rate:g} on the all-cases split, errors ≤ "
              f"{MAX_ERROR_RATE:.0%}, every case run.", "", "| group | model | result |", "|---|---|---|"]
    for r in accept(summary, models, min_rate):
        lines.append(f"| {r['group']} | {r['model']} | {r['why'] if r['ok'] else 'misses: ' + r['why']} |")
    for g, grp in summary["groups"].items():
        lines += ["", f"## {g} (positive label: {grp['positive']})"]
        for name in SPLITS:
            split = grp["splits"][name]
            lines += ["", _split_title(name, split), ""]
            if not split["cases"]:
                lines.append("No cases.")
                continue
            lines += ["| judge | TPR [95% CI] | TNR [95% CI] | precision [95% CI] | errors | missing | n |",
                      "|---|---|---|---|---|---|---|"]
            lines += [_row_cells(n, row) for n, row in split["models"].items()]
            lines += [_row_cells(f"majority: {t}", row) for t, row in split["majority"].items()]
            k = split["kappa"]
            if k is not None:
                value = "n/a" if k["value"] is None else f"{k['value']:.2f}"
                lines += ["", f"Agreement: Fleiss' kappa {value} ({k['models']} models, {k['cases']} cases every "
                              "model labelled)."]
    lines += ["", "## Per rule", "", "| group | rule | split | judge | TPR [95% CI] | TNR [95% CI] | errors | n |",
              "|---|---|---|---|---|---|---|---|"]
    for g, by_rule in summary["rules"].items():
        for rule, splits in by_rule.items():
            for s in SPLITS:
                for n, row in splits[s].items():
                    if row["n"] or row["missing"]:
                        lines.append(f"| {g} | {rule} | {s} | {n} | {_rate(row['tpr'])} | {_rate(row['tnr'])} | "
                                     f"{row['errors']} | {row['n']} |")
    lines += ["", "## Errors", ""]
    if summary["errors"]:
        lines += ["| model | reason | count |", "|---|---|---|"]
        for n, reasons in summary["errors"].items():
            lines += [f"| {n} | {why.replace('|', '/')} | {count} |" for why, count in reasons.items()]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"
