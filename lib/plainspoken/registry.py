"""Load and validate data/rules.toml: the single source for rule ids, lists and thresholds.

`PLAINSPOKEN_RULES=<path>` points every load at another copy (the kaizen calibrate loop measures a
proposal's effect on a temp copy; it never edits the real file)."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

from plainspoken.profile import KNOWN_FLAGS, Profile, ProfileError

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "rules.toml"
_METHODS = {"lint", "lint+judge", "judge", "n/a"}
# A rule's severity is BLOCK or WARN (CANDIDATE and INFO are finding-level only). Anything else would drop a
# fail out of both the BLOCK and WARN lists at merge, a silent false PASS, so the loader refuses it.
_SEVERITIES = {"BLOCK", "WARN"}
# `deprecated` is the first retirement step (kaizen dormant trigger): it behaves exactly as `active` everywhere
# (lint, judges, merge coverage); only the profile summary lists it. `shadow` rules report INFO and never block.
_STATUSES = {"active", "deprecated", "shadow"}
_GROUPS = {"J1", "J2", "J3", "J4"}
_CONTENT_TYPES = ("article", "social")
_ISE = re.compile(r"(?<=[a-z])is(e|ed|es|ing|ation|ations|er|ers)\b")
_IZE = re.compile(r"(?<=[a-z])iz(e|ed|es|ing|ation|ations|er|ers)\b")
_YSE = re.compile(r"(?<=[a-z])ys(e|ed|es|ing)\b")
_YZE = re.compile(r"(?<=[a-z])yz(e|ed|es|ing)\b")
_REQUIRES = {f"flag:{f}" for f in KNOWN_FLAGS} | {"lexicon:extra_bans"}


def spelling_variants(term: str) -> set[str]:
    """Both spelling families of a word: utilise/utilize, catalyse/catalyze. Unchanged words map to themselves."""
    out = {term}
    out.add(_ISE.sub(lambda m: "iz" + m.group(1), term))
    out.add(_IZE.sub(lambda m: "is" + m.group(1), term))
    out.add(_YSE.sub(lambda m: "yz" + m.group(1), term))
    out.add(_YZE.sub(lambda m: "ys" + m.group(1), term))
    return out


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    method: str
    severity: str
    group: str | None = None
    requires: str | None = None
    judge_may_block: bool = False
    content_types: tuple[str, ...] = _CONTENT_TYPES
    status: str = "active"
    era: str = ""
    models: tuple[str, ...] = ()
    source: str = ""

    def applies_to(self, profile: Profile) -> bool:
        if self.id in profile.rules_disabled:
            return False
        if self.requires is None:
            return True
        kind, _, value = self.requires.partition(":")
        return value in profile.flags if kind == "flag" else bool(profile.extra_bans)


@dataclass(frozen=True)
class Config:
    version: str
    rules: dict[str, Rule]
    lists: dict[str, list[str]]
    aliases: tuple[tuple[str, str], ...]
    _thresholds: dict[str, dict] = field(repr=False)

    def thresholds(self, profile: Profile | None = None, content_type: str = "article") -> dict:
        """default → profile → content-type layer: a profile that loosens an article cap (em_dash_max = 5, say)
        never lifts a social cap, so social caps always apply to social posts. With no profile, the ruleset's own
        values (`thresholds()` is a copy of `[thresholds."default"]`): the public way to read them."""
        merged = dict(self._thresholds["default"])
        if profile is not None:
            merged.update(profile.thresholds)
        if content_type != "article":
            merged.update(self._thresholds.get(content_type, {}))
        return merged

    def thresholds_for(self, doc) -> dict:
        return self.thresholds(doc.profile, doc.content_type)

    def rules_for_profile(self, profile: Profile, content_type: str = "article") -> list[Rule]:
        return [r for r in self.rules.values() if r.applies_to(profile) and content_type in r.content_types]

    def check_profile(self, profile: Profile) -> None:
        """Profile keys the ruleset doesn't know fail closed, naming the profile file and the key."""
        known = self._thresholds["default"]
        for key, value in profile.thresholds.items():
            if key not in known:
                raise ProfileError(f"{profile.source}: [thresholds] {key}: unknown threshold")
            int_wanted = isinstance(known[key], int) and not isinstance(known[key], bool)
            if (isinstance(known[key], bool) != isinstance(value, bool)
                    or (int_wanted and isinstance(value, float))):  # an int may stand in for a float, not vice versa
                raise ProfileError(f"{profile.source}: [thresholds] {key}: expected {type(known[key]).__name__}")
        unknown = sorted(profile.rules_disabled - set(self.rules))
        if unknown:
            raise ProfileError(f"{profile.source}: [rules] disabled: unknown rule id(s) {unknown}")


def _need(table: dict, key: str, src: Path, where: str = ""):
    """A required key, or a ValueError naming the file and the key (the CLI exits 2; a KeyError would traceback)."""
    if key not in table:
        raise ValueError(f"{src}: {where}missing key {key!r}")
    return table[key]


def load_config(path: Path | None = None) -> Config:
    src = path or Path(os.environ.get("PLAINSPOKEN_RULES") or DEFAULT_PATH)
    raw = tomllib.loads(src.read_text(encoding="utf-8"))
    for key, kind, typ in (("version", "string", str), ("rules", "list", list), ("lists", "table", dict),
                           ("thresholds", "table", dict)):
        if key in raw and not isinstance(raw[key], typ):
            raise ValueError(f"{src}: '{key}' must be a {kind}")
    rules: dict[str, Rule] = {}
    for n, item in enumerate(_need(raw, "rules", src), 1):
        rid = str(_need(item, "id", src, f"[[rules]] #{n}: "))
        for key in ("name", "method", "severity"):
            _need(item, key, src, f"rule {rid}: ")
        if rid in rules:
            raise ValueError(f"duplicate rule id {rid}")
        method = item["method"]
        if method not in _METHODS:
            raise ValueError(f"rule {rid}: bad method {method!r}")
        severity = item["severity"]
        if severity not in _SEVERITIES:
            raise ValueError(f"rule {rid}: bad severity {severity!r} (expected one of {sorted(_SEVERITIES)})")
        group = item.get("group")
        if "judge" in method and group not in _GROUPS:
            raise ValueError(f"rule {rid}: method {method} needs a group in {sorted(_GROUPS)}, got {group!r}")
        if "judge" not in method and group is not None:
            raise ValueError(f"rule {rid}: group {group!r} on a rule with no judge (method {method})")
        requires = item.get("requires")
        if requires is not None and requires not in _REQUIRES:
            raise ValueError(f"rule {rid}: unknown requires {requires!r} (expected one of {sorted(_REQUIRES)})")
        judge_may_block = bool(item.get("judge_may_block", False))
        content_types = tuple(item.get("content_types", _CONTENT_TYPES))
        bad_ct = [c for c in content_types if c not in _CONTENT_TYPES]
        if bad_ct:
            raise ValueError(f"rule {rid}: unknown content_types {bad_ct!r} (expected {list(_CONTENT_TYPES)})")
        status = item.get("status", "active")
        if status not in _STATUSES:
            raise ValueError(f"rule {rid}: bad status {status!r} (expected one of {sorted(_STATUSES)})")
        if status == "shadow" and method != "lint":
            raise ValueError(f"rule {rid}: shadow rules are lint-only")
        rules[rid] = Rule(
            id=rid,
            name=item["name"],
            method=method,
            severity=severity,
            group=group,
            requires=requires,
            judge_may_block=judge_may_block,
            content_types=content_types,
            status=status,
            era=str(item.get("era", "")),
            models=tuple(item.get("models", ())),
            source=str(item.get("source", "")),
        )
    lists: dict[str, list[str]] = {}
    for name, items in _need(raw, "lists", src).items():
        bad = [x for x in items if not isinstance(x, str)]
        if bad:
            raise ValueError(f"list {name}: non-string item(s) {bad!r}")
        lists[name] = list(items)
    for name in raw.get("spelling", {}).get("expand", []):
        if name not in lists:
            raise ValueError(f"[spelling] expand: unknown list {name!r}")
        seen: list[str] = []
        for word in lists[name]:
            for v in sorted(spelling_variants(word), key=lambda w: (w != word, w)):
                if v not in seen:
                    seen.append(v)
        lists[name] = seen
    aliases = tuple((str(a), str(b)) for a, b in raw.get("aliases", {}).items())
    thresholds = _need(raw, "thresholds", src)
    _need(thresholds, "default", src, "[thresholds] ")
    return Config(version=str(_need(raw, "version", src)), rules=rules, lists=lists, aliases=aliases,
                  _thresholds=thresholds)
