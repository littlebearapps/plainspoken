"""Deterministic integrity checks for prominent numbers, used by the `integrity` hook when a file has no claims ledger.

Three checks on a saved markdown file:
  * a chart (`<figure>`/`<svg>`) whose visible text holds a statistic, with no citation in its sourcing window: the
    chart plus the prose on each side up to the midpoint of the gap to the next chart, so a second chart never inherits
    the first one's citation;
  * a statistic in the `> **TL;DR:**` blockquote with no markdown link;
  * a statistic in frontmatter `description`/`tldr`/`ogDescription` whose number is on no line carrying a link.

w3.org and schema.org URLs (SVG namespaces, JSON-LD vocabularies) never count as citations. Escapes are scoped:
`<!-- integrity:allow … -->` (alias `integrity:first-hand`) clears one chart when it sits in that chart's window, or
the TL;DR when it's inside the block or within 300 characters above it, except a marker inside a chart: that one is
the chart's and never clears a TL;DR. `# integrity: allow` inside the frontmatter clears the frontmatter check
only. Own data is then recorded as a `first_hand` claim in the ledger.

`chart_spans`, `visible_parts` and the `CURRENCY` pattern are shared with `extraction`. The two scanners are linear:
a lazy `.*?` regex goes quadratic on a file full of unclosed tags.
"""
from __future__ import annotations

import re
from bisect import bisect_right

from plainspoken._util import clip

__all__ = ["CURRENCY", "FRONTMATTER", "SKIP_SUFFIXES", "TLDR", "chart_spans", "findings", "gaps_message", "is_internal",
           "unsourced_message", "visible_parts"]

SKIP_SUFFIXES = (".claims.toml", ".claims.json", ".reader-value.toml")
MAX_GAPS = 10
MAX_ROWS = 5
MAX_STATS = 6

_NUM = r"\d(?:[\d,]*\d)?(?:\.\d+)?"  # no trailing comma: "US$20," is US$20
_MAGNITUDE = r"(?:\s?[kKmMbB](?![a-zA-Z]))?"
_CODES = r"(?:AUD|USD|GBP|EUR)"
# An amount of money. Shared with `extraction` (its `currency` candidates), so both find the same amounts.
CURRENCY = re.compile(
    rf"(?:(?:(?<![A-Za-z])(?:AU|US|NZ|A))?\$|£|€){_NUM}{_MAGNITUDE}"  # $5, A$300, AU$1,200, US$20, NZ$9, £450, €1.2m
    rf"|\b{_CODES}\s?{_NUM}{_MAGNITUDE}"  # AUD 300, USD20
    rf"|(?<![\w.]){_NUM}{_MAGNITUDE}\s?{_CODES}\b"  # 450 GBP, 1.2m EUR
)
# A statistic: a percentage, an amount of money (CURRENCY) or an Nx multiplier.
_STAT = re.compile(rf"\d+(?:\.\d+)?%|{CURRENCY.pattern}|\b\d+(?:\.\d+)?x\b")
_BARE = re.compile(_NUM)
_CHART_OPEN = re.compile(r"<(figure|svg)[\s>]", re.I)
_VISIBLE_OPEN = re.compile(r"<(text|tspan|title|desc|figcaption)", re.I)
_NOT_A_SOURCE = r"(?!(?:www\.)?(?:w3|schema)\.org)"
_MD_LINK = re.compile(rf"\]\(https?://{_NOT_A_SOURCE}", re.I)
_SOURCE_URL = re.compile(rf"[Ss]ource[^\n]{{0,160}}?https?://{_NOT_A_SOURCE}")
_MARKER = re.compile(r"<!--\s*integrity:(?:allow|first-hand)\b.{0,500}?-->", re.S)
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---", re.S)  # shared with extraction
_META_KEY = re.compile(r"^\s*(description|tldr|ogDescription)\s*:", re.I)
_FM_ALLOW = re.compile(r"^\s*#\s*integrity:\s*(?:allow|first-hand)\b", re.M)
TLDR = re.compile(r"^>\s*\*\*TL;DR:?\*\*.*(?:\n>.*)*", re.M | re.I)  # shared with extraction

ALLOW = "<!-- integrity:allow — what you measured -->"
FOOTER = ("Record your own data as a first_hand claim in the claims ledger, or run /plainspoken:claims to build "
          "the ledger.")


# --- linear tag scanning ----------------------------------------------------------------------------------------
def chart_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each `<figure …>…</figure>` or `<svg …>…</svg>`, outermost first: the same spans as
    `re.finditer(r"<figure[\\s>].*?</figure>|<svg[\\s>].*?</svg>", text, re.S | re.I)`, in linear time."""
    lower, spans, pos, unclosed = text.lower(), [], 0, set()
    while (m := _CHART_OPEN.search(text, pos)):
        tag = m.group(1).lower()
        close = -1 if tag in unclosed else lower.find(f"</{tag}>", m.end())
        if close == -1:  # no closing tag after here, so none after any later opening either
            unclosed.add(tag)
            pos = m.end()
            continue
        spans.append((m.start(), close + len(tag) + 3))
        pos = spans[-1][1]
    return spans


def visible_parts(block: str) -> list[tuple[int, str]]:
    """(offset, text) of each `<text|tspan|title|desc|figcaption …>…</same>` body in `block`: the same matches as
    `re.finditer(r"<(text|tspan|title|desc|figcaption)[^>]*>(.*?)</\\1>", block, re.S | re.I)`, in linear time."""
    lower, parts, pos, unclosed, gt = block.lower(), [], 0, set(), -1
    while (m := _VISIBLE_OPEN.search(block, pos)):
        if gt < m.end():  # the first `>` after this opening; reused while it's still ahead
            gt = block.find(">", m.end())
        if gt == -1:  # no `>` left: no later opening can complete either
            break
        tag = m.group(1).lower()
        close = -1 if tag in unclosed else lower.find(f"</{tag}>", gt + 1)
        if close == -1:
            unclosed.add(tag)
            pos = m.end()
            continue
        parts.append((gt + 1, block[gt + 1:close]))
        pos = close + len(tag) + 3
    return parts


# --- the checks -------------------------------------------------------------------------------------------------
def _stats(text: str) -> list[str]:
    found = list(dict.fromkeys(m.group(0) for m in _STAT.finditer(text)))
    return found[:MAX_STATS] + (["…"] if len(found) > MAX_STATS else [])


def _sourced(window: str) -> bool:
    return bool(_MD_LINK.search(window) or _SOURCE_URL.search(window))


def _line_index(text: str) -> list[int]:
    return [0] + [m.end() for m in re.finditer("\n", text)]


def _capped(rows: list[str], noun: str) -> list[str]:
    extra = len(rows) - MAX_ROWS
    return rows[:MAX_ROWS] + ([f"- +{extra} more {noun}"] if extra > 0 else [])


def check_charts(content: str) -> list[str]:
    """One row per chart with an unsourced statistic (the first MAX_ROWS, then `+N more`), then the fix."""
    spans, starts, rows = chart_spans(content), None, []
    for i, (start, end) in enumerate(spans):
        stats = _stats(" | ".join(t for _off, t in visible_parts(content[start:end])))
        if not stats:
            continue
        lo = (spans[i - 1][1] + start) // 2 if i else 0
        hi = (end + spans[i + 1][0]) // 2 if i + 1 < len(spans) else len(content)
        window = content[lo:hi]
        if _MARKER.search(window) or _sourced(window):
            continue
        starts = starts or _line_index(content)
        rows.append(f"- Chart (line {bisect_right(starts, start)}): {', '.join(stats)} has no source link near it.")
    if not rows:
        return []
    return [*_capped(rows, "charts"), "  Cite each chart in a <figcaption> or in the prose beside it. If one is your "
            f"own measurement, put {ALLOW} inside its <figure>."]


def check_tldr(content: str) -> list[str]:
    m = TLDR.search(content)
    if not m:
        return []
    stats = _stats(m.group(0))
    if not stats or _MARKER.search(m.group(0)) or _MD_LINK.search(m.group(0)):
        return []
    above = [a.start() for a in _MARKER.finditer(content, max(0, m.start() - 300), m.start())]
    spans = chart_spans(content) if above else []
    if any(not any(start <= pos < end for start, end in spans) for pos in above):  # a chart's marker is the chart's
        return []
    return [f"- TL;DR: {', '.join(stats)} has no source link. Cite it inline. If it's your own figure, put {ALLOW} "
            "on the line above the TL;DR."]


def _on_a_cited_line(stat: str, cited: str) -> bool:
    number = _BARE.search(stat)
    if not number:
        return True
    return bool(re.search(rf"(?<![\d.,]){re.escape(number.group(0))}(?!\d|[.,]\d)", cited))


def check_meta(content: str) -> list[str]:
    """One row per frontmatter `description`/`tldr`/`ogDescription` line with an unsourced statistic, then the fix."""
    fm = FRONTMATTER.search(content)
    if not fm or not content[fm.end():].strip() or _FM_ALLOW.search(fm.group(1)):
        return []
    cited = "\n".join(ln for ln in content.splitlines() if _MD_LINK.search(ln))
    rows = []
    for line in fm.group(1).splitlines():
        key = _META_KEY.match(line)
        unsourced = [s for s in _stats(line) if s != "…" and not _on_a_cited_line(s, cited)] if key else []
        if unsourced:
            rows.append(f"- Frontmatter `{key.group(1)}`: {', '.join(unsourced)} is on no line with a source link.")
    if not rows:
        return []
    return [*rows, "  Cite each figure in the body or reword the line. If it's your own figure, add "
            "`# integrity: allow` inside the frontmatter."]


def findings(content: str) -> list[str]:
    """Every no-ledger finding in `content`, as message rows; [] when there are none."""
    content = content.replace("\r\n", "\n")
    return [*check_charts(content), *check_tldr(content), *check_meta(content)]


# --- messages and scope -----------------------------------------------------------------------------------------
def unsourced_message(name: str, rows: list[str]) -> str:
    return "\n".join([f"plainspoken integrity: {name} has prominent numbers with no source.", *rows, FOOTER])


def gaps_message(name: str, ledger_rel: str, gaps: list[dict]) -> str:
    rows = [f"  {g['line']} {g['value']}: {clip(' '.join(str(g['text']).split()), 110)}" for g in gaps[:MAX_GAPS]]
    if len(gaps) > MAX_GAPS:
        rows.append(f"  +{len(gaps) - MAX_GAPS} more")
    return "\n".join([f"plainspoken integrity: {len(gaps)} number(s) or quote(s) in {name} aren't in its claims "
                      f"ledger ({ledger_rel}):", *rows,
                      "Add each one to the ledger as a claim or an exclusion, then run /plainspoken:claims."])


def is_internal(rel: str) -> bool:
    """plainspoken's own files: anything under .plainspoken/, a claims ledger or a reader-value contract."""
    return ".plainspoken" in rel.split("/") or rel.lower().endswith(SKIP_SUFFIXES)
