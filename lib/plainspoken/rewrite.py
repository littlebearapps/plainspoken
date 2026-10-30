"""Engine-side rewrite graders (Phase 6 evals).

`grade` checks one rewrite the way the `evals/rewrite/` cases' regex graders check a reply, with the engine's own
rules: it FAILs on any lint BLOCK (the lint checks `check` runs, `report.lint_doc`), on more em dashes than the
content type's cap (`em_dash_max` from the ruleset, layered default → profile → content type, as rule 1 reads it),
or on a number the draft has that the source doesn't. The em-dash cap is checked here as well as by rule 1, so a
profile that switches rule 1 off still can't pass a rewrite over the cap.

Numbers are digit runs with `,` or `.` inside them. A comma is a thousands separator only between groups of three
digits (`2,500`, `1,000,000`); those commas are dropped before comparing, so `2,500` and `2500` are the same number,
either way round. Any other comma separates numbers (`4,7` is 4 and 7), and `40` (from `40%`) is new when the source
has only `4`. Em dashes and numbers are counted in the visible text the lint reads (`checks_lexical.text_units`): body
sentences, H2/H3 headings and visible frontmatter, not code, list markers or frontmatter dates. Each file is read
once. No model is called.

Numbers written as words count too, on both sides (`word_numbers`): zero to nineteen, the tens (twenty to ninety, and
compounds like twenty-one), hundred, thousand and million with a count before them ("two hundred and twelve" is 212,
"a hundred" is 100), and "a dozen" (12). So "seven in every ten" is 7 and 10, and matches a source's `7` and `10`.
Ordinals ("second"), fractions ("half"), plurals ("hundreds", "dozens") and a scale word with no count of its own
aren't numbers here (in "2 million" only the 2 counts; "a few thousand" has none), and nor is "one" on its own: it's
mostly a pronoun ("no one", "one of them"). It counts inside a compound ("one hundred", "twenty-one").

A number the source doesn't have is *derived*, not new, when it's worked out from the source's own numbers
(`derivation`): a rounding of one source number to a coarser place (a whole number, the nearest 10, 100 …) no more
than 6% off it (150 for 151, "about 20" for 19); the sum, difference or product of two different source numbers; their
ratio (a / b: exact, or rounded when the piece number has decimals); or, for a rate, one source number's share of
another at the rate's base, rounded to the piece number's decimal places: 71% is 100 × 151 / 212, and "seven in every
ten" is 10 × 151 / 212 (a rate is a number followed by `%` or "per cent", base 100, or by "in", "in every", "out of"
or "out of every" and a base; a rate's base is part of it, so it's derived along with it).
A spelled count from two to five is derived, too, when the piece's sentence that holds it names that many people or
places the source names, as a list ("Two sisters, Ana and Ruth Silva", from "sisters Ana and Ruth Silva"):
`counted_names`.
Derived numbers are listed with how they were worked out, so a reader can check them, and don't fail a rewrite; only
new ones do."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from itertools import permutations
from pathlib import Path

from plainspoken import metrics, report
from plainspoken.checks_lexical import text_units
from plainspoken.doc import parse
from plainspoken.profile import Profile
from plainspoken.registry import load_config

NUMBER = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)*")
GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)*")  # thousands separators: 2,500 · 1,000,000 · 12,500.5
SUFFIXES = (".md", ".txt")


def numbers(text: str) -> list[str]:
    """Every number in `text`, as written, in order (repeats kept). A run whose commas aren't thousands separators
    is several numbers: `4,7` is `4` and `7`."""
    out: list[str] = []
    for n in NUMBER.findall(text):
        out += [n] if "," not in n or GROUPED.fullmatch(n) else [p for p in n.split(",") if p]
    return out


def number_key(n: str) -> str:
    """The comparison form of a number: thousands separators dropped (`2,500` → `2500`); a decimal point stays. A
    number in words is its value in digits (`twenty-one` → `21`)."""
    if not n[:1].isdigit():
        found = word_numbers(n)
        return str(found[0][1]) if len(found) == 1 else n
    return n.replace(",", "") if GROUPED.fullmatch(n) else n


# --- numbers written as words ---------------------------------------------------------------------------------------
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine".split())}
_TEENS = {w: i + 10 for i, w in enumerate(
    "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000}
_WORDS = {**_UNITS, **_TEENS, **_TENS, **_SCALES, "dozen": 12}
_W = "(?:" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")\b"
# A run of number words joined by spaces, hyphens or "and", with an optional "a"/"an" in front ("a hundred").
WORD_RUN = re.compile(rf"\b(?:an?[ \t]+(?={_W}))?{_W}(?:(?:[ \t]+and[ \t]+|[ \t-]+){_W})*", re.I)
_TOKEN = re.compile(rf"{_W}|\band\b|\ban?\b", re.I)


def _parse_run(run: str) -> list[tuple[int, int, int]]:
    """The numbers in one run of number words, as (start, end, value) in the run. A run splits where the words stop
    making one number ("seven and ten" is 7 and 10). Bare "one" and a scale word with no count aren't numbers."""
    out: list[tuple[int, int, int]] = []
    state = {"start": None, "end": 0, "total": 0, "cur": 0, "last": None, "words": [], "a": None}

    def flush() -> None:
        words = state["words"]
        bare = words == ["one"] or (len(words) == 1 and words[0] in _SCALES and state["a"] is None)
        if words and not bare:
            out.append((state["start"], state["end"], state["total"] + state["cur"]))
        state.update(start=None, total=0, cur=0, last=None, words=[], a=None)

    for m in _TOKEN.finditer(run):
        w = m.group(0).lower()
        if w in ("a", "an"):
            flush()
            state["a"] = m.start()
            continue
        if w == "and":
            if state["last"] not in ("hundred", "thousand", "million"):
                flush()
            continue
        kind = ("unit" if w in _UNITS else "teen" if w in _TEENS else "tens" if w in _TENS
                else "dozen" if w == "dozen" else w)
        last = state["last"]
        if kind in ("unit", "teen", "tens") and (last in ("unit", "teen") or (last == "tens" and kind != "unit")):
            flush()
        elif kind == "unit" and last == "tens" and state["cur"] % 10:
            flush()
        elif kind in ("hundred", "dozen") and (last in ("hundred", "thousand", "million", "dozen")
                                               or state["cur"] >= 100):
            flush()
        elif kind in ("thousand", "million") and last in ("thousand", "million", "dozen"):
            flush()
        if state["start"] is None:
            a = state["a"]
            state["start"] = a if a is not None and kind in ("hundred", "thousand", "million", "dozen") else m.start()
            if state["start"] != a:
                state["a"] = None
        state["words"].append(w)
        state["end"] = m.end()
        if kind in ("unit", "teen", "tens"):
            state["cur"] += _WORDS[w]
        elif kind == "hundred":
            state["cur"] = max(state["cur"], 1) * 100
        elif kind == "dozen":
            state["cur"] = max(state["cur"], 1) * 12
        else:
            state["total"] += max(state["cur"], 1) * _SCALES[w]
            state["cur"] = 0
        state["last"] = kind
    flush()
    return out


def word_numbers(text: str) -> list[tuple[str, int]]:
    """Every number written in words in `text`, as (words as written, value), in order (repeats kept)."""
    out: list[tuple[str, int]] = []
    for run in WORD_RUN.finditer(text):
        out += [(run.group(0)[a:b], v) for a, b, v in _parse_run(run.group(0))]
    return out


PERCENT = re.compile(r"[ \t]?(?:%|per[ \t]?cent\b|percent\b)", re.I)
RATE = re.compile(r"[ \t]+(?:in|out[ \t]+of)[ \t]+(?:every[ \t]+)?", re.I)  # "seven in every ten", "3 out of 4"


def figures(text: str) -> list[tuple[str, str, str | None]]:
    """Every number in `text`, in digits or in words, as (as written, comparison key, rate base), in text order. The
    rate base is `100` for a percentage (`%`, "per cent"), the next number's key for "seven in every ten" or "3 out of
    4", else None."""
    found = []
    for m in NUMBER.finditer(text):
        whole = m.group(0)
        if "," not in whole or GROUPED.fullmatch(whole):
            found.append((m.start(), m.end(), whole))
            continue
        pos = m.start()
        for part in whole.split(","):  # `4,7` is two numbers
            if part:
                found.append((pos, pos + len(part), part))
            pos += len(part) + 1
    for run in WORD_RUN.finditer(text):
        found += [(run.start() + a, run.start() + b, run.group(0)[a:b]) for a, b, _ in _parse_run(run.group(0))]
    found.sort()
    out = []
    for i, (_, end, n) in enumerate(found):
        rate = RATE.match(text, end)
        base = ("100" if PERCENT.match(text, end)
                else number_key(found[i + 1][2]) if rate and i + 1 < len(found) and found[i + 1][0] == rate.end()
                else None)
        out.append((n, number_key(n), base))
    return out


# --- derived numbers: worked out from the source's own ----------------------------------------------------------------
ROUNDING_SLACK = Decimal("0.06")  # a rounding is at most 6% off the number it rounds (151 → 150, 19 → 20)


def _value(key: str) -> Decimal | None:
    try:
        v = Decimal(key)
    except InvalidOperation:  # `1.4.0`, a version, isn't a value
        return None
    return v if v.is_finite() else None


def _fmt(v: Decimal) -> str:
    return f"{v.normalize():f}"


def derivation(n: str, sources: list[str], base: str | None = None) -> str | None:
    """How piece number `n` (a comparison key) is worked out from the source numbers' keys, or None when it isn't:
    "= 1.4" (the same value), "≈ 151" (a rounding), "= 212 + 151", "= 212 − 151", "= 151 × 2", "≈ 212 / 151" or, for a rate with this `base`
    (`figures`), "≈ 100 × 151 / 212". The rules are in the module docstring."""
    p, m = _value(n), None if base is None else _value(base)
    if p is None:
        return None
    vals = sorted({v for v in (_value(k) for k in sources) if v is not None}, reverse=True)
    if p in vals:  # the same value written another way (`1.40` for `1.4`)
        return f"= {_fmt(p)}"
    for s in vals:  # a rounding of one source number
        if s <= 0 or abs(p - s) > s * ROUNDING_SLACK:
            continue
        place = s.as_tuple().exponent + 1
        while Decimal(10) ** place <= s * 10:
            if s.quantize(Decimal(1).scaleb(place), rounding=ROUND_HALF_UP) == p:
                return f"≈ {_fmt(s)}"
            place += 1
    exp = p.as_tuple().exponent
    step = Decimal(1).scaleb(min(exp, 0))

    def near(x: Decimal) -> bool:  # x rounded to p's own decimal places
        try:
            return x.quantize(step, rounding=ROUND_HALF_UP) == p
        except InvalidOperation:  # too many digits to round: not a match
            return False

    for a, b in permutations(vals, 2):
        if a > b and a + b == p:
            return f"= {_fmt(a)} + {_fmt(b)}"
        if a > b and a - b == p:
            return f"= {_fmt(a)} − {_fmt(b)}"
        if a > b and a * b == p:
            return f"= {_fmt(a)} × {_fmt(b)}"
        if b != 0 and (a / b == p or (exp < 0 and near(a / b))):
            return f"{'=' if a / b == p else '≈'} {_fmt(a)} / {_fmt(b)}"
        if m is not None and b != 0 and near(m * a / b):
            return f"{'=' if m * a / b == p else '≈'} {_fmt(m)} × {_fmt(a)} / {_fmt(b)}"
    return None


COUNT_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5}
_NAME = r"[A-Z][\w'’-]*(?: [A-Z][\w'’-]*)*"
_NAME_LIST = re.compile(rf"\b({_NAME})((?:, {_NAME})*),? and ({_NAME})")


def counted_names(word: str, text: str, source: str) -> str | None:
    """How a spelled count (`two` … `five`) in `text` counts names the source gives, or None: some sentence of the
    piece that holds the word also lists exactly that many capitalised names ("Ana and Ruth Silva", "Hobart, Launceston
    and Devonport"), and every one of them is in the source. A sentence-initial capital ("Two") is the word itself, not
    a name, so it's never counted."""
    n = COUNT_WORDS.get(word.lower())
    if n is None:
        return None
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if not re.search(rf"\b{re.escape(word)}\b", sentence, re.I):
            continue
        for m in _NAME_LIST.finditer(sentence):
            names = [m.group(1), *[x for x in m.group(2).split(", ") if x], m.group(3)]
            names = [x for x in names if x.lower() not in COUNT_WORDS]
            if len(names) == n and all(re.search(rf"\b{re.escape(x)}\b", source) for x in names):
                return f"counts {n} names in the source ({' and '.join(names)})"
    return None


def _read(path: Path) -> str:
    """The file's text, read once. ValueError naming the file when it isn't UTF-8; OSError when it can't be read."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{path}: not UTF-8 text") from None


def _visible(doc) -> str:
    return "\n".join(text for _, text, _ in text_units(doc))


def grade(draft: Path, source: Path | None, profile: Profile, content_type: str = "article", cfg=None) -> dict:
    """Grade one rewrite. `source` None skips the number check (nothing to compare with). Raises ValueError for a
    bad profile, content type or non-UTF-8 file (naming it), and OSError for an unreadable one."""
    cfg = load_config() if cfg is None else cfg
    cfg.check_profile(profile)
    draft = Path(draft)
    doc = parse(_read(draft), path=str(draft), profile=profile, content_type=content_type)
    _, findings = report.lint_doc(doc, profile, content_type, cfg)
    blocks = sorted({f["rule"] for f in findings if f["severity"] == "BLOCK"})
    text = _visible(doc)
    em_dashes = text.count("—")
    cap = cfg.thresholds(profile, content_type)["em_dash_max"]
    new: list[str] = []
    derived: list[dict] = []
    if source is not None:
        src = parse(_read(Path(source)), path=str(source), profile=profile, content_type=content_type)
        src_text = _visible(src)
        known = [k for _, k, _ in figures(src_text)]
        seen = set(known)
        rate: str | None = None  # a derived rate this number is the base of ("seven" in "seven in every ten")
        for n, k, base in figures(text):
            rate_of, rate = rate, None
            if k in seen:
                continue
            how = f"base of the rate {rate_of} in {n}" if rate_of else derivation(k, known, base)
            if how is None and base is None:
                how = counted_names(n, text, src_text)
            if how is not None and base not in (None, "100") and how != derivation(k, known):
                rate = n  # derived as a rate, so its base comes with it
            if how is None:
                new.append(n)
            else:
                derived.append({"number": n, "from": how})
            seen.add(k)
    verdict = "FAIL" if blocks or em_dashes > cap or new else "PASS"
    warns = sum(1 for f in findings if f["severity"] == "WARN")
    return {"draft": str(draft), "source": None if source is None else str(source), "profile": profile.name,
            "content_type": content_type, "blocks": blocks, "em_dashes": em_dashes, "em_dash_cap": cap,
            "new_numbers": new, "derived_numbers": derived, "words": metrics.compute(doc, cfg)["words"],
            "verdict": verdict,
            "block_findings": sum(1 for f in findings if f["severity"] == "BLOCK"), "warn_findings": warns}


def _files(folder: Path, recursive: bool = False) -> list[Path]:
    folder = Path(folder)
    found = folder.rglob("*") if recursive else folder.iterdir()
    return sorted(p for p in found if p.is_file() and p.suffix in SUFFIXES
                  and not any(part.startswith(".") for part in p.relative_to(folder).parts))


def grade_many(drafts_dir: Path, sources_dir: Path | None, profile: Profile, content_type: str = "article",
               cfg=None, *, recursive: bool = False) -> list[dict]:
    """Grade every `.md`/`.txt` draft in `drafts_dir` (and, with `recursive`, in its subfolders; hidden files and
    folders are skipped), each against the file in `sources_dir` with the same stem (any of those suffixes).
    `sources_dir` None grades without sources. A draft with no source, or with two, is a ValueError naming it: a
    silent skip would pass a number check that never ran."""
    cfg = load_config() if cfg is None else cfg
    sources: dict[str, list[Path]] = {}
    if sources_dir is not None:
        for p in _files(sources_dir):
            sources.setdefault(p.stem, []).append(p)
    rows = []
    for draft in _files(drafts_dir, recursive):
        source = None
        if sources_dir is not None:
            found = sources.get(draft.stem, [])
            if len(found) != 1:
                what = "no source" if not found else f"{len(found)} sources"
                raise ValueError(f"{draft.name}: {what} named {draft.stem}.* in {sources_dir}")
            source = found[0]
        rows.append(grade(draft, source, profile, content_type, cfg))
    return rows


def summarise(g: dict) -> str:
    """The human-readable lines `eval rewrite` prints without --json."""
    nums = ("not checked (no --source)" if g["source"] is None
            else ", ".join(g["new_numbers"]) or "none")
    lines = [
        f"rewrite: {g['verdict']} · {Path(g['draft']).name} · {g['profile']} · {g['content_type']}",
        f"  lint BLOCKs: {', '.join('r' + r for r in g['blocks']) or 'none'}",
        f"  em dashes: {g['em_dashes']} (cap {g['em_dash_cap']})",
        f"  new numbers: {nums}",
    ]
    if g.get("derived_numbers"):
        lines.append(f"  derived numbers (from the source's own, not counted as new): {derived_list(g)}")
    return "\n".join(lines + [f"  words: {g['words']}"])


def derived_list(g: dict) -> str:
    """`150 ≈ 151, 363 = 212 + 151`: each derived number with how it was worked out."""
    return ", ".join(f"{d['number']} {d['from']}" for d in g.get("derived_numbers", []))


# --- the rewrite delta: both arms of a `claude plugin eval` rewrite run, lint-counted --------------------------------
SOCIAL_CASES = ("rewrite--linkedin-post",)  # graded with the social caps, as in the case-file tests
# Drafting cases whose piece is a short social text: `<suite>--<kind>-…` with one of these kinds.
SOCIAL_KINDS = ("sms-", "linkedin-", "instagram-", "x-thread-", "bluesky-", "facebook-")
PIECE = re.compile(r"<<<PIECE[ \t]*\n(.*?)\n[ \t]*PIECE>>>", re.S)


def content_type_for(case: str) -> str:
    """`social` for the short social pieces (their caps differ), else `article`."""
    base = case.removesuffix("--slash")
    kind = base.split("--", 1)[1] if "--" in base else base
    return "social" if base in SOCIAL_CASES or kind.startswith(SOCIAL_KINDS) else "article"


def piece(reply: str) -> str:
    """The piece itself: the text between `<<<PIECE` and `PIECE>>>` when a case asks for those markers (a skill's
    report around it isn't the writing being judged), else the whole reply."""
    found = PIECE.findall(reply)
    text = found[-1].strip() if found else reply
    # A model without the plugin sometimes adds a note that the slash command isn't installed: that's about the run,
    # not the writing, and a reader would spot it at once.
    lines = [ln for ln in text.splitlines() if "plainspoken" not in ln.lower()]
    while lines and lines[0].strip() in ("", "---", "***", "___"):  # a leading rule would read as frontmatter
        lines.pop(0)
    return "\n".join(lines).strip()


def passage(prompt: str) -> str:
    """The pasted text of a rewrite case: the prompt's blockquote lines, without the `> ` marker."""
    return "\n".join(ln[2:] if ln.startswith("> ") else ln[1:] for ln in prompt.splitlines() if ln.startswith(">"))


def final_reply(trace: Path) -> str | None:
    """The run's final reply: the `result` of the last `result` row in a kept `trace.jsonl`; None when there is none."""
    import json
    reply = None
    for line in Path(trace).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("type") == "result" and isinstance(row.get("result"), str):
            reply = row["result"]
    return reply


def delta(result: dict, suite_root: Path, profile: Profile, cfg=None, save: Path | None = None) -> dict:
    """Grade every run of a with-without rewrite run (the `aggregate-result.json` of `claude plugin eval --tag
    rewrite[-slash] --keep-temp`) with the engine, per arm: lint BLOCK and WARN findings, em dashes over the cap, new
    numbers. The regex graders only pass or fail; the counts show a difference even when both arms pass them all.
    A run whose trace is gone (no --keep-temp) is listed as missing, never counted as clean. `save` writes each graded
    piece to `<save>/<case>/<arm>-<run>.md`, for the blind readers (`eval pairwise`)."""
    import tempfile
    cfg = load_config() if cfg is None else cfg
    rows, missing = [], []
    for case in result.get("cases", []):
        name = case["name"]
        ctype = content_type_for(name)
        prompt = (Path(suite_root) / case["dir"] / "prompt.md").read_text(encoding="utf-8")
        scaffold = Path(suite_root) / case["dir"] / "scaffold.sh"
        draft_in = re.search(r"<<'DRAFT'\n(.*?)\nDRAFT", scaffold.read_text(encoding="utf-8"), re.S) if scaffold.is_file() else None
        with tempfile.TemporaryDirectory(prefix="plainspoken-delta-") as tmp:
            source = Path(tmp) / "source.md"
            # the source is the pasted passage, or for a fix case the draft its scaffold saved
            source.write_text((draft_in.group(1) if draft_in else passage(prompt.split("\n---\n", 1)[-1])) + "\n",
                              encoding="utf-8")
            for arm in ("with", "without"):
                for i, run in enumerate(case.get("arms", {}).get(arm, [])):
                    trace = run.get("tracePath")
                    # a run that ended on an API error has an error message, not a rewrite, as its final reply
                    text = (final_reply(Path(trace)) if trace and Path(trace).is_file() and not run.get("error")
                            else None)
                    if text is None:
                        missing.append(f"{name} {arm} #{i + 1}")
                        continue
                    text = piece(text)
                    draft = Path(tmp) / f"{arm}-{i}.md"
                    draft.write_text(text + "\n", encoding="utf-8")
                    if save is not None:
                        out = Path(save) / name
                        out.mkdir(parents=True, exist_ok=True)
                        (out / f"{arm}-{i + 1}.md").write_text(text + "\n", encoding="utf-8")
                    g = grade(draft, source, profile, ctype, cfg)
                    rows.append({"case": name, "arm": arm, "run": i + 1, "blocks": g["block_findings"],
                                 "warns": g["warn_findings"], "em_dashes_over": max(0, g["em_dashes"] - g["em_dash_cap"]),
                                 "new_numbers": len(g["new_numbers"]),
                                 "derived_numbers": len(g["derived_numbers"]), "derived": derived_list(g),
                                 "verdict": g["verdict"]})

    def mean(arm: str, key: str) -> float | None:
        vals = [r[key] for r in rows if r["arm"] == arm]
        return round(sum(vals) / len(vals), 3) if vals else None

    summary = {}
    for key in ("blocks", "warns", "em_dashes_over", "new_numbers", "derived_numbers"):
        w, wo = mean("with", key), mean("without", key)
        summary[key] = {"with": w, "without": wo, "delta": None if w is None or wo is None else round(wo - w, 3)}
    passes = {arm: sum(1 for r in rows if r["arm"] == arm and r["verdict"] == "PASS") for arm in ("with", "without")}
    return {"profile": profile.name, "rows": rows, "missing": missing, "summary": summary, "passes": passes,
            "runs": {arm: sum(1 for r in rows if r["arm"] == arm) for arm in ("with", "without")}}


def summarise_delta(d: dict) -> str:
    lines = [f"rewrite delta · {d['profile']} · runs with {d['runs']['with']}, without {d['runs']['without']}"
             f" · engine PASS with {d['passes']['with']}, without {d['passes']['without']}",
             "  mean per rewrite (lower is better; delta = without - with, positive favours the plugin):"]
    for key, label in (("blocks", "lint BLOCK findings"), ("warns", "lint WARN findings"),
                       ("em_dashes_over", "em dashes over the cap"), ("new_numbers", "new numbers")):
        s = d["summary"][key]
        lines.append(f"  {label}: with {s['with']}, without {s['without']}, delta {s['delta']}")
    s = d["summary"].get("derived_numbers")
    if s and (s["with"] or s["without"]):  # listed, never counted against an arm
        lines.append(f"  derived numbers (worked out from the source's own; not counted as new): with {s['with']},"
                     f" without {s['without']}")
    for r in d["rows"]:
        derived = f" · derived {r['derived_numbers']} ({r['derived']})" if r.get("derived_numbers") else ""
        lines.append(f"    {r['case']} {r['arm']} #{r['run']}: {r['verdict']} · BLOCK {r['blocks']} · WARN {r['warns']}"
                     f" · em-dash over {r['em_dashes_over']} · new numbers {r['new_numbers']}{derived}")
    if d["missing"]:
        lines.append(f"  missing traces (run with --keep-temp): {', '.join(d['missing'])}")
    return "\n".join(lines)
