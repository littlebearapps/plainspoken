"""meaning-diff (#147): the numbers, limits and promises a fix or rewrite changed, listed for the owner.

Free and deterministic: no model, no network. It counts marker words (`data/meaning.toml`) in the sentences a fix
changed and lists a change only when the whole text has fewer (dropped) or more (added) of that word than before, so a
word that moved to another sentence isn't a change. It's word-level: a change made without one of these words (an
added detail, "support" -> "raising money") isn't seen, and every listing says so (`FOOTER`).

- `markers(sentence, lex)`: the marker counts of one sentence, keyed `(class, lemma)`.
- `diff(before, after)`: the changed sentences, each with the marker changes inside it.
- `record`, `saved`, `summarise`: the CLI's saved result and its lines (`plainspoken meaning-diff`).

It never changes a verdict: `check`, `status`, `eval rewrite` and `rewrite-delta` exit as they would without it.
"""
from __future__ import annotations

import hashlib
import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "meaning.toml"
FOOTER = "meaning-diff: word-level; a change made without these words isn't seen."

# class -> the label used in output, and which way a change is listed
CLASSES = {"num": "number", "qual": "qualifier", "neg": "negation", "commit": "commitment", "oblig": "obligation",
           "cond": "condition", "excl": "exclusion", "free": "free", "incl": "inclusion", "cause": "reason"}
DIRECTION = {"num": "both", "qual": "dropped", "neg": "both", "commit": "added", "oblig": "dropped",
             "cond": "dropped", "excl": "dropped", "free": "dropped", "incl": "added", "cause": "added"}

_TOKEN = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:[.,]\d+)*|[,.;:!?]")
_CONTRACTED = {"won't": "will", "can't": "can", "shan't": "shall"}
_CLAUSE_END = {".", "!", "?", ";"}
_PUNCT = {".", ",", ";", ":", "!", "?"}
_NUMBER_WORD = (r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|"
                r"fifty|sixty|hundred)\b")


@dataclass(frozen=True)
class Lexicon:
    negations: frozenset
    negation_context: frozenset
    commitment_modals: frozenset
    commitment_subjects: frozenset
    adverbs: frozenset
    obligations: frozenset
    conditions: frozenset
    time_after: frozenset
    exclusions: frozenset
    free: frozenset
    inclusions: frozenset
    reasons: frozenset
    phrases: tuple  # (phrase words, counted as), longest first
    qualifiers: dict
    qualifier: re.Pattern
    tax: re.Pattern
    price_context: re.Pattern
    frames: re.Pattern


@lru_cache(maxsize=4)
def load_lexicon(path: Path = DATA_PATH) -> Lexicon:
    """The word lists from `path` (default `data/meaning.toml`), read once."""
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    pats = raw["patterns"]
    quals = {str(k).lower(): str(v) for k, v in raw["qualifiers"].items()}
    qual_alt = "|".join(sorted((re.escape(q) for q in quals), key=len, reverse=True))
    phrases = sorted(((tuple(k.lower().split()), v) for k, v in raw["phrases"].items()), key=lambda p: -len(p[0]))

    def words(key: str) -> frozenset:
        return frozenset(str(w).lower() for w in raw[key])
    return Lexicon(
        negations=words("negations"), negation_context=words("negation_context"),
        commitment_modals=words("commitment_modals"), commitment_subjects=words("commitment_subjects"),
        adverbs=words("adverbs"), obligations=words("obligations"), conditions=words("conditions"),
        time_after=words("time_after"), exclusions=words("exclusions"), free=words("free"),
        inclusions=words("inclusions"), reasons=words("reasons"), phrases=tuple(phrases), qualifiers=quals,
        qualifier=re.compile(rf"\b({qual_alt})\s+(?=[$£€]?\d|{_NUMBER_WORD})", re.I),
        tax=re.compile(pats["tax"], re.I), price_context=re.compile(pats["price_context"], re.I),
        frames=re.compile("|".join(f"(?:{f})" for f in pats["frames"]), re.I))


def lexicon_sha256(path: Path = DATA_PATH) -> str:
    """The word lists' hash: a saved result made with other lists is stale."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tokens(text: str) -> list[str]:
    """Lower-case words, numbers and punctuation; contractions split ("won't" -> "will", "not"; "we'll" -> "we",
    "will"), curly apostrophes read as straight, a hyphenated word kept whole."""
    out: list[str] = []
    for t in _TOKEN.findall(text):
        t = t.lower().replace("’", "'")
        if "-" in t:
            out.append(t)  # must-see, follow-up: one word, never a marker
        elif t.endswith("n't"):
            out += [_CONTRACTED.get(t, t[:-3]), "not"]
        elif t.endswith("'ll"):
            out += [t[:-3], "will"]
        elif t.endswith("'d"):
            out += [t[:-2], "would"]
        elif re.search(r"'(?:re|ve|m|s)$", t):
            out.append(t.rsplit("'", 1)[0])
        else:
            out.append(t)
    return out


def _phrased(toks: list[str], lex: Lexicon) -> list[str]:
    out, i = [], 0
    while i < len(toks):
        for words, lemma in lex.phrases:
            if tuple(toks[i:i + len(words)]) == words:
                out.append(lemma)
                i += len(words)
                break
        else:
            out.append(toks[i])
            i += 1
    return out


def _window(toks: list[str], i: int, n: int = 5) -> list[str]:
    """Up to `n` words either side of `toks[i]`, inside its clause."""
    lo = hi = i
    while lo > 0 and i - lo < n and toks[lo - 1] not in _CLAUSE_END:
        lo -= 1
    while hi < len(toks) - 1 and hi - i < n and toks[hi + 1] not in _CLAUSE_END:
        hi += 1
    return toks[lo:i] + toks[i + 1:hi + 1]


def _is_time(word: str, lex: Lexicon) -> bool:
    return not word or word in _PUNCT or word[:1].isdigit() or word in lex.time_after


def markers(sentence: str, lex: Lexicon) -> Counter:
    """The marker counts of `sentence`, keyed `(class, lemma)`, plus the context keys the diff reads:
    `("negctx", "negation")` (a negation with a limit word or I/we near it) and `("negctxword", word)`."""
    toks = _phrased(tokens(lex.frames.sub(" ", sentence)), lex)
    c: Counter = Counter()
    if n := len(lex.tax.findall(sentence)):
        c[("excl", "plus GST/fees")] += n
    priced = bool(lex.price_context.search(sentence))
    for i, t in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if t in lex.negations:
            c[("neg", "negation")] += 1  # one count for the class: "do not hold" -> "without" is no change
            ctx = [w for w in _window(toks, i) if w in lex.negation_context]
            if t == "without" or ctx or any(w in lex.commitment_subjects for w in _window(toks, i, 3)):
                c[("negctx", "negation")] += 1
            for w in ctx:
                c[("negctxword", w)] += 1
        if t in lex.obligations:
            c[("oblig", t)] += 1
        if t in lex.conditions and not (t in ("before", "after") and _is_time(nxt, lex)):
            c[("cond", t)] += 1
        if t in lex.exclusions and (t != "extra" or priced):
            c[("excl", t)] += 1
        if t in lex.free:
            c[("free", "free")] += 1
        if t in lex.inclusions and priced:
            c[("incl", t)] += 1
        if t in lex.reasons:
            c[("cause", t)] += 1
        if t in lex.commitment_modals:
            p1 = toks[i - 1] if i else ""
            p2 = toks[i - 2] if i > 1 else ""
            if p1 in lex.commitment_subjects or (p2 in lex.commitment_subjects and p1 in lex.adverbs):
                c[("commit", f"{p1 if p1 in lex.commitment_subjects else p2} {t}")] += 1
    return c
