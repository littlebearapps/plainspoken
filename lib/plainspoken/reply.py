"""Find the draft in a chat reply, and the one message about what the lint found in it (#125).

- `drafts(reply, writing_ask, min_words)`: the drafts in a reply, at most MAX_DRAFTS, each with its shape. Marked
  shapes first (a prose fence, a blockquote, labelled variants, text between rules, a letter); the unmarked
  fallbacks (`framed`, `whole`) only after a writing ask, with a 40-word floor, and never on a reply that talks
  about the drafting ("before I write it", "I didn't draft it yet") or ends on a question. Only the wrapper is
  stripped (fence lines, `>` prefixes, a lead-in and trailing offers); the draft's own markdown is kept, and
  `prose.extract` takes out code, tables, links and quoted threads, as it does for the tool-call check.
- `is_write_report(reply)`: the reply carries the write skill's status block (a line starting OWNER_MARKER). That
  file was already checked, so the chat-reply check leaves it alone.
- `message(found, host)`: at most MESSAGE_LINES lines and MESSAGE_CHARS characters, plain text (it may land in a
  terminal or a Telegram chat, before or after the reply), naming the top findings and the host's check command.

Stdlib only, and only `plainspoken.prose` and `_util` at import time.
"""
from __future__ import annotations

import re
from collections import namedtuple

from plainspoken import prose
from plainspoken._util import clip

# The write skill's status block line (`run.py status`) that lists what needs the owner. The one definition: the
# status command prints it, the chat-reply check skips a reply that carries it, and #75's report guard keys on it.
OWNER_MARKER = "needs the owner:"
SHAPES = ("fence", "quote", "variants", "rules", "letter", "framed", "whole")
MIN_WORDS = 25
FALLBACK_WORDS = 40  # the unmarked fallbacks need at least this many words, whatever min_words says
MAX_DRAFTS = 3
MESSAGE_LINES = 6
MESSAGE_CHARS = 600
SHOWN_FINDINGS = 3

# text: what gets linted · words: its word count · shape: one of SHAPES · kind: "email" for a letter shape, else None
Draft = namedtuple("Draft", "text words shape kind")

_OWNER = re.compile(r"^[ \t]*" + re.escape(OWNER_MARKER), re.M)
_PROSE_TAGS = {"", "text", "txt", "plain", "plaintext", "markdown", "md", "email", "message", "mail", "letter"}
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*([\w+-]*)[^\n]*\n(.*?)^[ \t]*\1[ \t]*$", re.M | re.S)
_QUOTE_RUN = re.compile(r"(?:^[ \t]*>[^\n]*(?:\n|$))+", re.M)
_QUOTE_MARK = re.compile(r"^[ \t]*> ?", re.M)
_RULE = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.M)
_VARIANT = re.compile(r"^[ \t]*(?:#{1,4}[ \t]+|\*\*)(?:option|version|variant|draft|take)\b[^\n]*$", re.I | re.M)
_GREETING = re.compile(r"^(?:hi|hello|hey|dear|g'day|good (?:morning|afternoon|evening))\b[^\n]{0,40}[,!]?$", re.I)
_SIGNOFF = re.compile(r"^(?:cheers|thanks(?: again| so much)?|thank you|regards|kind regards|warm regards|best"
                      r"(?: wishes)?|many thanks|sincerely|talk soon|see you(?: then| soon)?|all the best|ta)[,!.]?$",
                      re.I)
_SUBJECT = re.compile(r"^\**subject:?\**:?\s+\S", re.I)
_LEAD_IN = re.compile(r"^(?:sure|okay|ok|here(?:'s| is| are)|below is|i've (?:drafted|written|put together)|"
                      r"this (?:one|version|draft)|draft|try this|two options|three options)\b[^\n]*[:.!]$", re.I)
_TRAILER = re.compile(r"^(?:want (?:me|a|an|it|this|something)|would you (?:like|prefer)|let me know|i can|"
                      r"if you(?:'d)? like|happy to|shall i|should i|notes?:|a few notes|i kept|i've kept|i left|"
                      r"i used|i went with|i avoided|i didn't|feel free|tweak|adjust|swap)\b", re.I)
_LIST = re.compile(r"^[ \t]*(?:[-*•+]|\d+[.)])[ \t]+\S", re.M)
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]", re.M)
_KEY_VALUE = re.compile(r"^[ \t]*[\w -]{1,24}:[ \t]*\S")
_DRAFTING_TALK = re.compile(
    r"\bbefore i (?:write|draft)\b|\bi (?:didn'?t|did not|haven'?t|have not|can'?t|won'?t)(?: yet)? "
    r"(?:write|draft|written|drafted)\b|\bi'?ll (?:write|draft) (?:it|one|that|this)\b[^.?!]{0,20}\b(?:once|when|"
    r"after|as soon as)\b|\b(?:once|if) you (?:tell|send|confirm|let) me\b|\bquick question\b", re.I)


def is_write_report(reply: str) -> bool:
    return isinstance(reply, str) and _OWNER.search(reply) is not None


def _paragraphs(text: str) -> list[str]:
    return [p.strip("\n") for p in re.split(r"\n[ \t]*\n", text) if p.strip()]


def _unframe(text: str) -> str:
    """`text` without a one-line lead-in at the top and offers or notes at the bottom."""
    paras = _paragraphs(text)
    if paras and "\n" not in paras[0].strip() and _LEAD_IN.match(paras[0].strip()):
        paras = paras[1:]
    while paras and _TRAILER.match(paras[-1].strip()):
        paras = paras[:-1]
    return "\n\n".join(paras)


def _letter(text: str) -> str | None:
    """From a Subject line or a greeting line through a sign-off (and one short name line after it)."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _SUBJECT.match(ln.strip()) or _GREETING.match(ln.strip())), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if _SIGNOFF.match(lines[i].strip())), None)
    if end is None:
        return None
    if end + 1 < len(lines) and 0 < len(lines[end + 1].split()) <= 3 and not _TRAILER.match(lines[end + 1].strip()):
        end += 1
    return "\n".join(lines[start:end + 1])


def _draft(text: str, shape: str, floor: int) -> Draft | None:
    """A Draft when `text` holds prose of at least `floor` words, else None."""
    found = prose.extract(text)
    if found.reason is not None or found.words < floor:
        return None
    lines = [ln for ln in found.text.splitlines() if ln.strip()]
    if sum(1 for ln in lines if _KEY_VALUE.match(ln) and len(ln.split()) <= 6) * 2 >= len(lines):
        return None  # a key: value list, not writing
    body = found.text
    return Draft(body, len(body.split()), shape, "email" if _letter(body) else None)


def _keep(texts, shape: str, floor: int) -> list[Draft]:
    out = []
    for text in texts:
        d = _draft(text, shape, floor)
        if d is not None:
            out.append(d)
    return out[:MAX_DRAFTS]


def drafts(reply: str, writing_ask: bool, min_words: int = MIN_WORDS) -> list[Draft]:
    """The drafts in `reply`, first matching shape wins; [] when there's none."""
    if not isinstance(reply, str) or not reply.strip() or is_write_report(reply):
        return []
    fenced = [m.group(3) for m in _FENCE.finditer(reply) if m.group(2).lower() in _PROSE_TAGS]
    if found := _keep(fenced, "fence", min_words):
        return found
    quoted = [_QUOTE_MARK.sub("", m.group()) for m in _QUOTE_RUN.finditer(reply)]
    if found := _keep(quoted, "quote", min_words):
        return found
    body = _FENCE.sub("", reply)  # a code fence is never the draft
    if _VARIANT.search(body):
        if found := _keep([_unframe(p) for p in _VARIANT.split(body)[1:]], "variants", min_words):
            return found
    if _RULE.search(body):
        segments = _RULE.split(body)
        inner = segments[1:-1] if len(segments) >= 3 else segments[1:]
        if found := _keep([_unframe(s) for s in inner], "rules", min_words):
            return found
    letter = _letter(body)
    if letter and (found := _keep([letter], "letter", min_words)):
        return found
    if not writing_ask or _DRAFTING_TALK.search(body):
        return []
    floor = max(min_words, FALLBACK_WORDS)
    framed = _unframe(body)
    if not framed or framed.rstrip().endswith("?") or _LIST.search(framed):
        return []
    shape = "framed" if framed != body.strip() else "whole"
    if shape == "whole" and _HEADING.search(framed):
        return []
    return _keep([framed], shape, floor)


def _top(found: list[tuple[Draft, dict]]) -> tuple[list[dict], int]:
    """The findings to show (BLOCKs first, then WARNs, in draft order) and how many were left out."""
    shown: list[dict] = []
    total = 0
    for sev in ("BLOCK", "WARN"):
        for _, lint in found:
            for f in lint["findings"]:
                if f["severity"] == sev:
                    total += 1
                    if len(shown) < SHOWN_FINDINGS:
                        shown.append(f)
    return shown, total - len(shown)


def message(found: list[tuple[Draft, dict]], host: str) -> str:
    """The person's message for drafts whose lint had a BLOCK or WARN finding (`found`: (draft, lint) pairs)."""
    from plainspoken import hostreply, textlint
    totals = {"BLOCK": 0, "WARN": 0}
    for _, lint in found:
        for sev, n in textlint.counts(lint).items():
            totals[sev] += n
    tally = textlint.count_text(totals)
    if len(found) == 1:
        d = found[0][0]
        what = f"the draft in this reply ({d.kind + ', ' if d.kind else ''}{d.words} words) has"
    else:
        sizes = [str(d.words) for d, _ in found]
        what = f"{len(found)} drafts in this reply ({', '.join(sizes[:-1])} and {sizes[-1]} words) have"
    lines = [f"plainspoken: {what} {tally} (lint only, judges not run):"]
    shown, left = _top(found)
    for f in shown:
        lines.append(f"  {f['severity']:5} r{f['rule']:<3} {clip(str(f['message']), 90)}")
    if left:
        lines.append(f"  … and {left} more")
    lines.append(f"Ask for a fix, or run {hostreply.skill_ref(host, 'check')} on it before it goes out.")
    text = "\n".join(lines)
    return clip(text, MESSAGE_CHARS)

