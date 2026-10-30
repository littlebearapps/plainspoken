"""Lexical anti-AI checks: word lists, phrase lists and counts. One function per rule id.

Every word/phrase list comes from rules.toml (`cfg.lists`); nothing is hard-coded here.
Verbatim quotations (attributed blockquotes, straight- or curly-quoted spans of 4+ words, including one
that runs over several sentences of a paragraph) and allow-marked phrases are kept at INFO and never count
toward a count rule. One occurrence in the text counts once
per rule, even when list entries overlap ("meanwhile" in two lists, a phrase that prefixes another).
"""
import re
from collections import Counter
from functools import lru_cache
from typing import Callable

from plainspoken.doc import Doc, _clean_inline, split_sentences
from plainspoken.findings import Finding
from plainspoken.registry import Config

Check = Callable[[Doc, Config], list[Finding]]

# Characters that may sit in front of a sentence's first word: quotes, brackets, emphasis markers.
_LEAD = re.compile(r"^[\s\"'“‘(\[*_]*")
# A source line that starts a new paragraph (so an allow marker before it can't reach back past it).
_BLOCK_BREAK = re.compile(r"^\s*(?:$|---\s*$|#|[-*+]\s|\d+\.\s)")
_LINK_TEXT = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def _units(doc: Doc) -> list[tuple[int, str, bool, str]]:
    """(line, text, quoted, kind) in line order; kind is "sentence", "heading" or "frontmatter".

    Visible text = body sentences + H2/H3 heading text + visible frontmatter spans. Frontmatter spans are
    split into sentences so sentence-opening rules see FAQ answers properly; a span whose text repeats an
    earlier span (title == ogTitle) is counted once.
    """
    units = [(s.line, s.text, s.quoted, "sentence") for s in doc.all_sentences()]
    headings = [(ln, _clean_inline(title)) for ln, _, title in doc.headings]  # no inline code / link targets
    units += [(ln, title, False, "heading") for ln, title in headings if title]
    seen: set[str] = set()
    for sp in doc.visible_frontmatter:
        if sp.text in seen:
            continue
        seen.add(sp.text)
        units += [(sp.line, t, False, "frontmatter") for t in split_sentences(sp.text)]
    return sorted(units, key=lambda u: u[0])  # stable: sentences keep their order within a paragraph


def text_units(doc: Doc) -> list[tuple[int, str, bool]]:
    """(line, text, quoted) for every body sentence, H2/H3 heading and visible frontmatter sentence."""
    return [(line, text, quoted) for line, text, quoted, _ in _units(doc)]


def _openers(doc: Doc) -> list[tuple[int, str, bool, str]]:
    """Units that can open a sentence: everything except headings."""
    return [u for u in _units(doc) if u[3] != "heading"]


@lru_cache(maxsize=None)
def _pattern(phrase: str, inflect: bool) -> re.Pattern:
    esc = re.escape(phrase).replace(r"\ ", r"\s+").replace("'", "['’]")
    single = " " not in phrase
    if inflect and single and phrase.endswith("e"):
        # Ruling B1: the tail is required and includes the bare "e", so the base form matches too.
        # No -ation/-ion tails: "utilisation rate" (ruling B1) and "elevation" (narrative pieces about grounds) are literal.
        stem, tail = esc[:-1], r"(?:e|es|ed|ing|ely|ement|ements|er|ers)"
    else:
        stem, tail = esc, (r"(?:s|es|d|ed|ing|ly|ment|ments|ness)?" if inflect and single else "")
    return re.compile(rf"(?<![\w-]){stem}{tail}(?![\w-])", re.I)


@lru_cache(maxsize=None)
def _regex(pattern: str) -> re.Pattern:
    """Compile a rules.toml regex; a straight apostrophe outside a [class] also matches a curly one."""
    out, in_class, i = [], False, 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if c == "[" and not in_class:
            in_class = True
        elif c == "]" and in_class:
            in_class = False
        out.append("['’]" if c == "'" and not in_class else c)
        i += 1
    return re.compile("".join(out), re.I)


def _lead_len(text: str) -> int:
    return _LEAD.match(text).end()


def _block_lines(doc: Doc, line: int) -> range:
    """Source lines of the paragraph whose first line is `line` (Sentence.line is the paragraph's first line)."""
    end = line
    while end < len(doc.lines) and not _BLOCK_BREAK.match(doc.lines[end]):
        end += 1
    return range(line, end + 1)


def _allowed(doc: Doc, rule: str, matched: str, line: int) -> bool:
    """An allow marker for this rule + exact phrase on any source line of the unit's paragraph."""
    for a in doc.allows:
        if a.rule == rule and a.phrase.lower() == matched.lower() and a.line in _block_lines(doc, line):
            if 0 < a.line <= len(doc.lines) and matched.lower() in doc.lines[a.line - 1].lower():
                return True
    return False


def _severity(doc: Doc, rule: str, severity: str, m: re.Match, masked: str, quoted: bool, line: int) -> str:
    """INFO for a hit inside a verbatim quotation or covered by an allow marker; else the rule's severity."""
    in_quote = quoted or masked[m.start():m.end()].strip() == ""
    return "INFO" if in_quote or _allowed(doc, rule, m.group(0).strip(), line) else severity


def _pattern_hits(doc: Doc, rule: str, patterns: list[str], severity: str, message: str, *,
                  units: list[tuple[int, str, bool, str]] | None = None, pad: bool = False,
                  keep: Callable[[str], bool] | None = None) -> list[Finding]:
    """At most one finding per unit for the first matching regex, with the same quote/allow handling as phrases."""
    out = []
    for line, text, quoted, _ in (units if units is not None else _units(doc)):
        if keep is not None and not keep(text):
            continue
        lead = _lead_len(text)  # so an anchored pattern (^while, ^here are) sees past a leading quote or **
        target, masked = text[lead:], doc.masked(text, line)[lead:]
        if pad:
            target, masked = target + " ", masked + " "
        for p in patterns:
            m = _regex(p).search(target)
            if m:
                out.append(Finding(rule, _severity(doc, rule, severity, m, masked, quoted, line), line, text[:160], message))
                break
    return out


def _scan_groups(doc: Doc, rule: str, groups: list[tuple[list[str], str, str]], *,
                 inflect: bool = False, sentence_start: bool = False,
                 skip_unit: Callable[[int, str], bool] | None = None,
                 adjust: Callable[[str, str, re.Match, str, str], tuple[str, str]] | None = None) -> list[Finding]:
    """Match every phrase of every (phrases, severity, message) group; overlapping matches count once.

    Longer phrases win, so "it is important to note that" beats its prefix "it is important to note".
    Sentence-start scans skip headings (a heading doesn't open a sentence).
    `adjust(phrase, text, match, severity, message) -> (severity, message)` can lower a hit's severity
    by context; a quote or allow marker still takes it to INFO afterwards.
    """
    entries = sorted(((p, sev, msg) for phrases, sev, msg in groups for p in dict.fromkeys(phrases)),
                     key=lambda e: -len(e[0]))
    out: list[tuple[int, int, Finding]] = []
    for ui, (line, text, quoted, _) in enumerate(_openers(doc) if sentence_start else _units(doc)):
        if skip_unit is not None and skip_unit(line, text):
            continue
        masked = doc.masked(text, line)
        start_at = _lead_len(text)
        taken: list[tuple[int, int]] = []
        for phrase, severity, message in entries:
            for m in _pattern(phrase, inflect).finditer(text):
                if sentence_start and m.start() != start_at:
                    continue
                if any(m.start() < e and s < m.end() for s, e in taken):
                    continue
                taken.append((m.start(), m.end()))
                base, msg = adjust(phrase, text, m, severity, message) if adjust else (severity, message)
                sev = _severity(doc, rule, base, m, masked, quoted, line)
                out.append((ui, m.start(), Finding(rule, sev, line, text[:160], f"{msg}: “{m.group(0)}”")))
    return [f for _, _, f in sorted(out, key=lambda x: (x[0], x[1]))]


def _scan(doc: Doc, rule: str, phrases: list[str], severity: str, message: str, **kw) -> list[Finding]:
    return _scan_groups(doc, rule, [(phrases, severity, message)], **kw)


def _count_rule(findings: list[Finding], threshold: int, rule: str, severity: str, message: str) -> list[Finding]:
    live = [f for f in findings if f.severity != "INFO"]
    if len(live) < threshold:
        return []
    words = Counter(f.message.split("“")[-1].rstrip("”").lower() for f in live)
    detail = ", ".join(f"{w} ×{n}" for w, n in words.most_common())
    return [Finding(rule, severity, 0, detail[:160], f"{message}: {len(live)} (limit {threshold - 1}) — {detail}")]


# doc.py's attribution markers, em-dash form only: a closing quote then `— Name`, or a line-start `— Name`.
_QUOTE_THEN_DASH = re.compile(r"[\"”],?\s*—\s+[A-Z]")
_LINE_START_DASH = re.compile(r"^—\s+[A-Z]")


def _last_blockquote_line(doc: Doc, line: int) -> str:
    """The last raw `>` line of the blockquote starting at `line`, without its `>`."""
    last = line
    while last < len(doc.lines) and doc.lines[last].lstrip().startswith(">"):
        last += 1
    return doc.lines[last - 1].lstrip()[1:].strip() if 0 < last <= len(doc.lines) else ""


def _attribution_tails(doc: Doc) -> Counter:
    """(line, text) of each attributed blockquote's last sentence whose attribution marker is an em dash.

    An em dash inside the quotation itself is prose and still counts; only the marker dash is excluded.
    """
    return Counter((p.sentences[-1].line, p.sentences[-1].text) for p in doc.prose_paragraphs()
                   if p.kind == "blockquote" and p.sentences and p.sentences[-1].quoted
                   and (_QUOTE_THEN_DASH.search(p.sentences[-1].text)
                        or _LINE_START_DASH.match(_last_blockquote_line(doc, p.line))))


# The house-format resource item (the house resource-list format): `- **Label** — text`,
# `- **[Label](url)** — text` or (Further reading) `- [Label](url) — text`. The em dash after the label is a
# separator, not prose; a dash inside the label or the text still counts.
RESOURCE_ITEM = re.compile(r"^\s*[-*+]\s+(?:\*\*(?:\[[^\]]+\]\(\S+?\)|[^*]+?)\*\*|\[[^\]]+\]\(\S+?\))\s*—\s")


def _separator_lines(doc: Doc) -> set[int]:
    """Lines of house-format resource items inside a resource-list section (the profile's `resource_list_headings`)."""
    return {ln for ln in doc.resources_lines() if 0 < ln <= len(doc.lines) and RESOURCE_ITEM.match(doc.lines[ln - 1])}


def em_dashes(doc: Doc, cfg: Config) -> list[Finding]:
    """Em dashes in all visible text, quotations included, except the dash that marks a quote's attribution
    and the label separator of a resource-list item (the house format, not prose). En dashes are counted
    separately, against their own cap (`_en_dashes`)."""
    limit = cfg.thresholds_for(doc)["em_dash_max"]
    tails = _attribution_tails(doc)
    separators = _separator_lines(doc)
    hits = []
    for line, text, quoted in text_units(doc):
        n = text.count("—")
        if quoted and tails[(line, text)] > 0:
            tails[(line, text)] -= 1
            n -= 1
        if n and line in separators:  # the item's first unit holds the separator
            separators.discard(line)
            n -= 1
        hits += [(line, text)] * n
    out = []
    if len(hits) > limit:
        lines = sorted({ln for ln, _ in hits})
        out.append(Finding("1", "BLOCK", lines[0], f"lines {lines[:12]}",
                           f"{len(hits)} em dashes (limit {limit} for profile {doc.profile.name}). "
                           "Use a hyphen, comma or full stop."))
    return out + _en_dashes(doc, cfg)


def _en_dashes(doc: Doc, cfg: Config) -> list[Finding]:
    """En dashes against `en_dash_max` (#104). The default, -1, means no limit, so nothing changes until a profile
    sets a cap. Once one is set, every en dash counts, number ranges (`9am–6pm`, `2020–2026`) included: a writer
    who caps en dashes at 0 doesn't use them, and a range reads as well with a hyphen or "to". A profile that keeps
    ranges sets a cap that leaves room for them. The attribution and resource-separator exemptions above are
    em-dash forms, so they don't apply here."""
    limit = cfg.thresholds_for(doc)["en_dash_max"]
    if limit < 0:
        return []
    hits = [line for line, text, _ in text_units(doc) for _ in range(text.count("–"))]
    if len(hits) <= limit:
        return []
    lines = sorted(set(hits))
    return [Finding("1", "BLOCK", lines[0], f"lines {lines[:12]}",
                    f"{len(hits)} en dashes (limit {limit} for profile {doc.profile.name}). "
                    "Use a hyphen, comma, full stop or \"to\".")]


def narrative_em_dash(doc: Doc, cfg: Config) -> list[Finding]:
    if "narrative" not in doc.profile.flags:
        return []
    return [Finding("NR-1", f.severity, f.line, f.excerpt, f.message) for f in em_dashes(doc, cfg)]


# A banned word that is the whole of a quoted span (`No "innovative."`) may be named (a mention) or scare-quoted
# (`a "robust" system`, still a use). The lint can't tell them apart, so the hit goes to judge J3 as a
# CANDIDATE; a verbatim quote of 4+ words or an attributed blockquote stays INFO.
_MENTION_BEFORE = re.compile(r"[\"“]$")
_MENTION_AFTER = re.compile(r"[.,;:!?]?[\"”]")


def ban_list(doc: Doc, cfg: Config) -> list[Finding]:
    """A hit inside a `ban_exempt_terms` entry (product name, fixed technical term, literal trade) is INFO.
    A literal banned word quoted on its own is a CANDIDATE: J3 decides mention (pass) vs scare quote (fail)."""
    exempt = [_pattern(t, False) for t in cfg.lists["ban_exempt_terms"]]

    def adjust(phrase: str, text: str, m: re.Match, severity: str, message: str) -> tuple[str, str]:
        for pat in exempt:
            if any(e.start() <= m.start() and m.end() <= e.end() for e in pat.finditer(text)):
                return "INFO", "Banned word inside an exempt technical term / product name"
        if _MENTION_BEFORE.search(text[:m.start()]) and _MENTION_AFTER.match(text, m.end()):
            return "CANDIDATE", "Banned word quoted on its own — mention or scare quote? judge J3 decides"
        return severity, message

    return _scan_groups(doc, "2", [
        (cfg.lists["ban_literal"], "BLOCK", "Banned word — use the plain swap"),
        (cfg.lists["ban_qualified"], "CANDIDATE", "Banned only when metaphorical / used as a verb — judge J3 decides"),
    ], inflect=True, adjust=adjust)


def claude_warn(doc: Doc, cfg: Config) -> list[Finding]:
    hits = _scan(doc, "2b", cfg.lists["claude_warn"], "WARN", "Claude WARN word")
    return _count_rule(hits, cfg.thresholds_for(doc)["claude_warn_total"], "2b", "WARN", "Claude WARN words")


# Text before a hit that makes it clause-initial: sentence start, or after , ; : — ( with an optional and/but/so.
_CLAUSE_START = re.compile(r"(?:^[\s\"'“‘(\[*_]*|[,;:—(]\s*)(?:(?:and|but|so)\s+)?$", re.I)


def academic_transitions(doc: Doc, cfg: Config) -> list[Finding]:
    """`academic_opener_only` phrases BLOCK only when they open a sentence or clause; mid-sentence they WARN."""
    opener_only = {p.lower() for p in cfg.lists["academic_opener_only"]}

    def adjust(phrase: str, text: str, m: re.Match, severity: str, message: str) -> tuple[str, str]:
        if phrase.lower() in opener_only and not _CLAUSE_START.search(text[:m.start()]):
            return "WARN", "Academic transition used mid-sentence — check it isn't a connective"
        return severity, message

    out = _scan(doc, "4a", cfg.lists["academic_transitions"], "BLOCK",
                "Academic transition — delete or use also/but/still", adjust=adjust)
    return out + _pattern_hits(doc, "4a", cfg.lists["academic_transition_patterns"], "BLOCK",
                               "“In today's …” opener — delete it")


def conversational_transitions(doc: Doc, cfg: Config) -> list[Finding]:
    t = cfg.thresholds_for(doc)
    hits = _scan(doc, "4a2", cfg.lists["conversational_transitions"], "WARN", "Conversational transition", sentence_start=True)
    out = _count_rule(hits, t["conversational_block"], "4a2", "BLOCK", "Conversational transitions")
    if not out:
        out = _count_rule(hits, t["conversational_warn"], "4a2", "WARN", "Conversational transitions")
    however = [h for h in hits if h.severity != "INFO" and h.message.lower().endswith("“however”")]
    if len(however) > t["however_max"]:
        out.append(Finding("4a2", "WARN", however[0].line, however[0].excerpt,
                           f"“However,” opens {len(however)} sentences (max {t['however_max']}) — prefer “But” or restructure"))
    return out


_OPENER_END = re.compile(r"[*_\"”]*(?:,|\s)")  # closing emphasis/quote, then a comma or whitespace
_NOT_CONNECTIVE = re.compile(r"instead\s+of\b", re.I)  # "Instead of X, do Y" is a preposition


def transition_density(doc: Doc, cfg: Config) -> list[Finding]:
    """Decision I3: sentence-opening connectives from the academic + conversational lists and the extra openers.

    Bare "And" / "But" are not in the vocabulary. Each sentence counts at most once (longest match wins).
    `density_total_only` words (Then / So / Now, v4) count toward the total but never get the per-word WARN.
    """
    t = cfg.thresholds_for(doc)
    vocab = sorted(dict.fromkeys(cfg.lists["academic_transitions"] + cfg.lists["conversational_transitions"]
                                 + cfg.lists["density_extra_openers"]), key=len, reverse=True)
    counts: Counter = Counter()
    first: dict[str, int] = {}
    for line, text, quoted, _ in _openers(doc):
        if quoted:
            continue
        lead = _lead_len(text)
        opener, spanned = text[lead:], doc.span_masked(text, line)[lead:]
        if _NOT_CONNECTIVE.match(opener):
            continue
        for v in vocab:
            m = _pattern(v, False).match(opener)
            if m and not spanned[m.start():m.end()].strip():  # inside a multi-sentence quotation
                break
            if m and _OPENER_END.match(opener, m.end()):  # "Next, …" / "Next it …", never "Next.js"
                counts[v] += 1
                first.setdefault(v, line)
                break
    total = sum(counts.values())
    out = []
    if total > t["transition_total_max"]:
        out.append(Finding("4b", "BLOCK", min(first.values()), str(dict(counts))[:160],
                           f"{total} sentence-opening transitions (max {t['transition_total_max']}). Let sentences stand alone."))
    total_only = set(cfg.lists.get("density_total_only", []))
    for word, n in counts.items():
        if n > t["transition_single_max"] and word not in total_only:
            out.append(Finding("4b", "WARN", first[word], word,
                               f"“{word}” opens {n} sentences (max {t['transition_single_max']})"))
    return out


def _simple(rule: str, key: str, severity: str, message: str, **kw) -> Check:
    return lambda doc, cfg: _scan(doc, rule, cfg.lists[key], severity, message, **kw)


def ghost_citations(doc: Doc, cfg: Config) -> list[Finding]:
    """Skip a sentence that carries a markdown link (the source is named and linked)."""
    def linked(line: int, text: str) -> bool:
        link_texts = [m.group(1).strip() for ln in _block_lines(doc, line) if 0 < ln <= len(doc.lines)
                      for m in _LINK_TEXT.finditer(doc.lines[ln - 1])]
        return any(lt and lt in text for lt in link_texts)
    return _scan(doc, "12b", cfg.lists["ghost_citations"], "CANDIDATE", "Unnamed source — name it or cut it",
                 skip_unit=linked)


def balance(doc: Doc, cfg: Config) -> list[Finding]:
    # pad=True: a rhetorical "The result?" can end its own sentence unit.
    return _pattern_hits(doc, "12", cfg.lists["balance_patterns"] + cfg.lists["rhetorical_question"], "CANDIDATE",
                         "Both-sides framing or rhetorical question — judge J2 decides", pad=True)


def from_x_to_y(doc: Doc, cfg: Config) -> list[Finding]:
    return _pattern_hits(doc, "16", [r"\bfrom [\w'’ -]{2,30} to [\w'’ -]{2,30}"], "CANDIDATE",
                         "“From X to Y” range — judge J2 decides",
                         keep=lambda t: not re.search(r"\bfrom \$?\d", t, re.I))


def challenges(doc: Doc, cfg: Config) -> list[Finding]:
    out = _pattern_hits(doc, "22", cfg.lists["challenges_skeleton"], "BLOCK",
                        "Verbatim “Challenges … continues to thrive” skeleton")
    for ln, level, title in doc.headings:
        if any(h in title.lower() for h in cfg.lists["challenges_headings"]):
            out.append(Finding("22", "CANDIDATE", ln, title, "“Challenges / Looking ahead” section — judge J2 checks for generic content"))
    return out


def filler(doc: Doc, cfg: Config) -> list[Finding]:
    hits = _scan(doc, "23", cfg.lists["filler_phrases"], "WARN", "Filler phrase")
    return _count_rule(hits, cfg.thresholds_for(doc)["filler_warn"], "23", "WARN", "Filler phrases")


def stock_significance(doc: Doc, cfg: Config) -> list[Finding]:
    """Rule 33: stock significance phrases, count-based like 2b: one is fine, a cluster is flagged."""
    hits = _scan(doc, "33", cfg.lists["stock_significance"], "WARN", "Stock significance phrase")
    return _count_rule(hits, cfg.thresholds_for(doc)["stock_significance_warn"], "33", "WARN",
                       "Stock significance phrases — say who it affects and how")


def vague(doc: Doc, cfg: Config) -> list[Finding]:
    hits = _scan(doc, "25", cfg.lists["vague_quantifiers"], "WARN", "Vague quantifier")
    return _count_rule(hits, cfg.thresholds_for(doc)["vague_quantifier_warn"], "25", "WARN", "Vague quantifiers")


def typography(doc: Doc, cfg: Config) -> list[Finding]:
    out = []
    curly, fence = [], None
    for i, line in enumerate(doc.lines, 1):
        stripped = line.lstrip()
        if fence is None and stripped[:3] in ("```", "~~~"):
            fence = stripped[:3]
            continue
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        if re.search(r"[“”‘’]", re.sub(r"`[^`]*`", "", line)):  # inline code isn't prose
            curly.append(i)
    if curly:
        out.append(Finding("24", "WARN", curly[0], doc.lines[curly[0] - 1].strip()[:160],
                           f"Curly quotes in markdown source on {len(curly)} line(s) — use straight quotes"))
    prose = [p for p in doc.prose_paragraphs() if p.kind == "prose"]
    words = sum(len(p.text.split()) for p in prose) or 1
    bold = sum(doc.lines[ln - 1].count("**") // 2 for p in prose for ln in _block_lines(doc, p.line)
               if 0 < ln <= len(doc.lines))  # every source line of a hard-wrapped paragraph
    per100 = bold / words * 100
    if per100 > cfg.thresholds_for(doc)["bold_spans_per_100w_warn"]:
        out.append(Finding("24", "WARN", 0, f"{bold} bold spans / {words} words",
                           f"Mechanical mid-prose bold ({per100:.1f} per 100 words) — bold sparingly"))
    return out


def announcement(doc: Doc, cfg: Config) -> list[Finding]:
    out = _scan(doc, "26", cfg.lists["announcement_openers"], "CANDIDATE", "Announcement opener", sentence_start=True)
    return out + _pattern_hits(doc, "26", cfg.lists["announcement_patterns"], "CANDIDATE",
                               "List-prefacing announcement", units=_openers(doc))


def profile_bans(doc: Doc, cfg: Config) -> list[Finding]:
    if not doc.profile.extra_bans:
        return []
    return _scan(doc, "PB", list(doc.profile.extra_bans), "BLOCK", "Profile ban list")


CHECKS: dict[str, Check] = {
    "1": em_dashes,
    "NR-1": narrative_em_dash,
    "2": ban_list,
    "2b": claude_warn,
    "4a": academic_transitions,
    "4a2": conversational_transitions,
    "4b": transition_density,
    "28": _simple("28", "salience_flags", "INFO", "Salience flag: say the thing instead of saying it matters"),
    "29": _simple("29", "sincerity_markers", "INFO", "Sincerity marker: drop it and just be honest"),
    "30": _simple("30", "signposting_openers", "INFO", "Signpost: start with the content"),
    "31": _simple("31", "gotcha_framing", "INFO", "Gotcha framing: state the catch plainly"),
    "32": _simple("32", "newer_model_words", "INFO", "Newer model-era word: use the plain word"),
    "33": stock_significance,
    "5b": _simple("5b", "meta_commentary", "CANDIDATE", "Meta-commentary — delete the frame"),
    "5c": _simple("5c", "copula_candidates", "CANDIDATE", "Possible copula avoidance — use is/has if it means that"),
    "5d": _simple("5d", "scope_disclaimers", "CANDIDATE", "Scope disclaimer — delete or state the caveat as fact"),
    "8": _simple("8", "sycophancy", "WARN", "Sycophancy"),
    "10": _simple("10", "hedges", "CANDIDATE", "Hedge — judge J3 decides"),
    "11": _simple("11", "conclusion_markers", "CANDIDATE", "Conclusion marker — just stop"),
    "12": balance,
    "12b": ghost_citations,
    "12c": _simple("12c", "stakes_inflation", "CANDIDATE", "Stakes inflation — state the real scale"),
    "14": _simple("14", "stock_filler", "WARN", "Stock filler — delete"),
    "16": from_x_to_y,
    "20": _simple("20", "cutoff_disclaimers", "BLOCK", "Chatbot artefact / knowledge-cutoff disclaimer"),
    "22": challenges,
    "23": filler,
    "24": typography,
    "25": vague,
    "26": announcement,
    "27": _simple("27", "optimise_forms", "CANDIDATE",
                  "“Optimise” — fine if technical, “improve” if marketing (judge J3)", inflect=True),
    "PB": profile_bans,
}
