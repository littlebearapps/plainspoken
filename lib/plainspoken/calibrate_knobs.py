"""Kaizen calibrate's settings and knobs (Phase 5; split from `calibrate`).

- `load_settings`: `data/kaizen.toml`, validated against the ruleset: the `[triggers]` thresholds and the
  `[[knobs]]` (each a rule, an optional facet and value, a direction and one edit: `set_threshold` with a `step` or
  `value`, or `list_add` from the term facet).
- `_pick`: the first knob of a rule and direction that fits the evidence and changes something.
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
_KNOB_KEYS = {"rule", "facet", "value", "direction", "edit"}


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
    return {"rule": rule, "facet": facet, "value": None if "value" not in k else str(k["value"]),
            "direction": direction, "edit": dict(edit)}


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


def _pick(rule: str, direction: str, n_spans: int, facets: Mapping, cal: dict, view: Mapping):
    """(knob, intent) for the first knob of `rule` + `direction` that fits the evidence and changes something:
    facet knobs (in file order) when at least half the evidence spans carry the value, then the broad knob."""
    knobs = [k for k in cal["knobs"] if k["rule"] == rule and k["direction"] == direction]
    for k in sorted(knobs, key=lambda k: k["facet"] is None):
        edit = k["edit"]
        if k["facet"] is not None:
            seen = facets.get(k["facet"], {})
            share = sum(seen.values()) if k["facet"] == "term" else seen.get(k["value"], 0)
            if not n_spans or not share or share * 2 < n_spans:
                continue
        if edit["kind"] == "list_add":
            intent = {"kind": "list_add", "list": edit["list"], "values": sorted(facets.get("term", {}))}
        else:
            intent = {"kind": "set_threshold", "table": "default", "key": edit["key"],
                      **({"step": edit["step"]} if "step" in edit else {"value": edit["value"]})}
        try:
            _concrete([intent], view)
        except rulesedit.EditError:
            continue
        return k, intent
    return None
