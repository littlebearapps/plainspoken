"""The eval history file and the anti-Goodhart report (Phase 6 evals).

`append` adds one line to `<project>/.plainspoken/evals/history.jsonl` (O_APPEND, one write, like the ledger), and
`read` reads it back, skipping a torn or damaged line. Every line has the keys in `KEYS`: `kind` is `judges` (one
line per model a judge-validation summary covers: the share of groups meeting the accept bar), `blind` (one line per
tier of a blind-test score: the majority of the non-Anthropic panel models, or the one such model, and the rater
majority, or the one rater: `plainspoken_judged_human` with its 95% Wilson interval, plus the generated drafts'
folder in `drafts`) or `lint` (the share of a folder's drafts with no lint BLOCK, `run` being that folder).

`goodhart` looks for the lint getting better while readers don't: between two consecutive blind entries of one
tier, the lint pass rate measured on each entry's drafts rose by at least `lint_jump` while the reader result didn't
improve (the two `plainspoken_judged_human` intervals overlap, or the later one is entirely below the earlier).
File order is the clock: a blind entry's lint measurement is the latest lint entry on its drafts at or before it,
else the first after it and before the next blind entry of its tier, so a reused drafts folder or a later re-lint
never changes an earlier run's side. Each flag prints both entries and says to investigate, never to tune against
the held-out set. A pair that can't be compared (no lint entry for a side, the same lint entry for both, a blind
entry with no value) is a note, not a flag. No composite score."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from plainspoken.adapters.llm_panel import is_anthropic

HISTORY = "history.jsonl"
KINDS = ("judges", "blind", "lint")
KEYS = ("date", "kind", "ruleset_version", "plugin_version", "metric", "value", "ci_low", "ci_high", "n", "run")
JUDGES_METRIC = "judges_meets_bar_groups"
BLIND_METRIC = "plainspoken_judged_human"
LINT_METRIC = "lint_pass_rate"
LINT_JUMP = 0.10
_EPS = 1e-9


def path(project: Path) -> Path:
    return Path(project) / ".plainspoken" / "evals" / HISTORY


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make(kind: str, metric: str, value: float | None, *, n: int, run: str, ruleset_version: str,
         plugin_version: str, ci: tuple[float, float] | list[float] | None = None, **extra) -> dict:
    lo, hi = (None, None) if ci is None else (ci[0], ci[1])
    return {"date": now(), "kind": kind, "ruleset_version": ruleset_version, "plugin_version": plugin_version,
            "metric": metric, "value": value, "ci_low": lo, "ci_high": hi, "n": n, "run": run, **extra}


def _problems(entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return ["not an object"]
    out = [f"no {k}" for k in KEYS if k not in entry]
    if entry.get("kind") not in KINDS:
        out.append(f"kind {entry.get('kind')!r} isn't one of {', '.join(KINDS)}")
    return out


def _safe_folder(project: Path) -> Path:
    """`<project>/.plainspoken/evals`, created; OSError when it, or `.plainspoken`, is a symlink."""
    project = Path(project)
    chain = (project / ".plainspoken", project / ".plainspoken" / "evals")
    for _ in range(2):  # before and after creating it
        for p in chain:
            if p.is_symlink():
                raise OSError(f"{p} is a symlink, so nothing was written")
        chain[-1].mkdir(parents=True, exist_ok=True)
    return chain[-1]


def append(project: Path, entry: dict) -> None:
    """Append one entry. ValueError for an entry without the `KEYS` or with an unknown `kind` (or a value JSON can't
    hold); OSError when the file can't be written safely (a symlinked folder or file, a short write)."""
    problems = _problems(entry)
    if problems:
        raise ValueError("bad history entry: " + "; ".join(problems))
    line = (json.dumps(entry, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    target = _safe_folder(project) / HISTORY
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(target, flags, 0o666)
    try:
        written = os.write(fd, line)
    finally:
        os.close(fd)
    if written != len(line):
        raise OSError(f"{target}: short write ({written} of {len(line)} bytes)")


def read_file(file: Path) -> list[dict]:
    """Every whole, valid entry in `file`, in order; a torn or damaged line is skipped. A missing file gives []."""
    try:
        text = Path(file).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not _problems(row):
            out.append(row)
    return out


def read(project: Path) -> list[dict]:
    return read_file(path(project))


# ---------------------------------------------------------------- the entries the eval commands append

def judges_entries(results: list[dict], run: str, *, min_rate: float, ruleset_version: str,
                   plugin_version: str, scored: str | None = None) -> list[dict]:
    """One `judges` entry per model in `evaljudges.accept`'s results: the share of its groups meeting the bar.
    `scored` (the summary's scoring time) goes on each entry, so `unrecorded` can tell a repeat from a new run."""
    by_model: dict[str, list[bool]] = {}
    for r in results:
        by_model.setdefault(r["model"], []).append(bool(r["ok"]))
    return [make("judges", JUDGES_METRIC, (sum(oks) / len(oks)) if oks else None, n=len(oks), run=run,
                 ruleset_version=ruleset_version, plugin_version=plugin_version, model=name, min_rate=min_rate,
                 scored=scored)
            for name, oks in by_model.items()]


def _judges_key(entry: dict) -> tuple:
    return (entry.get("kind"), entry.get("run"), entry.get("scored"), entry.get("min_rate"), entry.get("model"))


def unrecorded(project: Path, entries: list[dict]) -> list[dict]:
    """`entries` less the `judges` ones the project's history already holds for the same run, scoring time, bar
    and model (a `judges-report` after `judges`, or run twice). An entry with no `scored` is always kept."""
    seen = {_judges_key(e) for e in read(project) if e.get("kind") == "judges" and e.get("scored")}
    return [e for e in entries if not (e.get("kind") == "judges" and e.get("scored") and _judges_key(e) in seen)]


def blind_entries(summary: dict, run: str, drafts: str | None, *, ruleset_version: str,
                  plugin_version: str) -> list[dict]:
    """One `blind` entry per tier in a blind-test score. Tier 1 (people): its majority row, or its one rater. Tier 2
    (models): only the models from vendors other than Anthropic count (judges favour their own family, and the
    drafts are Claude-written), so it's the majority row over exactly those models, or the one such model; no line
    when every tier-2 judge is Anthropic. A row with no valid judgement (`n` 0) adds no line either: its interval
    is [0, 1] and says nothing."""
    rows: dict[str, list[dict]] = {}
    for j in summary.get("judges", []):
        rows.setdefault(j["tier"], []).append(j)
    majorities: dict[str, list[dict]] = {}
    for m in summary.get("majority", []):
        majorities.setdefault(m["tier"], []).append(m)
    out = []
    for tier, judged in rows.items():
        models = [j for j in judged if j.get("kind") == "model"]
        if models:
            others = [j for j in models  # the score's own call (by the model that answered); older scores: asked for
                      if not j.get("anthropic", is_anthropic(j.get("model_requested") or ""))]
            names = {j["name"] for j in others}
            if len(others) == 1:
                pick = others[0]
            else:
                pick = next((m for m in majorities.get(tier, []) if set(m.get("judges") or ()) == names), None)
            if not names or pick is None:
                continue
        elif majorities.get(tier):
            pick = majorities[tier][0]
        elif len(judged) == 1:
            pick = judged[0]
        else:
            continue
        r = pick["plainspoken_judged_human"]
        if not r.get("n"):  # no valid judgement (every call failed, raters disagreed on every pair): nothing to track
            continue
        out.append(make("blind", BLIND_METRIC, r["value"], n=r["n"], run=run, ci=r["ci"],
                        ruleset_version=ruleset_version, plugin_version=plugin_version, tier=tier,
                        judge=pick["name"], drafts=drafts, pairs=summary.get("pairs")))
    return out


def lint_entry(passed: int, n: int, ci: tuple[float, float], drafts: str, *, profile: str, ruleset_version: str,
               plugin_version: str) -> dict:
    return make("lint", LINT_METRIC, passed / n if n else None, n=n, run=drafts, ci=ci,
                ruleset_version=ruleset_version, plugin_version=plugin_version, profile=profile)


# ---------------------------------------------------------------- the anti-Goodhart report

def _series(entries: list[dict]) -> dict[str, list[int]]:
    """Per tier, the positions of its blind entries in file order (file order is the clock)."""
    out: dict[str, list[int]] = {}
    for i, e in enumerate(entries):
        if e["kind"] == "blind" and e["metric"] == BLIND_METRIC:
            out.setdefault(str(e.get("tier") or ""), []).append(i)
    return out


def enough(entries: list[dict]) -> bool:
    """True when some tier has two blind entries or more to compare."""
    return any(len(s) >= 2 for s in _series(entries).values())


def pair_count(entries: list[dict]) -> int:
    """How many consecutive blind pairs the report looks at."""
    return sum(max(0, len(s) - 1) for s in _series(entries).values())


def _lint_for(entries: list[dict], at: int, until: int) -> int | None:
    """The position of the lint entry measured on the drafts of the blind entry at `at`: the latest one at or before
    it, else the first one after it and before `until` (the next blind entry of its tier, or the end)."""
    drafts = entries[at].get("drafts")
    if not isinstance(drafts, str) or not drafts:
        return None

    def ok(i: int) -> bool:
        e = entries[i]
        return e["kind"] == "lint" and e["metric"] == LINT_METRIC and e["run"] == drafts

    before = [i for i in range(at) if ok(i)]
    if before:
        return before[-1]
    return next((i for i in range(at + 1, until) if ok(i)), None)


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _fmt(v: object) -> str:
    f = _num(v)
    return "n/a" if f is None else f"{f:.2f}"


def describe(e: dict) -> str:
    ci = "" if _num(e.get("ci_low")) is None else f" [{_fmt(e['ci_low'])}–{_fmt(e['ci_high'])}]"
    who = " ".join(str(e[k]) for k in ("tier", "judge") if e.get(k))
    where = f" · drafts {e['drafts']}" if e.get("drafts") else ""
    return (f"{e['kind']} {e['date']}{' ' + who if who else ''}: {e['metric']} {_fmt(e['value'])}{ci} (n {e['n']}) · "
            f"ruleset {e['ruleset_version']} · plugin {e['plugin_version']} · run {e['run']}{where}")


def _reader_change(a: dict, b: dict) -> str | None:
    """How the reader result moved from blind entry `a` to the later `b`: `better` (b's interval entirely above
    a's), `worse` (entirely below), `same` (the intervals overlap), or None when either has no interval."""
    lo1, hi1, lo2, hi2 = (_num(a.get("ci_low")), _num(a.get("ci_high")), _num(b.get("ci_low")), _num(b.get("ci_high")))
    if None in (lo1, hi1, lo2, hi2):
        return None
    if lo2 > hi1 + _EPS:
        return "better"
    if hi2 < lo1 - _EPS:
        return "worse"
    return "same"


def report(entries: list[dict], *, lint_jump: float = LINT_JUMP) -> tuple[list[str], list[str]]:
    """(flags, notes). A flag: between two consecutive blind entries of one tier, the lint pass rate on their drafts
    rose by at least `lint_jump` while the reader result didn't improve (the `plainspoken_judged_human` intervals
    overlap, or the later one is entirely below the earlier). A note: a pair that can't be compared (no lint entry
    for a side's drafts, the same lint entry for both, a blind entry with no value or no interval)."""
    flags: list[str] = []
    notes: list[str] = []
    for tier, series in _series(entries).items():
        bounds = [*series[1:], len(entries)]
        for k in range(len(series) - 1):
            before, after = entries[series[k]], entries[series[k + 1]]
            pair = f"{tier or 'blind'}: {before['run']} → {after['run']}"
            found = [_lint_for(entries, series[k], bounds[k]), _lint_for(entries, series[k + 1], bounds[k + 1])]
            missing = [str(e.get("drafts") or "not recorded") for e, i in zip((before, after), found) if i is None]
            if missing:
                notes.append(f"{pair}: no lint-rate entry for the drafts ({', '.join(missing)}), so not compared "
                             "(run `eval lint-rate --drafts DIR` on them)")
                continue
            if found[0] == found[1]:
                notes.append(f"{pair}: the same lint measurement for both runs, so not compared (run `eval "
                             "lint-rate` on the drafts before each blind run)")
                continue
            lints = [entries[i] for i in found]
            if _num(before.get("value")) is None or _num(after.get("value")) is None:
                notes.append(f"{pair}: a blind entry has no value, so not compared")
                continue
            change = _reader_change(before, after)
            if change is None:
                notes.append(f"{pair}: a blind entry has no interval, so not compared")
                continue
            v1, v2 = _num(lints[0]["value"]), _num(lints[1]["value"])
            if v1 is None or v2 is None:
                notes.append(f"{pair}: a lint-rate entry has no value, so not compared")
                continue
            if v2 - v1 >= lint_jump - _EPS and change != "better":
                how = ("whose " + BLIND_METRIC + " intervals overlap" if change == "same" else
                       "where readers got worse (the later " + BLIND_METRIC + " interval is entirely below the "
                       "earlier)")
                flags.append("\n".join([
                    f"flag: the lint pass rate rose {v1:.2f} → {v2:.2f} (+{v2 - v1:.2f}, at least {lint_jump:.2f}) "
                    f"between two blind runs {how}:",
                    f"  {describe(before)}",
                    f"  {describe(after)}",
                    f"  {describe(lints[0])}",
                    f"  {describe(lints[1])}",
                    "  investigate: the drafts may be dodging the lint's tells without reading any more like a "
                    "person. Fix the rules or the drafting from new evidence; never tune against the held-out set "
                    "(the golden cases or the blind pairs).",
                ]))
    return flags, notes


def goodhart(entries: list[dict], *, lint_jump: float = LINT_JUMP) -> list[str]:
    return report(entries, lint_jump=lint_jump)[0]
