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
    warns = sum(1 for f in findings if f["severity"] == "WARN")
    return {"draft": str(draft), "source": None if source is None else str(source), "profile": profile.name,
            "content_type": content_type, "blocks": blocks, "em_dashes": em_dashes, "em_dash_cap": cap,
            "new_numbers": new, "words": metrics.compute(doc, cfg)["words"], "verdict": verdict,
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
    return "\n".join([
        f"rewrite: {g['verdict']} · {Path(g['draft']).name} · {g['profile']} · {g['content_type']}",
        f"  lint BLOCKs: {', '.join('r' + r for r in g['blocks']) or 'none'}",
        f"  em dashes: {g['em_dashes']} (cap {g['em_dash_cap']})",
        f"  new numbers: {nums}",
        f"  words: {g['words']}",
    ])


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
                    text = final_reply(Path(trace)) if trace and Path(trace).is_file() else None
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
                                 "new_numbers": len(g["new_numbers"]), "verdict": g["verdict"]})

    def mean(arm: str, key: str) -> float | None:
        vals = [r[key] for r in rows if r["arm"] == arm]
        return round(sum(vals) / len(vals), 3) if vals else None

    summary = {}
    for key in ("blocks", "warns", "em_dashes_over", "new_numbers"):
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
    for r in d["rows"]:
        lines.append(f"    {r['case']} {r['arm']} #{r['run']}: {r['verdict']} · BLOCK {r['blocks']} · WARN {r['warns']}"
                     f" · em-dash over {r['em_dashes_over']} · new numbers {r['new_numbers']}")
    if d["missing"]:
        lines.append(f"  missing traces (run with --keep-temp): {', '.join(d['missing'])}")
    return "\n".join(lines)
