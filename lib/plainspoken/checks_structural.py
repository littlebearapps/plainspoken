"""Structural anti-AI checks: rhythm, shape and markers. One function per rule id.

Every word list comes from rules.toml (`cfg.lists`). Rhythm rules (7, 7d, 12d) read prose paragraphs only;
bullets and table cells are fragments by design. Count rules (5e, 6, 15) never count a verbatim quotation;
pattern rules (7c, 19) keep a hit inside one at INFO and honour allow markers, like the lexical rules.
"""
import re
from typing import Callable

from plainspoken import metrics
from plainspoken.checks_lexical import _pattern_hits, text_units
from plainspoken.doc import Doc, Sentence, _clean_inline, split_sentences, tokenise
from plainspoken.findings import Finding
from plainspoken.registry import Config

Check = Callable[[Doc, Config], list[Finding]]

_LEAD = re.compile(r"^[\s\"'“‘(\[*_]*")
_CONTRACTION = re.compile(r"\b\w+'(?:s|t|re|ve|ll|d|m)\b")
_FAQ = re.compile(r"\b(?:faqs?|frequently asked)\b", re.I)  # v4: FAQ sections get the relaxed 7d check
# #73: the 7d / 7 join remedy. A join only links what is there; it adds no clause, detail or reason ("because").
_NO_ADD = "add no clause, detail or reason"
_JOIN = f'with "and" or "but", or merge them; {_NO_ADD}'


def _prose_sentences(paragraphs, kinds=("prose",)) -> list[Sentence]:
    return [s for p in paragraphs if p.kind in kinds for s in p.sentences if s.words]


def _within(a: int, b: int, tol: float) -> bool:
    return bool(max(a, b)) and abs(a - b) / max(a, b) <= tol


def _runs(values: list[int], tol: float, length: int | list[int]) -> list[int]:
    """Start indexes of runs of `length` consecutive values within tol of the run's first value. `length` may be a
    list, one run length per start index (12d's FAQ knob)."""
    lengths = length if isinstance(length, list) else [length] * len(values)
    out, i = [], 0
    while i < len(values):
        n = lengths[i]
        if i + n <= len(values) and all(_within(values[i], values[j], tol) for j in range(i + 1, i + n)):
            out.append(i)
            i += n
        else:
            i += 1
    return out


def in_faq(doc: Doc, line: int) -> bool:
    """Body line `line` sits in a FAQ section: its H2 is a FAQ heading, or its nearest heading is one. The same test
    gives a kaizen finding its `faq` section facet (`capture.section_of`), so a FAQ knob turns where the evidence is."""
    before = [(level, title) for ln, level, title in doc.headings if ln <= line]
    if not before:
        return False
    h2 = [title for level, title in before if level == 2]
    return bool((h2 and _FAQ.search(h2[-1])) or _FAQ.search(before[-1][1]))


def uniform_sentences(doc: Doc, cfg: Config) -> list[Finding]:
    t = cfg.thresholds_for(doc)
    out = []
    for sec in doc.sections:
        sents = _prose_sentences(sec.paragraphs)
        for i in _runs([len(s.words) for s in sents], t["uniform_tolerance"], t["uniform_sentence_run"]):
            out.append(Finding("7", "WARN", sents[i].line, sents[i].text[:160],
                               f"{t['uniform_sentence_run']}+ consecutive sentences of near-identical length — join or split one; "
                               f"{_NO_ADD}"))
    return out


def _short_run(sents: list[Sentence], short_len: int, run_len: int) -> Sentence | None:
    """The sentence that completes the first run of `run_len` consecutive sentences under `short_len` words."""
    run = 0
    for s in sents:
        run = run + 1 if len(s.words) < short_len else 0
        if run == run_len:
            return s
    return None


def _faq_answer_sentences(doc: Doc) -> list[Sentence]:
    """The profile's FAQ frontmatter key renders as the page's FAQ; its answers are checked as one FAQ section."""
    key = doc.profile.faq_frontmatter_key
    if not key:
        return []
    out = []
    for span in doc.visible_frontmatter:
        if span.label.startswith(f"{key}[") and span.label.endswith(".answer"):
            out += [Sentence(t, span.line, tokenise(t), -1, -1) for t in split_sentences(span.text)]
    return [s for s in out if s.words]


def staccato(doc: Doc, cfg: Config) -> list[Finding]:
    """Blog: WARN if a section has no sentence over the long threshold, OR has a run of short sentences.

    Narrative profiles (decision I5, whole article): WARN only when the run AND the no-long-sentence condition
    both hold, except a section whose heading matches the profile's `long_sentence_headings`, which fails on no
    long sentence alone.

    FAQ sections, and frontmatter FAQ answers (every profile): short answers are the point, so only a run of
    `staccato_faq_short_run` short sentences WARNs.
    """
    t = cfg.thresholds_for(doc)
    long_, short_len, run_len = t["staccato_long_sentence"], t["staccato_short_len"], t["staccato_short_run"]
    faq_run = t["staccato_faq_short_run"]
    narrative = "narrative" in doc.profile.flags
    run_only = doc.content_type == "social"  # social: only a run of short sentences WARNs (severity table)
    out = []
    units = [(sec.heading, sec.level, sec.line, _prose_sentences(sec.paragraphs)) for sec in doc.sections]
    units.append(("FAQ (frontmatter faqs)", 2, 0, _faq_answer_sentences(doc)))
    for heading, level, line, sents in units:
        if len(sents) < 3:
            continue
        where, at = heading or "(intro)", line if level else sents[0].line
        if _FAQ.search(heading):
            run_end = _short_run(sents, short_len, faq_run)
            if run_end:
                out.append(Finding("7d", "WARN", run_end.line, run_end.text[:160],
                                   f"{faq_run} consecutive sentences under {short_len} words in the FAQ — join two {_JOIN}"))
            continue
        no_long = max(len(s.words) for s in sents) <= long_
        run_end = _short_run(sents, short_len, run_len)
        if narrative and any(p.search(heading) for p in doc.profile.long_sentence_headings) and no_long:
            out.append(Finding("7d", "WARN", at, where,
                               f"No sentence over {long_} words in this section — join two short sentences {_JOIN}"))
        elif narrative:
            if no_long and run_end:
                out.append(Finding("7d", "WARN", run_end.line, run_end.text[:160],
                                   f"{run_len} consecutive sentences under {short_len} words, none over {long_} — join two {_JOIN}"))
        elif no_long and not run_only:
            out.append(Finding("7d", "WARN", at, where,
                               f"No sentence over {long_} words in this section — join two short sentences {_JOIN}"))
        elif run_end:
            out.append(Finding("7d", "WARN", run_end.line, run_end.text[:160],
                               f"{run_len} consecutive sentences under {short_len} words — join two {_JOIN}"))
    return out


def narrative_staccato(doc: Doc, cfg: Config) -> list[Finding]:
    if "narrative" not in doc.profile.flags:
        return []
    return [Finding("NR-2", f.severity, f.line, f.excerpt, f.message) for f in staccato(doc, cfg)]


def uniform_paragraphs(doc: Doc, cfg: Config) -> list[Finding]:
    """A run of `paragraph_uniform_run` prose paragraphs of near-identical length WARNs; a run that starts in a FAQ
    section needs `paragraph_uniform_faq_run` instead (the knob calibrate turns for FAQ answers alone)."""
    t = cfg.thresholds_for(doc)
    prose = [p for p in doc.prose_paragraphs() if p.kind == "prose"]
    lengths = [t["paragraph_uniform_faq_run"] if in_faq(doc, p.line) else t["paragraph_uniform_run"] for p in prose]
    return [Finding("12d", "WARN", prose[i].line, prose[i].text[:160],
                    f"{lengths[i]}+ consecutive paragraphs of near-identical length")
            for i in _runs([len(p.text.split()) for p in prose], t["uniform_tolerance"], lengths)]


def narrative_paragraphs(doc: Doc, cfg: Config) -> list[Finding]:
    if "narrative" not in doc.profile.flags:
        return []
    t = cfg.thresholds_for(doc)
    counts = [len(p.text.split()) for p in doc.prose_paragraphs() if p.kind == "prose"]
    if counts and min(counts) < t["narrative_paragraph_short"] and max(counts) > t["narrative_paragraph_long"]:
        return []
    return [Finding("NR-5", "WARN", 0, f"shortest {min(counts or [0])}w, longest {max(counts or [0])}w",
                    f"A narrative piece needs one paragraph under {t['narrative_paragraph_short']} words and one over {t['narrative_paragraph_long']}")]


# Bold-first bullets: `- **Label**: text`, `- **Label:** text` and `- **Label** — text`.
_BOLD_BULLET = re.compile(r"^\s*[-*+]\s+\*\*[^*]+?(?::\*\*|\*\*\s*[:—–-])")
# A bold LINK label is the house resource-list format.
# `\S+?` (not `[^)]*`) so a URL with brackets in it, e.g. a Wikipedia `Foo_(bar)` page, still counts as a link.
_BOLD_LINK_BULLET = re.compile(r"^\s*[-*+]\s+\*\*\[[^\]]+\]\(\S+?\)\*\*")


def bold_bullets(doc: Doc, cfg: Config) -> list[Finding]:
    """Runs of `- **Label:** text` bullets. Inside a resource-list section (the profile's `resource_list_headings`)
    every bold label is the house format (Pattern B: `- **Label** — text`), so those bullets never count (010, 012)."""
    t = cfg.thresholds_for(doc)
    resources = doc.resources_lines()
    out, run, fence = [], 0, None
    for i, line in enumerate(doc.lines, 1):
        stripped = line.lstrip()
        if fence is None and stripped[:3] in ("```", "~~~"):
            fence, run = stripped[:3], 0
            continue
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        if _BOLD_BULLET.match(line) and not _BOLD_LINK_BULLET.match(line) and i not in resources:
            run += 1
            if run == t["bold_bullet_run"]:
                out.append(Finding("12e", "WARN", i, line.strip()[:160], f"{run}+ consecutive bold-first bullets"))
        elif stripped:
            run = 0
    return out


def title_case(doc: Doc, cfg: Config) -> list[Finding]:
    """A capitalised function word after a heading's first word. A word after a colon or a sentence end
    (FAQ-style "…? Why?") starts afresh; all-caps words of 2+ letters (IT, API) are acronyms, a lone "A" isn't; inline code and link
    targets aren't words."""
    fw = set(cfg.lists["title_case_function_words"])
    out = []
    for ln, _, title in doc.headings:
        clean = _clean_inline(title)
        for part in re.split(r"[:.!?]", clean):
            words = re.findall(r"[A-Za-z][\w'’-]*", part)
            if any(w[0].isupper() and not (w.isupper() and len(w) > 1) and w.lower() in fw for w in words[1:]):
                out.append(Finding("13", "WARN", ln, title[:160], "Title Case heading — use sentence case"))
                break
    return out


def _starts_with_ing(s: Sentence, stop: set[str]) -> bool:
    return bool(re.match(r"[A-Z][a-z]+ing\b", s.text[_LEAD.match(s.text).end():])) and s.words[0] not in stop


def _opens_in_quote(doc: Doc, s: Sentence) -> bool:
    """The sentence's first word is inside a quotation that started in an earlier sentence."""
    lead = _LEAD.match(s.text).end()
    return not doc.span_masked(s.text, s.line)[lead:lead + 1].strip()


def ing_openers(doc: Doc, cfg: Config) -> list[Finding]:
    """-ing openers in prose (not bullets, tables or quotations). Headings don't open sentences."""
    t = cfg.thresholds_for(doc)
    stop = set(cfg.lists["ing_stop"])
    out = []
    for sec in doc.sections:
        sents = [s for s in _prose_sentences(sec.paragraphs, ("prose", "blockquote"))
                 if not s.quoted and not _opens_in_quote(doc, s)]
        flags = [_starts_with_ing(s, stop) for s in sents]
        if sum(flags) >= t["ing_opener_section_warn"]:
            at = sec.line if sec.level else sents[0].line
            out.append(Finding("5e", "CANDIDATE", at, sec.heading or "(intro)",
                               f"{sum(flags)} -ing sentence openers in this section — judge J4 separates participles from gerund subjects"))
        run = 0
        for s, f in zip(sents, flags):
            run = run + 1 if f else 0
            if run == t["ing_opener_consecutive_block"]:
                out.append(Finding("5e", "CANDIDATE", s.line, s.text[:160], f"{run} consecutive -ing openers (BLOCK if confirmed)"))
    return out


def trailing_ing(doc: Doc, cfg: Config) -> list[Finding]:
    """The match is the verb itself, so an allow marker names it: `<!-- anti-ai-allow: 19 "highlighting" … -->`."""
    alts = "|".join(re.escape(v).replace(r"\ ", r"\s+") for v in cfg.lists["trailing_ing_verbs"])
    pattern = rf"(?<=, )(?:{alts})\b(?=[^.]{{3,}}[.!?][\"”')\]]*$)"
    return _pattern_hits(doc, "19", [pattern], "CANDIDATE", "Trailing -ing clause — real subject or decoration? (J4)")


def triplets(doc: Doc, cfg: Config) -> list[Finding]:
    pat = re.compile(r"\b[\w'-]+(?: [\w'-]+){0,3}, [\w'-]+(?: [\w'-]+){0,3},? (?:and|or) [\w'-]+", re.I)
    sents = [s for s in doc.all_sentences() if not s.quoted]
    hits = [(s.line, s.text) for s in sents if pat.search(doc.masked(s.text, s.line))]
    words = sum(len(s.words) for s in doc.all_sentences()) or 1
    rate = len(hits) / words * 1000
    if rate < cfg.thresholds_for(doc)["triplets_per_1000w_candidate"]:
        return []
    return [Finding("6", "CANDIDATE", ln, t[:160], f"Three-item list ({rate:.1f} per 1,000 words) — judge J2 decides") for ln, t in hits]


def press_release(doc: Doc, cfg: Config) -> list[Finding]:
    """The article's first prose sentence."""
    first = next((s for p in doc.prose_paragraphs() if p.kind == "prose" for s in p.sentences), None)
    if first and re.match(r"^[A-Z][a-z]+ed \d[\d,]* \w+ (?:across|in|for) \d", first.text):
        return [Finding("7b", "CANDIDATE", first.line, first.text[:160], "Press-release opener — open on an observation")]
    return []


def negative_parallel(doc: Doc, cfg: Config) -> list[Finding]:
    return _pattern_hits(doc, "7c", [r"\bnot (?:just|only|merely) [^.]{2,60}(?:, it'?s|but also|—)"], "CANDIDATE",
                         "“Not just X, it's Y” construction")


def contractions(doc: Doc, cfg: Config) -> list[Finding]:
    text = " ".join(doc.masked(t, ln) for ln, t, q in text_units(doc) if not q).lower().replace("’", "'")
    expanded = sum(len(re.findall(rf"\b{re.escape(p)}\b", text)) for p in cfg.lists["expanded_forms"])
    contracted = len(_CONTRACTION.findall(text))
    if expanded >= 5 and expanded >= contracted:
        return [Finding("15", "WARN", 0, f"{expanded} expanded vs {contracted} contracted",
                        "Contraction avoidance — use it's/don't/can't where it reads naturally")]
    return []


def human_markers(doc: Doc, cfg: Config) -> list[Finding]:
    paras = [p for p in doc.prose_paragraphs() if p.kind != "table"]
    sents = _prose_sentences(paras, ("prose", "bullet", "blockquote"))
    text = " ".join(s.text for s in sents).replace("’", "'")
    words = {w for s in sents for w in s.words}
    markers = {
        "contractions": bool(_CONTRACTION.search(text)),
        "fragments": any(len(s.words) <= 3 for s in _prose_sentences(paras)),  # a short bullet isn't a fragment
        "and_but_starters": any(s.words[0] in ("and", "but") for s in sents),
        "first_person": bool(words & {"i", "me", "my", "i'm", "i've", "i'd", "i'll"}),
        "casual_connectives": bool(words & {"because", "if", "so", "like"}),
        "asides": bool(re.search(r"\([^)]{3,}\)| - ", text)),
    }
    if any(markers.values()):
        return []
    return [Finding("HM", "WARN", 0, "no human markers",
                    "No contractions, fragments, And/But starters, first person, casual connectives or asides — "
                    "contract or join where it reads naturally; add nothing new")]


def slop_metrics(doc: Doc, cfg: Config) -> list[Finding]:
    t = cfg.thresholds_for(doc)
    m = metrics.compute(doc, cfg)
    if m["words"] < 300:
        return []
    out = []
    # Decision I4 (2026-09-26): MATTR gates; raw TTR is length-biased and reported as INFO only.
    if m["ttr"] < t["ttr_min"]:
        out.append(Finding("12f", "INFO", 0, f"ttr {m['ttr']}", f"Raw TTR {m['ttr']} (info only — MATTR gates, decision I4)"))
    if m["mattr"] < t["mattr_min"]:
        sev = "BLOCK" if t["mattr_blocking"] else "WARN"
        top = metrics.repeated_words(doc, cfg)
        where = (" Most repeated: " + ", ".join(f"{w} ×{n}" for w, n in top)
                 + " (names and topic words are expected; reword the generic ones, without synonym cycling)") if top else ""
        out.append(Finding("12f", sev, 0, f"mattr {m['mattr']}",
                           f"MATTR-{t['mattr_window']} {m['mattr']} < {t['mattr_min']} — vary the vocabulary.{where}"))
    if m["burstiness"] < t["burstiness_min"]:
        out.append(Finding("12f", "BLOCK", 0, f"burstiness {m['burstiness']}",
                           f"Burstiness {m['burstiness']} < {t['burstiness_min']} — join or split sentences to spread their lengths"))
    # (name, value, comparison, limit); only the tripped ones are named, so the writer knows what to fix (#26).
    # The opening limit scales with length (#25): top-3 share can't fall below 3/n.
    open_limit = round(metrics.opening_top3_limit(t["opening_top3_max"], metrics.opener_count(doc)), 3)
    checks = [
        ("opening repetition", m["opening_top3_share"], ">", open_limit),
        ("capsule transitions", m["capsule_transition_share"], ">", t["capsule_transition_max"]),
        ("paragraph SD", m["paragraph_sd"], "<", t["paragraph_sd_min"]),
        ("MATTR", m["mattr"], "<", t["mattr_min"]),
    ]
    tripped = [f"{name} {value:g} {op} {limit:g}" for name, value, op, limit in checks
               if (value > limit if op == ">" else value < limit)]
    if len(tripped) >= 2:
        # capture.py matches "slop metrics tripped"; keep the phrase.
        out.append(Finding("12f", "WARN", 0, str(m)[:160], f"{len(tripped)} slop metrics tripped: " + "; ".join(tripped)
                           + " — cut, join or split; never pad"))
    return out


def opinion(doc: Doc, cfg: Config) -> list[Finding]:
    if "narrative" not in doc.profile.flags:
        return []
    text = " ".join(t for _, t, _ in text_units(doc)).lower().replace("’", "'")
    if any(re.search(rf"\b{re.escape(m)}\b", text) for m in cfg.lists["opinion_markers"]):
        return [Finding("NR-6", "CANDIDATE", 0, "opinion marker present", "J4 confirms a real blunt take sits near the marker")]
    return [Finding("NR-6", "WARN", 0, "no opinion marker", "A narrative piece needs the opinion-delivery pattern at least once")]


CHECKS: dict[str, Check] = {
    "5e": ing_openers, "6": triplets, "7": uniform_sentences, "7b": press_release, "7c": negative_parallel,
    "7d": staccato, "12d": uniform_paragraphs, "12e": bold_bullets, "12f": slop_metrics, "13": title_case,
    "15": contractions, "19": trailing_ing, "HM": human_markers, "NR-2": narrative_staccato,
    "NR-5": narrative_paragraphs, "NR-6": opinion,
}
