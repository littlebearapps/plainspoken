"""PreToolUse write guard: the files an agent writes with the Write or Edit tool are never written through the shell.

Two kinds: an isolated agent's reply (`<key>.reply.json` for check's judges, `<key>.claims-reply.json`,
`<key>.delivery-reply.json`), which the record step reads verbatim, and the claims ledger (`*.claims.toml`,
`*.claims.json`), which the claims skill edits one claim at a time so each claim's five binding judgements are set
after reading its pinned passage, not in a loop. Claude Code's own shell check stops JSON in a heredoc, but not
`printf '…' > reply` or a script that writes the ledger (#44).

Refused, when the command names one of those files: a write redirection to it (a variable assigned its path is
followed), `tee`, `truncate`, a `cp`/`mv`/`install`/`ln`/`rsync` destination, `dd of=`, `sed -i`/`perl -i`, an
interpreter (`python3 -c`, `bash -c`, `node`, …) that isn't plainspoken's own CLI (`run.py`, `-m plainspoken`), a
heredoc or here-string that holds the path (a script that writes it), and a command the lexer can't parse.
Reading, `git`, `rm` and the CLI's `--from` stay allowed. A guardrail against a habit, not a security boundary: a
script written earlier and run by name isn't seen.

Always on and cheap: a command without `reply.json` or `.claims.` exits before anything beyond sys/json is imported.
Any error of its own is silent (exit 0), so it never blocks an unrelated Bash call."""
import json
import os
import sys

_MARKERS = ("reply.json", ".claims.")


def _deny(path: str, why: str) -> None:
    reason = (f"plainspoken: {path} is written with the Write or Edit tool, never through the shell ({why}). A reply: "
              "Write its JSON object to that path, then run the record command with --from. The claims ledger: Edit "
              "one claim at a time, setting its five binding judgements after reading its pinned passage.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))


def main() -> int:
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
        found = _writeguard.problem(command)
    except Exception:  # noqa: BLE001 - never block an unrelated Bash call on a bug here
        return 0
    if found is not None:
        _deny(*found)
    return 0


if __name__ == "__main__":
    sys.exit(main())
