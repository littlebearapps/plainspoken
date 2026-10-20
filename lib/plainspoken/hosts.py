"""Self-contained agent prompts for hosts that can't load plugin agents (Codex, Hermes Agent).

Claude Code starts `agents/<name>.md` as an isolated subagent. Other hosts get the same instructions as one prompt:
the agent file's body (frontmatter dropped), then the opener the skill would have sent, then the input. The caller
runs it in a fresh process (`codex exec --sandbox read-only`, `hermes chat -q`), so the agent still never sees the
writer's session. See hosts/codex.md and hosts/hermes.md.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = ["AGENTS", "agent_prompt", "agent_reply", "agents_dir"]

# The opener each skill sends before the input (check step 3, claims step 6, reader-value step 4).
# cold-reader's input is already its whole prompt (two lines: Reader, File), so it has no opener.
AGENTS = {
    "tells-judge": "Judge this. Your input:",
    "claims-checker": "Check this. Your input:",
    "delivery-checker": "Review this. Your input:",
    "cold-reader": "",
}

_FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)


def agents_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "agents"


def agent_prompt(name: str, payload: str, line: int | None = None) -> str:
    """The prompt for agent `name` with `payload` as its input.

    `line` picks the Nth non-blank line of `payload` (1-based), for `judge-input`'s one-object-per-line output.
    Raises ValueError for an unknown agent, a missing line or an empty input.
    """
    if name not in AGENTS:
        raise ValueError(f"unknown agent {name!r} (known: {', '.join(AGENTS)})")
    lines = [ln for ln in payload.splitlines() if ln.strip()]
    if line is not None:
        if not 1 <= line <= len(lines):
            raise ValueError(f"--line {line} is out of range: the input has {len(lines)} non-blank line(s)")
        lines = [lines[line - 1]]
    if not lines:
        raise ValueError("empty input: pipe the agent's input in (e.g. from judge-input)")
    body = _FRONTMATTER.sub("", (agents_dir() / f"{name}.md").read_text(encoding="utf-8"), count=1).strip()
    opener = AGENTS[name]
    parts = [body, ""]
    if opener:
        parts.append(opener)
    parts.append("\n".join(lines))
    return "\n".join(parts) + "\n"


def agent_reply(text: str) -> str:
    """The JSON object in an agent's final output: its first `{` to its last `}`, as compact JSON.

    The same cut check step 4 tells Claude Code to make by hand, for host CLIs that print a session line or a code
    fence around the reply. It only cuts; judge-record and the other record steps still validate the object.
    Raises ValueError when there's no single JSON object.
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the agent's output")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("the agent's output is not one JSON object")
    return json.dumps(obj, ensure_ascii=False) + "\n"
