"""PreToolUse write guard: the files an agent writes with the Write or Edit tool are never written through the shell.

Two kinds: an isolated agent's reply (`<key>.reply.json` for check's judges, `<key>.claims-reply.json`,
`<key>.delivery-reply.json`), which the record step reads verbatim, and the claims ledger (`*.claims.toml`,
`*.claims.json`), which the claims skill edits one claim at a time so each claim's five binding judgements are set
after reading its pinned passage, not in a loop. Claude Code's own shell check stops JSON in a heredoc, but not
`printf '…' > reply` or a script that writes the ledger (#44).

Refused, when the command names one of those files: a write redirection to it (a variable assigned its path is
followed), `tee`, `truncate`, a `cp`/`mv`/`install`/`ln`/`rsync` destination, `dd of=`, `sed -i`/`perl -i`, a
heredoc that holds a script that writes it, and a command the lexer can't parse. An interpreter that isn't
plainspoken's own CLI (`run.py`, `-m plainspoken`) is refused when its program names one (or the command does) and
writes files: inline code (`python3 -c`, `bash -c`, `node -e`), a heredoc or here-string on stdin, or a script run
by name (`python3 build.py`, `bash x.sh`, `./x.py`), whose file is read from the event's cwd (#57). A shell program
is followed command by command; other code counts as writing when it calls `open(…, 'w')`, `write_text`,
`json.dump(…, open(…, 'w'))`, `writeFile`, `subprocess`, `os.system` and the like. A program the guard can't see (a
missing script, `-m module`) is refused only when the command itself names a protected file.

Reading (`cat`, `python3 -c` that only loads the ledger), `git`, `rm` and the CLI's `--from` stay allowed. A
guardrail against a habit, not a security boundary: code that builds the path from parts, or a script piped in, isn't
seen.

Always on and cheap: a command without `reply.json`, `.claims.` or a script name exits before anything beyond
sys/json is imported. Any error of its own is silent (exit 0), so it never blocks an unrelated Bash call.
`--host codex` names apply_patch, Codex's file-writing tool, in the deny; `--host hermes` names write_file and patch."""
import json
import os
import sys

_MARKERS = ("reply.json", ".claims.", ".py", ".sh", ".bash", ".js", ".rb", ".pl", ".php")  # a script may name one


def _deny(path: str, why: str, host: str = "claude-code") -> None:
    tool, write, edit = {
        "codex": ("apply_patch", "Write its JSON object to that path with apply_patch",
                  "Edit one claim at a time with apply_patch"),
        "hermes": ("write_file or patch", "Write its JSON object to that path with write_file",
                   "Edit one claim at a time with patch"),
    }.get(host, ("the Write or Edit tool", "Write its JSON object to that path", "Edit one claim at a time"))
    reason = (f"plainspoken: {path} is written with {tool}, never through the shell ({why}). A reply: {write}, then "
              f"run the record command with --from. The claims ledger: {edit}, setting its five binding judgements "
              "after reading its pinned passage. To read one, use cat, or code that only reads it.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))


def main(argv: list[str]) -> int:
    host = argv[argv.index("--host") + 1] if "--host" in argv[:-1] else "claude-code"
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    tool_input = event.get("tool_input") if isinstance(event, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not any(m in command for m in _MARKERS):
        return 0
    try:
        hooks = os.path.dirname(os.path.realpath(__file__))
        if hooks not in sys.path:
            sys.path.insert(0, hooks)
        import _writeguard
        cwd = event.get("cwd")
        found = _writeguard.problem(command, cwd if isinstance(cwd, str) else None)
    except Exception:  # noqa: BLE001 - never block an unrelated Bash call on a bug here
        return 0
    if found is not None:
        _deny(*found, host)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
