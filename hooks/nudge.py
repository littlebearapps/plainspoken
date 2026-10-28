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
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOSTS = ("claude-code", "codex", "hermes")
LIMIT = 520
EDGE = 600  # the ask sits at the start or the end of a prompt; a long paste in the middle isn't read

# Kinds of writing people read. The generic ones (updates, pages, replies, descriptions, summaries) are mostly
# technical in this audience, so they count only with a person or audience next to them ("a reply to Sam") (#125).
_CONTENT = (r"e-?mails?|texts?|sms|messages?|posts?|tweets?|threads?|captions?|linkedin|bluesky|"
            r"instagram|facebook|tiktok|youtube|mastodon|newsletters?|blog(?: posts?)?|articles?|page|copy|bios?|"
            r"scripts?|podcasts?|videos?|voice-?overs?|pamphlets?|flyers?|brochures?|press releases?|speech(?:es)?|"
            r"letters?|announcements?|ads?|adverts?|intros?|outros?|blurbs?|paragraphs?|"
            r"release notes|newsletter items?|essays?|reports?|guides?|case stud(?:y|ies)|white ?papers?")
_GENERIC = r"repl(?:y|ies)|updates?|pages|descriptions?|summar(?:y|ies)"
_NOUN = re.compile(rf"\b(?:{_CONTENT}|{_GENERIC})\b", re.I)
_DRAFT_VERB = re.compile(r"\b(?:draft|write|compose|put together|prepare|come up with|help me (?:word|write|phrase|"
                         r"say|reply|respond))\b", re.I)
# The verb has to be the request itself: at the start of a sentence, a line or a clause, after nothing but a
# greeting, "please" or a "can you" / "I'd like you to" frame. "Does the hook run when I write emails" isn't an ask.
_LEAD = re.compile(
    r"(?:(?:please|pls|ok(?:ay)?|so|hey|hi|now|and|also|then|next|just|quick(?:ly)?|kindly|first|great|thanks|"
    r"cool|right|alright)\b[\s,!]*)*"
    r"(?:(?:can|could|would|will) (?:you|u)(?: (?:please|maybe|quickly|also|just))?(?: help me)?"
    r"|(?:i|we)(?: need| want| would like|['’]d like| d like)(?: (?:you|u) to)?|id like(?: you to)?"
    r"|help me|let['’]?s|go ahead and)?"
    r"[\s,]*(?:(?:please|just|quickly|also|now)\s+)*", re.I)
_BOUNDARY = re.compile(r"[.!?;:,\n()\[\]\"“”]|<[^<>]*>|(?:^|\s)[-*•>]\s")
# The noun has to be the verb's object: "write (me) a short email", not "write tests for the email extraction".
_DET = (r"(?:(?:me|us|up)\s+)?(?:(?:a few|a couple of|another|some|any|a|an|the|my|our|your|his|her|their|this|"
        r"that|these|those|one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+)?")
_BREAK = r"(?:when|whenever|if|that|which|who|for|how|why|what|where|whether|so|because|to|in|on|with|from)"
_PRE = rf"(?:[\"“”]?(?!{_BREAK}\b)[\w'’-]+[\"“”]?,?\s+){{0,3}}?"
_OBJECT = re.compile(rf"\s*{_DET}(?P<pre>{_PRE})(?P<noun>{_CONTENT})\b", re.I)
# Or the piece is named by where it goes: "a feature for our council newsletter", "a few lines for the parents' note".
_FOR_PIECE = re.compile(rf"\s*{_DET}(?P<pre>{_PRE})(?:for|in) (?:the |our |my |your |their |this |next |a |an )?"
                        rf"(?:[\w'’-]+\s+){{0,2}}?(?P<noun>{_CONTENT})\b"
                        rf"(?![ \t]+(?!(?:about|on|from|with|by|that|which|for|to|so|and)\b)[\w'’-])", re.I)
_GENERIC_OBJECT = re.compile(rf"\s*{_DET}(?P<pre>{_PRE})(?P<noun>{_GENERIC})\b", re.I)
# A tech object is a task, not writing for people: "write the docs page", "write a GitHub issue", "a page for the docs".
_TECH = (r"issues?|prs?|pull requests?|tests?|plans?|readmes?|docs?|documentation|hooks?|plugins?|config|configs|"
         r"changelogs?|specs?|github|api|cli|mcp|code|commits?|skills?|tickets?|schemas?|regex")
_TECH_WORD = re.compile(rf"\b(?:{_TECH})\b", re.I)
_PHRASE = re.compile(rf"\s*{_DET}((?:(?!{_BREAK}\b)[\w'’-]+,?\s*){{0,4}})", re.I)  # the first few words of an object
_TECH_DESTINATION = re.compile(rf"\s+(?:for|in|into|on|to)\s+(?:the |this |our |my |a |an )?(?:[\w-]+\s+)?"
                               rf"(?:{_TECH})\b", re.I)
_AUDIENCE = re.compile(
    r"[^.?!;\n]{0,30}?\b(?:to|for|with)\s+(?:the |my |our |your |his |her |their |this |that |a |an |all |every )?"
    r"(?:[\w'-]+\s+)?(?:parents?|customers?|clients?|members?|staff|team|students?|famil(?:y|ies)|volunteers?|"
    r"board|committee|landlord|boss|manager|colleagues?|users?|readers?|subscribers?|donors?|supporters?|"
    r"followers?|guests?|patients?|tenants?|neighbou?rs?|community|class|school|council|everyone|them|him|her|"
    r"people|[A-Z][a-z]+(?![\w-]* (?:" + _TECH + r")\b))")
_REWRITE_VERB = re.compile(r"\b(?:re-?write|re-?word|re-?draft|polish|tidy up|clean up|punch up|tighten)\b", re.I)
_STRONG_REWRITE = re.compile(
    r"\bhumani[sz]e\b|\bde-?ai\b"
    r"|\bsounds?\b[^.?!\n]{0,20}\blike (?:a |an )?(?:real )?(?:person|human|people)\b"
    r"|\b(?:sounds?|reads?|written)\b[^.?!\n]{0,12}\b(?:like|as if|by) (?:a |an )?(?:bot|robot|ai|chatgpt|gpt|"
    r"machine|llm)\b"
    r"|\bless (?:like )?(?:chatgpt|gpt|ai|an ai|a bot|robotic|stiff|formal|corporate|salesy|wooden)\b"
    r"|\b(?:sound|read)s? (?:more )?(?:natural|human)\b", re.I)
# Long-form cues go to the write skill (draft, check, fix): a stated size of about 250 words or more (or a few
# paragraphs, or two pages), a kind that's long by nature, or sources to research. The size of the piece decides, never
# its type alone: a newsletter note, press release, pamphlet or page from a handful of facts is short (#37).
_LONG = re.compile(
    r"\b(?:2[5-9][0-9]|[3-9][0-9]{2}|[1-9],?[0-9]{3,})\s*(?:-\s*)?words?\b"
    r"|\b(?:a few|several|many|multiple|[3-9]|three|four|five|six|seven|eight|nine|ten) paragraphs\b"
    r"|\b(?:[2-9]|two|three|four|five|multi)[- ]pages?\b|\blong-?form\b|\bin-depth\b"
    r"|\b(?:blog posts?|articles?|essays?|reports?|guides?|case stud(?:y|ies)|white ?papers?)\b"
    r"|\bfeatures? (?:on|about|stor(?:y|ies)|articles?)\b"
    r"|\bresearch(?:ing)?\b(?! (?:team|grants?|group|centre|center|projects?|papers?|lab|assistants?))"
    r"|\b(?:sources|cite|citations|references|fact-check)\b", re.I)
_URL = re.compile(r"https?://", re.I)
_CODE = re.compile(r"\b(?:python|javascript|typescript|bash|shell|sql|regex|function|bug|unit tests?|"
                   r"code|commit message|docstring|json|yaml|stack ?trace)\b|\w\.(?:py|js|ts|sh|rb|go)\b", re.I)
# Blocks the host wraps around a turn nobody typed: reminders, a subagent's hand-back, a task's report (#55). A whole
# block is dropped; a lone or unclosed tag goes on its own, so it never takes a real ask with it.
_WRAPPERS = r"system-reminder|agent-message|task-notification"
_WRAPPED = re.compile(rf"<({_WRAPPERS})(?:\s[^<>]*)?>.*?</\1\s*>", re.I | re.S)
_WRAPPER_TAG = re.compile(rf"</?(?:{_WRAPPERS})(?:\s[^<>]*)?>|</?(?:{_WRAPPERS})(?![\w-])", re.I)


def _requests(verb: re.Pattern, text: str) -> Iterator[str]:
    """Each match of `verb` that stands as the request, with the text after it."""
    for m in verb.finditer(text):
        lead = _BOUNDARY.split(text[:m.start()])[-1]
        if _LEAD.fullmatch(lead.strip()):
            yield text[m.end():]


def _asks_for_writing(rest: str) -> bool:
    """Whether the text after a draft verb starts with a kind of writing for people as its object."""
    for pattern, generic in ((_OBJECT, False), (_FOR_PIECE, False), (_GENERIC_OBJECT, True)):
        m = pattern.match(rest)
        if not m or _TECH_WORD.search(m.group("pre") + m.group("noun")):
            continue
        after = rest[m.end():]
        if _TECH_DESTINATION.match(after):
            continue
        if generic and not _AUDIENCE.match(after):
            continue
        return True
    return False


def intent(prompt: str) -> str | None:
    """'rewrite', 'draft-long', 'draft' or None for one user prompt."""
    if not isinstance(prompt, str):
        return None
    prompt = _WRAPPER_TAG.sub(" ", _WRAPPED.sub(" ", prompt))
    if not prompt.strip():
        return None
    if prompt.lstrip().startswith("/") or re.search(r"\bplainspoken\b", prompt, re.I):
        return None
    text = prompt if len(prompt) <= 2 * EDGE else prompt[:EDGE] + "\n" + prompt[-EDGE:]
    if _STRONG_REWRITE.search(text):
        return "rewrite"
    if _CODE.search(text) or not _NOUN.search(text):
        return None
    if any(not _TECH_WORD.search(_PHRASE.match(rest).group(1)) for rest in _requests(_REWRITE_VERB, text)):
        return "rewrite"
    if any(_asks_for_writing(rest) for rest in _requests(_DRAFT_VERB, text)):
        return "draft-long" if _LONG.search(text) or len(_URL.findall(text)) > 1 else "draft"
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
    elif kind == "draft-long":
        text = (f"plainspoken: this is a long piece people will read. Use {_skill(host, 'write')}: it drafts from the "
                f"notes, runs the full check and fixes what it finds. Never add a fact the notes don't give; say "
                f"what's missing instead.")
    else:
        text = (f"plainspoken: this asks for writing people will read. Short piece (under about 250 words, whatever "
                f"its type): draft it, pipe it to {lint} and cut what it flags (remove, never add facts). Longer, or "
                f"sources to research: use {_skill(host, 'write')}; inside it, this lint never replaces its check and "
                f"claims steps.")
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
