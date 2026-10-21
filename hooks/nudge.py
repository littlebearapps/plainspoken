"""UserPromptSubmit (Claude Code, Codex) and Hermes' pre_llm_call: an optional nudge when a prompt asks for writing.

Off by default: on only when the project's `[nudge] mode`, the user-wide file's, or the Claude Code option `nudge`
says so (`config.nudge_mode`). When a prompt asks to draft something for people to read (an email, a text, a post, a
script, a page) or to make text sound like a person wrote it, one short context line names the plainspoken step that
fits. It never claims a check ran, never blocks, and stays silent on chat, code, slash commands and anything already
naming plainspoken. Silent on any error.

`--host codex` switches the command syntax to Codex's `$plainspoken:<skill>`. Hermes imports `intent` and
`nudge_text` directly (`.hermes-plugin/__init__.py`)."""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOSTS = ("claude-code", "codex", "hermes")
LIMIT = 520
EDGE = 600  # the ask sits at the start or the end of a prompt; a long paste in the middle isn't read

_CONTENT = (r"e-?mails?|texts?|sms|messages?|repl(?:y|ies)|posts?|tweets?|threads?|captions?|linkedin|bluesky|"
            r"instagram|facebook|tiktok|youtube|mastodon|newsletters?|blog(?: posts?)?|articles?|pages?|copy|bios?|"
            r"scripts?|podcasts?|videos?|voice-?overs?|pamphlets?|flyers?|brochures?|press releases?|speech(?:es)?|"
            r"letters?|announcements?|ads?|adverts?|intros?|outros?|descriptions?|summar(?:y|ies) for|updates?|"
            r"release notes|newsletter items?")
_NOUN = re.compile(rf"\b(?:{_CONTENT})\b", re.I)
_DRAFT_VERB = re.compile(r"\b(?:draft|write|compose|put together|prepare|come up with|help me (?:word|write|phrase|"
                         r"say|reply|respond))\b", re.I)
_REWRITE_VERB = re.compile(r"\b(?:re-?write|re-?word|re-?draft|polish|tidy up|clean up|punch up|tighten)\b", re.I)
_STRONG_REWRITE = re.compile(
    r"\bhumani[sz]e\b|\bde-?ai\b"
    r"|\bsounds?\b[^.?!\n]{0,20}\blike (?:a |an )?(?:real )?(?:person|human|people)\b"
    r"|\b(?:sounds?|reads?|written)\b[^.?!\n]{0,12}\b(?:like|as if|by) (?:a |an )?(?:bot|robot|ai|chatgpt|gpt|"
    r"machine|llm)\b"
    r"|\bless (?:like )?(?:chatgpt|gpt|ai|an ai|a bot|robotic|stiff|formal|corporate|salesy|wooden)\b"
    r"|\b(?:sound|read)s? (?:more )?(?:natural|human)\b", re.I)
_CODE = re.compile(r"\b(?:python|javascript|typescript|bash|shell|sql|regex|function|bug|unit tests?|"
                   r"code|commit message|docstring|json|yaml|stack ?trace)\b|\w\.(?:py|js|ts|sh|rb|go)\b", re.I)


def intent(prompt: str) -> str | None:
    """'rewrite', 'draft' or None for one user prompt."""
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    if prompt.lstrip().startswith("/") or re.search(r"\bplainspoken\b", prompt, re.I):
        return None
    text = prompt if len(prompt) <= 2 * EDGE else prompt[:EDGE] + "\n" + prompt[-EDGE:]
    if _STRONG_REWRITE.search(text):
        return "rewrite"
    if _CODE.search(text) or not _NOUN.search(text):
        return None
    if _REWRITE_VERB.search(text):
        return "rewrite"
    if _DRAFT_VERB.search(text):
        return "draft"
    return None


def _skill(host: str, name: str) -> str:
    return {"claude-code": f"/plainspoken:{name}", "codex": f"$plainspoken:{name}"}.get(host, f"plainspoken:{name}")


def nudge_text(kind: str, host: str, root: str | Path, profile: str) -> str:
    """The one line for this kind of ask on this host. Short drafts are linted on stdin; long or outgoing pieces get
    the full check; rewrites go through humanize. Remove, never add."""
    lint = f"`python3 {root}/lib/run.py check - --plugin-profile '{profile}'`"
    if kind == "rewrite":
        text = (f"plainspoken: this asks for text that sounds like a person wrote it. Use {_skill(host, 'humanize')} "
                f"(remove the AI patterns, never add facts), then pipe the result to {lint} and cut what it flags.")
    else:
        text = (f"plainspoken: this asks for writing people will read. Short piece: draft it, pipe it to {lint} and "
                f"cut what it flags (remove, never add facts). Long or going out: save it and run "
                f"{_skill(host, 'check')}.")
    return text[:LIMIT]


def main(argv: list[str]) -> int:
    host = argv[argv.index("--host") + 1] if "--host" in argv[:-1] else "claude-code"
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0
    kind = intent(event.get("prompt"))
    if kind is None:
        return 0
    sys.path.insert(0, str(ROOT / "lib"))
    from plainspoken import config
    project = (Path(os.environ["CLAUDE_PROJECT_DIR"]) if os.environ.get("CLAUDE_PROJECT_DIR")
               else config.project_root(Path(event.get("cwd") or ".")))
    if config.nudge_mode(project, os.environ) != "on":
        return 0
    profile = os.environ.get("CLAUDE_PLUGIN_OPTION_PROFILE") or "default"
    text = nudge_text(kind, host if host in HOSTS else "claude-code", ROOT, profile)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:  # optional: never block a prompt
        sys.exit(0)
