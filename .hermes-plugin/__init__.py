"""plainspoken for Hermes Agent: registers the plugin's skills, tells the model where the plugin lives, and runs the
same hook scripts as Claude Code and Codex: the writing nudge, lint after each edit, the publish gate and write guard
before each `terminal` command, and the kaizen nudge at the end of each turn.

Install: `hermes plugins install littlebearapps/plainspoken --enable`, then start a new session. Hermes ignores
`.claude-plugin/`, so this folder is the Hermes entry point; the skills, agents and engine are the same files Claude
Code and Codex use. How the skills run here (paths, the judges as one-shot `hermes chat` processes, what's missing):
`hosts/hermes.md`.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_MARKER = "plainspoken plugin for hermes"
EDIT_TOOLS = ("write_file", "patch")  # Hermes' file-writing tools; lint-watch and integrity run after each
SHELL_TOOL = "terminal"  # Hermes' shell tool; the publish gate and the write guard run before each call
HOOK_TIMEOUT = 15  # the gate's, as on Claude Code; Hermes blocks a pre_tool_call callback that passes 30 s
GUARD_TIMEOUT = 5
NUDGE_TIMEOUT = 10
logger = logging.getLogger(__name__)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter_loader():
    # The engine's own YAML-subset reader, loaded by path so nothing is added to sys.path.
    return _load("_plainspoken_frontmatter", ROOT / "lib" / "plainspoken" / "frontmatter.py").load


def _hook_run(script: str, event: dict, *args: str, timeout: int = HOOK_TIMEOUT,
              env: dict | None = None) -> tuple[dict | None, bool]:
    """Run one of plainspoken's hook scripts (the same ones Claude Code and Codex run) on a Claude-shaped event.
    Returns (the JSON object it printed or None, whether it ran cleanly). It didn't when it couldn't start, timed
    out, exited non-zero or printed something that isn't a JSON object; a clean run that prints nothing is
    (None, True). Never raises."""
    try:
        cwd = event.get("cwd")
        done = subprocess.run([sys.executable, str(ROOT / "hooks" / script), *args], input=json.dumps(event),
                              capture_output=True, text=True, timeout=timeout, env=env,
                              cwd=cwd if isinstance(cwd, str) and os.path.isdir(cwd) else None)
        if not done.stdout.strip():
            return None, done.returncode == 0
        out = json.loads(done.stdout)
        return (out, done.returncode == 0) if isinstance(out, dict) else (None, False)
    except Exception:
        return None, False


def _hook_output(script: str, event: dict, *args: str, timeout: int = HOOK_TIMEOUT,
                 env: dict | None = None) -> dict | None:
    """The JSON object a hook script printed, or None, for callers where a hook that can't run should say nothing
    (the publish gate, the write guard, the kaizen nudge). Never raises."""
    return _hook_run(script, event, *args, timeout=timeout, env=env)[0]


# integrity.py's block-mode first line: must match the reason `_emit` builds in hooks/integrity.py.
BLOCK_LEAD = "The edit is saved, but fix this before going on.\n"
UNCHECKED = {"lint_watch.py": "it wasn't linted", "integrity.py": "its figures weren't checked"}


def _run_hook(script: str, event: dict, *args: str, quiet: bool = False) -> str | None:
    """A hook script's line for the model, or None when there's nothing to say. A block-mode reply comes back as a
    warning, since Hermes can't hold an edit back once it's saved. A hook that couldn't run says so in one line
    (never its error text), unless `quiet`, for the optional writing nudge. Never raises."""
    try:
        out, ran = _hook_run(script, event, *args)
        if not ran:
            if quiet:
                return None
            path = (event.get("tool_input") or {}).get("file_path")
            name = (Path(path).name if isinstance(path, str) else "") or "the file"
            unchecked = UNCHECKED.get(script, "this file wasn't checked")
            return f"plainspoken: {script} couldn't run on {name}; {unchecked}."
        if not isinstance(out, dict):
            return None
        reason = out.get("reason")
        if out.get("decision") == "block" and isinstance(reason, str) and reason.strip():
            return ("plainspoken: block mode isn't enforced on Hermes, so the edit is saved, but fix this before "
                    "going on.\n" + reason.removeprefix(BLOCK_LEAD))
        line = out.get("hookSpecificOutput", {}).get("additionalContext")
        return line if isinstance(line, str) and line else None
    except Exception:
        return None


def _deny_reason(out: dict | None) -> str | None:
    """The reason in a Claude-shaped PreToolUse deny, or None."""
    decision = out.get("hookSpecificOutput") if isinstance(out, dict) else None
    if isinstance(decision, dict) and decision.get("permissionDecision") == "deny":
        reason = decision.get("permissionDecisionReason")
        return reason if isinstance(reason, str) and reason else "plainspoken: blocked"
    return None


def session_cwd(ctx) -> str:
    """The session's working folder: Hermes runs plugins in a host process whose own folder isn't the project, so
    ask the session (`ctx.session_cwd()`), then the terminal's configured folder, then this process's."""
    try:
        cwd = ctx.session_cwd()
    except Exception:
        cwd = None
    if isinstance(cwd, str) and cwd.strip():
        return cwd
    return os.environ.get("TERMINAL_CWD") or os.getcwd()


def data_dir(ctx) -> Path:
    """Where the kaizen nudge keeps its once-per-session state: the profile's `plugin-data/<plugin>` folder, as
    Hermes gives a portable plugin (`ctx.state.data_dir`), else the same path under HERMES_HOME."""
    try:
        found = ctx.state.data_dir
        if isinstance(found, (str, os.PathLike)):
            return Path(found)
    except Exception:
        pass
    return Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser() / "plugin-data" / "plainspoken"


def tell(ctx, text: str) -> bool:
    """Show `text` to the person, never to the model: one message in the current conversation (`ctx.post_message`).
    Where Hermes refuses that (no conversation bound, no gateway, or `plugins.isolation: host`), the text goes to
    Hermes' log instead. Never raises."""
    try:
        handle = ctx.post_message(text)
        if getattr(handle, "ok", False):
            return True
        why = getattr(handle, "error", None) or "refused"
    except Exception as e:
        why = type(e).__name__
    logger.warning("plainspoken: couldn't post a message (%s): %s", why, text)
    return False


def edit_paths(tool_name: str, args: dict) -> list[str]:
    """The files a write_file or patch call changed: its `path`, or the `*** Update/Add File:` headers of a V4A
    patch (mode "patch")."""
    if not isinstance(args, dict):
        return []
    if tool_name == "patch" and args.get("mode") == "patch" and isinstance(args.get("patch"), str):
        common = _load("_plainspoken_hook_common", ROOT / "hooks" / "_common.py")
        events = common.edited_events({"tool_name": "apply_patch", "cwd": os.environ.get("TERMINAL_CWD") or os.getcwd(),
                                       "tool_input": {"command": args["patch"]}})
        return [e["tool_input"]["file_path"] for e in events]
    path = args.get("path")
    return [str(Path(path).expanduser())] if isinstance(path, str) and path else []


def _skill_files() -> list[Path]:
    skills = ROOT / "skills"
    found = sorted(p for p in skills.glob("*/SKILL.md") if p.is_file())
    if not found:
        # A bootstrap that skips quietly is how a broken install passes for a working one.
        raise RuntimeError(f"plainspoken: no skills under {skills}. Reinstall with "
                           "`hermes plugins install littlebearapps/plainspoken --enable`.")
    return found


def _description(skill_md: Path, load) -> str:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return ""
    block = text.split("\n---", 1)[0].split("\n", 1)[1] if "\n" in text else ""
    return str(load(block).get("description") or "")


def bootstrap() -> str:
    return (f"<!-- {BOOTSTRAP_MARKER} -->\n"
            f"plainspoken (writing skills: check, humanize, write, plain-language, voice and others) is installed. "
            f"Its plugin root is `{ROOT}`. Before you use any plainspoken skill, read `{ROOT}/hosts/hermes.md` once: "
            f"the skills are written for Claude Code and that note says how to run them here.")


def register(ctx):
    load = _frontmatter_loader()
    for skill_md in _skill_files():
        # register_skill needs a pathlib.Path (a str disables the whole plugin) and the description (without it the
        # skill shows blank in the list and the model can't pick it).
        ctx.register_skill(skill_md.parent.name, skill_md, description=_description(skill_md, load))

    text = bootstrap()
    nudge = _load("_plainspoken_nudge", ROOT / "hooks" / "nudge.py")
    guard_markers = _load("_plainspoken_write_guard", ROOT / "hooks" / "write_guard.py")._MARKERS

    def pre_llm_call(is_first_turn=None, user_message=None, session_id=None, **kwargs):
        # A pre_llm_call return is Hermes' documented way to add context; it's appended to this turn's user message.
        # The first turn gets the pointer to hosts/hermes.md; any turn that asks for writing gets the optional nudge
        # (off unless [nudge] mode = "on" in the project's or the user-wide config).
        parts = [text] if is_first_turn else []
        if nudge.intent(user_message):
            # Hermes runs plugins in a host process whose working folder isn't the user's project, so the
            # user-wide config (`setup --host hermes --scope user`) is what usually turns the nudge on here.
            line = _run_hook("nudge.py", {"hook_event_name": "UserPromptSubmit", "prompt": user_message,
                                          "cwd": os.environ.get("TERMINAL_CWD") or os.getcwd(),
                                          "session_id": session_id}, "--host", "hermes", quiet=True)
            if line:
                parts.append(line)
        return {"context": "\n\n".join(parts)} if parts else None

    def transform_tool_result(tool_name=None, args=None, result=None, session_id=None, **kwargs):
        # After write_file or patch: the lint-watch and integrity hooks, appended to the tool result the model reads.
        # A block-mode integrity reply comes back as a warning, and a hook that couldn't run says so. None keeps
        # the result as it is.
        if tool_name not in EDIT_TOOLS or not isinstance(result, str):
            return None
        lines = []
        for path in edit_paths(tool_name, args):
            # The project is found from the file's own folder (its nearest .plainspoken/config.toml or .git): the
            # plugin host's working folder isn't the user's.
            event = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": session_id or "hermes",
                     "cwd": str(Path(path).parent), "tool_input": {"file_path": path}}
            lines += [line for script in ("lint_watch.py", "integrity.py") if (line := _run_hook(script, event))]
        return result + "\n\n" + "\n".join(lines) if lines else None

    def pre_tool_call(tool_name=None, args=None, session_id=None, **kwargs):
        # Before a terminal command: the publish gate (a git push needs a current PASS for each gated file) and the
        # write guard (reply files and the claims ledger are never written through the shell). A deny becomes
        # Hermes' block, whose message is the tool result the model reads. A warn goes to the person only and the
        # command runs (not "approve", which would turn every warned push into a prompt). Hermes blocks the call
        # when a callback raises, so nothing here may.
        try:
            command = args.get("command") if tool_name == SHELL_TOOL and isinstance(args, dict) else None
            if not isinstance(command, str) or not command.strip():
                return None
            workdir = args.get("workdir")
            cwd = workdir if isinstance(workdir, str) and workdir.strip() else session_cwd(ctx)
            event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": session_id or "hermes",
                     "cwd": str(Path(cwd).expanduser()), "tool_input": {"command": command}}
            blocks = []
            if "push" in command or "git" in command:  # publish_gate.py's own fast exit, without the process
                out = _hook_output("publish_gate.py", event, "--host", "hermes")
                if reason := _deny_reason(out):
                    blocks.append(reason)
                elif isinstance(out, dict) and isinstance(out.get("systemMessage"), str):
                    tell(ctx, out["systemMessage"])
            if any(m in command for m in guard_markers):  # write_guard.py's own fast exit
                if reason := _deny_reason(_hook_output("write_guard.py", event, "--host", "hermes",
                                                       timeout=GUARD_TIMEOUT)):
                    blocks.append(reason)
            return {"action": "block", "message": "\n\n".join(blocks)} if blocks else None
        except Exception:
            return None

    def on_session_end(session_id=None, **kwargs):
        # Fires at the end of every turn, despite the name. The kaizen nudge: one line for the person when kaizen
        # proposals wait or calibrate is due, each at most once per session, posted, never put in the model's
        # context. Its return is ignored.
        try:
            if not session_id:
                return None
            env = {**os.environ}
            env.setdefault("CLAUDE_PLUGIN_DATA", str(data_dir(ctx)))
            out = _hook_output("kaizen_nudge.py", {"hook_event_name": "Stop", "session_id": str(session_id),
                                                   "cwd": session_cwd(ctx)},
                               "--host", "hermes", timeout=NUDGE_TIMEOUT, env=env)
            if isinstance(out, dict) and isinstance(out.get("systemMessage"), str):
                tell(ctx, out["systemMessage"])
        except Exception:
            pass
        return None

    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("transform_tool_result", transform_tool_result)
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("on_session_end", on_session_end)
