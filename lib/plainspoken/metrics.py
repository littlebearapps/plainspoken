"""Rule 12f quantified slop metrics.

Computed over body sentences (quotations included, per the global constraint). Table cells are data,
not prose rhythm, so they're left out. Paragraph SD uses prose paragraphs only (rule 12d's quantified form).
"""
import re
import statistics
from collections import Counter

from plainspoken.doc import Doc, Sentence
from plainspoken.registry import Config

_LEAD = re.compile(r"^[\s\"'“‘(\[*_]*")
_FIRST_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’]*")


def ttr(words: list[str]) -> float:
    return len(set(words)) / len(words) if words else 0.0


def mattr(words: list[str], window: int) -> float:
    """Moving-average TTR: the mean TTR of every `window`-word window (plain TTR when shorter)."""
    if len(words) <= window:
        return ttr(words)
    counts = Counter(words[:window])
    total = len(counts)
    for i in range(window, len(words)):  # slide one word at a time, updating the distinct count
        out, into = words[i - window], words[i]
        counts[out] -= 1
        if not counts[out]:
            del counts[out]
        counts[into] += 1
        total += len(counts)
    return total / (len(words) - window + 1) / window


def burstiness(lengths: list[int]) -> float:
    """Sentence-length standard deviation ÷ mean."""
    if len(lengths) < 2:
        return 0.0
    mean = statistics.mean(lengths)
    return statistics.pstdev(lengths) / mean if mean else 0.0


def _opener(sentence: str) -> str:
    m = _FIRST_WORD.search(sentence, _LEAD.match(sentence).end())
    return m.group(0).lower().replace("’", "'") if m else ""


def opening_top3_share(sentences: list[str]) -> float:
    """Share of sentences opened by the three most common opening words."""
    openers = [o for o in map(_opener, sentences) if o]
    if not openers:
        return 0.0
    return sum(n for _, n in Counter(openers).most_common(3)) / len(openers)


def paragraph_sd(counts: list[int]) -> float:
    return statistics.pstdev(counts) if len(counts) > 1 else 0.0


def _rhythm_sentences(doc: Doc) -> list[Sentence]:
    return [s for sec in doc.sections for p in sec.paragraphs if p.kind != "table" for s in p.sentences if s.words]


def _transition_opener(cfg: Config) -> re.Pattern:
    """Decision I3's vocabulary (the per-H2 form of rule 4b): a phrase, then a comma or whitespace."""
    vocab = sorted(dict.fromkeys(cfg.lists["academic_transitions"] + cfg.lists["conversational_transitions"]
                                 + cfg.lists["density_extra_openers"]), key=len, reverse=True)
    alts = "|".join(re.escape(v).replace(r"\ ", r"\s+").replace("'", "['’]") for v in vocab)
    return re.compile(rf"(?:{alts})(?=[*_\"”]*(?:,|\s))", re.I)


def repeated_words(doc: Doc, cfg: Config) -> list[tuple[str, int]]:
    """The most repeated non-function words (v4): where to look when MATTR is under the floor.

    Names and topic words are expected to repeat; the list just shows the writer where the recycling is.
    """
    t = cfg.thresholds_for(doc)
    stop = set(cfg.lists["repeat_stopwords"])
    counts = Counter(w for s in _rhythm_sentences(doc) for w in s.words if w not in stop and len(w) > 2)
    return [(w, n) for w, n in counts.most_common(t["repeat_top"]) if n >= t["repeat_min"]]


def compute(doc: Doc, cfg: Config) -> dict[str, float]:
    t = cfg.thresholds_for(doc)
    sents = _rhythm_sentences(doc)
    words = [w for s in sents for w in s.words]
    prose = [p for p in doc.prose_paragraphs() if p.kind == "prose"]
    h2 = [sec for sec in doc.sections if sec.level == 2 and sec.paragraphs and sec.paragraphs[0].sentences]
    opener = _transition_opener(cfg)
    capsule = 0
    for sec in h2:
        first = sec.paragraphs[0].sentences[0].text
        capsule += bool(opener.match(first, _LEAD.match(first).end()))
    return {
        "words": len(words),
        "ttr": round(ttr(words), 3),
        "mattr": round(mattr(words, t["mattr_window"]), 3),
        "burstiness": round(burstiness([len(s.words) for s in sents]), 3),
        "opening_top3_share": round(opening_top3_share([s.text for s in sents]), 3),
        "capsule_transition_share": round(capsule / len(h2), 3) if h2 else 0.0,
        "paragraph_sd": round(paragraph_sd([len(p.text.split()) for p in prose]), 1),
    }
