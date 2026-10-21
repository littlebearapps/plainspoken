"""SessionStart / SubagentStart: an optional writing brief of at most 800 characters, and the optional drafting rule.

Both are off by default. The brief is on when .plainspoken/config.toml has [brief] enabled = true. The drafting rule
(data/drafting-rule.md: use plainspoken whenever something people will read is drafted) is on when the project's
`[rule] enabled`, the user-wide file's, or the Claude Code option `rule` says so (`config.rule_enabled`); it's added at
SessionStart only, with this install's plugin root filled in, so it never points at an old version's path. Never for
plainspoken's own agents, so the judges and the cold reader stay isolated. Silent on any error: both are optional, and
lint-watch and the gate report config problems. The fast path imports only json, os and sys."""
import json
import os
import sys

OWN_AGENTS = "plainspoken:"
LIMIT = 800
RULE_LIMIT = 1200


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
    has_project = os.path.isfile(os.path.join(project, ".plainspoken", "config.toml"))
    user_dir = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    may_rule = name == "SessionStart" and (
        has_project or os.path.isfile(os.path.join(user_dir, "plainspoken", "config.toml"))
        or os.environ.get("CLAUDE_PLUGIN_OPTION_RULE", "").strip().lower() == "true")
    if not (has_project or may_rule):
        return 0
    parts = []
    try:
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / "lib"))
        from plainspoken import config
        if may_rule and config.rule_enabled(Path(project)):
            parts.append(rule_text(root, os.environ.get("CLAUDE_PLUGIN_OPTION_PROFILE") or "default"))
        if has_project and config.brief_enabled(Path(project)):
            parts.append(fit((root / "data" / "brief.md").read_text(encoding="utf-8").strip(), LIMIT))
    except Exception:
        return 0
    if parts:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": "\n\n".join(parts)}}))
    return 0


def rule_text(root, profile: str) -> str:
    """The drafting rule with this install's paths and Claude Code's skill syntax filled in."""
    text = (root / "data" / "drafting-rule.md").read_text(encoding="utf-8").strip()
    filled = (text.replace("{root}", str(root)).replace("{profile}", profile)
              .replace("{check}", "/plainspoken:check").replace("{humanize}", "/plainspoken:humanize"))
    return fit(filled, RULE_LIMIT)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
