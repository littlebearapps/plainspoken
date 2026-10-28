"""The tool-call check's cheap side (#124): which tool calls it reads, its `[tool_call]` settings, and the walk that
finds writing for a person in a tool's arguments.

- `settings(root, env)`: `[tool_call]` key by key from the project config, else the user-wide file, with the
  Claude Code option `tool_call` for the mode when neither sets it, else off. Never raises: a config it can't use
  turns the check off and says why in `error`. `config.tool_call_settings` is the strict reader (a ConfigError
  naming the file and key), and both give the same answer for a good config.
- `name_decision(name, host, settings)`: None when the call is checked, else why not (`not-mcp`, `core`,
  `skip-list`, `lookup`). Claude Code and Codex check MCP tools only; Hermes checks every tool but a shipped core list.
  `include` beats every skip.
- `walk(tool_input, skip_fields, min_words)`: one `Field` per string argument worth a look, with the prose
  `plainspoken.prose.extract` found in it and the outcome (`candidate`, `below-cutoff`, `too-long`,
  `not-prose:<reason>`).

Stdlib only. A hook that stops at the mode or the tool name loads only `os`, `re` and `fnmatch` from here (paths are
strings, not pathlib; hashlib, tomllib and `plainspoken.prose` load where they're used), so a skipped call costs a few
milliseconds on top of the interpreter. The shipped lists live in `data/tool-call.toml`.
"""
from __future__ import annotations

import fnmatch
import os
import re
from collections import namedtuple
from collections.abc import Mapping

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
DATA = os.path.join(ROOT, "data", "tool-call.toml")
MODES = ("off", "warn", "block-once", "ask")
HOSTS = ("claude-code", "codex", "hermes")
KEYS = ("mode", "min_words", "skip", "include", "skip_fields", "profile")
LIST_KEYS = ("skip", "include", "skip_fields")
MIN_WORDS = 25
MAX_WORDS = 10_000  # prose words in one field; past it the field isn't linted (`too-long`)
MAX_DEPTH = 12
MAX_LEAVES = 400
OPTION = "CLAUDE_PLUGIN_OPTION_TOOL_CALL"
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SHIPPED: dict | None = None


# path: where in the arguments, `body` or `message.blocks[].text` (no list indexes, so it's stable) · text: the
# stripped prose, what a lint sees · words · outcome: candidate, below-cutoff, too-long or not-prose:<reason>
Field = namedtuple("Field", "path text words outcome")


# --- names --------------------------------------------------------------------------------------------------------

def normalise_name(name: str) -> str:
    """Lower case, hyphens folded to underscores: the form every glob matches."""
    return str(name).lower().replace("-", "_")


def is_mcp(norm: str) -> bool:
    return norm.startswith("mcp_")


def split_name(norm: str) -> tuple[str, str]:
    """(server, the tool's own name) for a normalised name: `mcp__<server>__<tool>`; Hermes' older `mcp_<server>_<tool>`
    (the server taken as the first segment); a non-MCP tool has no server."""
    if norm.startswith("mcp__"):
        rest = norm[5:]
        if "__" in rest:
            server, tool = rest.rsplit("__", 1)
            return server, tool
        return "", rest
    if norm.startswith("mcp_"):
        server, _, tool = norm[4:].partition("_")
        return server, tool or server
    return "", norm


def server_hash(name: str) -> str:
    """8 hex for the server part of a tool name: a local server's name can name a client, so it's never stored."""
    import hashlib
    server, _ = split_name(normalise_name(name))
    return hashlib.sha256(server.encode("utf-8")).hexdigest()[:8]


def is_draft(name: str) -> bool:
    """The tool's own name says it holds a draft for a person to review (`create_draft`, `update_draft`)."""
    return "draft" in split_name(normalise_name(name))[1]


def shipped() -> dict:
    """The shipped lists from `data/tool-call.toml`, read once."""
    global _SHIPPED
    if _SHIPPED is None:
        import tomllib
        with open(DATA, encoding="utf-8") as f:
            raw = tomllib.loads(f.read())
        _SHIPPED = {k: [str(x).lower() for x in raw.get(k, [])]
                    for k in ("skip_tools", "lookup_prefixes", "skip_fields", "hermes_core")}
    return _SHIPPED


def _any(name: str, globs) -> bool:
    return any(fnmatch.fnmatchcase(name, g.lower()) for g in globs)


def name_decision(name: str, host: str, settings: Mapping) -> str | None:
    """None when a call to `name` is checked, else the reason it isn't."""
    norm = normalise_name(name)
    if _any(norm, settings.get("include") or ()):
        return None
    lists = shipped()
    if not is_mcp(norm):
        if host != "hermes":
            return "not-mcp"
        if _any(norm, lists["hermes_core"]):
            return "core"
    if _any(norm, lists["skip_tools"]) or _any(norm, settings.get("skip") or ()):
        return "skip-list"
    if split_name(norm)[1].startswith(tuple(lists["lookup_prefixes"])):
        return "lookup"
    return None


# --- settings -----------------------------------------------------------------------------------------------------

def settings_defaults() -> dict:
    return {"mode": "off", "min_words": MIN_WORDS, "skip": [], "include": [], "skip_fields": [], "profile": None,
            "source": "default", "error": None}


def section_errors(body: object) -> list[str]:
    """What's wrong with a `[tool_call]` table, as `[tool_call] <key> …` messages; [] when it's good."""
    if not isinstance(body, dict):
        return ["[tool_call] must be a table"]
    out = [f"unknown key [tool_call] {k}" for k in body if k not in KEYS]
    if "mode" in body and body["mode"] not in MODES:
        out.append(f"[tool_call] mode must be one of {', '.join(MODES)}, got {body['mode']!r}")
    n = body.get("min_words", MIN_WORDS)
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_WORDS:
        out.append(f"[tool_call] min_words must be a whole number from 1 to {MAX_WORDS}, got {n!r}")
    for key in LIST_KEYS:
        value = body.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            out.append(f"[tool_call] {key} must be a list of non-empty strings")
    if "profile" in body and not (isinstance(body["profile"], str) and body["profile"].strip()):
        out.append("[tool_call] profile must be a non-empty string")
    return out


def user_config_path(env: Mapping[str, str]) -> str:
    """The user-wide config file (as `config.user_config_path`), as a string."""
    base = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".config")
    return os.path.join(base, "plainspoken", "config.toml")


def _read(path: str) -> dict | None:
    """The parsed file, None when there's none. Raises ValueError with the reason when it can't be read."""
    if not os.path.exists(path):
        return None
    import tomllib
    try:
        with open(path, encoding="utf-8") as f:
            raw = tomllib.loads(f.read())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"{path}: not valid TOML ({e})") from None
    return raw


def settings(root, env: Mapping[str, str] | None = None) -> dict:
    """`[tool_call]` with defaults filled in, key by key: the project's section beats the user-wide file's, and the
    Claude Code option `tool_call` sets the mode when neither does. Plus `source` (where the mode came from: project
    config, user-wide config, plugin option or default) and `error` (None, or why a config couldn't be used, in which
    case the mode is off)."""
    env = os.environ if env is None else env
    out = settings_defaults()
    merged: dict = {}
    mode_from = None
    try:
        for path, where in ((user_config_path(env), "user-wide config"),
                            (os.path.join(str(root), ".plainspoken", "config.toml"), "project config")):
            raw = _read(path)
            if raw and "tool_call" in raw:
                body = raw["tool_call"]
                errors = section_errors(body)
                if errors:
                    raise ValueError(f"{path}: {errors[0]}")
                merged.update(body)
                if "mode" in body:
                    mode_from = where
    except ValueError as e:
        return {**out, "error": str(e)}
    out.update({k: (list(v) if k in LIST_KEYS else v) for k, v in merged.items()})
    if mode_from:
        out["source"] = mode_from
        return out
    option = str(env.get(OPTION) or "").strip()
    if option in MODES:
        out.update(mode=option, source="plugin option")
    return out


def project_root(start, env: Mapping[str, str] | None = None) -> str:
    """The project folder as a string, by `config.project_root`'s rule, without importing it or pathlib:
    CLAUDE_PROJECT_DIR when it's `start` or a parent, else the nearest folder up with .plainspoken/config.toml or
    .git, else `start`."""
    start = os.path.realpath(str(start))
    env = os.environ if env is None else env
    given = (env.get("CLAUDE_PROJECT_DIR") or "").strip()
    if given:
        p = os.path.realpath(given)
        if start == p or start.startswith(p.rstrip(os.sep) + os.sep):
            return p
    d = start
    while True:
        if os.path.isfile(os.path.join(d, ".plainspoken", "config.toml")) or os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return start
        d = parent


# --- the walk -----------------------------------------------------------------------------------------------------

def field_name(key: str) -> str:
    """A field's name as the field globs see it: camelCase split, lower case, hyphens to underscores."""
    return _CAMEL.sub("_", str(key)).lower().replace("-", "_")


def walk(tool_input: object, skip_fields: list[str], min_words: int = MIN_WORDS,
         max_words: int = MAX_WORDS) -> list[Field]:
    """One Field per string argument that isn't a skipped field or a 2-D grid cell, in order, at most MAX_LEAVES
    strings and MAX_DEPTH levels deep. Strings under a field named in the shipped or `skip_fields` list are never
    read."""
    if not isinstance(tool_input, dict):
        return []
    from plainspoken import prose
    globs = [g.lower() for g in (*shipped()["skip_fields"], *skip_fields)]
    out: list[Field] = []
    seen = 0

    def visit(node: object, path: str, key: str, depth: int, in_list: int) -> None:
        nonlocal seen
        if depth > MAX_DEPTH or seen >= MAX_LEAVES:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                name = field_name(k)
                if _any(name, globs):
                    continue
                visit(v, f"{path}.{k}" if path else str(k), name, depth + 1, 0)
        elif isinstance(node, list):
            for v in node:
                visit(v, f"{path}[]", key, depth + 1, in_list + 1)
        elif isinstance(node, str):
            seen += 1
            if in_list >= 2:  # a cell of a grid (`values[][]`): spreadsheet data, not writing
                return
            found = prose.extract(node)
            if found.reason is not None:
                outcome = f"not-prose:{found.reason}"
            elif found.words > max_words:
                outcome = "too-long"
            elif found.words < min_words:
                outcome = "below-cutoff"
            else:
                outcome = "candidate"
            out.append(Field(path, found.text, found.words, outcome))

    visit(tool_input, "", "", 0, 0)
    return out
