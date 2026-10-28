"""Stop hook: send a write report back once when it asks the owner to check something its `needs the owner` lines
don't list (issue #75).

Write's step 8 allows no such ask: a line worth the owner's check is held `blocking` in the claims ledger, so
`status` lists it, or it's cut. The hook reads the turn's last message (`last_assistant_message`), and only a message
that carries the `status` block with nothing listed is read at all (lib/plainspoken/owner_asks.py). On a hit it
prints a block decision whose reason quotes each ask and says to cut the line or hold it `blocking`, so Claude
carries on and reports again. It never sends a report back twice in a row (`stop_hook_active`), keeps no state,
writes no file and fails open: any problem is exit 0 with nothing printed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402

MARKER = "needs the owner:"


def main() -> int:
    event = _common.read_event(sys.stdin)
    if not event or event.get("stop_hook_active") is True:
        return 0  # the turn this hook already sent back gets to stop, whatever it says
    text = event.get("last_assistant_message")
    if not isinstance(text, str) or MARKER not in text:
        return 0  # fast exit: not a write report
    from plainspoken import owner_asks  # _common puts lib/ on sys.path
    asks = owner_asks.unlisted(text)
    if asks:
        print(json.dumps({"decision": "block", "reason": owner_asks.message(asks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # a guard on the report must never break a turn
        sys.exit(0)
