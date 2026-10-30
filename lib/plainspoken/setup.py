"""`setup`: turn the optional pieces (the writing nudge, the drafting rule, lint after edits, the chat-reply check) on
or off for one host, and set the spelling locale (`--locale`) and the tool-call check's mode (`--tool-call`).

It edits one config file: the project's `.plainspoken/config.toml` (scope `project`) or the user-wide
`~/.config/plainspoken/config.toml` (scope `user`). Every line it writes ends with MARK, and `--remove` deletes only
marked lines (and a section header it added, once that section is empty), so a hand-written setting is never lost.
The rest of the file is kept byte for byte. claude.ai and ChatGPT chat can't run hooks, so for them it prints the text
to paste into the app's instructions and writes nothing; `--locale` adds one sentence naming the variant to it.
"""
from __future__ import annotations

import re
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path

from plainspoken import config

MARK = "# set by plainspoken setup"
HOSTS = ("claude-code", "codex", "hermes", "claude-ai", "chatgpt")
FILE_HOSTS = ("claude-code", "codex", "hermes")
RULE_HOSTS = ("claude-code",)
# (section, key, value for "on", value for "off")
SETTINGS = {"nudge": ("nudge", "mode", '"on"', '"off"'),
            "rule": ("rule", "enabled", "true", "false"),
            "lint_watch": ("lint_watch", "mode", '"on"', '"off"'),
            "chat_reply": ("chat_reply", "mode", '"warn"', '"off"')}
LOCALE_NAMES = {"en-AU": "Australian English", "en-GB": "British English", "en-US": "American English"}
_HEADER = re.compile(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$")

PASTE = {
    "claude-ai": ("claude.ai and the Claude desktop app (chat): Settings → Profile → \"What personal preferences "
                  "should Claude consider in responses?\", or a Project's instructions. Paste:"),
    "chatgpt": ("ChatGPT: Settings → Personalization → Custom instructions (\"What traits should ChatGPT have?\"), "
                "or a Project's instructions. Paste:"),
}
AFTER = {
    "codex": ("Codex runs plugin hooks only after you trust them, and asks again after every plainspoken update: "
              "run /hooks in Codex and trust plainspoken's. ChatGPT Work uses the same hooks."),
    "hermes": "Start a new Hermes session (or reload the gateway) so the change takes effect.",
    "claude-code": "Start a new Claude Code session (or run /reload-plugins) so the change takes effect.",
}


class SetupError(ValueError):
    """A request setup can't carry out. The message says why and what to do instead."""


def config_path(scope: str, root: Path, env: Mapping[str, str]) -> Path:
    return config.user_config_path(env) if scope == "user" else root / ".plainspoken" / "config.toml"


def _sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    """section name → (header line index, end index exclusive) for each `[name]` table in the file."""
    out, current, start = {}, None, 0
    for i, line in enumerate(lines):
        m = _HEADER.match(line)
        if m:
            if current is not None:
                out.setdefault(current, (start, i))
            current, start = m.group(1).strip(), i
    if current is not None:
        out.setdefault(current, (start, len(lines)))
    return out


def set_key(text: str, section: str, key: str, value: str) -> str:
    """`text` with `[section] key = value` set, marked. An existing line for the key is replaced in place."""
    lines = text.splitlines()
    line = f"{key} = {value}  {MARK}"
    found = _sections(lines).get(section)
    if found is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ([""] if lines else []) + [f"[{section}]  {MARK}", line]
    else:
        start, end = found
        key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for i in range(start + 1, end):
            if key_re.match(lines[i]):
                lines[i] = line
                break
        else:
            last = start
            for i in range(start + 1, end):
                if lines[i].strip():
                    last = i
            lines.insert(last + 1, line)
    return "\n".join(lines) + "\n"


def unset_marked(text: str) -> str:
    """`text` without setup's marked key lines, and without a header setup added once its section has no keys."""
    lines = [ln for ln in text.splitlines() if not (ln.rstrip().endswith(MARK) and not _HEADER.match(ln))]
    drop = set()
    for start, end in _sections(lines).values():
        if lines[start].rstrip().endswith(MARK) and not any(
                ln.strip() and not ln.strip().startswith("#") for ln in lines[start + 1:end]):
            drop.update(range(start, end))
    keep = [ln for i, ln in enumerate(lines) if i not in drop]
    while keep and not keep[-1].strip():
        keep.pop()
    return "\n".join(keep) + "\n" if keep else ""


def _validate(path: Path, text: str, scope: str) -> None:
    """Refuse to write a file the engine couldn't read back."""
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "config.toml"
        probe.write_text(text, encoding="utf-8")
        try:
            config._read_config(probe, config._USER_SECTIONS if scope == "user" else tuple(config._SECTIONS))
        except config.ConfigError as e:
            raise SetupError(f"{path}: the change would leave an unreadable config "
                             f"({str(e).split(': ', 1)[-1]}); edit it by hand") from None


def plan(host: str, scope: str, wanted: dict[str, bool], root: Path, env: Mapping[str, str],
         remove: bool = False, locale: str | None = None, tool_call: str | None = None) -> tuple[Path, str, str]:
    """(path, text before, text after) for this request. `locale` sets `[locale] variant`; `tool_call` sets
    `[tool_call] mode`. Raises SetupError for a request that can't apply."""
    if host not in FILE_HOSTS:
        raise SetupError(f"{host} chat can't run hooks or read a config file: use `setup --host {host}` with no "
                         "other options to print the text to paste")
    if wanted.get("rule") is not None and host not in RULE_HOSTS:
        raise SetupError("the drafting rule is for Claude Code (and Cowork); for claude.ai chat, `setup --host "
                         "claude-ai` prints the text to paste")
    path = config_path(scope, root, env)
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    try:
        tomllib.loads(before)
    except tomllib.TOMLDecodeError as e:
        raise SetupError(f"{path}: not valid TOML ({e}); fix it first") from None
    after = unset_marked(before) if remove else before
    for name, on in wanted.items():
        if on is None:
            continue
        section, key, yes, no = SETTINGS[name]
        after = set_key(after, section, key, yes if on else no)
    if locale is not None:
        after = set_key(after, "locale", "variant", f'"{locale}"')
    if tool_call is not None:
        after = set_key(after, "tool_call", "mode", f'"{tool_call}"')
    if after != before:
        _validate(path, after, scope)
    return path, before, after


def apply(path: Path, after: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if after:
        path.write_text(after, encoding="utf-8")
    elif path.is_file():
        path.unlink()


def locale_sentence(variant: str) -> str:
    """The paste-in line for chat hosts, which can't read a config file."""
    name = LOCALE_NAMES.get(variant)
    return f"Spell in {name} ({variant})." if name else f"Spell in the {variant} variant of English."


def paste_text(host: str, locale: str | None = None) -> str:
    rule = (config_root() / "data" / "drafting-rule-chat.md").read_text(encoding="utf-8").strip()
    extra = f"\n\n{locale_sentence(locale)}" if locale else ""
    return f"{PASTE[host]}\n\n{rule}{extra}\n"


def config_root() -> Path:
    return Path(__file__).resolve().parents[2]


def status(root: Path, env: Mapping[str, str]) -> list[str]:
    """What's on now for this project, after project → user → plugin option."""
    user = config.user_config_path(env)
    try:
        nudge, rule = config.nudge_mode(root, env), config.rule_enabled(root, env)
        lint = config.lint_watch(root, env)["mode"]
        tool_call = config.tool_call_settings(root, env)["mode"]
        chat_reply = config.chat_reply_settings(root, env)["mode"]
    except config.ConfigError as e:
        return [f"config problem: {e}"]
    return [f"project: {root}",
            f"user-wide config: {user}{'' if user.is_file() else ' (none)'}",
            f"writing nudge: {nudge}",
            f"drafting rule: {'on' if rule else 'off'} (Claude Code and Cowork)",
            f"spelling locale: {_locale_status(root, env)}",
            f"lint after edits: {lint}",
            f"tool-call check: {tool_call}",
            f"chat-reply check: {chat_reply}"]


def _locale_status(root: Path, env: Mapping[str, str]) -> str:
    """The `[locale] variant` setup writes, from the project file, else the user-wide one. setup can't see the voice
    profile's or the plugin option's (`profile` shows the resolved locale), so the line says so."""
    found = config._project_config(root)
    if found and "variant" in found[1].get("locale", {}):
        return f"{found[1]['locale']['variant']} (project config)"
    user = config._user_config(env)
    if user and "variant" in user[1].get("locale", {}):
        return f"{user[1]['locale']['variant']} (user-wide config; a voice profile that sets one wins over it)"
    return "not set in a config file (the voice profile, the plugin option or en-AU applies; profile shows which)"
