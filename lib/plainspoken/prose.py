"""Find the writing for a person inside a string that may hold other things: markup, a quoted reply thread, a
signature, code, a table, links. Shared by the tool-call check (#124) and the chat-reply check (#125).

- `extract(text)`: the stripped text, its prose word count, and why it isn't prose (None when it is). The stripped
  text is what gets linted, so a quoted thread or a signature never earns a finding; the caller never changes the
  text it was given.
- `text_hash`, `fingerprint`, `overlap`: hashes of normalised text and of its sentences, so one check can tell that
  another already linted the same words without storing any of them.

Stdlib only and no other plainspoken import, with the rarer modules imported where they're used, so a hook can load
it in a few milliseconds.
"""
from __future__ import annotations

import re
from collections import namedtuple

__all__ = ["REASONS", "Extract", "extract", "strip", "word_count", "text_hash", "fingerprint", "overlap"]

_HTML_HINT = re.compile(r"<(?:p|br|div|span|table|html|body)\b", re.I)
_HTML_DROP = re.compile(r"<(style|script|blockquote|head)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_GMAIL_QUOTE = re.compile(r"<(?:div|blockquote)\b[^>]*class=[\"'][^\"']*gmail_quote.*", re.I | re.S)
_HTML_BREAK = re.compile(r"<(?:br|/p|/div|/li|/tr|/h[1-6]|li|p|div|tr)\b[^>]*>", re.I)
_HTML_TAG = re.compile(r"<[^<>]+>")
_FENCE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.M | re.S)
_ON_WROTE = re.compile(r"^[ \t]*On\b[^\n]{0,200}(?:\n[^\n]{0,200})?\bwrote:[ \t]*$", re.M)  # one or two lines
_ORIGINAL = re.compile(r"^\s*-{2,}\s*(?:Original Message|Forwarded message)\s*-{2,}", re.I | re.M)
_OUTLOOK = re.compile(r"^\s*From:[^\n]*\n(?:[^\n]*\n){0,2}?\s*(?:Sent|Date):", re.M)
_SIGNATURE = re.compile(r"^-- ?$", re.M)
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", re.I)
_CODE = re.compile(r"=>|[{};=<>]|\b(?:def|function|import|const|return|SELECT|WHERE)\b")
_LETTER = re.compile(r"[^\W\d_]")
_TWO_LETTERS = re.compile(r"[^\W\d_]{2}")
_SENTENCE_END = re.compile(r"[^\W\d_][)\"'’”]?[.!?](?:\s|$)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})

PROSE_SHARE = 0.7  # at least this share of tokens hold two letters in a row
CODE_PER_WORDS = 15  # code: more than one code symbol per this many words ...
CODE_MIN = 3  # ... and at least this many
REASONS = ("empty", "json", "encoded", "code", "symbols", "no-sentence")  # why a string isn't prose


# text: the stripped text, what a lint should see · words: prose words in it (tokens with a letter) · reason: None for
# prose, else one of REASONS. (A collections namedtuple: typing costs a hook a few milliseconds to import.)
Extract = namedtuple("Extract", "text words reason")


def _is_json(text: str) -> bool:
    head = text.lstrip()[:1]
    if head not in ("{", "["):
        return False
    import json
    try:
        json.loads(text)
    except (ValueError, RecursionError):
        return False
    return True


def _encoded(text: str) -> bool:
    tokens = text.split()
    return 0 < len(tokens) < 5 and any(len(t) > 60 for t in tokens)


def _cut(text: str, pattern: re.Pattern) -> str:
    for m in pattern.finditer(text):
        # A reply header names a date, a time or an address; "On Friday my sister wrote:" in a letter is kept.
        if pattern is not _ON_WROTE or re.search(r"[\d@<]", m.group()):
            return text[:m.start()]
    return text


def _strip_html(text: str) -> str:
    text = _GMAIL_QUOTE.sub("", text)
    text = _HTML_DROP.sub(" ", text)
    text = _HTML_BREAK.sub("\n", text)
    text = _HTML_TAG.sub(" ", text)
    import html
    return html.unescape(text)


def strip(text: str) -> str:
    """`text` without what isn't the writer's own prose: HTML markup (and its style, script, quoted blocks and
    Gmail's quoted thread), a plain-text quoted thread (`>` lines, an `On … wrote:` line and what follows, an
    `Original Message` or Outlook `From:`/`Sent:` header block), an RFC 3676 signature (`-- `), fenced code, table
    rows and links and email addresses."""
    if _HTML_HINT.search(text):
        text = _strip_html(text)
    text = _FENCE.sub("", text)
    for pattern in (_ON_WROTE, _ORIGINAL, _OUTLOOK, _SIGNATURE):
        text = _cut(text, pattern)
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">") and ln.count("|") < 2]
    text = _URL.sub("", "\n".join(lines))
    return text.strip()


def word_count(text: str) -> int:
    """Tokens that hold a letter."""
    return sum(1 for t in text.split() if _LETTER.search(t))


def extract(text: str) -> Extract:
    """The prose in `text`: the stripped text, its word count, and None, or the reason it isn't prose."""
    if not isinstance(text, str) or not text.strip():
        return Extract("", 0, "empty")
    if _is_json(text):
        return Extract("", 0, "json")
    if _encoded(text):
        return Extract("", 0, "encoded")
    body = strip(text)
    tokens = body.split()
    words = word_count(body)
    if not tokens:
        return Extract(body, 0, "empty")
    code = len(_CODE.findall(body))
    if code >= CODE_MIN and code * CODE_PER_WORDS > words:
        return Extract(body, words, "code")
    if sum(1 for t in tokens if _TWO_LETTERS.search(t)) < PROSE_SHARE * len(tokens):
        return Extract(body, words, "symbols")
    if not _SENTENCE_END.search(body):
        return Extract(body, words, "no-sentence")
    return Extract(body, words, None)


def _normalise(text: str) -> str:
    return " ".join(text.translate(_QUOTES).split()).lower()


def text_hash(text: str) -> str:
    """16 hex: sha256 of the text with quotes straightened, whitespace collapsed and letters lower-cased."""
    import hashlib
    return hashlib.sha256(_normalise(text).encode("utf-8")).hexdigest()[:16]


def fingerprint(text: str) -> tuple[str, ...]:
    """12 hex per sentence of three or more words (normalised as `text_hash`), once each, in order."""
    import hashlib
    out = []
    for sentence in _SENTENCE_SPLIT.split(_normalise(text)):
        if len(sentence.split()) >= 3:
            h = hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:12]
            if h not in out:
                out.append(h)
    return tuple(out)


def overlap(fp: tuple[str, ...] | list[str], seen: set[str]) -> float:
    """The share of `fp`'s sentences already in `seen` (0.0 for an empty fingerprint)."""
    return sum(1 for h in fp if h in seen) / len(fp) if fp else 0.0
