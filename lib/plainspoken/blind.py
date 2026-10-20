"""The blind reader test (Phase 6 evals), part one: the pairs, the raters' form and the panel prompts.
Does a reader pick plainspoken output as the person's writing about as often as the person's own?

`build` turns a spec of matched texts (a person's real writing and plainspoken output on the same brief) into
unlabelled pairs: both texts are normalised to plain paragraphs (no headings, links, lists, bold, tables, callouts,
curly quotes), cut to roughly the same length (the shortest run of whole sentences with at least N words), and
refused when they still differ by more than 15% or spell in different locales (AU/GB against US), so neither format,
length nor spelling gives the author away. A seeded, balanced shuffle puts half the people's texts in
position A. `pairs.jsonl` holds only the pair id and the two texts; the answers live in `key.json`, and `.heldout`
marks the folder as held-out data that no kaizen job may mine. A build that fails part-way removes what it wrote.

Two tiers judge the pairs. Tier 1 is people: `form` writes `form.md` and `answers.csv` for the author to send (the
plugin never contacts anyone). Tier 2 is the model panel, a proxy: `prompts` asks every pair in both orders (A/B
swapped), with a one-letter reply schema (`parse_blind`) that names no tell, rule or plugin. Scoring lives in
`blind_score`."""
from __future__ import annotations

import hashlib
import html
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from plainspoken import judges

SCHEMA = 1
PAIRS = "pairs.jsonl"
KEY = "key.json"
BUILD = "build.json"
HELDOUT = ".heldout"
FORM = "form.md"
ANSWERS = "answers.csv"
ORDERS = ("ab", "ba")
MAX_LENGTH_GAP = 0.15  # of the longer excerpt's word count
CSV_FIELDS = ("rater", "pair", "human", "better")
SPEC_KEYS = {"id", "human", "generated", "model", "brief"}


class BlindError(ValueError):
    """Bad input: a spec, folder or answers file that can't be used (the CLI exits 2)."""


class BlindRefusal(ValueError):
    """`build` refuses items it can't match for length or spelling locale (the CLI exits 1). Nothing is written."""

    def __init__(self, ids: list[str], why: list[str]):
        self.ids = ids
        super().__init__("; ".join(why))


# ---------------------------------------------------------------- normalise

_FRONTMATTER = re.compile(r"\A---[ \t]*\n.*?\n(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1\s*>", re.S | re.I)
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_ATX = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
_SETEXT_EQ = re.compile(r"^\s{0,3}=+\s*$")
_SETEXT_DASH = re.compile(r"^\s{0,3}-+\s*$")
_RULE = re.compile(r"^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_QUOTE = re.compile(r"^\s*(?:>\s?)+")
_CALLOUT = re.compile(r"^\*\*Try this:?\*\*", re.I)
_ITEM = re.compile(r"^\s*(?:[-*+]|(?P<num>\d{1,9})[.)])\s+(?:\[[ xX]\]\s+)?(?P<text>.*)$")
_JUMP = re.compile(r"\[[^\]]+\]\(#[^)\s]*\)")
_REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*\S")
_PARENS = r"\((?:[^()]|\([^()]*\))*\)"
_IMAGE = re.compile(r"!\[[^\]]*\](?:" + _PARENS + r"|\[[^\]]*\])")
_LINK = re.compile(r"\[([^\]]+)\](?:" + _PARENS + r"|\[[^\]]*\])")
_FOOTNOTE = re.compile(r"\[\^[^\]]+\]")
_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
_ATTRS = re.compile(r"\s*\{#[\w-]+\}")
_CODE = re.compile(r"(`+)(.+?)\1")
_EMPHASIS = (re.compile(r"\*\*(.+?)\*\*"), re.compile(r"(?<!\w)__(.+?)__(?!\w)"),
             re.compile(r"\*(?!\s)(.+?)(?<!\s)\*"), re.compile(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)"),
             re.compile(r"~~(.+?)~~"))
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!>|~])")
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
                         "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"'})


def _inline(text: str) -> str:
    spans: list[str] = []  # inline code keeps its content verbatim: no emphasis or escape handling inside it

    def keep(m: re.Match) -> str:
        spans.append(m.group(2).strip())
        return f"\x00{len(spans) - 1}\x00"

    text = _CODE.sub(keep, text.replace("\x00", ""))
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _FOOTNOTE.sub("", text)
    text = _TAG.sub("", text)
    text = _ATTRS.sub("", text)
    for pattern in _EMPHASIS:
        text = pattern.sub(r"\1", text)
    text = _ESCAPE.sub(r"\1", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)
    text = html.unescape(text).translate(_QUOTES)
    return " ".join(text.split())


def normalise(markdown: str) -> str:
    """Plain paragraphs, one per line, separated by a blank line. Frontmatter, headings, images, HTML (tags and
    comments, so module markers too), fenced code, tables, rules, footnotes and `> **Try this:**` callouts go;
    links become their text, and a list item that is only a link to an anchor on the page (a contents list) goes;
    bold, italic, strike and inline-code markers go; each list item becomes its own paragraph; blockquote markers
    go; curly quotes become straight ones; soft line breaks become spaces. As in CommonMark, an ordered marker other
    than `1.` can't interrupt a paragraph, so a wrapped line that starts "1999." stays prose."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    text = _FRONTMATTER.sub("", text, count=1)
    text = _SCRIPT.sub("", _COMMENT.sub("", text))
    paras: list[list[str]] = [[]]
    fence = None
    skip_block = False  # inside a callout or a table: drop lines until a blank one
    in_list = False  # the open paragraph is a list item's continuation, so a `2.` there starts the next item
    blank_before = True

    def br() -> None:
        if paras[-1]:
            paras.append([])

    for line in text.split("\n"):
        if fence:
            if re.match(r"^\s{0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*$", line):
                fence = None
            continue
        m = _FENCE.match(line)
        if m:
            br()
            fence = m.group(1)
            continue
        if not line.strip():
            skip_block = False
            blank_before = True
            br()
            continue
        after_blank, blank_before = blank_before, False
        if skip_block:
            continue
        if _TABLE_SEP.match(line):
            if paras[-1]:
                paras[-1].pop()  # the header row
            br()
            skip_block = True
            continue
        if line.lstrip().startswith("|") or _ATX.match(line) or _REF_DEF.match(line):
            br()
            in_list = False
            continue
        if _SETEXT_EQ.match(line) or _RULE.match(line):
            if paras[-1] and (_SETEXT_EQ.match(line) or _SETEXT_DASH.match(line)):
                paras[-1].pop()  # the text of a setext heading (`===` or `---` right under it)
            br()
            in_list = False
            continue
        quoted = _QUOTE.match(line)
        body = line[quoted.end():] if quoted else line
        if quoted and _CALLOUT.match(body.strip()):
            br()
            skip_block = True
            continue
        item = _ITEM.match(body)
        if item and not (item.group("num") and int(item.group("num")) != 1 and paras[-1] and not in_list):
            br()
            in_list = True
            if _JUMP.fullmatch(item.group("text").strip()):
                continue  # a page's own contents list ("jump to" links) is navigation, not prose
            paras[-1].append(item.group("text"))
            br()  # an item is its own paragraph; a continuation line joins the next one
            continue
        if after_blank and not paras[-1] and not body[:1].isspace():
            in_list = False  # a new, unindented paragraph after a blank line ends the list
        paras[-1].append(body.strip())
    out = [_inline(" ".join(p)) for p in paras if p]
    return "\n\n".join(p for p in out if p)


# ---------------------------------------------------------------- excerpt

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][\"')\]])\s+")


def _words(text: str) -> int:
    return len(text.split())


def excerpt(text: str, words: int) -> str:
    """From the start of `text` (normalised paragraphs), the shortest run of whole sentences with at least `words`
    words, paragraph breaks kept. A text with fewer words comes back whole."""
    if not isinstance(words, int) or words < 1:
        raise ValueError("words must be 1 or more")
    out: list[str] = []
    count = 0
    for para in text.split("\n\n"):
        kept: list[str] = []
        for sentence in _SENTENCE_END.split(para.strip()):
            if not sentence:
                continue
            kept.append(sentence)
            count += _words(sentence)
            if count >= words:
                break
        if kept:
            out.append(" ".join(kept))
        if count >= words:
            break
    return "\n\n".join(out)


# ---------------------------------------------------------------- spelling locale

# A small fixed list of word families whose spelling differs between Australian/British and US English, each
# (AU/GB pattern, US pattern). Look-alikes that Australian English also spells the US way (Labor, honorary,
# humorous) and words both locales share (prize, size, promise) are left out on purpose.
_ISE = r"(?:organ|real|recogn|apolog|priorit|summar|optim|critic|emphas|minim|maxim|special|custom|categor|" \
       r"standard|final|util|author|character)"
_OUR = r"(?:col|fav|behavi|hon|neighb|hum|flav|rum|endeav)"
_RE = r"(?:cent|theat|lit|fib|calib|somb|spect|lust|meag)"
_LL = r"(?:travel|cancel|model|label|fuel|signal|counsel|level|marvel|total)"
_SPELLING = tuple((re.compile(gb, re.I), re.compile(us, re.I)) for gb, us in (
    (rf"\b{_ISE}is(?:e|es|ed|ing|ation|ations)\b", rf"\b{_ISE}iz(?:e|es|ed|ing|ation|ations)\b"),
    (r"\banalys(?:e|ed|ing)\b", r"\banalyz(?:e|es|ed|ing)\b"),
    (rf"\b{_OUR}our(?:s|ed|ing|ite|ites|able|ful|hood|less)?\b",
     rf"\b{_OUR}or(?:s|ed|ing|ite|ites|able|ful|hood|less)?\b"),
    (rf"\b{_RE}res?\b", rf"\b{_RE}ers?\b"),
    (r"\bcentred\b", r"\bcentered\b"),
    (rf"\b{_LL}l(?:ed|ing|er|ers)\b", rf"\b{_LL}(?:ed|ing|er|ers)\b"),
    (r"\b(?:catalogue|defence|offence|aluminium)s?\b", r"\b(?:catalog|defense|offense|aluminum)s?\b"),
))
# grey/gray is also a surname (Asa Gray, Earl Grey): lowercase only, and never right after a capitalised word that
# doesn't start its sentence (a first name).
_GREY = (re.compile(r"\bgreys?\b"), re.compile(r"\bgrays?\b"))
_SENTENCE_START = re.compile(r"(?:\A|[.!?][\"')\]]?\s+)\Z")


def _grey_count(pattern: re.Pattern, text: str) -> int:
    n = 0
    for m in pattern.finditer(text):
        name = re.search(r"\b([A-Z][a-z]+)\s+\Z", text[:m.start()])
        if name and not _SENTENCE_START.search(text[:name.start()]):
            continue  # a capitalised word mid-sentence: a first name, so this is a surname
        n += 1
    return n


LOCALES = ("au/gb", "us", "mixed", "unknown")


def spelling(text: str) -> dict:
    """`{au_gb, us, locale}`: how many AU/GB and US spelling markers `text` has (a small fixed list of word
    families: -ise/-ize, -our/-or, -re/-er, doubled l, a few others), and the locale they show: `au/gb` or `us`
    when every marker is that locale's, `mixed` when both appear, `unknown` when there are none. grey/gray counts in
    lowercase only and not after a first name, so the surnames Grey and Gray aren't markers."""
    gb = sum(len(g.findall(text)) for g, _ in _SPELLING) + _grey_count(_GREY[0], text)
    us = sum(len(u.findall(text)) for _, u in _SPELLING) + _grey_count(_GREY[1], text)
    locale = "unknown" if not (gb or us) else "mixed" if gb and us else "au/gb" if gb else "us"
    return {"au_gb": gb, "us": us, "locale": locale}


# ---------------------------------------------------------------- build

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path, what: str, item: str) -> tuple[str, bytes]:
    try:
        raw = Path(path).read_bytes()
        return raw.decode("utf-8"), raw
    except FileNotFoundError:
        raise BlindError(f"item {item}: {what} file {path} doesn't exist") from None
    except UnicodeDecodeError:
        raise BlindError(f"item {item}: {what} file {path} isn't UTF-8 text") from None
    except OSError as e:
        raise BlindError(f"item {item}: can't read {what} file {path} ({e.strerror or type(e).__name__})") from None


def _check_spec(spec: list) -> None:
    if not isinstance(spec, list) or not spec:
        raise BlindError("the spec needs at least one item")
    seen: set[str] = set()
    for n, item in enumerate(spec, 1):
        if not isinstance(item, dict):
            raise BlindError(f"spec item {n} isn't a table of id, human, generated and model")
        name = item.get("id")
        label = repr(name) if isinstance(name, str) and name else f"#{n}"
        extra = sorted(set(item) - SPEC_KEYS)
        if extra:
            raise BlindError(f"item {label}: unknown key {', '.join(extra)} (allowed: {', '.join(sorted(SPEC_KEYS))})")
        for k in ("id", "human", "generated", "model"):
            if not isinstance(item.get(k), str) or not item[k].strip():
                raise BlindError(f"item {label}: {k} must be a non-empty string")
        if "brief" in item and not isinstance(item["brief"], str):
            raise BlindError(f"item {label}: brief must be a string")
        if name in seen:
            raise BlindError(f"item {label}: the id is used twice")
        seen.add(name)


def load_spec(path: Path) -> list[dict]:
    """A spec file: JSON (a list of items) or TOML (`[[pair]]` tables). Relative `human` and `generated` paths are
    taken from the spec file's folder and made absolute, so `build.json` (and the eval history's drafts folder)
    names the real files whatever folder a later command runs from."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise BlindError(f"{path}: can't read the spec ({getattr(e, 'strerror', None) or type(e).__name__})") from None
    try:
        if path.suffix == ".toml":
            import tomllib
            data = tomllib.loads(text).get("pair")
        else:
            data = json.loads(text)
    except ValueError as e:
        raise BlindError(f"{path}: not a {'TOML' if path.suffix == '.toml' else 'JSON'} spec "
                         f"({str(e).splitlines()[0] if str(e) else type(e).__name__})") from None
    _check_spec(data)
    out = []
    for item in data:
        item = dict(item)
        for k in ("human", "generated"):
            p = Path(item[k]).expanduser()
            item[k] = str((p if p.is_absolute() else path.parent / p).resolve())
        out.append(item)
    return out


def _width(n: int) -> int:
    return max(2, len(str(n)))


def build(spec: list[dict], out: Path, *, words: int = 350, seed: int) -> dict:
    """Write the pairs for `spec` to `out`: `pairs.jsonl` (`{pair, a, b}`, no labels), `key.json` (`{pair: {human:
    "a"|"b", model, brief, id}}`), `.heldout` and `build.json` (seed, words, each source's sha256 and word counts).
    Pair ids are neutral (`p01`…) in spec order. BlindError for bad input, BlindRefusal (naming every item) when an
    item's two excerpts differ by more than 15% of the longer one's words, or when one spells AU/GB and the other US
    (`spelling`; unknown or mixed is allowed); either way nothing is written. A write that fails part-way (OSError)
    removes the files written so far, and the folder when the build made it."""
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise BlindError("seed must be a whole number")
    if not isinstance(words, int) or isinstance(words, bool) or words < 1:
        raise BlindError("words must be 1 or more")
    _check_spec(spec)
    out = Path(out)
    for name in (PAIRS, KEY):
        if (out / name).exists():
            raise BlindError(f"{out} already holds a build ({name}): use a new --out")
    width = _width(len(spec))
    made, refused, why = [], [], []
    for n, item in enumerate(spec, 1):
        texts, sources = {}, {}
        for side in ("human", "generated"):
            text, raw = _read(Path(item[side]), side, repr(item["id"]))
            cut = excerpt(normalise(text), words)
            if not cut:
                raise BlindError(f"item {item['id']!r}: the {side} file {item[side]} has no prose once normalised")
            texts[side] = cut
            sources[side] = {"path": str(item[side]), "sha256": _sha(raw), "words": _words(cut),
                             "spelling": spelling(cut)}
        wh, wg = sources["human"]["words"], sources["generated"]["words"]
        problems = []
        if abs(wh - wg) > MAX_LENGTH_GAP * max(wh, wg):
            problems.append(f"excerpts of {wh} (person) and {wg} (generated) words differ by more than "
                            f"{MAX_LENGTH_GAP:.0%}")
        sh, sg = sources["human"]["spelling"], sources["generated"]["spelling"]
        if {sh["locale"], sg["locale"]} == {"au/gb", "us"}:
            problems.append(f"the person's excerpt spells {sh['locale'].upper()} ({sh['au_gb']} AU/GB, {sh['us']} "
                            f"US markers) and the generated one {sg['locale'].upper()} ({sg['au_gb']} AU/GB, "
                            f"{sg['us']} US)")
        if problems:
            refused.append(item["id"])
            why.append(f"item {item['id']!r}: " + " and ".join(problems))
            continue
        made.append((f"p{n:0{width}d}", item, texts, sources))
    if refused:
        raise BlindRefusal(refused, why)
    sides = ["a"] * (len(made) // 2) + ["b"] * (len(made) - len(made) // 2)
    random.Random(seed).shuffle(sides)
    pairs, key, meta_sources = [], {}, []
    for (pair, item, texts, sources), human_side in zip(made, sides):
        a, b = (texts["human"], texts["generated"]) if human_side == "a" else (texts["generated"], texts["human"])
        pairs.append({"pair": pair, "a": a, "b": b})
        key[pair] = {"human": human_side, "model": item["model"], "brief": item.get("brief"), "id": item["id"]}
        meta_sources.append({"pair": pair, "id": item["id"], **sources})
    meta = {"schema": SCHEMA, "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seed": seed,
            "words": words, "max_length_gap": MAX_LENGTH_GAP, "pairs": len(pairs), "sources": meta_sources}
    files = ((HELDOUT, "Held-out eval data (blind reader test): never mine, quote or tune against these texts.\n"),
             (KEY, json.dumps(key, indent=2, ensure_ascii=False) + "\n"),
             (BUILD, json.dumps(meta, indent=2, ensure_ascii=False) + "\n"),
             (PAIRS, "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in pairs)))
    made = not out.exists()
    written: list[Path] = []
    try:
        out.mkdir(parents=True, exist_ok=True)
        for name, text in files:
            written.append(out / name)
            _write(out / name, text)
    except BaseException:  # a part-built folder would refuse the re-run as "already holds a build"
        for path in written:
            for leftover in (path, path.with_name(f".{path.name}.tmp")):
                leftover.unlink(missing_ok=True)
        if made:
            try:
                out.rmdir()
            except OSError:
                pass
        raise
    return meta


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def generated_folder(out: Path) -> str | None:
    """The folder holding the build's generated texts (their nearest common folder), resolved, or None when
    `build.json` can't say. The eval history pairs a blind score with the lint rate measured on that folder."""
    try:
        meta = json.loads((Path(out) / BUILD).read_text(encoding="utf-8"))
        folders = {str(Path(s["generated"]["path"]).resolve().parent) for s in meta["sources"]}
        return os.path.commonpath(sorted(folders)) if folders else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def read_pairs(out: Path) -> list[dict]:
    path = Path(out) / PAIRS
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise BlindError(f"{out}: no {PAIRS} (run `eval blind build` first)") from None
    except (OSError, UnicodeDecodeError) as e:
        raise BlindError(f"{path}: can't read it ({getattr(e, 'strerror', None) or type(e).__name__})") from None
    pairs = []
    for n, line in enumerate(lines, 1):
        try:
            p = json.loads(line)
        except ValueError:
            raise BlindError(f"{path}: line {n} isn't JSON") from None
        if not (isinstance(p, dict) and set(p) == {"pair", "a", "b"} and all(isinstance(v, str) for v in p.values())):
            raise BlindError(f"{path}: line {n} isn't a {{pair, a, b}} line")
        pairs.append(p)
    if not pairs:
        raise BlindError(f"{path}: no pairs")
    return pairs


def read_key(out: Path) -> dict:
    path = Path(out) / KEY
    try:
        key = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BlindError(f"{out}: no {KEY} (run `eval blind build` first)") from None
    except (OSError, UnicodeDecodeError, ValueError):
        raise BlindError(f"{path}: can't read it") from None
    if not isinstance(key, dict) or not all(isinstance(v, dict) and v.get("human") in ("a", "b")
                                            for v in key.values()):
        raise BlindError(f"{path}: not a blind-test key")
    return key


# ---------------------------------------------------------------- form

FORM_INTRO = """# Reading test

Each numbered pair below has two short texts, A and B, on the same subject. One of the two was written by a person.

For each pair, answer two questions:

1. Which text did a person write? (A or B)
2. Which text is better to read? (A or B)

Put your answers in `answers.csv`, one row per pair: your name or initials in `rater`, the pair's number (for
example `p01`) in `pair`, and `a` or `b` in `human` and in `better`. Answer every pair; if you aren't sure, go with
your best guess. Please read the texts on your own and don't look anything up.
"""


def form(out: Path) -> Path:
    """Write `form.md` (every pair, A then B as stored, and the two questions) and, unless it already exists,
    `answers.csv` (a header and one blank row per pair). Returns the form's path."""
    out = Path(out)
    pairs = read_pairs(out)
    parts = [FORM_INTRO]
    for p in pairs:
        parts.append(f"---\n\n## Pair {p['pair']}\n\n### A\n\n{p['a']}\n\n### B\n\n{p['b']}\n\n"
                     f"Pair {p['pair']}: which text did a person write, A or B? Which is better to read, A or B?\n")
    path = out / FORM
    _write(path, "\n".join(parts))
    answers = out / ANSWERS
    if not answers.exists():  # never overwrite answers someone has filled in
        buf = [",".join(CSV_FIELDS)] + [f",{p['pair']},," for p in pairs]
        _write(answers, "\n".join(buf) + "\n")
    return path


# ---------------------------------------------------------------- prompts

BLIND_PROMPT = """You'll read two short texts, A and B, on the same subject. One of the two was written by a person.

Answer two questions:
1. Which text did a person write?
2. Which text is better to read?

Reply with one JSON object and nothing else, each answer a single letter, "A" or "B":
{{"human": "A or B", "better": "A or B"}}

## Text A

{a}

## Text B

{b}
"""


def prompt(first: str, second: str) -> str:
    return BLIND_PROMPT.format(a=first, b=second)


def prompts(out: Path) -> list[tuple[str, str]]:
    """Two prompts per pair, keyed `<pair>|ab` (A = the pair's a) and `<pair>|ba` (the texts swapped)."""
    out_list = []
    for p in read_pairs(out):
        out_list.append((f"{p['pair']}|ab", prompt(p["a"], p["b"])))
        out_list.append((f"{p['pair']}|ba", prompt(p["b"], p["a"])))
    return out_list


def parse_blind(reply: str) -> tuple[dict | None, str]:
    """`({"human": "A"|"B", "better": "A"|"B"}, "")`, or `(None, reason)`. The body is one JSON object, bare or alone
    in a code fence, with those two keys and no others; a letter's case and surrounding spaces don't matter."""
    try:
        data = judges._parse(reply or "")
    except ValueError:
        return None, "not one JSON object"
    extra = sorted(str(k) for k in data if k not in ("human", "better"))
    if extra:
        return None, f"unexpected key{'' if len(extra) == 1 else 's'} {', '.join(extra)}"
    got = {}
    for k in ("human", "better"):
        v = data.get(k)
        if v is None:
            return None, f"no {k} answer"
        if not isinstance(v, str) or v.strip().upper() not in ("A", "B"):
            return None, f"{k} {v!r} isn't A or B"
        got[k] = v.strip().upper()
    return got, ""
