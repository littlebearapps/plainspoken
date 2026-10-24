"""`doctor`: check whether this host can run what plainspoken needs, and say so. Warnings only, never a blocker.

`setup` prints the WARN lines of the same checks after its own output, and `doctor` prints all of them. Neither
writes, creates, installs, enables or deletes anything because of a check. The only commands run are `python3
--version` and `hermes chat --help`, each with a short timeout; nothing starts an agent session or calls a model.
What a script can't see (the agent's own tools and permissions, Codex's hook trust) is `not checked`, never `ok`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from plainspoken import config, hosts

__all__ = ["Check", "HERMES_FLAGS", "STATUSES", "format", "plugin_root", "run_checks", "setup_lines", "summary"]

OK, WARN, NOT_CHECKED = "ok", "WARN", "not checked"
STATUSES = (OK, WARN, NOT_CHECKED)
MIN_PYTHON = (3, 11)
TIMEOUT = 10  # seconds, for each external command
# The flags the judges' `hermes chat` command needs (hosts/hermes.md). `-p` is read before argparse, so --help
# never lists it.
HERMES_FLAGS = ("--query-file", "--oneshot", "--source")
PLUGIN_FILES = ("lib/run.py", "data/rules.toml", "skills/")
SHELL_HOSTS = ("claude-code", "codex", "hermes")
CHAT_NAMES = {"claude-ai": "claude.ai", "chatgpt": "ChatGPT"}
_VERSION = re.compile(r"Python (\d+)\.(\d+)(?:\.(\d+))?")
_WIDTH = len(NOT_CHECKED) + 2


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # one of STATUSES
    detail: str  # one line
    fix: str = ""  # one line: what the person could do; empty for ok

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _which(cmd: str, env: Mapping[str, str]) -> str | None:
    return shutil.which(cmd, path=env.get("PATH"))


def _run(args: list[str], env: Mapping[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL,
                          env=dict(env), check=False)


def _safe(name: str, fn: Callable[[], Check | list[Check]]) -> list[Check]:
    """Run one check. An exception gives `not checked` with its type only: no traceback, no message (it could hold a
    path or a value the person shouldn't see in a transcript)."""
    try:
        out = fn()
    except subprocess.TimeoutExpired:
        return [Check(name, NOT_CHECKED, f"timed out after {TIMEOUT} s")]
    except Exception as e:  # noqa: BLE001 - a check must never stop setup or doctor
        return [Check(name, NOT_CHECKED, f"couldn't run this check ({type(e).__name__})")]
    return out if isinstance(out, list) else [out]


# Shell hosts -------------------------------------------------------------------------------------------------------

def _python(env: Mapping[str, str]) -> Check:
    want = ".".join(map(str, MIN_PYTHON))
    fix = f"install Python {want} or later as python3 on PATH"
    path = _which("python3", env)
    if not path:
        return Check("python3", WARN, "no python3 on PATH, so the hooks skip", fix)
    done = _run([path, "--version"], env)
    m = _VERSION.search(f"{done.stdout}\n{done.stderr}")
    if not m:
        return Check("python3", NOT_CHECKED, f"{path} --version printed no version")
    version = ".".join(g for g in m.groups() if g is not None)
    if (int(m.group(1)), int(m.group(2))) < MIN_PYTHON:
        return Check("python3", WARN, f"python3 is {version} ({path}); the hooks need {want} or later and skip "
                                      "without it", fix)
    return Check("python3", OK, f"{version} ({path})")


def _plugin_files() -> Check:
    root = plugin_root()
    missing = [p for p in PLUGIN_FILES if not (root / p.rstrip("/")).exists()]
    if missing:
        return Check("plugin files", WARN, f"missing under {root}: {', '.join(missing)}",
                     "reinstall plainspoken (or update it)")
    return Check("plugin files", OK, str(root))


def _reports(root: Path) -> Check:
    target = root / ".plainspoken" / "reports"
    near = target
    while not near.exists() and near != near.parent:
        near = near.parent
    fix = f"make {near} writable, or run from a project folder you can write to"
    if not near.is_dir():
        return Check("reports folder", WARN, f"{near} is not a folder, so {target} can't be made", fix)
    if not os.access(near, os.W_OK | os.X_OK):
        return Check("reports folder", WARN, f"{near} isn't writable, so reports can't be saved to {target}", fix)
    return Check("reports folder", OK, f"{target} {'is writable' if near == target else 'can be made'}")


def _git(root: Path, env: Mapping[str, str]) -> Check:
    path = _which("git", env)
    if path:
        return Check("git", OK, path)
    strictness, _, _ = config.gate_strictness_safe(root, env)
    if strictness in ("warn", "block"):
        return Check("git", WARN, f"no git on PATH, and the publish gate is set to {strictness}: it can't see "
                                  "what a push sends", 'install git, or set [gate] strictness = "watch"')
    return Check("git", OK, "no git on PATH; the publish gate is off (watch), so it isn't needed")


def _first_line(e: BaseException) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


def _project_config(root: Path) -> Check:
    path = root / ".plainspoken" / "config.toml"
    try:
        found = config._project_config(root)
    except config.ConfigError as e:
        return Check("project config", WARN, _first_line(e), f"fix {path} by hand")
    return Check("project config", OK, str(path) if found else "none (defaults apply)")


def _user_config(host: str, env: Mapping[str, str]) -> Check:
    path = config.user_config_path(env)
    try:
        found = config._user_config(env)
    except config.ConfigError as e:
        return Check("user-wide config", WARN, _first_line(e), f"fix {path} by hand")
    if found:
        return Check("user-wide config", OK, str(path))
    if host == "hermes":
        return Check("user-wide config", WARN, f"none at {path}, and Hermes reads that one, so the nudge and lint "
                                               "settings stay at their defaults", "run setup --host hermes --scope user")
    return Check("user-wide config", OK, "none (defaults apply)")


def _shell(host: str, root: Path, env: Mapping[str, str]) -> list[Check]:
    out: list[Check] = []
    for name, fn in (("python3", lambda: _python(env)), ("plugin files", _plugin_files),
                     ("reports folder", lambda: _reports(root)), ("git", lambda: _git(root, env)),
                     ("project config", lambda: _project_config(root)),
                     ("user-wide config", lambda: _user_config(host, env))):
        out += _safe(name, fn)
    return out


# Per host ----------------------------------------------------------------------------------------------------------

def _agents() -> Check:
    folder = plugin_root() / "agents"
    missing = [name for name in hosts.AGENTS if not (folder / f"{name}.md").is_file()]
    if missing:
        return Check("plugin agents", WARN, f"missing from {folder}: {', '.join(missing)}",
                     "reinstall plainspoken (or update it)")
    return Check("plugin agents", OK, ", ".join(hosts.AGENTS))


def _claude_code() -> list[Check]:
    run = f"python3 {plugin_root()}/lib/run.py"
    return [*_safe("plugin agents", _agents),
            Check("Bash permission", NOT_CHECKED, "a script can't see Claude Code's permissions or sandbox",
                  f"allow Bash to run {run}")]


def _codex(env: Mapping[str, str]) -> list[Check]:
    def cli() -> Check:
        # Found on PATH only: even `codex --version` writes helper files under its own home folder.
        path = _which("codex", env)
        if path:
            return Check("codex CLI", OK, path)
        return Check("codex CLI", NOT_CHECKED, "no codex on PATH (the Codex app or ChatGPT Work may still run "
                                               "plainspoken; codex exec for the judges needs it)")
    return [*_safe("codex CLI", cli),
            Check("hooks trusted", NOT_CHECKED, "a script can't see whether Codex trusts the plugin's hooks",
                  "run /hooks in Codex and trust plainspoken's hooks"),
            Check("sandbox writes", NOT_CHECKED, "the engine saves reports to .plainspoken/reports in the project",
                  "run Codex with workspace write access (sandbox workspace-write) in the project folder"),
            Check("judges", NOT_CHECKED, "the judges need spawn_agent, or codex exec run outside the sandbox",
                  "confirm spawn_agent is in your tools, or that codex exec can run here")]


def _hermes(root: Path, env: Mapping[str, str]) -> list[Check]:
    out: list[Check] = []

    def cli() -> Check:
        path = _which("hermes", env)
        if path:
            return Check("hermes CLI", OK, path)
        return Check("hermes CLI", WARN, "no hermes on PATH, and the judges run as `hermes chat` processes",
                     "put the hermes command on PATH (the judges fall back to delegate_task without it)")

    def flags() -> list[Check]:
        names = [f"hermes chat {flag}" for flag in HERMES_FLAGS]
        path = _which("hermes", env)
        if not path:
            return [Check(n, NOT_CHECKED, "no hermes on PATH") for n in names]
        done = _run([path, "chat", "--help"], env)
        text = f"{done.stdout}\n{done.stderr}"
        if done.returncode != 0 or not text.strip():
            return [Check(n, NOT_CHECKED, f"`hermes chat --help` exited {done.returncode}") for n in names]
        rows = []
        for flag, name in zip(HERMES_FLAGS, names):
            if re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text):
                rows.append(Check(name, OK, "listed"))
            else:
                rows.append(Check(name, WARN, f"`hermes chat --help` doesn't list {flag}, which the judges' "
                                              "command needs", "update Hermes Agent"))
        return rows

    def profile() -> Check:
        home = (env.get("HERMES_HOME") or "").strip()
        if home:
            return Check("Hermes profile", OK, f"HERMES_HOME is {home}")
        return Check("Hermes profile", NOT_CHECKED, "HERMES_HOME not set (the sticky active profile applies)",
                     "confirm which Hermes profile this session runs in")

    out += _safe("hermes CLI", cli)
    out += _safe("hermes chat flags", flags)
    out += _safe("Hermes profile", profile)
    out.append(Check("working folder", NOT_CHECKED, f"the project is the Hermes profile's working folder "
                                                    f"(terminal.cwd); this run used {root}",
                     "confirm terminal.cwd is the project folder, or cd there before each run"))
    out.append(Check("toolsets", NOT_CHECKED, "the skills need terminal, read_file, write_file and patch, and the "
                                              "judges' fallback needs delegate_task",
                     "confirm these tools are on for this Hermes profile"))
    return out


def _chat(host: str) -> list[Check]:
    app = CHAT_NAMES[host]
    return [Check("shell", NOT_CHECKED, f"no shell in {app} chat, so the lint, the judges and the hooks don't run "
                                        "there"),
            Check("paste-in text", NOT_CHECKED, "the paste-in text is guidance the model follows, not a check, so "
                                                "a \"check\" in chat is the model's own read")]


def run_checks(host: str, root: Path, env: Mapping[str, str]) -> list[Check]:
    """Every check for `host`, in order. Never raises for a check; an unknown host is a ValueError."""
    if host in CHAT_NAMES:
        return _chat(host)
    if host not in SHELL_HOSTS:
        raise ValueError(f"unknown host {host!r}")
    root = Path(root)
    out = _shell(host, root, env)
    if host == "claude-code":
        out += _claude_code()
    elif host == "codex":
        out += _codex(env)
    else:
        out += _hermes(root, env)
    return out


def format(checks: list[Check]) -> list[str]:
    """One line per check: `  <status>  <name>: <detail>`, with ` → <fix>` when there's one."""
    return [f"  {c.status:<{_WIDTH}}{c.name}: {c.detail}" + (f" → {c.fix}" if c.fix else "") for c in checks]


def summary(checks: list[Check]) -> str:
    n = {s: sum(1 for c in checks if c.status == s) for s in STATUSES}
    return f"{n[OK]} ok · {n[WARN]} WARN · {n[NOT_CHECKED]} not checked"


def setup_lines(host: str, checks: list[Check]) -> list[str]:
    """What `setup` adds after its own output: the WARN lines and a count of what needs confirming; for the chat
    hosts, every line (there's nothing else to say). Empty when every check is ok."""
    if host in CHAT_NAMES:
        shown, unconfirmed = checks, 0
    else:
        shown = [c for c in checks if c.status == WARN]
        unconfirmed = sum(1 for c in checks if c.status == NOT_CHECKED)
    if not shown and not unconfirmed:
        return []
    lines = ["", "Host checks (warnings only; setup changed nothing because of them):", *format(shown)]
    if unconfirmed:
        verb = "check needs" if unconfirmed == 1 else "checks need"
        lines.append(f"  {unconfirmed} {verb} you to confirm: run doctor --host {host}")
    return lines
