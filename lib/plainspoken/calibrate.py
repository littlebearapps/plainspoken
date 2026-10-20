"""Kaizen calibrate (Phase 5): ledger evidence → triggers → candidates → at most `max_proposals` proposals.

Calibrate never edits the ruleset, the rubrics or a profile. A proposal's diff and corpus effect come from a copy in
a temporary folder; only `kaizen apply`, after a recorded approval, writes anything (`proposals.apply`).

The triggers, in priority order (one candidate per rule, its highest-priority trigger that survives the filters):
1. `stuck`: a BLOCK span dismissed with kind `unfixable` → demote, through a `demote` knob first.
2. `fp`: fires ≥ `fp_min_fires` and effective FP > `fp_rate` → loosen through a knob; else demote a BLOCK rule;
   else shadow a lint WARN rule; else review.
3. `missed`: `missed` events on one rule or pattern in ≥ `missed_min_docs` docs → review.
4. `kept`: `kept_docs` ≥ `kept_min_docs` (WARN spans only) → loosen through a knob, else review.
5. `dormant`: no fire in `dormant_days`, on a ledger at least that old → deprecate → shadow (lint) or remove → remove,
   one step per `cycle_days` since the rule's last applied proposal.

A demote is a severity edit only for a `judge`-method rule (a lint check sets its own severities
in code). A lint or lint+judge rule with no demote knob, and a `remove` that would orphan an [aliases] entry
or a knob in kaizen.toml, become `review` proposals: no edits, and `apply` refuses them.

Evidence is spent once a proposal for its rule is applied: only a rule's events after its latest
`applied` event count toward its triggers.

Candidates are filtered: a rule + action rejected within `cooldown_days`, and a candidate already stored and still
open (no decision, or approved and not applied), are skipped. Within a trigger: narrow (facet) knobs first, then more
evidence docs, then rule id.

`settings` is the `config.kaizen_settings` dict, optionally merged with `load_settings()` (keys `triggers` and
`knobs`); without them the shipped `data/kaizen.toml` is used. The settings, the knobs and the concrete edits a knob
makes live in `calibrate_knobs`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import tomllib
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from plainspoken import (adapters, config, kaizen, ledger, profile as _profile, proposals, registry, report,
                         rulesedit)
# The settings (data/kaizen.toml) and the knobs live in calibrate_knobs; these names stay calibrate's public face.
from plainspoken.calibrate_knobs import DEFAULT, DIRECTIONS, _cal, _concrete, _pick, _view, load_settings  # noqa: F401

TRIGGERS = ("stuck", "fp", "missed", "kept", "dormant")
GOLDEN = "not available until Phase 6"
_FIRES = ("BLOCK", "WARN")
_NATURAL = re.compile(r"(\d*)(.*)", re.S)


def _first_line(e: BaseException) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


# --- evidence -----------------------------------------------------------------------------------------------------

def _facet_value(value: object) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def candidate_key(c: Mapping) -> str:
    """Identifies a candidate across runs: its rule, trigger, action and edit intents (not the values it reads)."""
    return proposals.digest({k: c.get(k) for k in ("rule", "trigger", "action", "edits")})[:12]


# One id function for calibrate, mine and apply: an approval binds to everything apply acts on.
proposal_id = proposals.proposal_id


# --- candidates ----------------------------------------------------------------------------------------------------

def _natural(rule: str) -> tuple:
    digits, rest = _NATURAL.match(rule).groups()
    return (int(digits) if digits else 10 ** 6, rest)


def _span_facets(events: list[dict], pred) -> dict[str, dict]:
    """{rule: {span key: {facet: value}}} over the events `pred` accepts."""
    out: dict[str, dict] = {}
    for e in events:
        if e.get("rule") and pred(e):
            bucket = out.setdefault(str(e["rule"]), {}).setdefault((e.get("doc_id"), e.get("span_hash")), {})
            bucket.update({str(k): _facet_value(v) for k, v in (e.get("facets") or {}).items()})
    return out


def _counts(spans: Mapping) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for facets in spans.values():
        for k, v in facets.items():
            out.setdefault(k, {})
            out[k][v] = out[k].get(v, 0) + 1
    return out


def _excerpts(events: list[dict], rule: str, pred) -> list[str]:
    seen: list[str] = []
    for e in events:
        if e.get("rule") == rule and pred(e) and isinstance(e.get("excerpt"), str) and e["excerpt"] not in seen:
            seen.append(e["excerpt"])
    return seen[:3]


def _cand(rule, trigger, action, edits, reason, evidence, docs, narrow=False, excerpts=()) -> dict:
    return {"rule": rule, "trigger": trigger, "action": action, "edits": edits, "reason": reason,
            "evidence": evidence, "docs": docs, "narrow": narrow, "excerpts": list(excerpts)}


def _demote(rule, trigger, reason, evidence, docs, n, facets, cal, view, excerpts) -> dict:
    picked = _pick(rule.id, "demote", n, facets, cal, view)
    if picked:
        return _cand(rule.id, trigger, "demote", [picked[1]], reason, evidence, docs, picked[0]["facet"] is not None,
                     excerpts)
    if rule.method == "judge" and rule.severity == "BLOCK":  # a lint part sets its own severities in code
        return _cand(rule.id, trigger, "demote", [{"kind": "rule_field", "rule": rule.id, "field": "severity",
                                                   "new": "WARN"}], reason, evidence, docs, excerpts=excerpts)
    gap = (f"rule {rule.id} is lint-checked and sets its severities in code, so a demote needs a knob or a hand PR"
           if rule.method == "lint" else
           f"rule {rule.id}'s lint check sets its severities in code, so a demote needs a knob or a hand PR"
           if rule.method == "lint+judge" else f"rule {rule.id} has no demote step")
    return _cand(rule.id, trigger, "review", [], f"{reason}; {gap}", evidence, docs, excerpts=excerpts)


def _ledger_profiles(events: list[dict], settings: Mapping) -> list:
    """The profiles named in the ledger that load; the others are skipped."""
    root = settings.get("root")
    search = (Path(root) / ".plainspoken" / "profiles",) if root else ()
    out = []
    for name in sorted({e.get("profile") for e in events if isinstance(e.get("profile"), str)}):
        try:
            out.append(_profile.load(name, search=search))
        except (ValueError, OSError):
            continue
    return out


def _dormant(rule, m, events, profiles, aliases, knobbed, t, now) -> dict | None:
    if rule.method == "n/a":
        return None
    if rule.requires is not None and not any(rule.applies_to(p) for p in profiles):
        return None
    if rule.requires is None and profiles and not any(rule.applies_to(p) for p in profiles):
        return None  # every profile in the ledger disables it, so silence says nothing
    since = m.get("days_since_fired")
    if since is not None and since < t["dormant_days"]:
        return None
    last = max((e["ts"] for e in events if e.get("event") == "apply" and e.get("outcome") == "applied"
                and e.get("rule") == rule.id), default=None)
    if last is not None and now - datetime.fromisoformat(last) < timedelta(days=t["cycle_days"]):
        return None
    reason = f"no fire in {t['dormant_days']} days" if since is None else f"last fired {since} days ago"
    evidence = {"days_since_fired": since, "last_fired": m.get("last_fired"), "status": rule.status}
    if rule.status == "active":
        return _cand(rule.id, "dormant", "deprecate", [{"kind": "rule_field", "rule": rule.id, "field": "status",
                                                        "new": "deprecated"}], reason, evidence, 0)
    if rule.status == "deprecated" and rule.method == "lint":
        return _cand(rule.id, "dormant", "shadow", [{"kind": "rule_field", "rule": rule.id, "field": "status",
                                                     "new": "shadow"}], reason, evidence, 0)
    if rule.id in aliases:
        return _cand(rule.id, "dormant", "review", [], f"{reason}; rule {rule.id} is in [aliases], so removing it "
                     "needs a hand PR", evidence, 0)
    if rule.id in knobbed:
        return _cand(rule.id, "dormant", "review", [], f"{reason}; rule {rule.id} has a knob in kaizen.toml, so "
                     "removing it needs a hand PR", evidence, 0)
    return _cand(rule.id, "dormant", "remove", [{"kind": "rule_remove", "rule": rule.id}], reason, evidence, 0)


def _rule_candidates(rule, m, ctx) -> list[dict]:
    """Every trigger's candidate for one rule, in priority order."""
    t, cal, view, evs = ctx["t"], ctx["cal"], ctx["view"], ctx["events"]
    out = []
    stuck = ctx["stuck"].get(rule.id, {})
    if stuck:
        docs = len({k[0] for k in stuck})
        out.append(_demote(rule, "stuck", f"{len(stuck)} BLOCK span(s) dismissed as unfixable", {
            "unfixable_spans": len(stuck), "docs": docs, "facets": _counts(stuck)}, docs, len(stuck),
            _counts(stuck), cal, view, _excerpts(evs, rule.id, ctx["is_stuck"])))
    fp = m.get("effective_fp")
    if m["fires"] >= t["fp_min_fires"] and fp is not None and fp > t["fp_rate"]:
        reason = f"effective false positives {round(fp * 100)}% over {m['fires']} fires"
        evidence = {"fires": m["fires"], "docs": m["docs"], "dismissed": m["dismissed"], "upheld": m["upheld"],
                    "effective_fp": round(fp, 4), "facets": m["facets"]["dismissed"]}
        ex = _excerpts(evs, rule.id, lambda e: e.get("outcome") == "dismissed")
        facets = m["facets"]["dismissed"]
        picked = _pick(rule.id, "loosen", m["dismissed"], facets, cal, view)
        if picked:
            out.append(_cand(rule.id, "fp", "loosen", [picked[1]], reason, evidence, m["docs"],
                             picked[0]["facet"] is not None, ex))
        elif rule.severity == "BLOCK":
            out.append(_demote(rule, "fp", reason, evidence, m["docs"], m["dismissed"], facets, cal, view, ex))
        elif rule.method == "lint" and rule.status != "shadow":
            out.append(_cand(rule.id, "fp", "shadow", [{"kind": "rule_field", "rule": rule.id, "field": "status",
                                                        "new": "shadow"}], reason, evidence, m["docs"], excerpts=ex))
        else:
            out.append(_cand(rule.id, "fp", "review", [], f"{reason}; no knob fits a judged rule", evidence,
                             m["docs"], excerpts=ex))
    if m["missed_docs"] >= t["missed_min_docs"]:
        out.append(_cand(rule.id, "missed", "review", [], f"missed in {m['missed_docs']} docs",
                         {"missed": m["missed"], "missed_docs": m["missed_docs"]}, m["missed_docs"],
                         excerpts=_excerpts(evs, rule.id, lambda e: e.get("outcome") == "missed")))
    if m["kept_docs"] >= t["kept_min_docs"]:
        kept = ctx["kept"].get(rule.id, {})
        facets = m["facets"]["kept"]
        reason = f"kept in {m['kept_docs']} docs"
        evidence = {"kept_docs": m["kept_docs"], "kept_spans": len(kept), "jr_accept": m["jr_accept"],
                    "survived": m["survived"], "facets": facets}
        ex = _excerpts(evs, rule.id, ctx["is_kept"])
        picked = _pick(rule.id, "loosen", len(kept), facets, cal, view)
        if picked:
            out.append(_cand(rule.id, "kept", "loosen", [picked[1]], reason, evidence, m["kept_docs"],
                             picked[0]["facet"] is not None, ex))
        else:
            out.append(_cand(rule.id, "kept", "review", [], f"{reason}; no knob fits", evidence, m["kept_docs"],
                             excerpts=ex))
    if ctx["old_enough"]:
        c = _dormant(rule, m, evs, ctx["profiles"], ctx["aliases"], ctx["knobbed"], t,
                     ctx["now"])
        if c:
            out.append(c)
    return out


def _open_keys(settings: Mapping, events: list[dict]) -> set[str]:
    """Keys of stored proposals still open: no decision yet, or approved and not applied."""
    if not settings.get("proposals_dir"):
        return set()
    return {p.get("key") for p in proposals.stored(settings)
            if proposals.status(p["id"], events) in ("pending", "approved")}


def _cooling(settings: Mapping, events: list[dict], now: datetime, days: int) -> set[tuple]:
    """(rule, action) pairs rejected within `days`."""
    out = set()
    if not settings.get("proposals_dir"):
        return out
    for e in events:
        if (e.get("event") == "decision" and e.get("outcome") == "rejected"
                and now - datetime.fromisoformat(e["ts"]) < timedelta(days=days)):
            try:
                p = proposals.load(e.get("proposal"), settings)
            except proposals.UnknownProposal:
                continue
            out.add((p.get("rule"), p.get("action")))
    return out


_BOOKKEEPING = ("apply", "calibrate", "decision")  # events that record what the loop did, never evidence


def _unspent(events: list[dict], metrics: Mapping[str, Mapping], cfg, now: datetime) -> tuple[list[dict], dict]:
    """Evidence is spent once a proposal for its rule is applied: (the events without each rule's
    evidence up to and including its latest `applied` event, the metrics with those rules recounted). A profile
    apply spends only the evidence recorded under that profile. A review
    proposal is never applied, so it doesn't reset anything. Bookkeeping events stay, and so do `last_fired` and
    `days_since_fired`: the dormant trigger measures silence, and a rule that fired before the change wasn't silent."""
    last: dict[tuple[str, str | None], datetime] = {}
    for e in events:
        if e.get("event") == "apply" and e.get("outcome") == "applied" and e.get("rule"):
            # a profile apply spends that profile's evidence only; a ruleset apply (or one logged before the
            # target was recorded) spends every profile's
            scope = e.get("profile") if (e.get("facets") or {}).get("kind") == "profile" else None
            key, when = (str(e["rule"]), scope), datetime.fromisoformat(e["ts"])
            if key not in last or when > last[key]:
                last[key] = when

    def spent(e: Mapping) -> bool:
        if e.get("event") in _BOOKKEEPING or not e.get("rule"):
            return False
        cuts = [last[k] for k in ((str(e["rule"]), None), (str(e["rule"]), e.get("profile"))) if k in last]
        return bool(cuts) and datetime.fromisoformat(e["ts"]) <= max(cuts)

    if not last:
        return events, dict(metrics)
    kept = [e for e in events if not spent(e)]
    fresh = kaizen.rule_metrics(kept, cfg, now)
    out = dict(metrics)
    for rule in {r for r, _ in last}:
        if rule in fresh:
            old = metrics.get(rule, {})
            out[rule] = {**fresh[rule], "last_fired": old.get("last_fired"),
                         "days_since_fired": old.get("days_since_fired")}
    return kept, out


def candidates(metrics: Mapping[str, Mapping], events: Iterable[dict], cfg, settings: Mapping, now: datetime,
               ledger_start: datetime | None) -> list[dict]:
    """Deterministic, ranked candidates: trigger priority, then narrow knobs, then more evidence docs, then rule id.
    Each is `{"rule", "trigger", "action", "edits" (intents), "reason", "evidence", "docs", "narrow", "excerpts",
    "key"}`."""
    cal = _cal(settings)
    t = cal["triggers"]
    every = ledger.distinct(events)
    evs, metrics = _unspent(every, metrics, cfg, now)

    def is_stuck(e):
        return (e.get("outcome") == "dismissed" and e.get("severity") == "BLOCK"
                and (e.get("facets") or {}).get("kind") == "unfixable")

    def is_kept(e):
        return e.get("outcome") == "jr_accept" or (e.get("outcome") == "survived_publish"
                                                    and e.get("severity") == "WARN")

    old_enough = ledger_start is not None and ledger_start <= now - timedelta(days=t["dormant_days"])
    ctx = {"t": t, "cal": cal, "view": _view(cfg), "events": evs, "now": now, "old_enough": old_enough,
           "stuck": _span_facets(evs, is_stuck), "is_stuck": is_stuck, "kept": _span_facets(evs, is_kept),
           "is_kept": is_kept, "aliases": {x for pair in cfg.aliases for x in pair},
           "knobbed": {k["rule"] for k in cal["knobs"]},
           "profiles": _ledger_profiles(evs, settings) if old_enough else []}
    cooling = _cooling(settings, every, now, t["cooldown_days"])
    open_keys = _open_keys(settings, every)

    def keep(c) -> bool:
        c["key"] = candidate_key(c)
        return (c["rule"], c["action"]) not in cooling and c["key"] not in open_keys

    out = []
    for rid, rule in cfg.rules.items():
        if rid in metrics:
            found = next((c for c in _rule_candidates(rule, metrics[rid], ctx) if keep(c)), None)
            if found:
                out.append(found)
    for pattern, pm in kaizen.pattern_metrics(evs).items():
        if pm["docs"] >= t["missed_min_docs"]:
            c = _cand(f"pattern:{pattern}", "missed", "review", [], f"missed in {pm['docs']} docs, no rule covers it",
                      {"missed": pm["missed"], "missed_docs": pm["docs"]}, pm["docs"])
            if keep(c):
                out.append(c)
    return sorted(out, key=lambda c: (TRIGGERS.index(c["trigger"]) if c["trigger"] in TRIGGERS else len(TRIGGERS),
                                      not c["narrow"], -c["docs"], _natural(c["rule"])))


# --- proposals -----------------------------------------------------------------------------------------------------

def _field_value(v) -> str:
    """A field value as the summary shows it: an empty one (None, [], "") is `unset`, a list its items, a bool or
    number its TOML form (a falsy old value used to print as itself, often nothing)."""
    if v is None or v == [] or v == "":
        return "unset"
    if isinstance(v, (list, tuple)):
        return ", ".join(map(str, v))
    return json.dumps(v) if isinstance(v, (bool, int, float)) else str(v)


def _describe(e: Mapping) -> str:
    if e["kind"] == "set_threshold":
        return f"{e['key']} {json.dumps(e['old'])} → {json.dumps(e['new'])}"
    if e["kind"] == "list_add":
        return f"add {', '.join(e['values'])} to {e['list']}"
    if e["kind"] == "rule_field":
        return f"{e['field']} {_field_value(e['old'])} → {_field_value(e['new'])}"
    if e["kind"] == "rule_add":
        extra = [f"list {n}" for n in e.get("lists") or {}] + [f"threshold {k}" for k in e.get("thresholds") or {}]
        head = f"add rule {e['rule']} ({e['block'].get('name', '?')})"
        return head + (f" with {' and '.join(extra)}" if extra else "")
    if e["kind"] == "threshold_add":
        return f"add threshold {e['key']} = {json.dumps(e['value'])}"
    return "remove the rule"


def _lint_counts(lint: dict) -> tuple[Counter, frozenset]:
    found = [f for f in lint["findings"] if f.get("severity") in _FIRES]
    return (Counter(f["rule"] for f in found),
            frozenset((f["rule"], f["severity"], f.get("line"), str(f.get("excerpt"))) for f in found))


def _effect(edits: list[dict], new_text: str | None, cfg, profile, corpus: list[Path]) -> dict:
    if not edits or new_text is None:
        return {"corpus": "not measured (no edits)", "golden": GOLDEN}
    if not corpus:
        return {"corpus": "not measured (no corpus)", "golden": GOLDEN}
    if profile is None:
        return {"corpus": "not measured (no profile)", "golden": GOLDEN}
    before, after, changed, errors = Counter(), Counter(), [], 0
    with tempfile.TemporaryDirectory(prefix="plainspoken-calibrate-") as tmp:
        path = Path(tmp) / "rules.toml"
        path.write_text(new_text, encoding="utf-8")
        edited = registry.load_config(path)
        for f in corpus:
            try:
                (b, b_set), (a, a_set) = (_lint_counts(report.run_lint(Path(f), profile, cfg=c)) for c in (cfg, edited))
            except (ValueError, OSError):
                errors += 1
                continue
            before.update(b)
            after.update(a)
            if a_set != b_set:
                changed.append(Path(f).stem)
    out = {"files": len(corpus) - errors, "before": dict(sorted(before.items())),
           "after": dict(sorted(after.items())), "changed": changed}
    if errors:
        out["unreadable"] = errors
    return {"corpus": out, "golden": GOLDEN}


def _as_review(c: Mapping, why: str) -> dict:
    return {**c, "action": "review", "edits": [], "reason": f"{c.get('reason', '')}; {why}".strip("; ")}


def materialise(candidate: Mapping, rules_path: Path | None, cfg, profile, corpus: list[Path], now: datetime, *,
                skip_ids: set[str] | frozenset = frozenset()) -> dict | None:
    """The proposal for one candidate: concrete edits with `old` read from the ruleset file, the diff and the corpus
    effect from a temporary copy, evidence, targets and a one-line summary. Reads the ruleset; writes nothing
    outside a temporary folder. An edit that no longer applies turns the proposal into a `review`. None when its id
    is in `skip_ids` (already stored), worked out before the corpus effect, which lints every corpus file twice."""
    path = Path(rules_path) if rules_path is not None else proposals.default_rules()
    data = path.read_bytes()
    text = data.decode("utf-8")
    raw = tomllib.loads(text)
    c = dict(candidate)
    edits, new_text = [], None
    if c.get("edits"):
        try:
            edits = _concrete(c["edits"], raw)
            new_text = rulesedit.apply_edits(text, edits)
        except rulesedit.EditError as e:
            c, edits, new_text = _as_review(c, _first_line(e)), [], None
    action = c["action"]
    reason = c.get("reason", "")
    if edits:
        summary = f"rule {c['rule']}: {action} ({reason}): {'; '.join(_describe(e) for e in edits)}"
    else:
        summary = f"rule {c['rule']}: review ({reason}): make the change by hand in a PR if it's right"
    evidence = dict(c.get("evidence") or {})
    if c.get("excerpts"):
        evidence["excerpts"] = list(c["excerpts"])[:3]
    targets = ([] if not edits else
               ["ruleset", "profile"] if all(e["kind"] == "set_threshold" and e.get("table", "default") == "default"
                                             for e in edits) else ["ruleset"])
    out = {
        "id": None, "created": now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "rule": c["rule"], "trigger": c["trigger"], "action": action, "key": c.get("key") or candidate_key(candidate),
        "edits": edits, "bump": None if not edits else ("major" if action == "remove" else "minor"),
        "ruleset_version": str(raw.get("version")), "base_sha256": hashlib.sha256(data).hexdigest(),
        "diff": rulesedit.diff(text, new_text, path.name) if new_text is not None else "",
        "evidence": evidence, "effect": None,
        "targets": targets, "profile": getattr(profile, "name", None), "summary": " ".join(summary.split()),
    }
    out["id"] = proposal_id(now, out)  # the id doesn't cover the effect
    if out["id"] in skip_ids:
        return None
    out["effect"] = _effect(edits, new_text, cfg, profile, list(corpus))
    return out


def corpus_files(root: Path, globs: Iterable[str]) -> list[Path]:
    """The files the globs (relative to `root`) match, sorted and deduplicated."""
    out: dict[Path, None] = {}
    for g in globs:
        for p in sorted(Path(root).glob(g)):
            if p.is_file():
                out.setdefault(p, None)
    return list(out)


class _Emitter:
    """Sends proposals through one adapter, built on first use (so a run that sends nothing never needs the adapter's
    settings). `adapters.send` owns the failure path: a failed emit leaves `emit_error` and no `ref` on the stored
    proposal. A sent proposal whose file couldn't be updated keeps the ref in memory with `save_error` set."""

    def __init__(self, settings: Mapping, adapter=None):
        self.settings, self.adapter, self.error = settings, adapter, None

    def _get(self):
        if self.adapter is None and self.error is None:
            try:
                self.adapter = adapters.get(self.settings)
            except adapters.AdapterError as e:
                self.error = e
        if self.error is not None:
            raise self.error
        return self.adapter

    def __call__(self, p: dict) -> None:
        try:
            adapters.send(p, self.settings, self._get)
        except adapters.AdapterError:
            pass  # recorded on the proposal by send; the caller reports it
        except adapters.NotSaved as e:
            p["save_error"] = str(e)


def run(root: Path, settings: Mapping, now: datetime, corpus: Iterable[str] | None = None,
        adapter=None, resent: list | None = None) -> list[dict]:
    """Calibrate once: read the ledger, rank candidates, materialise up to `max_proposals` new proposals (skipping
    ids already stored), save each, emit it through `adapter` (default: the configured one; a failed emit leaves
    `emit_error` and no `ref` on the proposal), and log a `calibrate` event (`proposed`). Never writes the ruleset,
    the rubrics or a profile.

    First, every stored proposal still waiting for a decision that was never sent (no `ref`: its emit failed) is
    sent again, whether or not there are new candidates; those go into `resent` when a list is given."""
    cal = _cal(settings)
    cfg = registry.load_config()
    events, _bad = ledger.read(settings)
    emit = _Emitter(settings, adapter)
    for waiting in adapters.unsent(settings, events):
        emit(waiting)
        if resent is not None:
            resent.append(waiting)
    metrics = kaizen.rule_metrics(events, cfg, now)
    start = min((e["ts"] for e in events), default=None)
    cands = candidates(metrics, events, cfg, settings, now, None if start is None else datetime.fromisoformat(start))
    if not cands:
        return []
    try:
        prof = config.resolve_profile(None, Path(root), os.environ, plugin_option=config.PLUGIN_DEFAULT)
    except (ValueError, OSError):
        prof = None
    files = corpus_files(root, settings.get("corpus", []) if corpus is None else corpus)
    known = {p["id"] for p in proposals.stored(settings)}
    out: list[dict] = []
    for c in cands:
        if len(out) >= cal["triggers"]["max_proposals"]:
            break
        p = materialise(c, None, cfg, prof, files, now, skip_ids=known)
        if p is None:
            continue
        proposals.save(p, settings)
        known.add(p["id"])
        emit(p)
        try:
            ledger.append(ledger.make_event(event="calibrate", actor="engine", outcome="proposed",
                                            ruleset_version=cfg.version, profile=getattr(prof, "name", "unknown"),
                                            rule=p["rule"], proposal=p["id"], ts=now), settings)
        except ledger.LedgerError:
            pass  # the proposal is stored; an unwritable ledger mustn't stop calibrate
        out.append(p)
    return out
