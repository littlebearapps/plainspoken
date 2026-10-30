"""Trigger-eval results in the eval history (plan 8.4) and the next run's cost estimate.

`summarise` reads a `claude plugin eval` result file (its `--json` output or `aggregate-result.json`) from a run of the
trigger suite: each case's passing runs out of its runs (the `with` arm; the suite runs with `--ablation none`), the
pass rate over every run with its 95% Wilson interval, the CLI version, and the cost per run and per case. The result
file doesn't name the model, so the caller passes it. `compare` sets a new record against the last one: the pass
rate's change by interval (as `evaldrift.change`), a changed CLI version or model, and the cases that passed fewer
runs. `estimate` multiplies the last recorded cost per run by a case count and runs per case. It's one run's
figure scaled, not a quote. Free: no model is called."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from plainspoken import evaldrift
from plainspoken import evalmetrics as em
from plainspoken.golden import PLUGIN_ROOT

KIND = "triggers"
METRIC = "trigger_pass_rate"
TAG = "trigger"
CASES_DIR = PLUGIN_ROOT / "evals" / "triggers"
ARM = "with"


class TriggerError(ValueError):
    pass


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def summarise(result: object) -> dict:
    """The figures one trigger run gives the history. TriggerError for a file that isn't a `claude plugin eval`
    result, or a run of another suite."""
    if not (isinstance(result, dict) and isinstance(result.get("cases"), list) and isinstance(result.get("suite"),
                                                                                                 dict)):
        raise TriggerError("not a `claude plugin eval` result (no suite and cases)")
    suite = result["suite"]
    tags = [t for t in suite.get("tagFilters") or [] if isinstance(t, str)]
    if TAG not in tags:
        raise TriggerError(f"not a trigger-suite run (tags: {', '.join(tags) or 'none'}); run it with --tag {TAG}")
    cases: dict[str, dict] = {}
    per_case = Counter()
    for c in result["cases"]:
        if not (isinstance(c, dict) and isinstance(c.get("name"), str)):
            raise TriggerError("a case has no name")
        arms = c.get("arms") if isinstance(c.get("arms"), dict) else {}
        runs = arms.get(ARM) or []
        if not isinstance(runs, list):
            raise TriggerError(f"{c['name']}: its runs aren't a list")
        cases[c["name"]] = {"passed": sum(isinstance(r, dict) and r.get("passed") is True for r in runs),
                            "runs": len(runs)}
        if isinstance(c.get("runsPerCase"), int):
            per_case[c["runsPerCase"]] += 1
    passed = sum(c["passed"] for c in cases.values())
    runs = sum(c["runs"] for c in cases.values())
    cost = _num(result.get("costUsd"))
    plugin = next((p.get("version") for p in suite.get("plugins") or []
                   if isinstance(p, dict) and p.get("name") == "plainspoken"), None)
    model = result.get("model") if isinstance(result.get("model"), str) else None
    return {"claude_version": result.get("claudeVersion") if isinstance(result.get("claudeVersion"), str) else None,
            "started": result.get("startedAt") if isinstance(result.get("startedAt"), str) else None,
            "partial": bool(result.get("partial")), "tags": tags, "case_filter": suite.get("caseFilter"),
            "plugin_version": plugin if isinstance(plugin, str) else None, "model": model,
            "cases": cases, "case_count": len(cases), "passed": passed, "runs": runs,
            "rate": passed / runs if runs else None, "ci": list(em.wilson(passed, runs)),
            "runs_per_case": per_case.most_common(1)[0][0] if per_case else None,
            "cost_usd": cost, "cost_per_run": round(cost / runs, 6) if cost is not None and runs else None,
            "cost_per_case": round(cost / len(cases), 6) if cost is not None and cases else None}


def count_cases(folder: Path = CASES_DIR) -> int:
    """The trigger cases in the plugin today: one folder with a `prompt.md` each."""
    return sum(1 for p in Path(folder).glob("*/prompt.md") if p.is_file())


def _rate(e: dict) -> str:
    v, lo, hi = _num(e.get("value")), _num(e.get("ci_low")), _num(e.get("ci_high"))
    if v is None:
        return "n/a"
    return f"{v:.2f} [{lo:.2f}–{hi:.2f}] (n {e.get('n')})" if lo is not None and hi is not None else f"{v:.2f}"


def compare(prev: dict, new: dict) -> tuple[list[str], list[str]]:
    """(flags, lines) for a new `triggers` history entry against the previous one. A flag: the pass-rate interval
    fell entirely below the last one, the CLI version or the model changed. The lines: the rates, then each case
    both runs have that passed a smaller share of its runs."""
    flags: list[str] = []
    old_ci = [prev.get("ci_low"), prev.get("ci_high")] if _num(prev.get("ci_low")) is not None else None
    new_ci = [new.get("ci_low"), new.get("ci_high")] if _num(new.get("ci_low")) is not None else None
    how = evaldrift.change(old_ci, new_ci)
    lines = [f"against the run recorded {prev.get('started') or prev.get('date')}: pass rate {_rate(prev)} → "
             f"{_rate(new)} ({how})"]
    if how == "drop":
        flags.append(f"the pass rate dropped: {_rate(prev)} → {_rate(new)}")
    for key, what in (("claude_version", "CLI version"), ("model", "model")):
        if prev.get(key) != new.get(key):
            flags.append(f"{what} changed: {prev.get(key) or 'not recorded'} → {new.get(key) or 'not recorded'}")
    old_cases, new_cases = prev.get("cases") or {}, new.get("cases") or {}
    for name, n in new_cases.items():
        o = old_cases.get(name)
        if not (isinstance(o, dict) and o.get("runs") and n.get("runs")):
            continue
        if n["passed"] / n["runs"] < o["passed"] / o["runs"] - 1e-9:
            lines.append(f"  {name}: {o['passed']}/{o['runs']} → {n['passed']}/{n['runs']} runs passed")
    added = [n for n in new_cases if n not in old_cases]
    gone = [n for n in old_cases if n not in new_cases]
    if added or gone:
        lines.append(f"  cases: {len(added)} new, {len(gone)} no longer run")
    return flags, lines


def estimate(entry: dict, cases: int, runs: int) -> float | None:
    """US$ for `cases` × `runs` at the entry's cost per run; None when the entry has no cost per run."""
    per = _num(entry.get("cost_per_run"))
    return None if per is None else per * cases * runs
