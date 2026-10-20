"""PostToolUse (SubagentHandback) and SubagentStop backstop: count each plainspoken agent run once.

When a `plainspoken:*` agent hands back its report or stops, it logs one `agent_handback` friction line,
`{kind: "agent_handback", source: <agent_type>, detail: ""}`, per `agent_id` (state in CLAUDE_PLUGIN_DATA), so a
handback and the SubagentStop that follows it count once. `kaizen report` compares the judge runs counted here with
the judge replies `judge-record` accepted. The reply itself is never stored: replies carry the article's hash but not
its path, so they can't be tied to a document here.

It needs an existing kaizen ledger folder (it never creates one), prints nothing and always exits 0. It counts nothing
when `judge` is left out of `[kaizen] capture_sources` (the judge replies aren't captured either).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402

STATE = "kaizen-backstop-state.json"
PREFIX = "plainspoken:"


def main() -> int:
    event = _common.read_event(sys.stdin)
    if not event:
        return 0
    agent_type, agent_id = event.get("agent_type"), event.get("agent_id")
    if not (isinstance(agent_type, str) and agent_type.startswith(PREFIX) and len(agent_type) > len(PREFIX)):
        return 0
    if not (isinstance(agent_id, str) and agent_id):
        return 0  # without an id it can't be counted once, so it isn't counted
    root = _common.kaizen_root(event)  # the ledger `check` and `kaizen` use
    if not (root / ".plainspoken").is_dir():
        return 0  # fast exit: no plainspoken folder, so no ledger
    from plainspoken import capture, config, ledger
    settings = config.kaizen_settings(root, os.environ)
    if not capture.source_on(settings, "judge") or not Path(settings["ledger_dir"]).is_dir():
        return 0
    data = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or root / ".plainspoken")
    if _common.record_state(data, STATE, agent_id, "logged") == "logged":
        return 0
    ledger.friction("agent_handback", agent_type, "", settings)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # a backstop must never break a subagent
        sys.exit(0)
