"""One resolver for the engine's settings, so any tool can drive it.

Order: the --profile flag → PLAINSPOKEN_PROFILE → .plainspoken/config.toml (the first `[engine] profiles` entry
whose glob matches the file, when there is a file, then `[engine] profile`) → CLAUDE_PLUGIN_OPTION_PROFILE (Claude
Code userConfig). A project's own config beats the user-wide plugin option. No source → ProfileError: never a silent
default.

`--plugin-profile` carries the Claude Code userConfig value when the environment doesn't (skills pass
`${user_config.profile}`). An installed-from-directory plugin can leave that string unsubstituted, or substitute it
empty; either way it means the manifest's default profile, `default`. Only `--plugin-profile` gets that treatment.

The spelling locale (resolve_locale) has its own order: project `[locale] variant` → the voice profile's own
`[profile] locale` → user-wide `[locale] variant` → the plugin option (CLAUDE_PLUGIN_OPTION_LOCALE, else
`--plugin-locale`) → en-AU. No check reads it, so it never joins a report's stamps.
"""
from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

from plainspoken import _util, toolcall
from plainspoken.profile import DEFAULT_LOCALE, Profile, ProfileError, load, locales

_ENGINE_KEYS = {"profile", "profiles"}
_PROFILES_ENTRY_KEYS = {"glob", "profile"}
_GATE_KEYS = {"paths", "strictness"}
_BRIEF_KEYS = {"enabled"}
_CLAIMS_KEYS = {"ledger_dir", "sources_dir", "regulated_matrix", "platforms_extra"}
_READER_VALUE_KEYS = {"cta_phrases"}
_INTEGRITY_KEYS = {"mode", "paths"}
_LINT_WATCH_KEYS = {"mode", "paths"}
_NUDGE_KEYS = {"mode"}
_CHAT_REPLY_KEYS = {"mode", "min_words"}
_RULE_KEYS = {"enabled"}
_LOCALE_KEYS = {"variant"}
_TOOL_CALL_KEYS = set(toolcall.KEYS)
_KAIZEN_KEYS = {"capture", "capture_sources", "excerpts", "adapter", "ledger_dir", "proposals_dir", "corpus",
                "human_corpus", "approvers", "monthly_cap", "github", "trello"}
_KAIZEN_GITHUB_KEYS = {"repo", "labels"}
_KAIZEN_TRELLO_KEYS = {"list_id", "label_ids", "key_env", "token_env"}
_SECTIONS = {"engine": _ENGINE_KEYS, "gate": _GATE_KEYS, "brief": _BRIEF_KEYS, "claims": _CLAIMS_KEYS,
             "reader_value": _READER_VALUE_KEYS, "integrity": _INTEGRITY_KEYS, "lint_watch": _LINT_WATCH_KEYS,
             "kaizen": _KAIZEN_KEYS, "nudge": _NUDGE_KEYS, "rule": _RULE_KEYS, "locale": _LOCALE_KEYS,
             "tool_call": _TOOL_CALL_KEYS, "chat_reply": _CHAT_REPLY_KEYS}
# The user-wide file (~/.config/plainspoken/config.toml) holds only the settings that make sense outside a project:
# the nudge, the drafting rule, lint-watch, the spelling locale, the tool-call check and the chat-reply check (hosts
# without install options, Codex and Hermes, set them there). A project's own config wins over it.
_USER_SECTIONS = ("nudge", "rule", "lint_watch", "locale", "tool_call", "chat_reply")
STRICTNESS = ("watch", "warn", "block")
INTEGRITY_MODES = ("off", "warn", "block")
LINT_WATCH_MODES = ("on", "off")
NUDGE_MODES = ("on", "off")
CHAT_REPLY_MODES = ("off", "warn")  # warn is the only on-mode: the chat-reply check only ever tells the person
CHAT_REPLY_MIN_WORDS = 25
# Where kaizen events and friction come from: `check`, `merge`, `judge` (judge-record's rejected replies and the
# agent-run backstop), the `lint-watch` hook, the `tool-call` check and the `chat-reply` check. `[kaizen]
# capture_sources` keeps a subset; `capture = false` still turns all of them off.
CAPTURE_SOURCES = ("check", "merge", "judge", "lint-watch", "tool-call", "chat-reply")
CLAIMS_DEFAULTS = {"ledger_dir": ".plainspoken/claims", "sources_dir": ".plainspoken/sources",
                   "regulated_matrix": None, "platforms_extra": []}
ADAPTERS = ("file", "github", "trello")
KAIZEN_DEFAULTS = {"capture": True, "ledger_dir": ".plainspoken/ledger", "proposals_dir": ".plainspoken/kaizen",
                   "corpus": [], "human_corpus": [], "approvers": [], "monthly_cap": None}
KAIZEN_GITHUB_DEFAULTS = {"repo": None, "labels": ["kaizen"]}
KAIZEN_TRELLO_DEFAULTS = {"list_id": None, "label_ids": [], "key_env": "TRELLO_API_KEY", "token_env": "TRELLO_TOKEN"}
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PLACEHOLDER = re.compile(r"\$\{.*\}")
PLUGIN_DEFAULT = "default"


def is_placeholder(value: str | None) -> bool:
    """True for an unsubstituted `${...}` template string."""
    return bool(value) and _PLACEHOLDER.fullmatch(value) is not None


class ConfigError(ValueError):
    """A project config that can't be used. The message names the file and the key."""


def user_config_path(env: Mapping[str, str]) -> Path:
    """The user-wide config file: `$XDG_CONFIG_HOME/plainspoken/config.toml`, else `~/.config/plainspoken/config.toml`."""
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(base) / "plainspoken" / "config.toml"


def _user_config(env: Mapping[str, str]) -> tuple[Path, dict] | None:
    return _read_config(user_config_path(env), _USER_SECTIONS)


def _project_config(cwd: Path) -> tuple[Path, dict] | None:
    return _read_config(cwd / ".plainspoken" / "config.toml", tuple(_SECTIONS))


def _read_config(path: Path, sections: tuple[str, ...]) -> tuple[Path, dict] | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise ConfigError(f"{path}: not a file")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"{path}: not valid TOML ({e})") from None
    for section, body in raw.items():
        if section not in sections:
            known = [f"[{name}]" for name in sections]
            raise ConfigError(f"{path}: unknown section [{section}] (expected {', '.join(known[:-1])} or "
                              f"{known[-1]})")
        if not isinstance(body, dict):
            raise ConfigError(f"{path}: [{section}] must be a table")
        allowed = _SECTIONS[section]
        for key in body:
            if key not in allowed:
                raise ConfigError(f"{path}: unknown key [{section}] {key}")
        if section == "engine":
            value = body.get("profile")
            if "profile" in body and (not isinstance(value, str) or not value.strip()):
                raise ConfigError(f"{path}: [engine] profile must be a non-empty string")
            if "profile" in body:
                _check_profile_base(path, "[engine] profile", value)
            if "profiles" in body:
                _check_profiles(path, body["profiles"])
        elif section in ("brief", "rule"):
            if "enabled" in body and not isinstance(body["enabled"], bool):
                raise ConfigError(f"{path}: [{section}] enabled must be true or false")
        elif section in ("claims", "reader_value", "integrity"):
            _check_phase4_section(path, section, body)
        elif section == "lint_watch":
            if "mode" in body and body["mode"] not in LINT_WATCH_MODES:
                raise ConfigError(f"{path}: [lint_watch] mode must be one of {', '.join(LINT_WATCH_MODES)}, "
                                  f"got {body['mode']!r}")
            if "paths" in body and not _string_list(body["paths"]):
                raise ConfigError(f"{path}: [lint_watch] paths must be a list of non-empty strings")
        elif section == "kaizen":
            _check_kaizen_section(path, body)
        elif section == "nudge":
            if "mode" in body and body["mode"] not in NUDGE_MODES:
                raise ConfigError(f"{path}: [nudge] mode must be one of {', '.join(NUDGE_MODES)}, got {body['mode']!r}")
        elif section == "locale":
            known = sorted(locales())
            if "variant" in body and body["variant"] not in known:
                raise ConfigError(f"{path}: [locale] variant must be one of {', '.join(known)}, got "
                                  f"{body['variant']!r}")
        elif section == "chat_reply":
            if "mode" in body and body["mode"] not in CHAT_REPLY_MODES:
                raise ConfigError(f"{path}: [chat_reply] mode must be one of {', '.join(CHAT_REPLY_MODES)}, "
                                  f"got {body['mode']!r}")
            n = body.get("min_words", CHAT_REPLY_MIN_WORDS)
            if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= toolcall.MAX_WORDS:
                raise ConfigError(f"{path}: [chat_reply] min_words must be a whole number from 1 to "
                                  f"{toolcall.MAX_WORDS}, got {n!r}")
        elif section == "tool_call":
            errors = toolcall.section_errors(body)
            if errors:
                raise ConfigError(f"{path}: {errors[0]}")
            if "profile" in body:
                _check_profile_base(path, "[tool_call] profile", body["profile"])
        else:
            paths = body.get("paths", [])
            if not isinstance(paths, list) or not all(isinstance(g, str) and g.strip() for g in paths):
                raise ConfigError(f"{path}: [gate] paths must be a list of non-empty strings")
            if "strictness" in body and body["strictness"] not in STRICTNESS:
                raise ConfigError(f"{path}: [gate] strictness must be one of {', '.join(STRICTNESS)}, "
                                  f"got {body['strictness']!r}")
    return path, raw


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def _absolute(value: str) -> bool:
    """A POSIX or Windows absolute path (or a drive-relative one, `C:x`)."""
    return _util.is_absolute(value)


def _check_profiles(path: Path, value: object) -> None:
    """`[engine] profiles`: an array of `{ glob, profile }` tables. `glob` is matched against the file's path from the
    project root, so it can't be absolute; `profile` is what `[engine] profile` takes (a name, or a path relative to
    .plainspoken/), but not an absolute path, so a shared config never points outside the checkout."""
    shape = '[engine] profiles must be an array of tables, each { glob = "…", profile = "…" }'
    if not isinstance(value, list):
        raise ConfigError(f"{path}: {shape}")
    for n, entry in enumerate(value, 1):
        if not isinstance(entry, dict) or set(entry) != _PROFILES_ENTRY_KEYS:
            raise ConfigError(f"{path}: {shape} (entry {n} isn't)")
        for key in ("glob", "profile"):
            item = entry[key]
            if not isinstance(item, str) or not item.strip():
                raise ConfigError(f"{path}: [engine] profiles entry {n}: {key} must be a non-empty string")
            if _absolute(item):
                raise ConfigError(f"{path}: [engine] profiles entry {n}: {key} must be relative "
                                  f"({'to the project root' if key == 'glob' else 'to .plainspoken/, or a name'}), "
                                  f"got {item!r}")
        _check_profile_base(path, f"[engine] profiles entry {n}: profile", entry["profile"])


_PLAINSPOKEN_PREFIX = re.compile(r"(?:\.[\\/]+)*\.plainspoken[\\/]")


def _check_profile_base(path: Path, where: str, value: str) -> None:
    """A profile path is relative to .plainspoken/ already, so `.plainspoken/profiles/a.toml` would resolve to
    .plainspoken/.plainspoken/profiles/a.toml and fail at every check: refuse it here, with the fix."""
    if _PLAINSPOKEN_PREFIX.match(value):
        raise ConfigError(f"{path}: {where} is relative to .plainspoken/ (drop the leading .plainspoken/), "
                          f"got {value!r}")


def _relative_dir(value: object) -> bool:
    """A non-empty project-relative path: `_util.safe_relative`, the one rule for the paths a config names."""
    return _util.safe_relative(value)


def resolve_path(path: Path) -> Path:
    """`path` with every symlink followed, the same on every Python: a symlink loop raises (OSError or RuntimeError)
    even where a non-strict `resolve()` returns the looping path unchanged (3.13). A path that doesn't exist yet
    resolves as far as it can, as `resolve()` does."""
    try:
        return Path(path).resolve(strict=True)
    except FileNotFoundError:
        return Path(path).resolve()


def _is_project_root(root: Path, value: str) -> bool:
    """`value` (already a valid relative dir) names the project root: `.`, `./` and the like, or a link to it."""
    if all(part in ("", ".") for part in re.split(r"[\\/]", value)):
        return True
    try:
        return resolve_path(root / value) == resolve_path(root)
    except (OSError, ValueError, RuntimeError):
        return False  # unresolvable: recheck reports the snapshot instead


def _check_phase4_section(path: Path, section: str, body: dict) -> None:
    if section == "claims":
        for key in ("ledger_dir", "sources_dir"):
            if key in body and not _relative_dir(body[key]):
                raise ConfigError(f"{path}: [claims] {key} must be relative to the project root, with no '..', "
                                  f"got {body[key]!r}")
        if "sources_dir" in body and _is_project_root(path.parent.parent, body["sources_dir"]):
            raise ConfigError(f"{path}: [claims] sources_dir can't be the project root (every project file would "
                              f"count as a source); use a folder such as .plainspoken/sources, got "
                              f"{body['sources_dir']!r}")
        if "regulated_matrix" in body and not (isinstance(body["regulated_matrix"], str)
                                               and body["regulated_matrix"].strip()):
            raise ConfigError(f"{path}: [claims] regulated_matrix must be a non-empty string")
        if "platforms_extra" in body and not _string_list(body["platforms_extra"]):
            raise ConfigError(f"{path}: [claims] platforms_extra must be a list of non-empty strings")
    elif section == "reader_value":
        if "cta_phrases" in body and not _string_list(body["cta_phrases"]):
            raise ConfigError(f"{path}: [reader_value] cta_phrases must be a list of non-empty strings")
    else:
        if "mode" in body and body["mode"] not in INTEGRITY_MODES:
            raise ConfigError(f"{path}: [integrity] mode must be one of {', '.join(INTEGRITY_MODES)}, "
                              f"got {body['mode']!r}")
        if "paths" in body and not _string_list(body["paths"]):
            raise ConfigError(f"{path}: [integrity] paths must be a list of non-empty strings")


def _check_kaizen_section(path: Path, body: dict) -> None:
    for key in ("capture", "excerpts"):
        if key in body and not isinstance(body[key], bool):
            raise ConfigError(f"{path}: [kaizen] {key} must be true or false")
    if "capture_sources" in body:
        sources = body["capture_sources"]
        if not isinstance(sources, list) or not all(isinstance(v, str) for v in sources):
            raise ConfigError(f"{path}: [kaizen] capture_sources must be a list of source names")
        for v in sources:
            if v not in CAPTURE_SOURCES:
                raise ConfigError(f"{path}: [kaizen] capture_sources: unknown source {v!r} (expected "
                                  f"{', '.join(CAPTURE_SOURCES[:-1])} or {CAPTURE_SOURCES[-1]})")
    if "adapter" in body and body["adapter"] not in ADAPTERS:
        raise ConfigError(f"{path}: [kaizen] adapter must be one of {', '.join(ADAPTERS)}, got {body['adapter']!r}")
    for key in ("ledger_dir", "proposals_dir"):
        if key in body and not _relative_dir(body[key]):
            raise ConfigError(f"{path}: [kaizen] {key} must be relative to the project root, with no '..', "
                              f"got {body[key]!r}")
        if key in body and _is_project_root(path.parent.parent, body[key]):
            raise ConfigError(f"{path}: [kaizen] {key} can't be the project root (its files would mix with the "
                              f"project's); use a folder such as {KAIZEN_DEFAULTS[key]}, got {body[key]!r}")
    for key in ("corpus", "human_corpus", "approvers"):
        if key in body and not _string_list(body[key]):
            raise ConfigError(f"{path}: [kaizen] {key} must be a list of non-empty strings")
    if "monthly_cap" in body:
        cap = body["monthly_cap"]
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
            raise ConfigError(f"{path}: [kaizen] monthly_cap must be a whole number, 0 or more, got {cap!r}")
    for name, allowed in (("github", _KAIZEN_GITHUB_KEYS), ("trello", _KAIZEN_TRELLO_KEYS)):
        if name not in body:
            continue
        sub = body[name]
        if not isinstance(sub, dict):
            raise ConfigError(f"{path}: [kaizen.{name}] must be a table")
        for key in sub:
            if key not in allowed:
                raise ConfigError(f"{path}: unknown key [kaizen.{name}] {key}")
        if name == "github":
            if "repo" in sub and not (isinstance(sub["repo"], str) and _REPO.fullmatch(sub["repo"])):
                raise ConfigError(f"{path}: [kaizen.github] repo must be owner/name, got {sub['repo']!r}")
            if "labels" in sub and not _string_list(sub["labels"]):
                raise ConfigError(f"{path}: [kaizen.github] labels must be a list of non-empty strings")
        else:
            if "list_id" in sub and not (isinstance(sub["list_id"], str) and sub["list_id"].strip()):
                raise ConfigError(f"{path}: [kaizen.trello] list_id must be a non-empty string")
            if "label_ids" in sub and not _string_list(sub["label_ids"]):
                raise ConfigError(f"{path}: [kaizen.trello] label_ids must be a list of non-empty strings")
            for key in ("key_env", "token_env"):
                if key in sub and not (isinstance(sub[key], str) and _ENV_NAME.fullmatch(sub[key])):
                    raise ConfigError(f"{path}: [kaizen.trello] {key} must be an environment variable name, "
                                      f"got {sub[key]!r}")


def _section(cwd: Path, name: str) -> dict:
    found = _project_config(cwd)
    return dict(found[1].get(name, {})) if found else {}


def claims_settings(cwd: Path) -> dict:
    """`[claims]` with defaults filled in. `ledger_dir` and `sources_dir` are relative to the project root (`cwd`);
    `regulated_matrix` is None when unset (the plugin ships no matrix); `platforms_extra` adds to the shipped list."""
    body = _section(cwd, "claims")
    out = {**CLAIMS_DEFAULTS, **body}
    out["platforms_extra"] = list(out["platforms_extra"])
    return out


def reader_value_settings(cwd: Path) -> dict:
    """`[reader_value]` with defaults filled in. `cta_phrases` are the project's own, added by the caller to the
    shipped defaults; [] when unset."""
    return {"cta_phrases": list(_section(cwd, "reader_value").get("cta_phrases", []))}


def integrity_settings(cwd: Path) -> dict:
    """`[integrity]` with defaults filled in: mode `warn`; `paths` None when unset, so the caller falls back to the
    plugin `targets` option and then `["**/*.md"]` (config reads no environment, as with gate_paths)."""
    body = _section(cwd, "integrity")
    paths = body.get("paths")
    return {"mode": body.get("mode", "warn"), "paths": None if paths is None else list(paths)}


def _project_or_user(root: Path, name: str, env: Mapping[str, str] | None) -> dict:
    """A section from the project's config when it has one, else from the user-wide file, else {}."""
    found = _project_config(root)
    if found and name in found[1]:
        return dict(found[1][name])
    user = _user_config(os.environ if env is None else env)
    return dict(user[1].get(name, {})) if user else {}


def nudge_mode(root: Path, env: Mapping[str, str] | None = None) -> str:
    """Whether the prompt nudge is on: project `[nudge] mode` → user-wide `[nudge] mode` → the Claude Code option
    `nudge` (CLAUDE_PLUGIN_OPTION_NUDGE, "true") → off. Only an explicit true turns the option on."""
    env = os.environ if env is None else env
    body = _project_or_user(root, "nudge", env)
    if "mode" in body:
        return body["mode"]
    return "on" if str(env.get("CLAUDE_PLUGIN_OPTION_NUDGE", "")).strip().lower() == "true" else "off"


def rule_enabled(root: Path, env: Mapping[str, str] | None = None) -> bool:
    """Whether the drafting rule is added at session start: project `[rule] enabled` → user-wide `[rule] enabled` →
    the Claude Code option `rule` (CLAUDE_PLUGIN_OPTION_RULE, "true") → off."""
    env = os.environ if env is None else env
    body = _project_or_user(root, "rule", env)
    if "enabled" in body:
        return bool(body["enabled"])
    return str(env.get("CLAUDE_PLUGIN_OPTION_RULE", "")).strip().lower() == "true"


def lint_watch(root: Path, env: Mapping[str, str] | None = None) -> dict:
    """`[lint_watch]` with defaults filled in: mode `on`; `paths` None when unset, so the hook falls back to the plugin
    `targets` option and then `["**/*.md"]` (as with `[integrity] paths`). An empty list lints nothing. The project's
    section wins; without one, the user-wide file's applies."""
    body = _project_or_user(root, "lint_watch", env)
    paths = body.get("paths")
    return {"mode": body.get("mode", "on"), "paths": None if paths is None else list(paths)}


class Locale(NamedTuple):
    """The spelling locale and where it came from. `source` is one of `project config`, `profile`, `user-wide
    config`, `plugin option` or `default`; `where` is the config file for a config source; `note` explains a plugin
    option that was ignored."""
    variant: str
    source: str
    where: str = ""
    note: str = ""

    @property
    def label(self) -> str:
        """What `profile` prints in brackets: `plugin option`, `project config, .plainspoken/config.toml`, …"""
        return "; ".join(x for x in (", ".join(x for x in (self.source, self.where) if x), self.note) if x)


def _plugin_locale(value: str | None) -> str | None:
    """A plugin option value, or None when it's unset: empty, blank or an unsubstituted `${…}`."""
    value = (value or "").strip()
    return None if not value or is_placeholder(value) else value


def resolve_locale(prof: Profile | None, root: Path, env: Mapping[str, str],
                   plugin_locale: str | None = None) -> Locale:
    """The spelling locale the skills write in, first set wins: the project's `[locale] variant` (this body of
    writing's audience) → the voice profile's own `[profile] locale` (the writer's habit; skipped when `prof` is
    None) → the user-wide `[locale] variant` → the Claude Code option (CLAUDE_PLUGIN_OPTION_LOCALE in hooks, else
    `--plugin-locale` from a skill) → en-AU. A bad config value is a ConfigError naming the file and key; a plugin
    option that isn't a known variant is skipped, with a note. Only the drafting skills and register-check read it."""
    found = _project_config(Path(root))
    if found and "variant" in found[1].get("locale", {}):
        return Locale(found[1]["locale"]["variant"], "project config", ".plainspoken/config.toml")
    if prof is not None and prof.locale:
        return Locale(prof.locale, "profile")
    user = _user_config(env)
    if user and "variant" in user[1].get("locale", {}):
        return Locale(user[1]["locale"]["variant"], "user-wide config", str(user[0]))
    option = _plugin_locale(env.get("CLAUDE_PLUGIN_OPTION_LOCALE")) or _plugin_locale(plugin_locale)
    if option in locales():
        return Locale(option, "plugin option")
    note = f"plugin option {option!r} isn't a known variant" if option else ""
    return Locale(DEFAULT_LOCALE, "default", note=note)


def tool_call_settings(root: Path, env: Mapping[str, str] | None = None) -> dict:
    """`[tool_call]` with defaults filled in (`toolcall.settings`: each key from the project's section, else the
    user-wide file's; the Claude Code option `tool_call` for an unset mode; else off), read strictly: a bad project
    or user-wide file is a ConfigError naming the file and key. The hook uses the lean `toolcall.settings`, which
    gives the same answer."""
    env = os.environ if env is None else env
    _project_config(Path(root))
    _user_config(env)
    return toolcall.settings(Path(root), env)


def chat_reply_settings(root: Path, env: Mapping[str, str] | None = None) -> dict:
    """`[chat_reply]` with defaults filled in, as the nudge resolves: the project's section, else the user-wide file's,
    and for an unset mode the Claude Code option `chat_reply` (CLAUDE_PLUGIN_OPTION_CHAT_REPLY, "true" turns it to
    warn), else off. Plus `source`, where the mode came from. A bad file is a ConfigError naming the file and key."""
    env = os.environ if env is None else env
    found = _project_config(Path(root))
    if found and "chat_reply" in found[1]:
        body, where = found[1]["chat_reply"], "project config"
    else:
        user = _user_config(env)
        body, where = (user[1].get("chat_reply", {}), "user-wide config") if user else ({}, "default")
    out = {"mode": "off", "min_words": body.get("min_words", CHAT_REPLY_MIN_WORDS), "source": "default"}
    if "mode" in body:
        return {**out, "mode": body["mode"], "source": where}
    if str(env.get("CLAUDE_PLUGIN_OPTION_CHAT_REPLY", "")).strip().lower() == "true":
        return {**out, "mode": "warn", "source": "plugin option"}
    return out


def kaizen_settings(root: Path, env: Mapping[str, str]) -> dict:
    """`[kaizen]` with defaults filled in: the settings dict `ledger.append`, `ledger.read` and `ledger.friction` take.

    `monthly_cap` is the most proposals `kaizen calibrate` and `kaizen mine` may store between them in one calendar
    month (UTC), or None for no shared cap (each keeps its own per-run limit).

    `capture_sources` lists the sources that may record (CAPTURE_SOURCES, all six by default); `capture` false still
    turns every one off. `ledger_dir` and `proposals_dir` come back absolute, under `root`. `excerpts` comes from the
    project config, else CLAUDE_PLUGIN_OPTION_LEDGER_EXCERPTS (`true` or `1`), else false. `adapter` comes from the
    project config, else CLAUDE_PLUGIN_OPTION_KAIZEN_ADAPTER when it's a known value, else `file`. A project-config
    outward adapter (`github`, `trello`) with no `approvers` is a ConfigError: someone has to be named who may approve
    a proposal. The plugin option's outward adapter with no `approvers` falls back to `file` instead."""
    root = Path(root).resolve()
    found = _project_config(root)
    body = dict(found[1].get("kaizen", {})) if found else {}
    where = found[0] if found else root / ".plainspoken" / "config.toml"
    if "excerpts" in body:
        excerpts = body["excerpts"]
    else:
        excerpts = (env.get("CLAUDE_PLUGIN_OPTION_LEDGER_EXCERPTS") or "").strip().lower() in ("true", "1")
    out = {**KAIZEN_DEFAULTS, **{k: v for k, v in body.items() if k not in ("github", "trello")}}
    approvers = list(out["approvers"])
    adapter = body.get("adapter")
    if adapter is None:
        option = (env.get("CLAUDE_PLUGIN_OPTION_KAIZEN_ADAPTER") or "").strip()
        # The plugin option alone never sends anything outward: with nobody named to approve, it falls back to file.
        adapter = option if option in ADAPTERS and (option == "file" or approvers) else "file"
    if adapter != "file" and not approvers:
        raise ConfigError(f"{where}: [kaizen] adapter {adapter!r} sends proposals outside the project, so "
                          "[kaizen] approvers must name who may approve them")
    sources = list(body.get("capture_sources", CAPTURE_SOURCES))
    return {"capture": out["capture"], "capture_sources": sources, "excerpts": excerpts, "adapter": adapter,
            "ledger_dir": root / out["ledger_dir"], "proposals_dir": root / out["proposals_dir"],
            "corpus": list(out["corpus"]), "human_corpus": list(out["human_corpus"]), "approvers": approvers,
            "monthly_cap": out["monthly_cap"],
            "github": {**KAIZEN_GITHUB_DEFAULTS, **body.get("github", {})} | {
                "labels": list(body.get("github", {}).get("labels", KAIZEN_GITHUB_DEFAULTS["labels"]))},
            "trello": {**KAIZEN_TRELLO_DEFAULTS, **body.get("trello", {})} | {
                "label_ids": list(body.get("trello", {}).get("label_ids", []))},
            "root": root}


def brief_enabled(cwd: Path) -> bool:
    """[brief] enabled in the project config; False when unset (the session brief is off by default)."""
    found = _project_config(cwd)
    return bool(found and found[1].get("brief", {}).get("enabled", False))


def gate_paths(cwd: Path) -> list[str]:
    """The `[gate] paths` globs from the project config; [] when unset."""
    found = _project_config(cwd)
    return list(found[1].get("gate", {}).get("paths", [])) if found else []


def gate_strictness(cwd: Path, env: Mapping[str, str]) -> tuple[str, str]:
    """(the publish gate's strictness, where it came from). Order: `[gate] strictness` in the project config →
    CLAUDE_PLUGIN_OPTION_STRICTNESS → watch. A bad config value raises ConfigError; callers that must not deny (the
    publish gate) use gate_strictness_safe. A plugin option that isn't a known value means watch, as before the config
    key existed."""
    found = _project_config(cwd)
    if found and "strictness" in found[1].get("gate", {}):
        return found[1]["gate"]["strictness"], "project config"
    value = (env.get("CLAUDE_PLUGIN_OPTION_STRICTNESS") or "").strip()
    if value in STRICTNESS:
        return value, "plugin option"
    return "watch", "default"


def project_root(start: Path, env: Mapping[str, str] | None = None) -> Path:
    """The folder the engine treats as the project (report keys, reports folder, project config).

    CLAUDE_PROJECT_DIR when it is `start` or one of its parents; else the nearest folder from `start` up that holds
    .plainspoken/config.toml or .git (a folder, or a worktree's file); else `start`."""
    start = Path(start).resolve()
    env = os.environ if env is None else env
    given = (env.get("CLAUDE_PROJECT_DIR") or "").strip()
    if given:
        p = Path(given).resolve()
        if p == start or p in start.parents:
            return p
    for d in (start, *start.parents):
        if (d / ".plainspoken" / "config.toml").is_file() or (d / ".git").exists():
            return d
    return start


def gate_strictness_safe(cwd: Path, env: Mapping[str, str]) -> tuple[str, str, str | None]:
    """(strictness, source, problem); never raises. A usable config gives problem None. A config that can't be used
    gives its own readable `[gate] strictness` if it has one, else `block` only when the plugin option says so, else
    `warn`: someone who never opted in gets a warning, never a deny."""
    try:
        strictness, source = gate_strictness(cwd, env)
        return strictness, source, None
    except (ConfigError, OSError) as e:  # OSError: the file exists but can't be read
        problem = str(e)
    try:
        raw = tomllib.loads((cwd / ".plainspoken" / "config.toml").read_text(encoding="utf-8"))
        gate = raw.get("gate")
        if isinstance(gate, dict) and gate.get("strictness") in STRICTNESS:
            return gate["strictness"], "project config", problem
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        pass
    if (env.get("CLAUDE_PLUGIN_OPTION_STRICTNESS") or "").strip() == "block":
        return "block", "plugin option", problem
    return "warn", "config error", problem


def glob_match(rel: str, pattern: str) -> bool:
    """`rel` (a path from the project root, `/`-separated) matches `pattern`: `**/` is any number of folders, `**`
    anything, `*` anything but `/`, `?` one character but `/`. The same rules as the hooks' `_common.glob_match`."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.fullmatch(out, rel.replace("\\", "/")) is not None


def is_profile_path(value: str) -> bool:
    """A profile value names a file (a `/` in it, or a .toml ending), not a profile by name."""
    return "/" in value or value.endswith(".toml")


def _profile_ref(config_path: Path, value: str) -> str:
    """A profile value from the config as `profile.load` takes it: a name stays a name; a path is resolved against
    the config file's folder (.plainspoken/)."""
    return str((config_path.parent / value).resolve()) if is_profile_path(value) else value


def profile_for(path: Path, root: Path | None = None) -> str | None:
    """The profile the project config names for `path`: the first `[engine] profiles` entry whose glob matches the
    file's path from the project root, else `[engine] profile`, else None. A path is returned resolved, a name as it
    is. `root` defaults to the project the file is in. A bad config raises ConfigError."""
    root = project_root(Path(path).resolve().parent) if root is None else Path(root)
    found = _project_config(root)
    if not found:
        return None
    config_path, raw = found
    engine = raw.get("engine", {})
    try:
        rel = Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError, RuntimeError):
        rel = None  # outside the project: no glob matches
    for entry in engine.get("profiles", []) if rel is not None else ():
        if glob_match(rel, entry["glob"]):
            return _profile_ref(config_path, entry["profile"])
    value = engine.get("profile")
    return _profile_ref(config_path, value) if value else None


def profile_for_lint(lint: dict, root: Path, cli_value: str | None = None) -> Profile | None:
    """The profile the lint was made with (matched on `profile_sha256`), or None. It tries the lint's profile name,
    then the project's default profile. With `cli_value`, only that profile is tried, and a different one is a
    refusal."""
    want = lint.get("profile_sha256")
    if cli_value:
        prof = resolve_profile(cli_value, Path(root), os.environ)
        if prof.sha256 != want:
            raise ValueError(f"profile {prof.name} isn't the one the check used ({lint.get('profile')}): "
                             "pass that profile, or run check again")
        return prof
    article = lint.get("article")
    target = Path(article) if isinstance(article, str) and article else None
    for value in (lint.get("profile"), None):
        try:  # with no name, the profile the project config names for the article ([engine] profiles first)
            prof = resolve_profile(value, Path(root), os.environ, target=target)
        except (ValueError, OSError):
            continue
        if prof.sha256 == want:
            return prof
    return None


def project_profile_refs(root: Path) -> list[str]:
    """Every profile the project config names (`[engine] profile`, then each `[engine] profiles` entry's), once
    each, as `profile.load` takes them. A bad config raises ConfigError; no config gives []."""
    found = _project_config(Path(root))
    if not found:
        return []
    config_path, raw = found
    engine = raw.get("engine", {})
    values = [engine["profile"]] if engine.get("profile") else []
    values += [e["profile"] for e in engine.get("profiles", [])]
    return list(dict.fromkeys(_profile_ref(config_path, v) for v in values))


def profile_for_text(root: Path, env: Mapping[str, str], section: str = "tool_call",
                     plugin_option: str | None = PLUGIN_DEFAULT) -> Profile:
    """The profile for text that has no file (a tool call's arguments, a chat reply): PLAINSPOKEN_PROFILE →
    `[<section>] profile` (the project's section, else the user-wide file's) → `[engine] profile` → the Claude Code
    option → `plugin_option` (the plugin default). `[engine] profiles` globs are paths, so they never apply."""
    search = (Path(root) / ".plainspoken" / "profiles",)
    if env.get("PLAINSPOKEN_PROFILE"):
        return load(env["PLAINSPOKEN_PROFILE"], search=search)
    found = _project_config(Path(root))
    if found and "profile" in found[1].get(section, {}):
        return load(_profile_ref(found[0], found[1][section]["profile"]), search=search)
    user = _user_config(env)
    if user and "profile" in user[1].get(section, {}):
        return load(_profile_ref(user[0], user[1][section]["profile"]), search=search)
    return resolve_profile(None, Path(root), env, plugin_option=plugin_option)


def resolve_profile(cli_value: str | None, cwd: Path, env: Mapping[str, str],
                    plugin_option: str | None = None, target: Path | None = None) -> Profile:
    return resolve_profile_ex(cli_value, cwd, env, plugin_option, target)[0]


def resolve_profile_ex(cli_value: str | None, cwd: Path, env: Mapping[str, str],
                       plugin_option: str | None = None, target: Path | None = None) -> tuple[Profile, bool]:
    """The profile, and whether it came from the plugin option's placeholder fallback. `target` is the file the
    profile is for: with one, a matching `[engine] profiles` entry comes before `[engine] profile`."""
    search = (cwd / ".plainspoken" / "profiles",)
    for value in (cli_value, env.get("PLAINSPOKEN_PROFILE")):
        if value:
            return load(value, search=search), False
    if target is not None:
        ref = profile_for(target, cwd)
    else:
        found = _project_config(cwd)
        value = found[1].get("engine", {}).get("profile") if found else None
        ref = _profile_ref(found[0], value) if value else None
    if ref:
        return load(ref, search=search), False
    value = env.get("CLAUDE_PLUGIN_OPTION_PROFILE")
    if value:
        return load(value, search=search), False
    if plugin_option is not None:
        if not plugin_option.strip() or is_placeholder(plugin_option):
            return load(PLUGIN_DEFAULT, search=search), True
        return load(plugin_option, search=search), False
    raise ProfileError("no profile: pass --profile, set PLAINSPOKEN_PROFILE, "
                       "or add profile = \"<name>\" under [engine] in .plainspoken/config.toml")
