"""What a hook prints, per host, so a finding reaches the person and the model the way each host allows. Shared by
the tool-call check (#124) and the chat-reply check (#125).

- `pre_tool(host, …)`: a PreToolUse reply. `person` is one line for the person (`systemMessage`; Hermes posts it with
  `tell`); `model` is a note for the model (`additionalContext`, which Claude Code and Codex put next to the tool's
  result, so after the call has run); `decision` is `deny` (the reason goes to the model, and the call doesn't run)
  or `ask` (Claude Code only: the reason goes to the person, who decides).
- `notice(text)`: a line for the person only, from any hook event (`systemMessage`).
- `skill_ref(host, name)`: how a skill is named on each host.

It never writes `allow`, `updatedInput` or anything that rewrites a call: Codex fails a hook that sends `allow`
without `updatedInput` and drops its context, and plainspoken never changes what a person or model sends.
Stdlib only.
"""
from __future__ import annotations

from plainspoken._util import clip

HOSTS = ("claude-code", "codex", "hermes")
DECISIONS = ("deny", "ask")
LIMIT = 4000  # under Codex's ~2,500-token spill point and Claude Code's 10,000-character cap


def skill_ref(host: str, name: str) -> str:
    return {"claude-code": f"/plainspoken:{name}", "codex": f"$plainspoken:{name}"}.get(host, f"plainspoken:{name}")


def pre_tool(host: str, *, person: str | None = None, model: str | None = None, decision: str | None = None,
             reason: str | None = None, event: str = "PreToolUse") -> dict | None:
    """The reply object, or None when there's nothing to say. `ask` is refused off Claude Code (Codex fails the
    hook; Hermes has no person-facing prompt that fails open), so callers map it to `deny` first."""
    if decision is not None and decision not in DECISIONS:
        raise ValueError(f"unknown decision {decision!r}")
    if decision == "ask" and host != "claude-code":
        raise ValueError(f"{host} has no ask: send deny (block-once) instead")
    out: dict = {}
    if person:
        out["systemMessage"] = clip(person, LIMIT)
    specific: dict = {}
    if decision is not None:
        specific["permissionDecision"] = decision
        specific["permissionDecisionReason"] = clip(reason or "plainspoken: held back", LIMIT)
    elif model:
        specific["additionalContext"] = clip(model, LIMIT)
    if specific:
        out["hookSpecificOutput"] = {"hookEventName": event, **specific}
    return out or None


def notice(text: str) -> dict:
    return {"systemMessage": clip(text, LIMIT)}
