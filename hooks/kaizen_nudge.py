"""Stop hook: a one-line kaizen nudge for the person, never context for Claude.

It says something only when the project has a kaizen ledger and either some stored proposals await a decision, or
calibrate is due (no calibrate in 30 days and at least 50 distinct events since the last one). Each message is shown
at most once per session (state in CLAUDE_PLUGIN_DATA, as lint-watch keeps it). Output is only ever
`{"systemMessage": …}`. It reads the ledger and the proposal store, writes neither, never blocks and always exits 0.
`--host codex` writes the command as Codex's `$plainspoken:kaizen`, `--host hermes` as `plainspoken:kaizen`
(nudge.py's host map). Hermes runs it from the plugin's `on_session_end` and posts the message itself.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402

STATE = "kaizen-nudge-state.json"


def _root(event: dict) -> Path:
    return _common.kaizen_root(event)  # the ledger `check` and `kaizen` use


def main(argv: list[str]) -> int:
    host = argv[argv.index("--host") + 1] if "--host" in argv[:-1] else "claude-code"
    event = _common.read_event(sys.stdin)
    if not event:
        return 0
    root = _root(event)
    if not (root / ".plainspoken").is_dir():
        return 0  # fast exit: no plainspoken folder, so no ledger
    data = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or root / ".plainspoken")
    session = str(event.get("session_id"))
    shown = _common.read_state(data, STATE)
    if all(shown.get(f"{session}|{key}") == "shown" for key in ("review", "calibrate")):
        return 0  # both said already this session: don't read the ledger again
    from plainspoken import config, kaizen, ledger, proposals
    from nudge import _skill
    command = _skill(host, "kaizen")
    settings = config.kaizen_settings(root, os.environ)
    if not Path(settings["ledger_dir"]).is_dir():
        return 0
    events, _ = ledger.read(settings)
    messages = []
    if shown.get(f"{session}|review") != "shown":
        waiting = len(proposals.pending(settings, events))
        if waiting:
            messages.append(("review", f"plainspoken: {waiting} kaizen proposal(s) await a decision — "
                                       f"{command} review"))
    if shown.get(f"{session}|calibrate") != "shown":
        due = kaizen.calibrate_due(events, settings, datetime.now(timezone.utc))
        if due is not None:
            why = (f"{due} events, and it has never run" if kaizen.last_calibrated(events, settings) is None
                   else f"{due} new events since the last one")
            messages.append(("calibrate", f"plainspoken: kaizen calibrate is due ({why}) — "
                                          f"{command} calibrate"))
    if not messages:
        return 0
    for key, _ in messages:
        _common.record_state(data, STATE, f"{session}|{key}", "shown")
    print(json.dumps({"systemMessage": "\n".join(text for _, text in messages)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:  # a nudge must never break a turn
        sys.exit(0)
