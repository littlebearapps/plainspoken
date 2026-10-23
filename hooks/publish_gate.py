"""PreToolUse publish gate (opt-in): `git push` needs a current PASS for every pushed file in [gate] paths.

strictness: watch = off · warn = a warning message, push goes ahead · block = deny. It comes from `[gate] strictness`
in .plainspoken/config.toml, else the plugin option, else watch (lib/plainspoken/config.py gate_strictness). A config
it can't use gives a warning and the push goes ahead, unless block is known (the file's own readable strictness, else
the plugin option): someone who never opted in to block is never denied (config.gate_strictness_safe). Registered
without onFailure (an opt-in gate must not block every Bash call if python3 is missing); once block is known every
error here is a deny, never a traceback.

Registered without an `if` filter (docs/claude-code-facts.md section 6): the harness filter misses `env git push` and
`sudo git push`. So the first lines below exit fast, using only sys/os/json, for any command without the word "push"
or "git" (git aliases can hide a push), and for watch mode when the project has no config file.

`--host codex` writes the check command in the message as Codex's `$plainspoken:check`, and `--host hermes` as
Hermes' `plainspoken:check` (nudge.py's host map)."""
import json
import os
import sys

_HOOKS = os.path.dirname(os.path.realpath(__file__))
if _HOOKS not in sys.path:  # once, at import: main() may run more than once in one process (the tests)
    sys.path.insert(0, _HOOKS)


def _decide(strictness: str, problems: list[str], host: str = "claude-code") -> None:
    if not problems:
        return
    from _common import clip
    from nudge import _skill
    msg = clip(("plainspoken gate: " + "; ".join(problems)).replace("/plainspoken:", _skill(host, "")))
    if strictness == "block":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": msg}}))
    else:
        print(json.dumps({"systemMessage": msg}))


def main(argv: list[str] = ()) -> int:
    argv = list(argv)
    host = argv[argv.index("--host") + 1] if "--host" in argv[:-1] else "claude-code"
    env_strictness = (os.environ.get("CLAUDE_PLUGIN_OPTION_STRICTNESS") or "watch").strip()
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        event = None
    command = None
    if isinstance(event, dict):
        tool_input = event.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else ""
        if not isinstance(command, str) or ("push" not in command and "git" not in command):
            return 0
        cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    else:
        cwd = None
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or cwd or "."
    has_config = os.path.isfile(os.path.join(project_dir, ".plainspoken", "config.toml"))
    if not has_config and env_strictness not in ("warn", "block"):
        return 0
    # Until the settings are read, an error is a deny only for someone whose plugin option already says block.
    strictness = "block" if env_strictness == "block" else "warn"
    try:
        from pathlib import Path
        import _gate  # its _common import puts lib/ on sys.path
        from plainspoken import config
        project = config.project_root(Path(project_dir))
        strictness, _source, problem = config.gate_strictness_safe(project, os.environ)
        if problem is not None:
            if strictness != "watch" and (command is None or _gate.involves_push(command, project)):
                tail = [] if strictness == "block" else ["not checking this push"]
                _decide("block" if strictness == "block" else "warn",
                        [f"can't read the gate settings: {problem}", *tail], host)
            return 0
        if strictness not in ("warn", "block"):
            return 0
        if command is None:
            raise ValueError("hook input was not valid JSON")
        _decide(strictness, _gate.check(command, project, Path(cwd) if cwd else None), host)
    except Exception as e:
        _decide(strictness, [f"gate error: {type(e).__name__}: {e}"], host)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
