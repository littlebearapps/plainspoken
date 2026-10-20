"""Deterministic claim-candidate extraction: layer 1 of the claims coverage model.

This finds HIGH-SIGNAL candidate claims in markdown (an article, a page, an email) so they can be reconciled against
the claim ledger. It is the narrow, mechanical layer only: semantic claim review, a fresh-context coverage check and
human approval are model and human work. Never present this output as complete semantic extraction.

Surfaces: frontmatter keys (`frontmatter:<key>`), the TL;DR blockquote (`tldr`), body prose (`body`), headings
(`heading`), chart visible text (`chart`: <text>/<tspan>/<title>/<desc>/<figcaption> and aria-label, never raw
markup or coordinates), markdown tables (`table`), FAQ sections (`faq`) and embedded JSON-LD (`jsonld`). Image alt
text (`alt_text`) has its own function, `extract_alt_text_candidates`.

Candidate shape: {"surface", "kind", "text", "value", "line"}. `text` is the containing line (trimmed); `value` is the
matched token for the value kinds (statistic, currency, multiplier, count, version), else the matched phrase. `line`
is 1-indexed.

Platform names come from `data/claims.toml` `[extraction] platforms` plus the project's `[claims] platforms_extra`
(`platform_names`). Each name is matched literally (`re.escape`), case-sensitively, as a whole word.
"""
from __future__ import annotations

import functools
import re
from bisect import bisect_left, bisect_right
from pathlib import Path

from plainspoken import claims_data
from plainspoken.config import claims_settings
from plainspoken.integrity import CURRENCY, FRONTMATTER, TLDR, chart_spans, visible_parts
from plainspoken.pinning import normalise_text

__all__ = ["DATA_PATH", "VALUE_KINDS", "extract_alt_text_candidates", "extract_candidates", "platform_names",
           "shipped_platforms", "value_gaps"]

DATA_PATH = claims_data.DATA_PATH
VALUE_KINDS = ("statistic", "currency", "multiplier", "count", "version")

# --- token patterns (value-bearing kinds) -----------------------------------------------------------------------
_CODES = ("AUD", "USD", "GBP", "EUR")  # integrity's currency codes
# A count starts a number: no digit (or digit then , or .) just before it, and a word boundary or a currency code.
_COUNT_START = r"(?<!\d)(?<!\d[,.])(?:\b|" + "|".join(f"(?<={c})" for c in _CODES) + ")"
_CURRENCY = CURRENCY  # integrity's pattern: $5, A$300, US$20, £450, €1.2m, AUD 300, 450 GBP
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("statistic", re.compile(r"\d+(?:\.\d+)?%")),
    ("currency", _CURRENCY),
    ("multiplier", re.compile(r"\b\d+(?:\.\d+)?x\b")),
    # counts: magnitude-suffixed (900M, 1.4M, 25k, 3 million) or comma-grouped (1,548), each from the start of its
    # number: never "000,000" out of "1,000,000" or "5M" out of "2.5M", but a count right after a word's comma or
    # full stop ("rose,1,548") is kept. A currency amount gives a count too, after a symbol ($900M) or a code
    # (EUR1.5M) alike: one rule.
    ("count", re.compile(rf"(?=\d){_COUNT_START}(?:\d+(?:\.\d+)?\s?(?:million|billion|thousand)\b"
                         r"|\d+(?:\.\d+)?[MBk](?![a-zA-Z])"
                         r"|\d{1,3}(?:,\d{3})+\b)")),
    ("version", re.compile(r"\bv\d+\.\d+(?:\.\d+)?\b")),
]

# --- sentence-level kinds (no single numeric value) -------------------------------------------------------------
_COMPARATIVE = re.compile(
    r"\b(?:more|less|fewer|higher|lower|faster|slower|better|worse)\s+(?:\w+\s+)?than\b"
    r"|\bthe\s+(?:most|least|best|worst|largest|biggest|fastest|first|only)\b",
    re.I,
)
_CAUSAL = re.compile(
    r"\b(?:because of|due to|leads? to|results? in|causes?|drives?|improves?|improved|"
    r"reduces?|reduced|increases?|increased|boosts?|boosted)\b",
    re.I,
)
_PLATFORM_VERBS = (r"\b(?:ranks?|indexes|index|crawls?|cites?|uses?|requires?|supports?|shows?|"
                   r"displays?|penali[sz]es?|rewards?|deprecat\w+|retir\w+|ignores?)\b")
# A quote worth checking: >=4 words inside double quotes (straight or curly).
_QUOTE = re.compile(r"[\"“]([^\"“”\n]{2,400}?)[\"”]")

# --- structural patterns ----------------------------------------------------------------------------------------
_FRONTMATTER_LINE = re.compile(r"^(\w[\w-]*):\s*(.+)$", re.M)
_ARIA_LABEL = re.compile(r'aria-label="([^"]*)"', re.I)
_SCRIPT_OPEN = re.compile(r"<script", re.I)
_JSONLD_TAG = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>', re.I)
_HEADING = re.compile(r"^#{1,6}[ \t]+(.*)$", re.M)
_TABLE_ROW = re.compile(r"^\|.*\|\s*$")
_FAQ_HEADING = re.compile(r"\bFAQ|frequently asked", re.I)
# A bare year is date context, not a high-signal count.
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

_MD_IMAGE_ALT = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_HTML_IMG_ALT = re.compile(r"<img\b[^>]*\balt=[\"']([^\"']*)[\"']", re.I)


# --- platforms --------------------------------------------------------------------------------------------------
def shipped_platforms() -> tuple[str, ...]:
    """The shipped platform names, `data/claims.toml` `[extraction] platforms`."""
    return claims_data.string_list("extraction", "platforms")


def platform_names(cwd: Path) -> tuple[str, ...]:
    """The shipped platform names plus the project's `[claims] platforms_extra`, in order, without repeats.
    A malformed project config raises `ConfigError`."""
    extra = [n.strip() for n in claims_settings(cwd)["platforms_extra"]]
    return tuple(dict.fromkeys([*shipped_platforms(), *extra]))


@functools.lru_cache(maxsize=32)
def _platform_pattern(names: tuple[str, ...]) -> re.Pattern[str] | None:
    names = tuple(n for n in names if n.strip())
    if not names:
        return None
    # Longest first, so "Search Console" wins over any shorter name it starts with.
    alternation = "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)[^.\n]{{0,120}}?{_PLATFORM_VERBS}")


# --- candidate building -----------------------------------------------------------------------------------------
class _Lines:
    """1-indexed line numbers by character offset, computed once per document."""

    def __init__(self, full: str):
        self._starts = [0] + [m.end() for m in re.finditer("\n", full)]

    def of(self, offset: int) -> int:
        return bisect_right(self._starts, offset)


class _Context:
    """The trimmed line around a match in one text, at most 300 characters. Each line is found by bisecting the
    text's newlines and cut once, however many matches it holds, so a long one-line text stays linear."""

    def __init__(self, text: str):
        self._text = text
        self._newlines: list[int] | None = None  # found on the first match: most lines have none
        self._cut: dict[tuple[int, int], str] = {}

    def around(self, start: int, end: int) -> str:
        """The line(s) from the one holding `start` to the one holding `end`, stripped, cut to 300 characters."""
        if self._newlines is None:
            self._newlines = [m.start() for m in re.finditer("\n", self._text)]
        i = bisect_left(self._newlines, start)
        lo = self._newlines[i - 1] + 1 if i else 0
        j = bisect_left(self._newlines, end)
        hi = self._newlines[j] if j < len(self._newlines) else len(self._text)
        if (lo, hi) not in self._cut:
            self._cut[(lo, hi)] = self._text[lo:hi].strip()[:300]
        return self._cut[(lo, hi)]


def _candidate(surface: str, kind: str, text: str, value: str, line: int) -> dict:
    return {"surface": surface, "kind": kind, "text": text, "value": value, "line": line}


def _token_candidates(text: str, surface: str, base: int, lines: _Lines,
                      ctx: _Context | None = None) -> list[dict]:
    ctx = ctx or _Context(text)
    out = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text):
            out.append(_candidate(surface, kind, ctx.around(m.start(), m.start()), m.group(0).strip(),
                                  lines.of(base + m.start())))
    return out


def _sentence_candidates(text: str, surface: str, base: int, lines: _Lines, platform: re.Pattern[str] | None,
                         quotes: bool = True, ctx: _Context | None = None) -> list[dict]:
    ctx = ctx or _Context(text)
    out = []
    kinds = [("comparative", _COMPARATIVE), ("causal", _CAUSAL)]
    if platform is not None:
        kinds.append(("platform_behaviour", platform))
    for kind, pat in kinds:
        for m in pat.finditer(text):
            out.append(_candidate(surface, kind, ctx.around(m.start(), m.end()), m.group(0).strip(),
                                  lines.of(base + m.start())))
    if quotes:
        for m in _QUOTE.finditer(text):
            quoted = m.group(1).strip()
            if len(quoted.split()) >= 4:  # skip scare quotes and single terms
                out.append(_candidate(surface, "quote", quoted[:400], quoted[:80], lines.of(base + m.start())))
    return out


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _dedupe(cands: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for c in cands:
        key = (c["surface"], c["kind"], c["value"], c["line"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _frontmatter(markdown: str, lines: _Lines, platform: re.Pattern[str] | None) -> tuple[list[dict], int]:
    """Every scalar line becomes surface `frontmatter:<key>`. Returns (candidates, body start offset)."""
    fm = FRONTMATTER.search(markdown)
    if not fm:
        return [], 0
    cands: list[dict] = []
    for lm in _FRONTMATTER_LINE.finditer(fm.group(1)):
        key, val = lm.group(1), lm.group(2)
        off = fm.start(1) + lm.start(2)
        # YAML quoting is syntax, not quotation: strip one surrounding pair so a quoted title isn't a "quote" claim.
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
            off += 1
        surface = f"frontmatter:{key}"
        ctx = _Context(val)
        cands += _token_candidates(val, surface, off, lines, ctx)
        cands += _sentence_candidates(val, surface, off, lines, platform, ctx=ctx)
    return cands, fm.end()


def _jsonld_blocks(body: str) -> list[tuple[int, int, int]]:
    """(start, content start, end) of each `<script … type="application/ld+json" …>…</script>`: the same matches as
    `re.finditer(r'<script[^>]*type="application/ld\\+json"[^>]*>(.*?)</script>', body, re.S | re.I)`. Linear in
    the length of `body`: the lazy regex goes quadratic on unclosed script tags, and so would re-testing every
    `<script` stacked before one `>`."""
    lower, out, pos = body.lower(), [], 0
    while (m := _SCRIPT_OPEN.search(body, pos)):
        gt = body.find(">", m.end())
        if gt == -1:
            break
        if not _JSONLD_TAG.fullmatch(body, m.start(), gt + 1):
            # A later `<script` before this `>` sees a suffix of this tag, so it lacks the type attribute too.
            pos = gt + 1
            continue
        close = lower.find("</script>", gt + 1)
        if close == -1:  # no closing tag after here, so none after any later opening either
            break
        out.append((m.start(), gt + 1, close + 9))
        pos = close + 9
    return out


def extract_candidates(markdown: str, platforms: tuple[str, ...] | None = None) -> list[dict]:
    """High-signal claim candidates in `markdown`. `platforms` defaults to the shipped list; pass
    `platform_names(cwd)` to include the project's own."""
    platform = _platform_pattern(shipped_platforms() if platforms is None else tuple(platforms))
    lines = _Lines(markdown)
    cands, body_start = _frontmatter(markdown, lines, platform)
    body = markdown[body_start:]
    excluded: list[tuple[int, int]] = []

    # charts: visible text and aria-label only
    for start, end in chart_spans(body):  # linear scanners: a lazy regex goes quadratic on unclosed tags
        excluded.append((start, end))
        block = body[start:end]
        parts = visible_parts(block)
        parts += [(a.start(1), a.group(1)) for a in _ARIA_LABEL.finditer(block)]
        for rel, part in parts:
            cands += _token_candidates(part, "chart", body_start + start + rel, lines)

    # JSON-LD: every string is quoted, so the quote kind means nothing here
    for start, inner, end in _jsonld_blocks(body):
        excluded.append((start, end))
        off, block = body_start + inner, body[inner:end - 9]
        ctx = _Context(block)
        cands += _token_candidates(block, "jsonld", off, lines, ctx)
        cands += _sentence_candidates(block, "jsonld", off, lines, platform, quotes=False, ctx=ctx)

    tl = TLDR.search(body)
    if tl:
        excluded.append((tl.start(), tl.end()))
        ctx = _Context(tl.group(0))
        cands += _token_candidates(tl.group(0), "tldr", body_start + tl.start(), lines, ctx)
        cands += _sentence_candidates(tl.group(0), "tldr", body_start + tl.start(), lines, platform, ctx=ctx)

    for hm in _HEADING.finditer(body):
        excluded.append((hm.start(), hm.end()))
        cands += _token_candidates(hm.group(1), "heading", body_start + hm.start(1), lines)

    cands += _prose_candidates(body, body_start, _merge(excluded), lines, platform)
    # a bare year is date context, not a count
    return _dedupe([c for c in cands if not (c["kind"] == "count" and _YEAR.fullmatch(c["value"]))])


def _prose_candidates(body: str, body_start: int, excluded: list[tuple[int, int]], lines: _Lines,
                      platform: re.Pattern[str] | None) -> list[dict]:
    """Body prose, tables and FAQ: every line whose start isn't inside an already-scanned span."""
    cands: list[dict] = []
    pos = 0
    span = 0
    faq_mode = False
    for ln in body.splitlines(keepends=True):
        stripped = ln.strip()
        if stripped.startswith("##"):
            faq_mode = bool(_FAQ_HEADING.search(stripped))
        while span < len(excluded) and excluded[span][1] <= pos:
            span += 1
        inside = span < len(excluded) and excluded[span][0] <= pos
        if stripped and not inside:
            surface = "faq" if faq_mode else ("table" if _TABLE_ROW.match(stripped) else "body")
            ctx = _Context(ln)
            cands += _token_candidates(ln, surface, body_start + pos, lines, ctx)
            cands += _sentence_candidates(ln, surface, body_start + pos, lines, platform, ctx=ctx)
        pos += len(ln)
    return cands


def extract_alt_text_candidates(markdown: str) -> list[dict]:
    """Value-bearing candidates inside image alt text (markdown and HTML), surface `alt_text`. Decorative alt text
    (no value token) gives nothing. Kept apart from `extract_candidates` so the integrity hook's input doesn't
    change."""
    out: list[dict] = []
    for line_no, line in enumerate(markdown.splitlines(), 1):
        alts = [m.group(1) for m in _MD_IMAGE_ALT.finditer(line)]
        alts += [m.group(1) for m in _HTML_IMG_ALT.finditer(line)]
        for alt in (a.strip() for a in alts):
            if not alt:
                continue
            for kind, pat in _PATTERNS:
                for tm in pat.finditer(alt):
                    out.append(_candidate("alt_text", kind, alt, tm.group(0), line_no))
    return out


# --- ledger reconcile -------------------------------------------------------------------------------------------
def _value_forms(value: str) -> list[str]:
    """Normalise magnitude notation so '900M' matches '900 million' and the reverse."""
    v = normalise_text(value).lower()
    forms = [v]
    for suffix, word in (("m", "million"), ("b", "billion"), ("k", "thousand")):
        if v.endswith(suffix) and v[:-1].replace(".", "").replace(",", "").isdigit():
            forms.append(f"{v[:-1]} {word}")
        if v.endswith(" " + word):
            forms.append(v.removesuffix(" " + word) + suffix)
    forms.append(v.replace(",", ""))
    return forms


def _contains_value(hay: str, form: str) -> bool:
    """`form` occurs in `hay` as a whole value: '40%' is not found inside '140%', nor '$3,000' inside '$3,000,000'."""
    if not form:
        return False
    i = hay.find(form)
    while i != -1:
        before = hay[i - 1] if i else ""
        after = hay[i + len(form):i + len(form) + 2]
        clash_before = (form[0].isalnum() and before != "" and (before.isalnum() or before in ".,")
                        and hay[max(0, i - 3):i].upper() not in _CODES)  # "eur1.5m" holds "1.5m"
        clash_after = form[-1].isalnum() and (after[:1].isalnum() or (after[:1] in ".," and after[1:2].isdigit()))
        if not clash_before and not clash_after:
            return True
        i = hay.find(form, i + 1)
    return False


def _str(v: object) -> str:
    return v if isinstance(v, str) else ""


def _list(v: object) -> list:
    return v if isinstance(v, list) else []


def _ledger_corpus(ledger: object) -> tuple[str, str]:
    """(claims corpus, exclusions corpus), normalised (`pinning.normalise_text`: typographic quotes straightened,
    whitespace runs including no-break spaces collapsed) and lowercased. The claims corpus is each live claim's text
    and notes plus its pinned passages; a `removed` claim is audit history, never coverage. Tolerates any shape,
    because the integrity hook passes whatever ledger is on disk."""
    if not isinstance(ledger, dict):
        return "", ""
    parts: list[str] = []
    for claim in _list(ledger.get("claims")):
        if not isinstance(claim, dict) or claim.get("status") == "removed":
            continue
        parts += [_str(claim.get("text")), _str(claim.get("notes"))]
        binding = claim.get("binding")
        if isinstance(binding, dict):
            parts.append(_str(binding.get("passage")))
            parts += [_str(p.get("passage")) for p in _list(binding.get("additional_passages")) if isinstance(p, dict)]
    exclusions = [_str(e.get("text")) for e in _list(ledger.get("exclusions")) if isinstance(e, dict)]
    return _corpus(parts), _corpus(exclusions)


def _corpus(parts: list[str]) -> str:
    return "\n".join(normalise_text(p) for p in parts if p).lower()


def value_gaps(markdown: str, ledger: dict, platforms: tuple[str, ...] | None = None) -> list[dict]:
    """Value and quote candidates the ledger doesn't represent. A value is represented when it appears in a live
    claim's text, notes or pinned passage, or in an exclusion. Both sides are normalised before matching."""
    corpus, exclusions = _ledger_corpus(ledger)
    gaps = []
    for c in extract_candidates(markdown, platforms):
        if c["kind"] in VALUE_KINDS:
            if not any(_contains_value(corpus, f) or _contains_value(exclusions, f) for f in _value_forms(c["value"])):
                gaps.append(c)
        elif c["kind"] == "quote":
            probe = normalise_text(c["text"])[:60].lower().strip().strip(".,;:'\"")
            if probe not in corpus and probe not in exclusions:
                gaps.append(c)
    return gaps
