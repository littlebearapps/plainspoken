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
import json
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


def _split(text: str) -> list[tuple[str, str]]:
    """(word, as written) for each word, number and punctuation mark of `text`: lower case, contractions split
    ("won't" -> "will", "not"; "we'll" -> "we", "will", both parts written "won't" or "we'll"), curly apostrophes read
    as straight, a hyphenated word kept whole."""
    out: list[tuple[str, str]] = []
    for raw in _TOKEN.findall(text):
        t = raw.lower().replace("’", "'")
        if "-" in t:
            parts = [t]  # must-see, follow-up: one word, never a marker
        elif t.endswith("n't"):
            parts = [_CONTRACTED.get(t, t[:-3]), "not"]
        elif t.endswith("'ll"):
            parts = [t[:-3], "will"]
        elif t.endswith("'d"):
            parts = [t[:-2], "would"]
        elif re.search(r"'(?:re|ve|m|s)$", t):
            parts = [t.rsplit("'", 1)[0]]
        else:
            parts = [t]
        out += [(w, raw) for w in parts]
    return out


def tokens(text: str) -> list[str]:
    """The words of `text` as `markers` reads them (`_split`)."""
    return [w for w, _ in _split(text)]


def _written(parts: list[str]) -> str:
    """The words as written, a contraction's two halves once ("I'll", not "I'll I'll")."""
    out: list[str] = []
    for w in parts:
        if not out or out[-1] != w:
            out.append(w)
    return " ".join(out)


def _phrased(toks: list[tuple[str, str]], lex: Lexicon) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(toks):
        for words, lemma in lex.phrases:
            if tuple(w for w, _ in toks[i:i + len(words)]) == words:
                out.append((lemma, _written([r for _, r in toks[i:i + len(words)]])))
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


def _occurrences(sentence: str, lex: Lexicon) -> list[tuple[tuple[str, str], str]]:
    """Each marker in `sentence` as ((class, lemma), as written), with the context keys `markers` documents."""
    pairs = _phrased(_split(lex.frames.sub(" ", sentence)), lex)
    toks = [w for w, _ in pairs]
    occ: list[tuple[tuple[str, str], str]] = [(("excl", "plus GST/fees"), m.group(0).strip())
                                              for m in lex.tax.finditer(sentence)]
    priced = bool(lex.price_context.search(sentence))
    for i, (t, raw) in enumerate(pairs):
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if t in lex.negations:
            occ.append((("neg", "negation"), raw))  # one count for the class: "do not hold" -> "without" is no change
            ctx = [w for w in _window(toks, i) if w in lex.negation_context]
            if t == "without" or ctx or any(w in lex.commitment_subjects for w in _window(toks, i, 3)):
                occ.append((("negctx", "negation"), raw))
            occ += [(("negctxword", w), w) for w in ctx]
        if t in lex.obligations:
            occ.append((("oblig", t), raw))
        if t in lex.conditions and not (t in ("before", "after") and _is_time(nxt, lex)):
            occ.append((("cond", t), raw))
        if t in lex.exclusions and (t != "extra" or priced):
            occ.append((("excl", t), raw))
        if t in lex.free:
            occ.append((("free", "free"), raw))
        if t in lex.inclusions and priced:
            occ.append((("incl", t), raw))
        if t in lex.reasons:
            occ.append((("cause", t), raw))
        if t in lex.commitment_modals:
            p1 = toks[i - 1] if i else ""
            p2 = toks[i - 2] if i > 1 else ""
            if p1 in lex.commitment_subjects:
                occ.append((("commit", f"{p1} {t}"), _written([r for _, r in pairs[i - 1:i + 1]])))
            elif p2 in lex.commitment_subjects and p1 in lex.adverbs:
                occ.append((("commit", f"{p2} {t}"), _written([r for _, r in pairs[i - 2:i + 1]])))
    return occ


def markers(sentence: str, lex: Lexicon) -> Counter:
    """The marker counts of `sentence`, keyed `(class, lemma)`, plus the context keys the diff reads:
    `("negctx", "negation")` (a negation with a limit word or I/we near it) and `("negctxword", word)`."""
    return Counter(k for k, _ in _occurrences(sentence, lex))


# --- numbers and their qualifiers -------------------------------------------------------------------------------------
def _number_written(n: str, text: str) -> str:
    """`n` as `text` writes it, with its currency sign ("$300")."""
    m = re.search(rf"[$£€]\s?(?<![\d.,]){re.escape(n)}(?![\d])", text)
    return m.group(0).replace(" ", "") if m else n


def _qualified(text: str, lex: Lexicon) -> tuple[Counter, dict]:
    """(qualifier group, number key) for each number with a qualifier in front ("over 22", "up to 5"), and how each
    is written. "from" counts only before a price: "from 9am to 3pm" is a range."""
    from plainspoken.rewrite import figures
    out: Counter = Counter()
    written: dict = {}
    for m in lex.qualifier.finditer(text):
        word = m.group(1).lower()
        if lex.qualifiers.get(word) == "from" and not re.match(r"[$£€]", text[m.end():]):
            continue
        f = figures(text[m.end():m.end() + 30])
        if f:
            key = (lex.qualifiers[word], f[0][1])
            out[key] += 1
            written.setdefault(key, f"{m.group(1)} {_number_written(f[0][0], text[m.end():m.end() + 30])}")
    return out, written


# --- sentence alignment -----------------------------------------------------------------------------------------------
_STOP = frozenset("""a an the and or but of to in on at for with by from as is are was were be been being it its this that
these those i you we they he she my your our their me us them his her there here what which who whom whose do does
did done have has had just also very really get got go going come""".split())
_COMMENT = re.compile(r"<!--.*?-->", re.S)
MATCH = 0.3  # the share of the smaller sentence's content words two sentences must share to be paired


def _stem(t: str) -> str:
    t = {"children": "child", "kids": "child", "kid": "child"}.get(t, t)
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > 4 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def _content(s: str) -> set[str]:
    return {_stem(t) for t in tokens(s) if (t not in _STOP and len(t) > 2 and t.isalpha()) or t[:1].isdigit()}


def _prose(text: str) -> list[tuple[str, int]]:
    """(sentence, first line) for each prose sentence: frontmatter, fenced code and HTML comments left out, a
    heading's `#` and a table row's `|` taken off."""
    from plainspoken import capture, sentdiff
    text = _COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    lines = text.splitlines()
    skip = set(range(1, capture.frontmatter_end(lines) + 1))
    fence = None
    for n, raw in enumerate(lines, start=1):
        m = sentdiff._FENCE.match(raw)
        if fence is not None or m:
            skip.add(n)
            if m and (fence is None or m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)):
                fence = m.group(1) if fence is None else None
    out = []
    for s, first, _ in sentdiff.units(text):
        if first in skip:
            continue
        s = s.lstrip("#|").strip() if s.startswith(("#", "|")) else s
        if s:
            out.append((s, first))
    return out


def _groups(old: list[tuple[str, int]], new: list[tuple[str, int]]) -> list[tuple[list, list]]:
    """The changed sentences, grouped: inside a changed run, each sentence joins its best match on the other side
    (shared content words), so a join or a split is one group."""
    from plainspoken import sentdiff
    out = []
    for tag, i1, i2, j1, j2 in sentdiff.opcodes([" ".join(tokens(s)) for s, _ in old],
                                                [" ".join(tokens(s)) for s, _ in new]):
        if tag == "equal":
            continue
        o, n = old[i1:i2], new[j1:j2]
        if len(o) <= 1 or len(n) <= 1:
            out.append((o, n))
            continue
        co, cn = [_content(s) for s, _ in o], [_content(s) for s, _ in n]

        def score(a: set, b: set) -> float:
            return len(a & b) / max(1, min(len(a), len(b)))
        edges = set()
        for i, a in enumerate(co):
            j = max(range(len(n)), key=lambda j: score(a, cn[j]))
            if score(a, cn[j]) >= MATCH:
                edges.add((i, j))
        for j, b in enumerate(cn):
            i = max(range(len(o)), key=lambda i: score(co[i], b))
            if score(co[i], b) >= MATCH:
                edges.add((i, j))
        parent = {("o", i): ("o", i) for i in range(len(o))} | {("n", j): ("n", j) for j in range(len(n))}

        def find(x: tuple) -> tuple:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for i, j in edges:
            parent[find(("o", i))] = find(("n", j))
        comps: dict = {}
        for node in parent:
            comps.setdefault(find(node), []).append(node)

        def place(nodes: list) -> float:  # after-text order; a cut sentence where it stood
            news = [v for k, v in nodes if k == "n"]
            return min(news) / len(n) if news else min(v for _, v in nodes) / len(o)
        for nodes in sorted(comps.values(), key=place):
            out.append(([o[v] for k, v in sorted(nodes) if k == "o"], [n[v] for k, v in sorted(nodes) if k == "n"]))
    return out


# --- the diff ---------------------------------------------------------------------------------------------------------
def _words(key: tuple, n: int, side: list, other: list) -> list[str]:
    """How `n` of `key`'s markers on `side` are written, the ones the other side doesn't also write first."""
    mine = [w for k, w in side if k == key]
    theirs = Counter(w for k, w in other if k == key)
    gone = []
    for w in mine:
        if theirs[w]:
            theirs[w] -= 1
        else:
            gone.append(w)
    return (gone + [w for w in mine if w not in gone])[:n] or [key[1]]


def diff(before: str, after: str, lex: Lexicon | None = None) -> list[dict]:
    """The sentences `after` changed from `before` with a marker change inside, in after-text order:
    `{"id": "M1", "line" (after's line, 0 when cut), "before", "after", "items": [{"class", "change", "words"}]}`.
    A change is listed only when the whole text has fewer (dropped) or more (added) of that marker."""
    from plainspoken.rewrite import counted_names, derivation, figures
    lex = lex or load_lexicon()
    old, new = _prose(before), _prose(after)
    src_text, new_text = " ".join(s for s, _ in old), " ".join(s for s, _ in new)
    src_keys = [k for _, k, _ in figures(src_text)]
    new_keys = {k for _, k, _ in figures(new_text)}
    whole_o, whole_n = markers(src_text, lex), markers(new_text, lex)
    whole_qo, whole_qn = _qualified(src_text, lex)[0], _qualified(new_text, lex)[0]
    out = []
    for o, n in _groups(old, new):
        bt, at = " ".join(s for s, _ in o), " ".join(s for s, _ in n)
        oo, on = _occurrences(bt, lex), _occurrences(at, lex)
        mo, mn = Counter(k for k, _ in oo), Counter(k for k, _ in on)
        before_words = set(tokens(bt))
        found: list[tuple[str, str, list[str]]] = []
        for key, k in sorted((mo - mn).items()):
            cls = key[0]
            if DIRECTION.get(cls) not in ("both", "dropped") or whole_n[key] >= whole_o[key]:
                continue
            if cls == "neg" and not mo[("negctx", "negation")]:
                continue  # a dropped negation matters only beside the thing it limits
            found.append((cls, "dropped", _words(key, k, oo, on)))
        for key, k in sorted((mn - mo).items()):
            cls = key[0]
            if DIRECTION.get(cls) not in ("both", "added") or whole_n[key] <= whole_o[key]:
                continue
            if cls == "neg" and not (mn[("negctx", "negation")] and any(
                    w in before_words for (c, w), v in mn.items() if c == "negctxword" and v)):
                continue  # an added negation counts only where the sentence kept the word it limits (can -> can't)
            found.append((cls, "added", _words(key, k, on, oo)))
        for written, key, _ in figures(bt):
            if key not in new_keys:  # gone from the whole text, not moved or reworded
                found.append(("num", "dropped", [_number_written(written, bt)]))
        seen = set()
        for written, key, base in figures(at):
            if key in src_keys or key in seen:
                continue
            seen.add(key)
            if written.lower() in ("two", "three", "four", "five", "a dozen"):
                continue  # a spelled small count usually counts what the text lists (#158)
            if derivation(key, src_keys, base) or (base is None and counted_names(written, new_text, src_text)):
                continue  # worked out from the source's own numbers: eval rewrite lists these
            found.append(("num", "added", [_number_written(written, at)]))
        (qo, qwritten), (qn, _) = _qualified(bt, lex), _qualified(at, lex)
        for key, k in sorted((qo - qn).items()):
            if whole_qn[key] < whole_qo[key] and key[1] in new_keys:  # the number stayed, its qualifier went
                found.append(("qual", "dropped", [qwritten[key]]))
        items: dict = {}
        for cls, change, words in found:
            item = items.setdefault((cls, change), {"class": CLASSES[cls], "change": change, "words": []})
            item["words"] += [w for w in words if w not in item["words"]]
        if items:
            out.append({"id": f"M{len(out) + 1}", "line": n[0][1] if n else 0, "before": bt, "after": at,
                        "items": list(items.values())})
    return out


# --- the saved baseline and result (`plainspoken meaning-diff`) --------------------------------------------------------
def _paths(path: Path, root: Path, reports_dir: Path) -> dict:
    from plainspoken import report
    return report.report_paths(Path(path), Path(reports_dir), Path(root))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _shown(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


def start(path: Path, root: Path, reports_dir: Path) -> Path:
    """Save `path`'s bytes as the baseline (`<key>.before.md`) and drop any result from an earlier run. The text must
    read as UTF-8 (a UnicodeDecodeError otherwise, and nothing is written)."""
    from plainspoken import report
    data = Path(path).read_bytes()
    data.decode("utf-8")
    p = _paths(path, root, reports_dir)
    p["before"].parent.mkdir(parents=True, exist_ok=True)
    report.write_atomic(p["before"], data)
    p["meaning"].unlink(missing_ok=True)
    return p["before"]


def baseline(path: Path, root: Path, reports_dir: Path) -> str | None:
    """The saved baseline's text, or None when `start` never ran."""
    p = _paths(path, root, reports_dir)["before"]
    return p.read_bytes().decode("utf-8") if p.is_file() else None


def record(path: Path, root: Path, reports_dir: Path, before_text: str) -> dict:
    """Compare `before_text` with `path` now and write `<key>.meaning.json`, bound to both texts' sha256 and the word
    lists'. Returns what it wrote."""
    from plainspoken import report
    data = Path(path).read_bytes()
    rec = {"article": _shown(path, root), "before_sha256": _sha(before_text.encode("utf-8")),
           "after_sha256": _sha(data), "lexicon_sha256": lexicon_sha256(),
           "changes": diff(before_text, data.decode("utf-8"))}
    p = _paths(path, root, reports_dir)["meaning"]
    p.parent.mkdir(parents=True, exist_ok=True)
    report.write_atomic(p, json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    return rec


def saved(path: Path, root: Path, reports_dir: Path) -> tuple[str, list[dict]]:
    """(state, changes) of the saved result: `current` (bound to `path` as it is now, the saved baseline and these
    word lists), `stale` (any of those changed since), `missing` (a baseline but no result) or `no-baseline`. The
    changes come back only when current."""
    p = _paths(path, root, reports_dir)
    if not p["meaning"].is_file():
        return ("missing" if p["before"].is_file() else "no-baseline"), []
    try:
        rec = json.loads(p["meaning"].read_text(encoding="utf-8"))
        current = (rec["after_sha256"] == _sha(Path(path).read_bytes())
                   and rec["lexicon_sha256"] == lexicon_sha256()
                   and (not p["before"].is_file() or rec["before_sha256"] == _sha(p["before"].read_bytes())))
        changes = rec["changes"] if current and isinstance(rec["changes"], list) else []
    except (OSError, ValueError, KeyError, TypeError):
        return "stale", []
    return ("current" if current else "stale"), changes


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def what_changed(change: dict) -> str:
    """`dropped "isn't", "separate"; added "covers"` for one listed change."""
    parts = []
    for kind in ("dropped", "added"):
        words = [w for i in change["items"] if i["change"] == kind for w in i["words"]]
        if words:
            parts.append(f"{kind} " + ", ".join(f'"{w}"' for w in words))
    return "; ".join(parts)


def summarise(changes: list[dict], shown: int = 10, path: str = "") -> str:
    """One line per listed change (at most `shown`, then how many more and where), or `nothing listed`; always ends
    with the word-level footer."""
    if not changes:
        return f"meaning-diff: nothing listed\n{FOOTER}"
    lines = []
    for c in changes[:shown]:
        where = f"{c['id']} line {c['line']}" if c["line"] else f"{c['id']} cut"
        now = f'; now: "{_clip(c["after"], 80)}"' if c["after"] else ""
        lines.append(f'{where}: {what_changed(c)}; was: "{_clip(c["before"], 80)}"{now}')
    if len(changes) > shown:
        lines.append(f"… {len(changes) - shown} more in {path}" if path else f"… {len(changes) - shown} more")
    return "\n".join([*lines, FOOTER])
