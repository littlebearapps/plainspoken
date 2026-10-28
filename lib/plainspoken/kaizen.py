"""Kaizen metrics (Phase 5): the ledger read back as per-rule counts, the `kaizen report` table and the anonymised
`kaizen report --share` export.

Counting. An event id includes `doc_sha`, so every draft version re-fires the same span with
a new id. Metrics therefore count distinct *span keys*, `(doc_id, rule, span_hash)`, among the events with each
outcome, after `ledger.distinct` has dropped exact duplicates. A span that re-appears after a fix counts once.

- `rule_metrics`: one entry for every ruleset rule, plus any other rule the ledger names. Pattern-only `missed`
  events (rule `?`, facet `pattern`) are never a rule row: `pattern_metrics` counts them by pattern.
  Nor are the `pattern:<name>` ids a missed-pattern review proposal carries (its proposal and decision events).
  Calibrate reads missed-by-rule from `rule_metrics` and missed-by-pattern from `pattern_metrics`.
- `friction_summary`: `friction.jsonl` (read with `ledger.read_friction`) counted by kind, plus the judge replies the
  backstop hook saw returned against the judge and JR verdicts that reached the ledger.
- `report_lines`: a fixed-width table, one row per rule with any event, with no composite score.
- `share`: counts only. No profile name, doc ids, hashes, facets (ruleset list words), reasons, excerpts or paths.
- `calibrate_due` / `mark_calibrated`: whether the Stop nudge should say calibrate is due, and the stamp
  `kaizen calibrate` leaves so a run that proposes nothing still counts as a run.
"""
from __future__ import annotations

import json
import textwrap
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from plainspoken import ledger

PLUGIN_JSON = Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"
FIRE_SEVERITIES = ("BLOCK", "WARN")
PATTERN_RULE = "?"  # overrides.PATTERN_RULE (not imported: overrides pulls in the whole engine)
PATTERN_PROPOSAL = "pattern:"  # the rule id prefix of a missed-pattern review proposal (calibrate)
JUDGE_AGENTS = ("plainspoken:tells-judge",)  # the agent whose handbacks are judge (and JR) replies
COUNTS = ("fires", "docs", "fixed", "justified", "jr_accept", "jr_reject", "dismissed", "upheld", "missed",
          "survived")
RATES = ("fix_rate", "justify_rate", "jr_accept_rate", "dismiss_rate", "effective_fp", "agreement")
# outcome -> metric, for the plain span counts (`justified:<kind>` is matched by prefix).
_OUTCOME_METRIC = {"fixed": "fixed", "jr_accept": "jr_accept", "jr_reject": "jr_reject", "dismissed": "dismissed",
                   "upheld": "upheld", "missed": "missed", "survived_publish": "survived"}
_FALSE_POSITIVE = "false_positive"

SpanKey = tuple[str | None, str, str | None]


def _key(e: Mapping) -> SpanKey:
    return e.get("doc_id"), str(e["rule"]), e.get("span_hash")


def _rate(num: int | float, den: int) -> float | None:
    """`num / den`, at most 1, or None when `den` is 0. With a `--since` window a numerator can hold spans that
    first fired before it (a fix of an older fire), so a rate is capped at 100% rather than read past it."""
    return None if den == 0 else min(1.0, num / den)


def _later(held: tuple[str, str] | None, ts: str, eid: str) -> bool:
    """`(ts, id)` is at or after `held`: the latest wins, and the event id breaks a tie in `ts`, so the answer never
    depends on the order of the ledger lines."""
    return held is None or (ts, eid) >= held


def _facet_value(value: object) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def _facet_counts(spans: Mapping[SpanKey, set[tuple[str, str]]]) -> dict[str, dict[str, int]]:
    """{facet key: {value: number of spans carrying it}} over the union of each span's facets."""
    out: dict[str, dict[str, int]] = {}
    for pairs in spans.values():
        for k, v in pairs:
            out.setdefault(k, {})
            out[k][v] = out[k].get(v, 0) + 1
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def _empty() -> dict:
    return {"fired": {}, "fixed": set(), "justified": set(), "jr_accept": set(), "jr_reject": set(),
            "dismissed": {}, "upheld": set(), "missed": set(), "survived": set(), "kept": {}, "kept_docs": set(),
            "fp_kind": {}, "agree": {}, "last_fired": None, "events": 0}


def _add_facets(bucket: dict, key: SpanKey, facets: Mapping) -> None:
    bucket.setdefault(key, set()).update((str(k), _facet_value(v)) for k, v in facets.items())


def _fp_kind(acc: dict, key: SpanKey, e: Mapping, kind: str) -> None:
    """Keep the span's latest justification kind (by `ts`, then id): a justification rewritten from
    `false_positive` to another kind no longer counts as a false positive."""
    ts, eid = str(e.get("ts", "")), str(e.get("id", ""))
    held = acc["fp_kind"].get(key)
    if _later(None if held is None else held[:2], ts, eid):
        acc["fp_kind"][key] = (ts, eid, kind)


def _since_days(ts: str | None, now: datetime) -> int | None:
    if ts is None:
        return None
    try:
        return max(0, (now - datetime.fromisoformat(ts)).days)
    except (TypeError, ValueError):
        return None


def _finish(acc: dict, now: datetime) -> dict:
    fires = len(acc["fired"])
    fp_accepted = sum(1 for k in acc["jr_accept"] if acc["fp_kind"].get(k, (None, None, None))[2] == _FALSE_POSITIVE)
    agree_known = len(acc["agree"])
    agree_true = sum(1 for _, _, value in acc["agree"].values() if value)
    out = {
        "fires": fires,
        "docs": len({k[0] for k in acc["fired"]}),
        **{m: len(acc[m]) for m in ("fixed", "justified", "jr_accept", "jr_reject", "dismissed", "upheld", "missed",
                                    "survived")},
        "missed_docs": len({k[0] for k in acc["missed"]}),
        "kept_docs": len(acc["kept_docs"]),
        "events": acc["events"],
    }
    out.update({
        "fix_rate": _rate(out["fixed"], fires),
        "justify_rate": _rate(out["justified"], fires),
        "jr_accept_rate": _rate(out["jr_accept"], out["jr_accept"] + out["jr_reject"]),
        "dismiss_rate": _rate(out["dismissed"], fires),
        "effective_fp": _rate(max(0, out["dismissed"] + fp_accepted - out["upheld"]), fires),
        "agreement": _rate(agree_true, agree_known),
        "last_fired": acc["last_fired"],
        "days_since_fired": _since_days(acc["last_fired"], now),
        "facets": {"fired": _facet_counts(acc["fired"]), "kept": _facet_counts(acc["kept"]),
                   "dismissed": _facet_counts(acc["dismissed"])},
    })
    return out


def rule_metrics(events: Iterable[dict], cfg, now: datetime) -> dict[str, dict]:
    """Per-rule metrics, keyed by rule id (ruleset order, then other ids sorted). Each entry has:
    - counts of distinct span keys: `fires` (`fired` at BLOCK or WARN, any actor), `fixed`, `justified`
      (`justified:<kind>`), `jr_accept`, `jr_reject`, `dismissed`, `upheld`, `missed`, `survived`
      (`survived_publish`); `docs` and `missed_docs`, the distinct `doc_id`s among the fired and missed spans;
    - `kept_docs`: distinct docs with a `jr_accept`, or a `survived_publish` on a WARN span;
    - rates, None when the denominator is 0: `fix_rate`, `justify_rate` and `dismiss_rate` over `fires`;
      `jr_accept_rate` over `jr_accept + jr_reject`; `effective_fp` = max(0, dismissed + JR-accepted spans whose
      justification kind is `false_positive` − upheld) / fires, the kind being the latest (by `ts`, then id) of the
      `jr` event's facet and the `justify` events on the same span key; `agreement` = judge verdicts with `agree`
      true / those with `agree` (each span key counted once, by its latest verdict, the id breaking a tie in `ts`).
      Every rate is capped at 1: a `--since` window can count a fix or dismissal of a span first fired before it;
    - `last_fired`: the latest `ts` of any `fired` event (INFO shadow fires too: a firing rule isn't dormant), and
      `days_since_fired` from `now`;
    - `facets`: `{"fired" | "kept" | "dismissed": {facet: {value: spans}}}`, bools as "true" / "false";
    - `events`: the rule's distinct events of any kind (a rule with any is a report row).
    Events with no rule, pattern-only `missed` events (rule `?`) and the `pattern:<name>` events of a missed-pattern
    review proposal are left out: they belong to the missed patterns (`pattern_metrics`)."""
    accs: dict[str, dict] = {rid: _empty() for rid in cfg.rules}
    for e in ledger.distinct(events):
        rule = e.get("rule")
        if rule is None or rule == PATTERN_RULE or str(rule).startswith(PATTERN_PROPOSAL):
            continue
        acc = accs.setdefault(str(rule), _empty())
        acc["events"] += 1
        key, outcome, facets = _key(e), e.get("outcome"), e.get("facets") or {}
        if outcome == "fired":
            ts = e.get("ts")
            if isinstance(ts, str) and (acc["last_fired"] is None or ts > acc["last_fired"]):
                acc["last_fired"] = ts
            if e.get("severity") in FIRE_SEVERITIES:
                _add_facets(acc["fired"], key, facets)
        if (str(e.get("actor", "")).startswith("judge:") and outcome in ("fired", "passed")
                and isinstance(facets.get("agree"), bool)):  # live (event judge) or backfilled verdicts
            ts, eid = str(e.get("ts", "")), str(e.get("id", ""))
            held = acc["agree"].get(key)
            if _later(None if held is None else held[:2], ts, eid):
                acc["agree"][key] = (ts, eid, facets["agree"])
        if isinstance(outcome, str) and outcome.startswith("justified:"):
            acc["justified"].add(key)
            _fp_kind(acc, key, e, outcome.partition(":")[2])
        elif outcome == "dismissed":
            _add_facets(acc["dismissed"], key, facets)
        elif outcome in _OUTCOME_METRIC:
            acc[_OUTCOME_METRIC[outcome]].add(key)
        if outcome == "jr_accept":
            if isinstance(facets.get("kind"), str):
                _fp_kind(acc, key, e, facets["kind"])
            acc["kept_docs"].add(key[0])
            _add_facets(acc["kept"], key, facets)
        elif outcome == "survived_publish" and e.get("severity") == "WARN":
            acc["kept_docs"].add(key[0])
            _add_facets(acc["kept"], key, facets)
    order = list(cfg.rules) + sorted(r for r in accs if r not in cfg.rules)
    return {rid: _finish(accs[rid], now) for rid in order}


def pattern_metrics(events: Iterable[dict]) -> dict[str, dict]:
    """Pattern-only `missed` tells (rule `?`, facet `pattern`): `{pattern: {"missed": distinct spans, "docs":
    distinct docs}}`, sorted by pattern."""
    spans: dict[str, set[SpanKey]] = {}
    for e in ledger.distinct(events):
        pattern = (e.get("facets") or {}).get("pattern")
        if e.get("rule") == PATTERN_RULE and e.get("outcome") == "missed" and isinstance(pattern, str):
            spans.setdefault(pattern, set()).add(_key(e))
    return {p: {"missed": len(s), "docs": len({k[0] for k in s})} for p, s in sorted(spans.items())}


def has_events(m: Mapping) -> bool:
    """The rule has any event in the ledger (a row in the report and the share export)."""
    return bool(m.get("events"))


# --- friction ------------------------------------------------------------------------------------------------------

def friction_summary(rows: Iterable[dict], events: Iterable[dict]) -> dict:
    """`{"kinds": {kind: n}, "judge_returned": n, "judge_recorded": n}`. Returned: the backstop hook's
    `agent_handback` friction from the judge agent (one per agent run). Recorded: distinct `(doc_id, doc_sha,
    actor)` among `judge` and `jr` events, one per judge group (or JR) reply that reached a merge for that article
    version. The judge agent also answers in JR mode, so JR verdicts count as recorded replies too."""
    kinds: dict[str, int] = {}
    returned = 0
    for row in rows:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        if row["kind"] == "agent_handback" and row.get("source") in JUDGE_AGENTS:
            returned += 1
    recorded = {(e.get("doc_id"), e.get("doc_sha"), e.get("actor")) for e in events
                if e.get("event") in ("judge", "jr")}
    return {"kinds": dict(sorted(kinds.items())), "judge_returned": returned, "judge_recorded": len(recorded)}


# --- report --------------------------------------------------------------------------------------------------------

# (header, metric, width, kind)
_COLUMNS = (("rule", None, 6, "id"), ("fires", "fires", 5, "n"), ("docs", "docs", 4, "n"),
            ("fixed", "fixed", 5, "n"), ("just", "justified", 4, "n"), ("jr+", "jr_accept", 4, "n"),
            ("jr-", "jr_reject", 4, "n"), ("dism", "dismissed", 4, "n"), ("uphd", "upheld", 4, "n"),
            ("miss", "missed", 4, "n"), ("surv", "survived", 4, "n"), ("kept", "kept_docs", 4, "n"),
            ("fix%", "fix_rate", 4, "%"), ("just%", "justify_rate", 5, "%"), ("jr+%", "jr_accept_rate", 4, "%"),
            ("dism%", "dismiss_rate", 5, "%"), ("fp%", "effective_fp", 4, "%"), ("agr%", "agreement", 4, "%"),
            ("last fired", "last_fired", 10, "date"))
_LEGEND = ("just = justified · jr+/jr- = JR accepted/rejected · dism = dismissed · uphd = upheld · surv = survived "
           "publication · kept = docs kept (JR-accepted or a WARN that reached publication) · fp% = effective false "
           "positives · agr% = judge agrees with lint · - = no denominator · spans are counted once per document")


def _cell(m: Mapping, rid: str, metric: str | None, width: int, kind: str) -> str:
    if kind == "id":
        return rid.ljust(width)
    value = m[metric]
    if value is None:
        text = "-"
    elif kind == "%":
        text = f"{round(value * 100)}%"
    elif kind == "date":
        text = str(value)[:10]
    else:
        text = str(value)
    return text.rjust(width)


def _row(m: Mapping | None, rid: str) -> str:
    if m is None:
        return " ".join(h.ljust(w) if k == "id" else h.rjust(w) for h, _, w, k in _COLUMNS)
    return " ".join(_cell(m, rid, metric, w, k) for _, metric, w, k in _COLUMNS)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def report_lines(metrics: Mapping[str, Mapping], bad_lines: int, friction: Mapping,
                 patterns: Mapping[str, Mapping] | None = None) -> list[str]:
    """The `kaizen report` text: a fixed-width table with one row per rule with any event (ruleset order), the
    missed patterns, `N unreadable ledger lines` when there are any, and the friction counts. No composite score."""
    rows = [rid for rid, m in metrics.items() if has_events(m)]
    patterns = patterns or {}
    out: list[str] = []
    if not rows and not patterns:
        out.append("no kaizen events yet")
    if rows:
        out += [_row(None, ""), *(_row(metrics[rid], rid) for rid in rows), "", *textwrap.wrap(_LEGEND, 110)]
    if patterns:
        out += ["", "missed patterns (no rule covers them):"]
        out += [f"  {p}: {_plural(v['missed'], 'span')} in {_plural(v['docs'], 'doc')}" for p, v in patterns.items()]
    if bad_lines:
        out += ["", f"{_plural(bad_lines, 'unreadable ledger line')} (skipped)"]
    kinds = friction.get("kinds") or {}
    out += ["", "friction: " + (", ".join(f"{k} {n}" for k, n in kinds.items()) or "none")]
    out.append(f"judge replies returned (backstop) {friction.get('judge_returned', 0)} vs recorded "
               f"{friction.get('judge_recorded', 0)}")
    return out


# --- calibrate due -------------------------------------------------------------------------------------------------

DUE_DAYS = 30     # the Stop nudge says calibrate is due after this long without one...
DUE_EVENTS = 50   # ...and at least this many distinct events since the last one
LAST_CALIBRATE = "last-calibrate.txt"  # in `proposals_dir`: when `kaizen calibrate` last ran, proposals or not


def mark_calibrated(settings: Mapping, now: datetime) -> None:
    """Record that `kaizen calibrate` ran at `now`, in `<proposals_dir>/last-calibrate.txt`. A calibrate that finds
    nothing writes no ledger event, so without this the nudge could never be satisfied. Never raises."""
    try:
        from plainspoken import report  # the engine; kept out of the metrics import path
        stamp = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
        report.write_atomic(Path(settings["proposals_dir"]) / LAST_CALIBRATE, stamp + "\n")
    except Exception:  # deliberate: a missing stamp only means an early nudge
        return


def _last_marked(settings: Mapping) -> str | None:
    try:
        path = Path(settings["proposals_dir"]) / LAST_CALIBRATE
        if path.is_symlink() or not path.is_file():
            return None
        stamp = path.read_text(encoding="utf-8").strip()
        datetime.fromisoformat(stamp)
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return None
    return stamp if ledger.valid_ts(stamp) else None


def last_calibrated(events: Iterable[dict], settings: Mapping) -> str | None:
    """When calibrate last ran: the later of the newest `calibrate` ledger event and the `last-calibrate.txt` stamp,
    or None when it never has."""
    stamps = [e["ts"] for e in events if e.get("event") == "calibrate"]
    marked = _last_marked(settings)
    if marked is not None:
        stamps.append(marked)
    return max(stamps, default=None)


def calibrate_due(events: Iterable[dict], settings: Mapping, now: datetime) -> int | None:
    """The number of distinct events since the last calibrate (`last_calibrated`; every event when it never ran)
    when calibrate is due (none for `DUE_DAYS` and at least `DUE_EVENTS` distinct events since), else None."""
    events = ledger.distinct(events)
    last = last_calibrated(events, settings)
    if last is not None and now - datetime.fromisoformat(last) < timedelta(days=DUE_DAYS):
        return None
    n = sum(1 for e in events if last is None or e["ts"] > last)
    return n if n >= DUE_EVENTS else None


# --- share ---------------------------------------------------------------------------------------------------------

def plugin_version(path: Path = PLUGIN_JSON) -> str:
    """The plugin's `version` from `.claude-plugin/plugin.json`, or `unknown`."""
    try:
        version = json.loads(Path(path).read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return "unknown"
    return version if isinstance(version, str) and version else "unknown"


def share(metrics: Mapping[str, Mapping], cfg, plugin_version: str, *, since: str | None = None,
          until: str | None = None) -> dict:
    """The anonymised export a person may paste into an upstream issue: `{"plainspoken", "ruleset_version",
    "window": {since, until}, "rules": {id: {the COUNTS}}}` for each ruleset rule with any event. Counts only: no
    profile name, doc ids, hashes, facets, reasons, excerpts, paths, rates or dates. Only ids in `cfg.rules` are
    exported: a hand-edited ledger line could carry any string as its rule."""
    return {"plainspoken": str(plugin_version), "ruleset_version": str(cfg.version),
            "window": {"since": since, "until": until},
            "rules": {rid: {c: int(m[c]) for c in COUNTS} for rid, m in metrics.items()
                      if rid in cfg.rules and has_events(m)}}


# --- window --------------------------------------------------------------------------------------------------------

def parse_when(text: str) -> str:
    """An ISO date (00:00 UTC) or datetime (UTC when naive) as the ledger's `ts` form,
    `YYYY-MM-DDTHH:MM:SS+00:00`. Raises ValueError otherwise."""
    value = str(text).strip()
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{value!r} isn't an ISO date or datetime (e.g. 2026-10-01)") from None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).replace(microsecond=0).isoformat()


# --- the tool-call check (#124) ------------------------------------------------------------------------------------
# Read from `tool-calls.jsonl` (`ledger.read_rows`): one row per field the check looked at, with no text. Proposals
# are lines for a person to weigh, never applied.

TC_LINTED = ("clean", "warned", "blocked", "asked", "resent-changed", "resent-unchanged")
TC_FINDINGS = ("warned", "blocked", "asked", "resent-changed", "resent-unchanged")
TC_HOLDS = ("blocked", "asked")
TC_RAISE_HOLDS, TC_RAISE_SHARE = 30, 0.5  # raise min_words: 30+ holds, over half of the lowest band's resent unchanged
TC_LOWER_NEAR, TC_LOWER_RATE, TC_LOWER_RESENT = 20, 0.3, 0.2
TC_SKIP_HOLDS, TC_SKIP_SHARE = 10, 0.6  # a skip glob for a tool: 10+ holds, 60%+ resent unchanged


def tool_call_summary(rows: Iterable[dict], min_words: int) -> dict:
    """Counts by word band (linted, with findings, holds, resent unchanged), near misses (under the cut-off, at
    least half of it), the band just above the cut-off, and holds by tool."""
    bands = {name: {"linted": 0, "findings": 0, "holds": 0, "resent_unchanged": 0} for _, name in ledger.BUCKETS}
    above = {"linted": 0, "findings": 0, "holds": 0, "resent_unchanged": 0}
    tools: dict[str, dict[str, int]] = {}
    near = total = 0
    for r in rows:
        total += 1
        outcome = r["outcome"]
        if outcome == "below-cutoff" and r["words"] >= min_words / 2:
            near += 1
        if outcome not in TC_LINTED:
            continue
        cells = [bands[r["bucket"]]] + ([above] if r["words"] < 2 * min_words else [])
        tool = tools.setdefault(r["tool_name"], {"holds": 0, "resent_unchanged": 0})
        for c in cells:
            c["linted"] += 1
            c["findings"] += outcome in TC_FINDINGS
            c["holds"] += outcome in TC_HOLDS
            c["resent_unchanged"] += outcome == "resent-unchanged"
        tool["holds"] += outcome in TC_HOLDS
        tool["resent_unchanged"] += outcome == "resent-unchanged"
    return {"rows": total, "min_words": min_words, "near_misses": near, "above_cutoff": above,
            "bands": {k: v for k, v in bands.items() if v["linted"]},
            "tools": {k: v for k, v in sorted(tools.items()) if v["holds"]}}


def tool_call_proposals(summary: Mapping) -> list[str]:
    """Proposals from the starting tuning rules; a person decides, nothing changes on its own."""
    out = []
    bands, n = summary["bands"], summary["min_words"]
    holds = sum(b["holds"] for b in bands.values())
    lowest = next((name for name, b in bands.items() if b["holds"]), None)
    if holds >= TC_RAISE_HOLDS and lowest:
        b = bands[lowest]
        if b["resent_unchanged"] > TC_RAISE_SHARE * b["holds"]:
            out.append(f"raise [tool_call] min_words from {n}: {b['resent_unchanged']} of {b['holds']} holds in the "
                       f"{lowest}-word band were sent again unchanged")
    a = summary["above_cutoff"]
    if (summary["near_misses"] >= max(TC_LOWER_NEAR, a["linted"]) and a["linted"]
            and a["findings"] >= TC_LOWER_RATE * a["linted"]
            and a["resent_unchanged"] < TC_LOWER_RESENT * max(a["holds"], 1)):
        out.append(f"lower [tool_call] min_words from {n}: {summary['near_misses']} fields fell just under it, and "
                   f"{a['findings']} of {a['linted']} just over it had findings")
    for tool, t in summary["tools"].items():
        if t["holds"] >= TC_SKIP_HOLDS and t["resent_unchanged"] >= TC_SKIP_SHARE * t["holds"]:
            out.append(f"add a [tool_call] skip glob for *__{tool}: {t['resent_unchanged']} of {t['holds']} holds "
                       "were sent again unchanged")
    return out


def tool_call_lines(summary: Mapping) -> list[str]:
    """The `kaizen report` section for the tool-call check; [] when it hasn't recorded anything."""
    if not summary.get("rows"):
        return []
    out = ["", f"tool-call check (min_words {summary['min_words']}):"]
    for name, b in summary["bands"].items():
        out.append(f"  {name:>8} words: {_plural(b['linted'], 'field')} linted, {b['findings']} with findings, "
                   f"{b['holds']} held, {b['resent_unchanged']} sent again unchanged")
    out.append(f"  near misses (half the cut-off up to it): {summary['near_misses']}")
    for tool, t in summary["tools"].items():
        out.append(f"  {tool}: {t['holds']} held, {t['resent_unchanged']} sent again unchanged")
    out += [f"  proposal: {p}" for p in tool_call_proposals(summary)]
    return out
