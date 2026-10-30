"""Stop hook: send a write report back once when it asks the owner to check something its `needs the owner` lines
don't list (issue #75).

Write's step 8 allows no such ask: a line worth the owner's check is held `blocking` in the claims ledger, so
`status` lists it, or it's cut. The hook reads the turn's last message (`last_assistant_message`), and only a message
that carries the `status` block is read at all. An ask about a claim the block lists is allowed; any other ask, a
decision handed to the owner ("cut it if you'd rather …") included, is caught (lib/plainspoken/owner_asks.py). On a hit it
prints a block decision whose reason quotes each ask and says to cut the line or hold it `blocking`, so Claude
carries on and reports again. A write turn whose last message leaves the block out (#171: 2 of 3 round-8
verification reports opened with prose) is sent back too, to start with it: the hook reads the turn in the
transcript (`transcript_path`) and acts only when that turn started the write skill and `status` printed the block.
It never sends a report back twice in a row (`stop_hook_active`), keeps no state, writes no file and fails open: any
problem is exit 0 with nothing printed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402


MISSING_BLOCK = ("plainspoken: this write report leaves out the status block. Start the report with it, with no "
                 "words before it: `Draft: <draft path>`, then every line `status` printed (check, claims and its "
                 "reasons, needs the owner, words, the reader-value contract), copied exactly. Then the rest of "
                 "the report, with figures and statuses as those lines give them (write step 8).")
SKILL_BASE = "Base directory for this skill:"
MAX_TRANSCRIPT = 50_000_000  # bytes: past this the turn isn't read (fail open)


def _turn(path) -> list[dict]:
    """The main thread's records since its last prompt from the person (subagent sidechains and tool results left
    out of that test), or [] when the transcript can't be read."""
    try:
        p = Path(path)
        if p.stat().st_size > MAX_TRANSCRIPT:
            return []
        records = [json.loads(line) for line in p.read_text(encoding="utf-8", errors="replace").splitlines()
                   if line.strip()]
    except (OSError, TypeError, ValueError):
        return []
    records = [r for r in records if isinstance(r, dict) and not r.get("isSidechain") and not r.get("parent_tool_use_id")]
    start = 0
    for i, r in enumerate(records):
        content = (r.get("message") or {}).get("content") if r.get("type") == "user" else None
        if r.get("isMeta") or _skill_body(content) is not None:
            continue  # a skill's instructions, loaded into the turn: not a prompt
        if isinstance(content, str) or (isinstance(content, list) and content and not any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content)):
            start = i
    return records[start:]


def _skill_body(content) -> str | None:
    """The skill folder named by a loaded skill's instructions ("Base directory for this skill: …/skills/write"), or
    None when this isn't one."""
    texts = [content] if isinstance(content, str) else [
        str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"
    ] if isinstance(content, list) else []
    for t in texts:
        if t.startswith(SKILL_BASE):
            return t[len(SKILL_BASE):].split("\n", 1)[0].strip()
    return None


def _write_turn_printed_block(path, marker: str) -> bool:
    """True when this turn started the write skill (its Skill call, or `/plainspoken:write` typed) and a tool result
    in it holds the `status` block's owner line, so the report was meant to carry the block."""
    started = printed = False
    for r in _turn(path):
        content = (r.get("message") or {}).get("content")
        body = _skill_body(content) if r.get("type") == "user" else None
        if body is not None:
            started = started or body.rstrip("/").endswith("/skills/write")
            continue
        if isinstance(content, str):
            started = started or "/plainspoken:write" in content
            continue
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") == "Skill":
                started = started or str((b.get("input") or {}).get("skill", "")) in ("plainspoken:write", "write")
            elif b.get("type") == "text" and r.get("type") == "user":
                started = started or "/plainspoken:write" in str(b.get("text", ""))
            elif b.get("type") == "tool_result":
                body = b.get("content")
                body = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
                printed = printed or any(line.lstrip().startswith(marker) for line in body.replace("\\n", "\n").splitlines())
    return started and printed


def main() -> int:
    event = _common.read_event(sys.stdin)
    if not event or event.get("stop_hook_active") is True:
        return 0  # the turn this hook already sent back gets to stop, whatever it says
    from plainspoken.reply import OWNER_MARKER  # _common puts lib/ on sys.path; the one definition of the marker
    text = event.get("last_assistant_message")
    if not isinstance(text, str):
        return 0
    if OWNER_MARKER not in text:
        if _write_turn_printed_block(event.get("transcript_path"), OWNER_MARKER):
            print(json.dumps({"decision": "block", "reason": MISSING_BLOCK}, ensure_ascii=False))
        return 0  # otherwise not a write report
    from plainspoken import owner_asks
    asks = owner_asks.unlisted(text)
    if asks:
        print(json.dumps({"decision": "block", "reason": owner_asks.message(asks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # a guard on the report must never break a turn
        sys.exit(0)
