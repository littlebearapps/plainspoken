"""register-check items as data (data/register-checklist.toml), filtered by message kind and filled from the profile."""
from __future__ import annotations

import string
import tomllib
from pathlib import Path

from plainspoken.profile import PRONOUNS, Profile

DATA = Path(__file__).resolve().parents[2] / "data" / "register-checklist.toml"
KINDS = ("email", "message", "post", "page", "outreach", "follow-up")
_KEYS = {"id", "title", "ask", "flag_when", "applies_to", "by_pronoun"}
_FILLS = ("formality", "reader", "locale", "pronoun_rule")  # the placeholders checklist() fills


def _placeholders(where: str, key: str, text: str) -> set[str]:
    """The `{name}` fields in `text`; a ValueError naming the item for a malformed or unknown one."""
    try:
        fields = {f for _, f, _, _ in string.Formatter().parse(text) if f is not None}
    except ValueError as e:
        raise ValueError(f"{where}: {key}: {e}") from None
    unknown = sorted(f for f in fields if f not in _FILLS)
    if unknown:
        raise ValueError(f"{where}: {key}: unknown placeholder {', '.join('{' + f + '}' for f in unknown)} "
                         f"(expected some of {', '.join('{' + f + '}' for f in _FILLS)})")
    return fields


def load_items(path: Path = DATA) -> list[dict]:
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"{path}: can't read the register checklist ({type(e).__name__})") from None
    items, seen = raw.get("items"), set()
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path}: no [[items]]")
    for item in items:
        iid = item.get("id") if isinstance(item, dict) else None
        where = f"{path}: item {iid!r}"
        if not isinstance(iid, str) or iid in seen:
            raise ValueError(f"{where}: missing or duplicate id")
        seen.add(iid)
        if set(item) - _KEYS:
            raise ValueError(f"{where}: unknown key(s) {sorted(set(item) - _KEYS)}")
        for key in ("title", "ask", "flag_when"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"{where}: {key} must be a non-empty string")
        kinds = item.get("applies_to")
        if not isinstance(kinds, list) or not kinds or set(kinds) - set(KINDS):
            raise ValueError(f"{where}: applies_to must be a non-empty list from {', '.join(KINDS)}")
        fields = _placeholders(where, "ask", item["ask"]) | _placeholders(where, "flag_when", item["flag_when"])
        by = item.get("by_pronoun", {})
        if not isinstance(by, dict) or not all(isinstance(v, str) and v.strip() for v in by.values()):
            raise ValueError(f"{where}: by_pronoun must be a table of non-empty strings, one per pronoun")
        if "pronoun_rule" in fields and set(by) != set(PRONOUNS):
            raise ValueError(f"{where}: by_pronoun must cover {', '.join(PRONOUNS)}")
    return items


def checklist(kind: str, prof: Profile, register_name: str | None = None) -> list[dict]:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r} (expected one of {', '.join(KINDS)})")
    reg = None
    if register_name is not None:
        reg = next((r for r in prof.registers if r.name == register_name), None)
        if reg is None:
            have = ", ".join(r.name for r in prof.registers) or "none"
            raise ValueError(f"no register {register_name!r} in profile {prof.name} (has: {have})")
    pronoun = (reg.pronoun if reg and reg.pronoun else prof.pronoun) or "I"
    fill = {
        "formality": (reg.formality if reg and reg.formality else "the profile's usual register"),
        "reader": prof.reader_persona or "the reader",
        "locale": prof.locale,
    }
    out = []
    for item in load_items():
        if kind not in item["applies_to"]:
            continue
        values = {**fill, "pronoun_rule": item.get("by_pronoun", {}).get(pronoun, "")}
        out.append({"id": item["id"], "title": item["title"],
                    "ask": item["ask"].format(**values), "flag_when": item["flag_when"].format(**values)})
    return out
