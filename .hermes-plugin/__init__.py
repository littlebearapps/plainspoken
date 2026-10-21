"""plainspoken for Hermes Agent: registers the plugin's skills and tells the model where the plugin lives.

Install: `hermes plugins install littlebearapps/plainspoken --enable`, then start a new session. Hermes ignores
`.claude-plugin/`, so this folder is the Hermes entry point; the skills, agents and engine are the same files Claude
Code and Codex use. How the skills run here (paths, the judges as one-shot `hermes chat` processes, what's missing):
`hosts/hermes.md`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_MARKER = "plainspoken plugin for hermes"
EDIT_TOOLS = ("write_file", "patch")  # Hermes' file-writing tools; lint-watch and integrity run after each
HOOK_TIMEOUT = 15


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter_loader():
    # The engine's own YAML-subset reader, loaded by path so nothing is added to sys.path.
    return _load("_plainspoken_frontmatter", ROOT / "lib" / "plainspoken" / "frontmatter.py").load


def _run_hook(script: str, event: dict, *args: str) -> str | None:
    """Run one of plainspoken's hook scripts (the same ones Claude Code and Codex run) on a Claude-shaped event and
    return its context line, or None. Never raises: the hooks are optional."""
    try:
        done = subprocess.run([sys.executable, str(ROOT / "hooks" / script), *args], input=json.dumps(event),
                              capture_output=True, text=True, timeout=HOOK_TIMEOUT, cwd=event.get("cwd") or None)
        out = json.loads(done.stdout) if done.stdout.strip() else None
        return out["hookSpecificOutput"]["additionalContext"] if out else None
    except Exception:
        return None


def edit_paths(tool_name: str, args: dict) -> list[str]:
    """The files a write_file or patch call changed: its `path`, or the `*** Update/Add File:` headers of a V4A
    patch (mode "patch")."""
    if not isinstance(args, dict):
        return []
    if tool_name == "patch" and args.get("mode") == "patch" and isinstance(args.get("patch"), str):
        common = _load("_plainspoken_hook_common", ROOT / "hooks" / "_common.py")
        events = common.edited_events({"tool_name": "apply_patch", "cwd": os.getcwd(),
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

    def pre_llm_call(is_first_turn=None, user_message=None, session_id=None, **kwargs):
        # A pre_llm_call return is Hermes' documented way to add context; it's appended to this turn's user message.
        # The first turn gets the pointer to hosts/hermes.md; any turn that asks for writing gets the optional nudge
        # (off unless [nudge] mode = "on" in the project's or the user-wide config).
        parts = [text] if is_first_turn else []
        if nudge.intent(user_message):
            line = _run_hook("nudge.py", {"hook_event_name": "UserPromptSubmit", "prompt": user_message,
                                          "cwd": os.getcwd(), "session_id": session_id}, "--host", "hermes")
            if line:
                parts.append(line)
        return {"context": "\n\n".join(parts)} if parts else None

    def transform_tool_result(tool_name=None, args=None, result=None, session_id=None, **kwargs):
        # After write_file or patch: the lint-watch and integrity hooks, appended to the tool result the model reads.
        # None keeps the result as it is.
        if tool_name not in EDIT_TOOLS or not isinstance(result, str):
            return None
        lines = []
        for path in edit_paths(tool_name, args):
            event = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": session_id or "hermes",
                     "cwd": os.getcwd(), "tool_input": {"file_path": path}}
            lines += [line for script in ("lint_watch.py", "integrity.py") if (line := _run_hook(script, event))]
        return result + "\n\n" + "\n".join(lines) if lines else None

    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("transform_tool_result", transform_tool_result)
