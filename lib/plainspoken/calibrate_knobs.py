"""Kaizen calibrate's settings and knobs (Phase 5; split from `calibrate`).

- `load_settings`: `data/kaizen.toml`, validated against the ruleset: the `[triggers]` thresholds and the
  `[[knobs]]` (each a rule, an optional facet and value (or list of values), optional `where` conditions on other
  facets, a direction and one edit: `set_threshold` with a `step` or `value`, or `list_add` from the term facet).
  A knob's facet, value and `where` say which findings its edit clears (#212). A facet makes a knob narrow; `where`
  only limits what a knob fits, so a broad knob with one stays broad (ranked after the narrow ones).
- `_pick`: the first knob of a rule and direction that fits the evidence and changes something; `_pick_kept`, the
  same for the `kept` trigger, by the docs whose every kept span the knob covers.
- `_concrete`: edit intents as `rulesedit` edits, with `old` read from the ruleset (`_view` builds what it reads from
  a loaded Config; the thresholds come through the public `Config.thresholds()`).
"""
from __future__ import annotations

import decimal
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path

from plainspoken import ledger, registry, rulesedit

DEFAULT = Path(__file__).resolve().parents[2] / "data" / "kaizen.toml"
DIRECTIONS = ("loosen", "demote")
_TRIGGER_TYPES = {"fp_min_fires": int, "fp_rate": float, "kept_min_docs": int, "missed_min_docs": int,
                  "dormant_days": int, "cycle_days": int, "cooldown_days": int, "max_proposals": int}
_KNOB_KEYS = {"rule", "facet", "value", "where", "direction", "edit"}
# The facet values a knob condition may name: the ledger's own, so a typo fails at load.
_FACET_VALUES = {"section": ledger.FACET_SECTIONS, "form": ledger.FACET_FORMS, "metric": ledger.FACET_METRICS}
# (rule, facet, value) where a rule no longer fires. Calibrate spends the spans logged there before the change, so
# they turn no knob: a 12d kept in a FAQ section proposes nothing (#208: 12d leaves FAQ sections out).
EXEMPT = {("12d", "section", "faq")}


# --- evidence ------------------------------------------------------------------------------------------------------

def _facet_value(value: object) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def _span_facets(events: list[dict], pred) -> dict[str, dict]:
    """{rule: {span key: {facet: {values}}}} over the events `pred` accepts: every value any of a span's events
    carries (a doc justified twice with findings in different sections holds both)."""
    out: dict[str, dict] = {}
    for e in events:
        if e.get("rule") and pred(e):
            bucket = out.setdefault(str(e["rule"]), {}).setdefault((e.get("doc_id"), e.get("span_hash")), {})
            for k, v in (e.get("facets") or {}).items():
                bucket.setdefault(str(k), set()).add(_facet_value(v))
    return out


def _counts(spans: Mapping) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for facets in spans.values():
        for k, values in facets.items():
            for v in values:
                out.setdefault(k, {})
                out[k][v] = out[k].get(v, 0) + 1
    return out


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _knob(where: str, k: object, cfg) -> dict:
    if not isinstance(k, dict):
        raise ValueError(f"{where}: a knob must be a table")
    if set(k) - _KNOB_KEYS:
        raise ValueError(f"{where}: unknown key(s) {sorted(set(k) - _KNOB_KEYS)}")
    rule, facet, direction, edit = k.get("rule"), k.get("facet"), k.get("direction"), k.get("edit")
    if not isinstance(rule, str) or rule not in cfg.rules:
        raise ValueError(f"{where}: unknown rule {rule!r}")
    if facet is not None and facet not in ledger.FACET_KEYS:
        raise ValueError(f"{where}: unknown facet {facet!r}")
    if (facet is None or facet == "term") == ("value" in k):
        raise ValueError(f"{where}: a facet knob needs a value (a term knob doesn't), and a broad knob has neither")
    if "where" in k and facet == "term":
        raise ValueError(f"{where}: a term knob takes no where")
    when = {} if facet is None or facet == "term" else {facet: _values(where, facet, k["value"])}
    extra = k.get("where", {})
    if not isinstance(extra, dict) or not all(isinstance(f, str) for f in extra):
        raise ValueError(f"{where}: where must be a table of facet = value or [values]")
    for f, v in extra.items():
        if f not in ledger.FACET_KEYS or f in ("term", facet):
            raise ValueError(f"{where}: where can't name facet {f!r}")
        when[f] = _values(where, f, v)
    if direction not in DIRECTIONS:
        raise ValueError(f"{where}: direction must be one of {', '.join(DIRECTIONS)}")
    if not isinstance(edit, dict):
        raise ValueError(f"{where}: edit must be a table")
    kind = edit.get("kind")
    if kind == "set_threshold":
        defaults = cfg.thresholds()
        key = edit.get("key")
        if key not in defaults:
            raise ValueError(f"{where}: unknown threshold {key!r}")
        if set(edit) - {"kind", "key", "step", "value"} or ("step" in edit) == ("value" in edit):
            raise ValueError(f"{where}: a set_threshold edit takes key and one of step or value")
        cur = defaults[key]
        if "step" in edit and not (_number(edit["step"]) and _number(cur)):
            raise ValueError(f"{where}: step needs a numeric threshold and a number")
        if "value" in edit and (isinstance(edit["value"], bool) != isinstance(cur, bool) or not
                                (isinstance(cur, bool) or _number(edit["value"]))):
            raise ValueError(f"{where}: value must be the same type as {key}")
    elif kind == "list_add":
        if edit.get("list") not in cfg.lists:
            raise ValueError(f"{where}: unknown list {edit.get('list')!r}")
        if facet != "term" or set(edit) - {"kind", "list"}:
            raise ValueError(f"{where}: a list_add knob takes only a list, and its values from the term facet")
    else:
        raise ValueError(f"{where}: edit kind must be set_threshold or list_add, got {kind!r}")
    value = k.get("value")
    return {"rule": rule, "facet": facet, "value": None if value is None else
            str(value) if not isinstance(value, list) else [str(x) for x in value],
            "when": when, "direction": direction, "edit": dict(edit)}


def _values(where: str, facet: str, v: object) -> tuple[str, ...]:
    """A condition's values: a string or a non-empty list of strings, each one the ledger allows for the facet."""
    values = [v] if isinstance(v, str) else v
    if not isinstance(values, list) or not values or not all(isinstance(x, str) for x in values):
        raise ValueError(f"{where}: facet {facet} needs a string or a list of strings")
    allowed = _FACET_VALUES.get(facet)
    if allowed is not None and set(values) - set(allowed):
        raise ValueError(f"{where}: facet {facet} must be one of {', '.join(allowed)}")
    return tuple(values)


def _when(k: Mapping) -> dict[str, tuple[str, ...]]:
    """The knob's conditions, {facet: allowed values}: what `_knob` built, or (a knob made in code) its facet and
    value. A term knob has none, and a broad knob only its `where`."""
    if "when" in k:
        return dict(k["when"])
    if k.get("facet") is None or k["facet"] == "term":
        return {}
    v = k.get("value")
    return {k["facet"]: tuple(v) if isinstance(v, (list, tuple)) else (str(v),)}


def load_settings(path: Path = DEFAULT, cfg=None) -> dict:
    """`data/kaizen.toml`, validated against the ruleset (`cfg`, default `registry.load_config()`):
    `{"triggers": {...}, "knobs": [...]}`. A knob for an unknown rule, threshold or list is a ValueError."""
    cfg = registry.load_config() if cfg is None else cfg
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: not valid TOML ({e})") from None
    triggers = raw.get("triggers")
    if not isinstance(triggers, dict):
        raise ValueError(f"{path}: missing [triggers]")
    if set(triggers) - set(_TRIGGER_TYPES):
        raise ValueError(f"{path}: unknown trigger setting(s) {sorted(set(triggers) - set(_TRIGGER_TYPES))}")
    out = {}
    for key, typ in _TRIGGER_TYPES.items():
        v = triggers.get(key)
        if not _number(v) or v < 0 or (typ is int and not isinstance(v, int)):
            raise ValueError(f"{path}: [triggers] {key} must be a non-negative {typ.__name__}")
        out[key] = v
    if not 0 < out["fp_rate"] < 1:
        raise ValueError(f"{path}: [triggers] fp_rate must be between 0 and 1")
    knobs = raw.get("knobs", [])
    if not isinstance(knobs, list):
        raise ValueError(f"{path}: knobs must be an array of tables")
    return {"triggers": out, "knobs": [_knob(f"{path}: [[knobs]] #{n}", k, cfg) for n, k in enumerate(knobs, 1)]}


def _cal(settings: Mapping) -> dict:
    if "triggers" in settings and "knobs" in settings:
        return {"triggers": settings["triggers"], "knobs": settings["knobs"]}
    return load_settings()


# --- concrete edits ------------------------------------------------------------------------------------------------

def _decimals(x) -> int:
    exp = decimal.Decimal(repr(x)).as_tuple().exponent
    return max(0, -exp) if isinstance(exp, int) else 0


def _view(cfg) -> dict:
    """The parts of a parsed rules.toml that edits read, built from a Config (rule fields unset when default)."""
    rules = [{"id": r.id, "severity": r.severity, **({"status": r.status} if r.status != "active" else {})}
             for r in cfg.rules.values()]
    return {"thresholds": {"default": cfg.thresholds()}, "lists": cfg.lists, "rules": rules}


def _concrete(intents: Iterable[dict], raw: Mapping) -> list[dict]:
    """Edit intents (a `step`, a `value`, values to add, a field's new value) as rulesedit edits with `old` read from
    `raw`. Raises EditError when an intent changes nothing or names something the ruleset hasn't got."""
    out = []
    try:
        for it in intents:
            kind = it["kind"]
            if kind == "set_threshold":
                table, key = it.get("table", "default"), it["key"]
                cur = raw["thresholds"][table][key]
                if "new" in it:
                    new = it["new"]
                elif "value" in it:
                    new = it["value"]
                else:
                    new = cur + it["step"]
                    if isinstance(new, float):
                        new = round(new, max(_decimals(cur), _decimals(it["step"])))
                    if new < 0:
                        raise rulesedit.EditError(f"{key} can't go below 0")
                if new == cur and isinstance(new, bool) == isinstance(cur, bool):
                    raise rulesedit.EditError(f"{key} is already {cur!r}")
                out.append({"kind": kind, "table": table, "key": key, "old": cur, "new": new})
            elif kind == "list_add":
                have = {str(x).casefold() for x in raw["lists"][it["list"]]}
                values = sorted({v for v in it["values"] if v.casefold() not in have})
                if not values:
                    raise rulesedit.EditError(f"every value is already in {it['list']}")
                out.append({"kind": kind, "list": it["list"], "values": values})
            elif kind == "rule_field":
                rule = next(r for r in raw["rules"] if str(r.get("id")) == it["rule"])
                out.append({"kind": kind, "rule": it["rule"], "field": it["field"], "old": rule.get(it["field"]),
                            "new": it["new"]})
            elif kind == "rule_remove":
                rule = next(r for r in raw["rules"] if str(r.get("id")) == it["rule"])
                # the state the removal was proposed in, so apply refuses it if the rule moved since
                out.append({"kind": kind, "rule": it["rule"],
                            "old": {f: rule.get(f) for f in ("severity", "status")}})
            elif kind == "rule_add":
                if any(str(r.get("id")) == it["rule"] for r in raw["rules"]):
                    raise rulesedit.EditError(f"rule {it['rule']} already exists")
                out.append({k: it[k] for k in ("kind", "rule", "block", "lists", "thresholds") if k in it})
            elif kind == "threshold_add":
                if it["key"] in raw["thresholds"]["default"]:
                    raise rulesedit.EditError(f"threshold {it['key']} already exists")
                out.append({k: it[k] for k in ("kind", "key", "value", "after") if k in it})
            else:
                raise rulesedit.EditError(f"unknown edit kind {kind!r}")
    except (KeyError, StopIteration, TypeError) as e:
        raise rulesedit.EditError(f"the ruleset has no {e}") from None
    return out


def _intent(k: Mapping, terms: Iterable[str]) -> dict:
    edit = k["edit"]
    if edit["kind"] == "list_add":
        return {"kind": "list_add", "list": edit["list"], "values": sorted(set(terms))}
    return {"kind": "set_threshold", "table": "default", "key": edit["key"],
            **({"step": edit["step"]} if "step" in edit else {"value": edit["value"]})}


def _changes(intent: dict, view: Mapping) -> bool:
    try:
        _concrete([intent], view)
    except rulesedit.EditError:
        return False
    return True


def _pick(rule: str, direction: str, n_spans: int, facets: Mapping, cal: dict, view: Mapping):
    """(knob, intent) for the first knob of `rule` + `direction` that fits the evidence and changes something:
    facet knobs (in file order), then the broad knob. A knob fits when at least half the evidence spans carry an
    allowed value of each of its conditions (its facet and `where`; a term knob: any term)."""
    knobs = [k for k in cal["knobs"] if k["rule"] == rule and k["direction"] == direction]
    for k in sorted(knobs, key=lambda k: k["facet"] is None):
        shares = ([sum(facets.get("term", {}).values())] if k["facet"] == "term" else
                  [sum(facets.get(f, {}).get(v, 0) for v in values) for f, values in _when(k).items()])
        if shares and not (n_spans and all(share and share * 2 >= n_spans for share in shares)):
            continue
        intent = _intent(k, facets.get("term", {}))
        if _changes(intent, view):
            return k, intent
    return None


def _fits(k: Mapping, span: Mapping[str, set]) -> bool:
    """Whether the knob's edit is one that clears this span: a term knob needs a term, a facet knob every one of its
    facets present with only allowed values. A broad knob fits any span. A span with no facet never fits a facet
    knob, so old evidence (a justification logged before #212) can't turn one."""
    if k["facet"] == "term":
        return bool(span.get("term"))
    return all(span.get(f) and set(span[f]) <= set(values) for f, values in _when(k).items())


def _pick_kept(rule: str, kept: Mapping[tuple, Mapping[str, set]], min_docs: int, cal: dict, view: Mapping):
    """(knob, intent, covered docs) for the `kept` trigger: the first loosen knob of `rule` (facet knobs in file
    order, then the broad one) that covers at least `min_docs` docs and changes something. A doc is covered when
    the knob fits every span kept in it (`_fits`), so a proposal turns only a setting that clears what it cites;
    None (a review) otherwise."""
    docs: dict = {}
    for (doc, _span), facets in kept.items():
        docs.setdefault(doc, []).append(facets)
    knobs = [k for k in cal["knobs"] if k["rule"] == rule and k["direction"] == "loosen"]
    for k in sorted(knobs, key=lambda k: k["facet"] is None):
        covered = {d for d, spans in docs.items() if all(_fits(k, s) for s in spans)}
        if len(covered) < max(1, min_docs):
            continue
        intent = _intent(k, (t for d in covered for s in docs[d] for t in s.get("term", ())))
        if _changes(intent, view):
            return k, intent, covered
    return None
