"""SessionStart / SubagentStart: an optional writing brief of at most 800 characters.

Off by default: on only when .plainspoken/config.toml has [brief] enabled = true. Never for plainspoken's own agents,
so the judges and the cold reader stay isolated. Silent on any error: the brief is optional, and lint-watch and the
gate report config problems. The fast path imports only json, os and sys."""
import json
import os
import sys

OWN_AGENTS = "plainspoken:"
LIMIT = 800


def fit(text: str, limit: int) -> str:
    """`text` when it fits in `limit` characters; else cut after the last sentence end (`.`, `!` or `?` before a space
    or the end) that fits, else at the last space, and only with neither at the limit itself."""
    if len(text) <= limit:
        return text
    ends = [i + 1 for i in range(limit) if text[i] in ".!?" and text[i + 1].isspace()]
    if ends:
        return text[:ends[-1]]
    space = text.rfind(" ", 0, limit + 1)
    return text[:space].rstrip() if space > 0 else text[:limit]


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0
    name = event.get("hook_event_name")
    if name not in ("SessionStart", "SubagentStart"):
        return 0
    if str(event.get("agent_type") or "").startswith(OWN_AGENTS):
        return 0
    project = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or "."
    if not os.path.isfile(os.path.join(project, ".plainspoken", "config.toml")):
        return 0
    try:
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / "lib"))
        from plainspoken import config
        if not config.brief_enabled(Path(project)):
            return 0
        text = fit((root / "data" / "brief.md").read_text(encoding="utf-8").strip(), LIMIT)
    except Exception:
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
