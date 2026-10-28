"""Voice profiles: per-project settings that replace hostname branches in the checks.

A profile is TOML. Loading fails closed: a missing file, invalid TOML, an unknown section or key, an
unknown flag or locale, a wrong type or a bad regex raises ProfileError naming the file and the key.
Threshold names and disabled rule ids are checked against the ruleset by Config.check_profile.

The voice sections ([identity], [voice], [rhythm], [reader], [blends], [formatting], [avoid], the lexicon habits,
[[registers]] and [[anchors]]) are optional. The checker ignores them; the skills read them through the CLI
(`profile --voice`, `anchors`). Loading never opens an anchor file, so a missing one can't break a check.
"""
from __future__ import annotations

import hashlib
import math
import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from plainspoken._util import is_absolute

ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = ROOT / "data" / "profiles"
LOCALES_DIR = ROOT / "data" / "locales"
KNOWN_FLAGS = frozenset({"narrative"})
DEFAULT_LOCALE = "en-AU"  # when no project config, profile, user-wide file or plugin option sets one (config.py)
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]*")
CONTENT_KINDS = ("article", "page", "email", "social")
PRONOUNS = ("I", "we", "either")
BLENDS = ("answer-first", "narrative")
_VOICE_SECTIONS = ("identity", "voice", "rhythm", "reader", "blends", "formatting", "avoid")
_LEXICON_HABITS = ("starters", "fillers", "closers")

# section -> {key: expected type}; "str_list" and "regex_list" are lists of strings
_SCHEMA: dict[str, dict[str, str]] = {
    "profile": {"name": "str", "locale": "str", "flags": "str_list"},
    "thresholds": {},  # any key; values must be numbers or booleans (names checked against the ruleset)
    "lexicon": {"extra_bans": "str_list"},
    "document": {
        "visible_frontmatter_keys": "str_list",
        "faq_frontmatter_key": "str",
        "resource_list_headings": "regex_list",
        "long_sentence_headings": "regex_list",
    },
    "rules": {"disabled": "str_list"},
    "judges": {"calibration_notes": "str"},
    "identity": {"pronoun": "pronoun", "writer": "str"},
    "voice": {"principles": "str_list", "opinion_pattern": "str", "humour": "str", "emoji_max": "count",
              "exclamation_max": "count", "tone": "unit_table", "tone_notes": "str_table"},
    "rhythm": {"sentence_mean": "number", "sentence_sd": "number", "burstiness": "number",
               "long_share": "unit", "short_share": "unit", "notes": "str"},
    "reader": {"persona": "str", "comprehension_floor": "year", "glossary": "str", "knows": "str_list"},
    "blends": {k: "blend" for k in CONTENT_KINDS},
    "formatting": {k: "str" for k in CONTENT_KINDS},
    "avoid": {"topics": "str_list", "moves": "str_list"},
}
_SCHEMA["lexicon"].update({k: "str_list" for k in _LEXICON_HABITS})
# array-of-tables sections: [[registers]], [[anchors]]
_ARRAYS: dict[str, dict[str, str]] = {
    "registers": {"name": "name", "pronoun": "pronoun", "formality": "str", "notes": "str"},
    "anchors": {"id": "name", "tags": "name_list", "text": "str", "path": "str", "lines": "line_range",
                "source": "str"},
}
_REQUIRED = {"registers": ("name",), "anchors": ("id", "tags")}


class ProfileError(ValueError):
    """A profile that can't be used. The message names the file and the key."""


@dataclass(frozen=True)
class Anchor:
    """A passage in the writer's own voice. `path` is relative to `base`, the profile's folder."""
    id: str
    tags: tuple[str, ...]
    text: str = ""
    path: str = ""
    lines: tuple[int, int] | None = None
    source: str = ""
    base: str = ""


@dataclass(frozen=True)
class Register:
    name: str
    pronoun: str = ""
    formality: str = ""
    notes: str = ""


@dataclass(frozen=True, eq=False)
class Profile:
    name: str
    locale: str | None = None  # None: the profile doesn't set one, so config.resolve_locale looks further
    flags: frozenset[str] = frozenset()
    thresholds: dict = field(default_factory=dict)
    extra_bans: tuple[str, ...] = ()
    visible_frontmatter_keys: tuple[str, ...] = ("title", "description")
    faq_frontmatter_key: str = ""
    resource_list_headings: tuple[re.Pattern, ...] = ()
    long_sentence_headings: tuple[re.Pattern, ...] = ()
    rules_disabled: frozenset[str] = frozenset()
    calibration_notes: str = ""
    source: str = ""
    sha256: str = ""
    pronoun: str = "I"
    reader_persona: str = ""
    comprehension_floor: int = 7
    registers: tuple[Register, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    voice: dict = field(default_factory=dict)  # the validated voice tables, as loaded (skills read them via the CLI)


def locales() -> set[str]:
    """The English variants plainspoken knows: one data/locales/<variant>.toml each."""
    return {p.stem for p in LOCALES_DIR.glob("*.toml")}


def _resolve(ref: str | Path, search: tuple[Path, ...]) -> Path:
    if isinstance(ref, Path) or "/" in str(ref) or str(ref).endswith(".toml"):
        return Path(ref)
    dirs = (*search, PROFILES_DIR)
    for d in dirs:
        cand = d / f"{ref}.toml"
        if cand.is_file():
            return cand
    raise ProfileError(f"profile {ref!r} not found in {', '.join(str(d) for d in dirs)}")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_type(path: Path, section: str, key: str, value, kind: str, where: str | None = None) -> None:
    where = where or f"{path}: [{section}] {key}"
    if kind in ("str", "pronoun", "blend") and not isinstance(value, str):
        raise ProfileError(f"{where}: expected a string, got {type(value).__name__}")
    if kind in ("str_list", "regex_list"):
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ProfileError(f"{where}: expected a list of strings")
        if kind == "regex_list":
            for x in value:
                try:
                    re.compile(x)
                except re.error as e:
                    raise ProfileError(f"{where}: bad regex {x!r} ({e})") from None
    elif kind == "pronoun" and value not in PRONOUNS:
        raise ProfileError(f"{where}: {value!r} unknown (expected one of {', '.join(PRONOUNS)})")
    elif kind == "blend" and value not in BLENDS:
        raise ProfileError(f"{where}: {value!r} unknown (expected one of {', '.join(BLENDS)})")
    elif kind == "count" and not (isinstance(value, int) and not isinstance(value, bool) and value >= 0):
        raise ProfileError(f"{where}: expected a whole number 0 or more")
    elif kind == "number" and not _is_number(value):
        raise ProfileError(f"{where}: expected a finite number")
    elif kind == "unit" and not (_is_number(value) and 0 <= value <= 1):
        raise ProfileError(f"{where}: expected a number from 0 to 1")
    elif kind == "year" and not (isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 12):
        raise ProfileError(f"{where}: expected a school year, a whole number from 1 to 12")
    elif kind in ("unit_table", "str_table"):
        if not isinstance(value, dict):
            raise ProfileError(f"{where}: must be a table")
        for inner, v in value.items():
            _check_type(path, section, key, v, "unit" if kind == "unit_table" else "str",
                        f"{path}: [{section}] {key}.{inner}")
    elif kind == "name" and not (isinstance(value, str) and _NAME.fullmatch(value)):
        raise ProfileError(f"{where}: expected a name (lowercase letters, digits, - and _)")
    elif kind == "name_list":
        if not isinstance(value, list) or not value:
            raise ProfileError(f"{where}: expected a non-empty list of names")
        for x in value:
            _check_type(path, section, key, x, "name", where)
    elif kind == "line_range" and not (
            isinstance(value, list) and len(value) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in value) and 1 <= value[0] <= value[1]):
        raise ProfileError(f"{where}: expected [first, last] line numbers with 1 <= first <= last")


def _validate_array(path: Path, section: str, body) -> None:
    if not isinstance(body, list) or not all(isinstance(x, dict) for x in body):
        raise ProfileError(f"{path}: [[{section}]] must be an array of tables")
    id_key = _REQUIRED[section][0]
    seen: set[str] = set()
    for n, item in enumerate(body, 1):
        where = f"{path}: [[{section}]] #{n}"
        for key, value in item.items():
            if key not in _ARRAYS[section]:
                raise ProfileError(f"{where}: unknown key {key}")
            _check_type(path, section, key, value, _ARRAYS[section][key], f"{where} {key}")
        for key in _REQUIRED[section]:
            if key not in item:
                raise ProfileError(f"{where}: {key} is required")
        ident = item[id_key]
        if ident in seen:
            singular = section.removesuffix("s")
            raise ProfileError(f"{where}: duplicate {singular} {id_key} {ident!r}")
        seen.add(ident)
        if section == "anchors":
            if ("text" in item) == ("path" in item):
                raise ProfileError(f"{where}: give text or path, not both" if "text" in item
                                   else f"{where}: needs text or path")
            if not (item.get("text", "").strip() or item.get("path", "").strip()):
                raise ProfileError(f"{where}: text or path is empty")
            if item.get("path", "").startswith(("/", "~")):
                raise ProfileError(f"{where} path: must be relative to the profile")
            if "lines" in item and "path" not in item:
                raise ProfileError(f"{where} lines: only goes with path")


def _validate(path: Path, raw: dict) -> None:
    for section, body in raw.items():
        if section in _ARRAYS:
            _validate_array(path, section, body)
            continue
        if section not in _SCHEMA:
            known = sorted([*_SCHEMA, *(f"[{a}]" for a in _ARRAYS)])
            raise ProfileError(f"{path}: unknown section [{section}] (expected {', '.join(known)})")
        if not isinstance(body, dict):
            raise ProfileError(f"{path}: [{section}] must be a table")
        if section == "thresholds":
            for key, value in body.items():
                if not isinstance(value, (bool, int, float)):  # booleans allowed: mattr_blocking is one
                    raise ProfileError(f"{path}: [thresholds] {key}: expected a number or true/false")
                if isinstance(value, float) and not math.isfinite(value):  # nan/inf would switch a rule off
                    raise ProfileError(f"{path}: [thresholds] {key}: expected a finite number, got {value}")
            continue
        for key, value in body.items():
            if key not in _SCHEMA[section]:
                raise ProfileError(f"{path}: unknown key [{section}] {key}")
            _check_type(path, section, key, value, _SCHEMA[section][key])
    glossary = raw.get("reader", {}).get("glossary")
    if glossary is not None and (not glossary.strip() or glossary.startswith("~") or is_absolute(glossary)):
        raise ProfileError(f"{path}: [reader] glossary: must be a path relative to the profile")
    prof = raw.get("profile", {})
    name = prof.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ProfileError(f"{path}: [profile] name is required (lowercase letters, digits, - and _)")
    locale = prof.get("locale")
    if locale is not None and locale not in locales():
        raise ProfileError(f"{path}: [profile] locale {locale!r} unknown (expected one of {sorted(locales())})")
    unknown = sorted(set(prof.get("flags", [])) - KNOWN_FLAGS)
    if unknown:
        raise ProfileError(f"{path}: [profile] flags: unknown flag(s) {unknown} (expected some of {sorted(KNOWN_FLAGS)})")


def load(ref: str | Path, search: tuple[Path, ...] = ()) -> Profile:
    path = _resolve(ref, search)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ProfileError(f"{path}: can't read profile ({e.strerror or e})") from None
    try:
        raw = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ProfileError(f"{path}: not valid TOML ({e})") from None
    _validate(path, raw)
    notes = raw.get("judges", {}).get("calibration_notes", "")
    digest = hashlib.sha256(data)
    if notes:
        notes_path = (path.parent / notes).resolve()
        if not notes_path.is_file():
            raise ProfileError(f"{path}: [judges] calibration_notes: {notes_path} not found")
        try:
            notes_bytes = notes_path.read_bytes()
        except OSError as e:
            raise ProfileError(f"{path}: [judges] calibration_notes: can't read {notes_path} ({e.strerror or e})") from None
        # The notes steer the judges, so editing them invalidates the lint and every judge file (report contract).
        digest = hashlib.sha256(data + b"\0" + notes_bytes)
        notes = str(notes_path)
    prof, doc, lex = raw.get("profile", {}), raw.get("document", {}), raw.get("lexicon", {})
    reader = raw.get("reader", {})
    voice = {k: raw[k] for k in _VOICE_SECTIONS if k in raw}
    voice["lexicon"] = {k: lex[k] for k in _LEXICON_HABITS if k in lex}
    return Profile(
        name=prof["name"],
        locale=prof.get("locale"),
        flags=frozenset(prof.get("flags", [])),
        thresholds=dict(raw.get("thresholds", {})),
        extra_bans=tuple(lex.get("extra_bans", [])),
        visible_frontmatter_keys=tuple(doc.get("visible_frontmatter_keys", ["title", "description"])),
        faq_frontmatter_key=doc.get("faq_frontmatter_key", ""),
        resource_list_headings=tuple(re.compile(x, re.I) for x in doc.get("resource_list_headings", [])),
        long_sentence_headings=tuple(re.compile(x, re.I) for x in doc.get("long_sentence_headings", [])),
        rules_disabled=frozenset(raw.get("rules", {}).get("disabled", [])),
        calibration_notes=notes,
        source=str(path),
        sha256=digest.hexdigest(),
        pronoun=raw.get("identity", {}).get("pronoun", "I"),
        reader_persona=reader.get("persona", ""),
        comprehension_floor=reader.get("comprehension_floor", 7),
        registers=tuple(Register(**r) for r in raw.get("registers", [])),
        anchors=tuple(Anchor(id=a["id"], tags=tuple(a["tags"]), text=a.get("text", ""), path=a.get("path", ""),
                             lines=tuple(a["lines"]) if "lines" in a else None, source=a.get("source", ""),
                             base=str(path.parent)) for a in raw.get("anchors", [])),
        voice=voice,
    )


@lru_cache(maxsize=1)
def default() -> Profile:
    return load(PROFILES_DIR / "default.toml")
