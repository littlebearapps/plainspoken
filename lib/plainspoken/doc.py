"""Markdown document model for the anti-AI linter.

Visible text = body prose + the profile's visible frontmatter fields (and its FAQ frontmatter key, if set).
Not prose: fenced code, inline code, HTML comments, raw HTML/SVG block lines (any line whose
stripped form starts with `<`, plus whole <svg>/<script>/<style> blocks), inline HTML tags, URLs,
link targets, image syntax, headings (headings are kept separately on Section for rule 13).
"""
import re
from dataclasses import dataclass, field

from plainspoken.frontmatter import FrontmatterError, load as load_frontmatter
from plainspoken.profile import Profile, default as default_profile

_ABBREV = ("e.g.", "i.e.", "etc.", "vs.", "Dr.", "Mr.", "Mrs.", "Ms.", "St.", "No.", "approx.", "cf.")
# Split on whitespace after . ! ? (optionally followed by one closing quote or bracket, which stays with the
# sentence it ends, so a quotation's mask still sees both quote marks).
_SENT_SPLIT = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"'”’)\]]))\s+(?=[\"'“‘(\[]?[A-Z0-9])")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*(?:-[A-Za-z]+)*")
_QUOTED = re.compile(r"\"([^\"]+)\"|“([^”]+)”")
_QUOTE_LEAD = "([{—–-:;,/*_"  # what may sit right before a straight quote that opens one
_ALLOW = re.compile(r"<!--\s*anti-ai-allow:\s*(\S+)\s+\"([^\"]+)\"\s*(.*?)-->")
_INLINE_CODE = re.compile(r"`[^`]*`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_HTML_TAG = re.compile(r"</?[A-Za-z][^<>]*>")  # tag-shaped only, so "x < 5 and y > 3" survives
_SKIP_BLOCK = re.compile(r"^\s*<(svg|script|style)\b", re.I)
_INLINE_CODE_TAG = re.compile(r"<code\b[^>]*>.*?</code>", re.I | re.S)
# A line led by one of these inline tags is prose; any other "<"-led line is a skipped HTML block line.
_INLINE_LEAD = re.compile(r"^<(?:strong|em|b|i|span|abbr|code|a(?![^>]*\bid=))\b", re.I)
_CAPTION_OPEN = re.compile(r"^<figcaption\b[^>]*>", re.I)
_CAPTION_CLOSE = re.compile(r"</figcaption\s*>", re.I)
# Blockquote attributions, tested on the LAST raw blockquote line only.
_ATTR_AFTER_QUOTE = re.compile(r"[\"”],?\s*[—–-]\s+[A-Z]")  # …" - Jane Smith, Example Weekly
_ATTR_OWN_LINE = re.compile(r"^[—–]\s+[A-Z]")  # – Jane Smith / — Jane Smith (never a list marker)
_ATTR_DASH_LINE = re.compile(r"^-\s+[A-Z]")  # "- Name": attribution only straight after a closing quote


@dataclass
class Sentence:
    text: str
    line: int
    words: list[str]
    section: int
    paragraph: int
    quoted: bool = False


@dataclass
class Paragraph:
    text: str
    line: int
    section: int
    kind: str  # prose | bullet | blockquote | table
    sentences: list[Sentence] = field(default_factory=list)


@dataclass
class Section:
    heading: str
    level: int
    line: int
    paragraphs: list[Paragraph] = field(default_factory=list)


@dataclass
class Span:
    label: str
    text: str
    line: int


@dataclass
class Allow:
    rule: str
    phrase: str
    line: int  # the line the allow applies to (the one after the marker)
    reason: str = ""  # the marker's free-text reason (listed in the host's state section)


@dataclass
class Doc:
    path: str
    profile: Profile
    content_type: str
    frontmatter: dict
    visible_frontmatter: list[Span]
    sections: list[Section]
    headings: list[tuple[int, int, str]]  # (line, level, text) for H2/H3
    allows: list[Allow]
    lines: list[str]
    # (paragraph line, sentence text) -> the text with the part inside a multi-sentence quotation blanked, for
    # a sentence only partly inside one; a sentence wholly inside one is `quoted` instead.
    quote_masks: dict[tuple[int, str], str] = field(default_factory=dict)

    def all_sentences(self) -> list[Sentence]:
        return [s for sec in self.sections for p in sec.paragraphs for s in p.sentences]

    def prose_paragraphs(self) -> list[Paragraph]:
        return [p for sec in self.sections for p in sec.paragraphs]

    def masked(self, text: str, line: int | None = None) -> str:
        """Blank out verbatim quotations of 4+ words so phrase rules skip them. With the sentence's paragraph `line`,
        the part of a multi-sentence quotation that falls in this sentence is blanked too."""
        def repl(m: re.Match) -> str:
            inner = m.group(1) or m.group(2) or ""
            return " " * len(m.group(0)) if len(inner.split()) >= 4 else m.group(0)
        return _QUOTED.sub(repl, self.span_masked(text, line))

    def span_masked(self, text: str, line: int | None) -> str:
        """`text` with only the part of a multi-sentence quotation blanked; unchanged for any other sentence."""
        return text if line is None else self.quote_masks.get((line, text), text)

    def resources_lines(self) -> set[int]:
        """Source lines of every section whose H2 matches the profile's `resource_list_headings` (a house-format
        resource list), heading to the next H2, whose `- **Label** — text` items are template."""
        h2 = [(ln, title) for ln, level, title in self.headings if level == 2]
        out: set[int] = set()
        for i, (ln, title) in enumerate(h2):
            if any(p.match(title) for p in self.profile.resource_list_headings):
                out.update(range(ln, h2[i + 1][0] if i + 1 < len(h2) else len(self.lines) + 1))
        return out

    def is_allowed(self, rule: str, phrase: str, line: int) -> bool:
        return any(a.rule == rule and a.line == line and a.phrase.lower() == phrase.lower() for a in self.allows)


def tokenise(text: str) -> list[str]:
    return [w.lower().replace("’", "'") for w in _WORD.findall(text)]


def split_sentences(text: str) -> list[str]:
    protected = text
    for i, ab in enumerate(_ABBREV):
        protected = protected.replace(ab, ab.replace(".", f"\x00{i}\x00"))
    parts = [p.strip() for p in _SENT_SPLIT.split(protected) if p.strip()]
    out = []
    for p in parts:
        for i, ab in enumerate(_ABBREV):
            p = p.replace(ab.replace(".", f"\x00{i}\x00"), ab)
        out.append(p)
    return out


def _quote_spans(text: str) -> list[tuple[int, int]]:
    """`[start, end)` of every closed straight or curly double-quoted span in one paragraph's text. A quote still
    open at the paragraph's end closes nothing, so its words stay unquoted.

    A straight `"` is ambiguous, so it opens only after the start, whitespace or opening punctuation, and closes
    only when no letter or digit follows; any other straight `"` (an inch mark: `6'2"`, `a 12" board`) is ignored,
    so it can't pair with a later real quote and blank the sentences between."""
    spans, start = [], None
    for i, c in enumerate(text):
        prev = text[i - 1] if i else " "
        nxt = text[i + 1] if i + 1 < len(text) else " "
        if c == '"':
            if start is None and (prev.isspace() or prev in _QUOTE_LEAD):
                start = i
            elif start is not None and not nxt.isalnum():
                spans.append((start, i + 1))
                start = None
        elif start is None and c == "“":
            start = i
        elif start is not None and c == "”":
            spans.append((start, i + 1))
            start = None
    return spans


def _sentence_quotes(text: str, sentences: list[str]) -> list[tuple[bool, str | None]]:
    """Per sentence of a paragraph: (wholly inside a quotation, its text with the quoted part blanked or None).

    Only a quotation of 4+ words that crosses a sentence boundary counts here; one inside a single sentence is left
    to `Doc.masked`, as before. A sentence is wholly quoted when no word is left outside the quotation."""
    out: list[tuple[bool, str | None]] = []
    bounds, pos = [], 0
    for s in sentences:
        at = text.find(s, pos)
        at = pos if at < 0 else at
        bounds.append((at, at + len(s)))
        pos = at + len(s)
    spans = [(a, b) for a, b in _quote_spans(text) if len(text[a + 1:b - 1].split()) >= 4
             and sum(1 for lo, hi in bounds if lo < b and a < hi) > 1]
    for s, (lo, hi) in zip(sentences, bounds):
        chars = list(s)
        for a, b in spans:
            for i in range(max(a, lo), min(b, hi)):
                chars[i - lo] = " "
        if chars == list(s):
            out.append((False, None))
            continue
        rest = "".join(chars)
        out.append((not _WORD.search(rest), rest))
    return out


def _is_attribution(bq_lines: list[str]) -> bool:
    """True when a blockquote ends with an attribution, so its text is a verbatim quotation.

    `> - Item` lines are list items (quote cards), unless the line before ends with a closing quote.
    """
    last = bq_lines[-1].strip()
    if _ATTR_AFTER_QUOTE.search(last) or _ATTR_OWN_LINE.match(last):
        return True
    return bool(_ATTR_DASH_LINE.match(last)) and len(bq_lines) > 1 and bq_lines[-2].rstrip().endswith(('"', "”"))


def _clean_inline(text: str) -> str:
    text = _INLINE_CODE.sub(" ", text)
    text = _INLINE_CODE_TAG.sub(" ", text)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _HTML_TAG.sub(" ", text)  # before URLs: an href URL would otherwise swallow the tag's tail
    text = _URL.sub(" ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)  # "provider </a>." -> "provider."
    return re.sub(r"\s+", " ", text).strip()


def _split_frontmatter(text: str) -> tuple[dict, str, int]:
    if not text.startswith("---\n"):
        return {}, text, 0
    end = text.find("\n---", 3)  # 3, not 4: an empty frontmatter closes straight after the opener
    if end == -1:  # fail closed: never lint frontmatter as prose
        raise FrontmatterError("unclosed frontmatter (no closing --- line)")
    fm_text = text[4:end]
    body_start_line = text[:end + 1].count("\n") + 1  # line number of the closing ---
    body = text[end + 4:].lstrip("\n")
    skipped = text[end + 4:].count("\n") - body.count("\n")
    fm = load_frontmatter(fm_text)
    return (fm if isinstance(fm, dict) else {}), body, body_start_line + skipped - 1


def _fm_line(lines: list[str], needle: str) -> int:
    for i, line in enumerate(lines, 1):
        if needle and needle[:40] in line:
            return i
    return 1


CONTENT_TYPES = ("article", "social")


def _normalise(text: str) -> str:
    return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def split_lines(text: str) -> list[str]:
    """The lines the lint numbers (from 1): a leading BOM dropped, CR LF and CR read as LF, split on "\n" only.
    Not splitlines(): that also breaks on U+2028/U+2029, \x0b, \x0c, \x1c-\x1e and \x85, which shifts every later
    line number away from the \n offsets the frontmatter split counts. Shared with the eval prompts and the golden
    set's evidence check, so a judge's line numbers are the lint's."""
    lines = _normalise(text).split("\n")
    if lines[-1] == "":  # a trailing "\n" (or empty text) leaves an empty last element; splitlines drops it
        lines.pop()
    return lines


def parse(text: str, *, path: str = "", profile: Profile | None = None, content_type: str = "article") -> Doc:
    if content_type not in CONTENT_TYPES:
        raise ValueError(f"unknown content type {content_type!r} (expected one of {CONTENT_TYPES})")
    text = _normalise(text)
    profile = profile or default_profile()
    lines = split_lines(text)
    fm, _, offset = _split_frontmatter(text)
    visible: list[Span] = []
    for key in profile.visible_frontmatter_keys:
        if isinstance(fm.get(key), str):
            visible.append(Span(key, fm[key], _fm_line(lines, fm[key])))
    faq_key = profile.faq_frontmatter_key
    for i, qa in enumerate((fm.get(faq_key) or []) if faq_key else []):
        for part in ("question", "answer"):
            if isinstance(qa, dict) and isinstance(qa.get(part), str):
                visible.append(Span(f"{faq_key}[{i}].{part}", qa[part], _fm_line(lines, qa[part])))

    allows: list[Allow] = []
    sections = [Section("", 0, 1)]
    headings: list[tuple[int, int, str]] = []
    in_code = False
    skip_until = ""  # closing marker of a multi-line HTML comment or <svg>/<script>/<style> block
    in_caption = False  # inside a multi-line <figcaption>, whose text is visible prose
    buf: list[tuple[int, str]] = []
    kind = "prose"
    quote_masks: dict[tuple[int, str], str] = {}

    def flush():
        nonlocal buf, kind
        if not buf:
            return
        raw = " ".join(t for _, t in buf)
        raw = _HTML_COMMENT.sub(" ", raw)
        cleaned = _clean_inline(raw)
        if cleaned:
            sec_i = len(sections) - 1
            para = Paragraph(cleaned, buf[0][0], sec_i, kind)
            quoted_para = kind == "blockquote" and _is_attribution([t for _, t in buf])
            sents = split_sentences(cleaned)
            for s, (inside, mask) in zip(sents, _sentence_quotes(cleaned, sents)):
                if mask is not None and not inside:
                    quote_masks[(buf[0][0], s)] = mask
                para.sentences.append(Sentence(s, buf[0][0], tokenise(s), sec_i, len(sections[-1].paragraphs),
                                               quoted_para or inside))
            sections[-1].paragraphs.append(para)
        buf, kind = [], "prose"

    start = offset + 1  # offset is 0 when there's no frontmatter
    for ln in range(start, len(lines) + 1):
        line = lines[ln - 1]
        m = _ALLOW.search(line)
        if m:
            if m.group(0).strip() == line.lstrip().lstrip(">").strip():  # marker alone (even as `> <!-- … -->`): next line
                allows.append(Allow(m.group(1), m.group(2), ln + 1, m.group(3).strip()))
                continue
            allows.append(Allow(m.group(1), m.group(2), ln, m.group(3).strip()))  # inline marker: applies to its own line
            line = (line[:m.start()] + line[m.end():]).rstrip()
        if line.strip().startswith("```"):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        if skip_until:
            if skip_until in line.lower():
                skip_until = ""
            continue
        stripped = line.strip()
        if in_caption or _CAPTION_OPEN.match(stripped):  # <figcaption> text is visible prose
            if not in_caption:
                flush()
            closed = bool(_CAPTION_CLOSE.search(stripped))
            buf.append((ln, _CAPTION_CLOSE.split(_CAPTION_OPEN.sub("", stripped))[0]))
            in_caption = not closed
            if closed:
                flush()
            continue
        if stripped.startswith("<") and not _INLINE_LEAD.match(stripped):  # raw HTML/SVG block line
            flush()
            block = _SKIP_BLOCK.match(line)
            if stripped.startswith("<!--") and "-->" not in stripped:
                skip_until = "-->"
            elif block and f"</{block.group(1).lower()}>" not in stripped.lower():
                skip_until = f"</{block.group(1).lower()}>"
            continue
        h = re.match(r"^(#{2,3})\s+(.*)$", line)
        if h:
            flush()
            level, title = len(h.group(1)), re.sub(r"\s*\{#[^}]+\}\s*$", "", h.group(2)).strip()
            headings.append((ln, level, title))
            if level == 2:
                sections.append(Section(title, 2, ln))
            continue
        if line.startswith("# "):
            continue
        if not stripped:
            flush()
            continue
        b = re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$", line)
        if b:
            flush()
            kind = "bullet"
            buf = [(ln, b.group(1))]  # flushed by the next blank line, bullet or block (continuations)
            continue
        if line.lstrip().startswith(">"):
            if kind != "blockquote":
                flush()
                kind = "blockquote"
            buf.append((ln, line.lstrip()[1:].strip()))
            continue
        if line.lstrip().startswith("|"):
            if kind != "table":
                flush()
                kind = "table"
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                buf.append((ln, ". ".join(c for c in cells if c) + "."))
            continue
        if kind == "bullet":  # an indented or lazy continuation line belongs to the list item above it
            buf.append((ln, line.strip()))
            continue
        if kind != "prose":
            flush()
        buf.append((ln, line.strip()))
    flush()
    if not sections[0].paragraphs and len(sections) > 1:
        sections[0] = Section("", 0, 1)
    return Doc(path, profile, content_type, fm, visible, sections, headings, allows, lines, quote_masks)
