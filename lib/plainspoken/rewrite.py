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
once. No model is called."""
from __future__ import annotations

import re
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
    """The comparison form of a number: thousands separators dropped (`2,500` → `2500`); a decimal point stays."""
    return n.replace(",", "") if GROUPED.fullmatch(n) else n


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
    if source is not None:
        src = parse(_read(Path(source)), path=str(source), profile=profile, content_type=content_type)
        known = {number_key(n) for n in numbers(_visible(src))}
        for n in numbers(text):
            if number_key(n) not in known and n not in new:
                new.append(n)
    verdict = "FAIL" if blocks or em_dashes > cap or new else "PASS"
    return {"draft": str(draft), "source": None if source is None else str(source), "profile": profile.name,
            "content_type": content_type, "blocks": blocks, "em_dashes": em_dashes, "em_dash_cap": cap,
            "new_numbers": new, "words": metrics.compute(doc, cfg)["words"], "verdict": verdict}


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
    return "\n".join([
        f"rewrite: {g['verdict']} · {Path(g['draft']).name} · {g['profile']} · {g['content_type']}",
        f"  lint BLOCKs: {', '.join('r' + r for r in g['blocks']) or 'none'}",
        f"  em dashes: {g['em_dashes']} (cap {g['em_dash_cap']})",
        f"  new numbers: {nums}",
        f"  words: {g['words']}",
    ])
