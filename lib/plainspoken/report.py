"""Lint report and merge (coverage proof) for anti-AI checks."""
import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from plainspoken import _util, justify, metrics
from plainspoken.checks_lexical import CHECKS as LEXICAL
from plainspoken.checks_structural import CHECKS as STRUCTURAL
from plainspoken.doc import CONTENT_TYPES, parse
from plainspoken.profile import Profile
from plainspoken.registry import load_config

GROUPS = ("J1", "J2", "J3", "J4")
ALL_CHECKS = {**LEXICAL, **STRUCTURAL}
LINT_METHODS = ("lint", "lint+judge")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_atomic(path: Path, text: str | bytes) -> Path:
    """Write `text` to a temp file in `path`'s folder (made if missing) and return the temp path; `commit_staged`
    puts it in place. Bytes are written as they are. The file gets the mode a plain write would (0o666 less the
    umask), not mkstemp's 0600. Nothing is left behind when it fails."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with (os.fdopen(fd, "wb") if isinstance(text, bytes) else os.fdopen(fd, "w", encoding="utf-8")) as f:
            f.write(text)
        mask = os.umask(0)
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return Path(tmp)


def commit_staged(staged: Path, path: Path) -> None:
    """Rename a `stage_atomic` temp file over `path` (atomic within one folder). On failure the temp file is
    removed and the error raised."""
    try:
        os.replace(staged, path)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise


def write_atomic(path: Path, text: str | bytes) -> None:
    """Write `text` to `path` through a temp file in the same folder and `os.replace`, so a reader never sees half a
    report (`stage_atomic` then `commit_staged`)."""
    commit_staged(stage_atomic(path, text), path)


def report_key(article: Path, cwd: Path) -> str:
    """The file-name key for an article's reports: `<stem>-<8 hex>`, the hex from its project-relative path.

    Two `index.md` files in different folders get different keys (docs/report-contract.md)."""
    return _util.path_key(article, cwd)


def report_paths(article: Path, reports_dir: Path, cwd: Path) -> dict[str, Path]:
    key = report_key(article, cwd)
    names = {"lint": "lint", "JR": "JR.judge", "justify": "justify", "report": "report", "reply": "reply",
             "claims": "claims", "claims-check": "claims-check",
             "delivery": "delivery", "delivery-reply": "delivery-reply",
             **{g: f"{g}.judge" for g in GROUPS}}
    out = {name: Path(reports_dir) / f"{key}.{suffix}.json" for name, suffix in names.items()}
    out["checked"] = Path(reports_dir) / f"{key}.checked.md"  # the check snapshot: the article's bytes, as checked
    return out


def lint_doc(doc, profile: Profile, content_type: str, cfg) -> tuple[list[str], list[dict]]:
    """(the lint rule ids run, their findings as dicts) for a parsed `doc`; shadow rules' findings are INFO. The
    caller has checked the profile against `cfg`."""
    lint_rules = [r.id for r in cfg.rules_for_profile(profile, content_type) if r.method in LINT_METHODS]
    findings = []
    for rid in lint_rules:
        findings += [f.to_dict() for f in ALL_CHECKS[rid](doc, cfg)]
    shadow = {r.id for r in cfg.rules.values() if r.status == "shadow"}
    return lint_rules, [{**f, "severity": "INFO", "message": "[shadow] " + f["message"]} if f["rule"] in shadow
                        else f for f in findings]


def run_lint(path: Path, profile: Profile, content_type: str = "article", cfg=None) -> dict:
    """Lint one article. `cfg` is the ruleset to use (the caller's, so capture sees the same lists); None loads the
    default ruleset as before."""
    cfg = load_config() if cfg is None else cfg
    cfg.check_profile(profile)
    doc = parse(path.read_text(encoding="utf-8"), path=str(path), profile=profile, content_type=content_type)
    lint_rules, findings = lint_doc(doc, profile, content_type, cfg)
    metrics_out = metrics.compute(doc, cfg)
    words = max(metrics_out["words"], 1)
    counts = Counter(f["rule"] for f in findings)
    rates = {rid: round(n * 1000 / words, 2) for rid, n in sorted(counts.items())}
    return {
        "article": str(path),
        "profile": profile.name,
        "profile_sha256": profile.sha256,
        "ruleset_version": cfg.version,
        "content_type": content_type,
        "article_sha256": sha256(path),
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lint_rules": lint_rules,
        "findings": findings,
        "metrics": metrics_out,
        "rates_per_1k": rates,
        "allows": [asdict(a) for a in doc.allows],
    }


def rule_counts(lint: dict) -> dict[str, dict[str, int]]:
    """rule id → severity → number of findings."""
    counts: dict[str, dict[str, int]] = {}
    for f in lint["findings"]:
        sev = counts.setdefault(f["rule"], {})
        sev[f["severity"]] = sev.get(f["severity"], 0) + 1
    return counts


def lint_status(lint: dict) -> str:
    return "BLOCK" if any(f["severity"] == "BLOCK" for f in lint["findings"]) else "CLEAN"


def summarise(lint: dict) -> str:
    by: dict[str, list[dict]] = {}
    for f in lint["findings"]:
        by.setdefault(f["severity"], []).append(f)
    lines = [f"anti-AI lint · {Path(lint['article']).name} · {lint['profile']} · {lint_status(lint)}"]
    for sev in ("BLOCK", "WARN", "CANDIDATE"):
        hits = by.get(sev, [])
        for f in hits[:15]:
            lines.append(f"  {sev:9} r{f['rule']:<4} L{f['line']:<4} {f['message'][:140]}")
        if len(hits) > 15:
            lines.append(f"  {sev:9} … {len(hits) - 15} more (see --json)")
    lines.append(f"  metrics: {json.dumps(lint['metrics'])}")
    return "\n".join(lines)


# --- merge: coverage proof + status -------------------------------------------------------------

def _resolved(rid: str, accepted: set[str], rejected: set[str], aliases: tuple[tuple[str, str], ...]) -> bool:
    """Accepted directly, or through its alias partner (the ruleset's `[aliases]`, e.g. NR-2
    re-thresholds 7d and NR-1 re-thresholds 1). A rule whose own justification JR rejected stays unresolved
    whatever its partner got."""
    if rid in rejected:
        return False
    return rid in accepted or any((rid == a and b in accepted) or (rid == b and a in accepted) for a, b in aliases)


def read_json(path: Path) -> dict | None:
    """The JSON object at `path`, or None when it's missing, unreadable or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # JSONDecodeError and UnicodeDecodeError are both ValueErrors
        return None
    return data if isinstance(data, dict) else None


def _lint_shape_ok(lint: dict) -> bool:
    """The keys merge reads, with the right types (a hash-current lint JSON can still be hand-damaged)."""
    findings = lint.get("findings")
    return (isinstance(lint.get("profile"), str) and isinstance(lint.get("profile_sha256"), str)
            and isinstance(lint.get("lint_rules"), list) and isinstance(lint.get("metrics"), dict)
            and isinstance(findings, list)
            and all(isinstance(f, dict) and "rule" in f and "severity" in f for f in findings))


def _lint_entry(rule, findings: list[dict]) -> dict:
    """A lint rule's verdict. Severity comes from the findings, so a WARN finding under a BLOCK rule
    (e.g. 12f MATTR while `mattr_blocking` is false) stays WARN; the merge never invents a stricter one."""
    sevs = {f["severity"] for f in findings}
    failed = bool(sevs & {"BLOCK", "WARN"})
    severity = "BLOCK" if "BLOCK" in sevs else ("WARN" if failed else rule.severity)
    return {"source": "lint", "verdict": "fail" if failed else "pass", "severity": severity, "findings": findings}


def _bad_verdict(v, g: str, expected: dict, seen: set) -> bool:
    if not isinstance(v, dict):
        return True
    rid = str(v.get("rule"))
    rule = expected.get(rid)
    return (rule is None or rule.group != g or rid in seen or v.get("verdict") not in ("pass", "fail")
            or not isinstance(v.get("evidence", []), list)  # the report schema's evidence is a list
            or (v["verdict"] == "fail" and not v.get("evidence")))


def merge(article: Path, reports_dir: Path, profile: Profile, cwd: Path | None = None) -> dict:
    """Combine `<key>.lint.json` + `<key>.J{1..4}.judge.json` into `<key>.report.json`.
    Fails closed: anything missing, stale (hash ≠ the article's current hash, or a lint or judge file made with
    another profile or another ruleset version) or malformed → INCOMPLETE.
    A failing WARN rule without an accepted justification → UNRESOLVED (never PASS)."""
    cfg = load_config()
    judge_block_rules = {r.id for r in cfg.rules.values() if r.judge_may_block}
    d = reports_dir
    paths = report_paths(article, d, cwd or Path.cwd())
    key = report_key(article, cwd or Path.cwd())
    sha = sha256(article)
    problems: list[str] = []
    rules_out: dict[str, dict] = {}

    lint = read_json(paths["lint"])
    lint_ok = (lint is not None and lint.get("article_sha256") == sha and _lint_shape_ok(lint)
               and lint.get("profile_sha256") == profile.sha256)
    ruleset_ok = lint is not None and lint.get("ruleset_version") == cfg.version
    # Only trust the lint's content_type once the lint is hash-current, well-formed and made with this profile; a bad
    # file falls back to "article". (A lint from another ruleset still names the right content type.)
    ctype = lint["content_type"] if lint_ok and lint.get("content_type") in CONTENT_TYPES else "article"
    if not lint_ok:
        problems.append("lint report missing, unreadable, malformed, stale (article changed) or made with another "
                        "profile — rerun `check`")
    elif not ruleset_ok:
        problems.append(f"lint report made under ruleset {lint.get('ruleset_version')!r}, current is "
                        f"{cfg.version!r} (the ruleset changed) — rerun `check`")
    if not (lint_ok and ruleset_ok):
        lint = run_lint(article, profile, ctype)
    expected = {r.id: r for r in cfg.rules_for_profile(profile, ctype) if r.method != "n/a" and r.status != "shadow"}

    for rid in lint["lint_rules"]:
        rule = expected.get(rid)
        if rule is None:
            continue
        entry = _lint_entry(rule, [f for f in lint["findings"] if f["rule"] == rid])
        if rule.method == "lint+judge":  # the judge owns the verdict; a lint BLOCK still stands
            entry["lint_block"] = entry["severity"] == "BLOCK" and entry["verdict"] == "fail"
            entry["verdict"] = "pending-judge"
        rules_out[rid] = entry

    for g in sorted({r.group for r in expected.values() if r.group}):
        j = read_json(paths[g])
        if j is None:
            problems.append(f"{g}: judge file missing or not valid JSON")
            continue
        if j.get("article_sha256") != sha:
            problems.append(f"{g}: judged a different version of the article (stale) — rerun the judge")
            continue
        if j.get("profile_sha256") != profile.sha256 or j.get("ruleset_version") != cfg.version:
            problems.append(f"{g}: judged under another profile or ruleset (stale) — rerun the judge")
            continue
        verdicts = j.get("verdicts")
        if not isinstance(verdicts, list):
            problems.append(f"{g}: no verdicts list")
            continue
        seen: set[str] = set()
        for v in verdicts:
            rid = str(v.get("rule")) if isinstance(v, dict) else "?"
            if rid in cfg.rules and rid not in expected:
                continue  # a registered rule that doesn't apply to this profile (ruling B6)
            if _bad_verdict(v, g, expected, seen):
                problems.append(f"{g}: bad verdict entry for rule {rid}")
                continue
            seen.add(rid)
            prev = rules_out.get(rid, {})
            lint_block = prev.get("lint_block", False)
            judge_block = v.get("severity") == "BLOCK" and rid in judge_block_rules
            rules_out[rid] = {
                "source": f"judge:{g}",
                "verdict": "fail" if lint_block else v["verdict"],
                "judge_verdict": v["verdict"],  # the judge's own call, before a lint BLOCK overrides it (kaizen)
                "severity": "BLOCK" if lint_block or judge_block else expected[rid].severity,
                "evidence": v.get("evidence", []),
                "findings": prev.get("findings", []),
            }

    missing = sorted(rid for rid in expected if rules_out.get(rid, {}).get("verdict") in (None, "pending-judge"))
    blocks = sorted(rid for rid, e in rules_out.items() if e["verdict"] == "fail" and e["severity"] == "BLOCK")
    warns = sorted(rid for rid, e in rules_out.items() if e["verdict"] == "fail" and e["severity"] == "WARN")
    # fix or justify (2026-09-29): a WARN fail needs an accepted reason
    res = justify.resolve(d, key, sha, warns, stamps={"profile_sha256": profile.sha256, "ruleset_version": cfg.version})
    problems += res["problems"]
    rejected = {j["rule"] for j in res["justified"] if j["review"] == "reject"}
    unresolved = [rid for rid in warns if not _resolved(rid, res["accepted"], rejected, cfg.aliases)]
    if missing or problems:
        status = "INCOMPLETE"
    elif blocks:
        status = "FAIL"
    elif unresolved:
        status = "UNRESOLVED"
    else:
        status = "PASS"
    merged = {
        "article": str(article),
        "profile": profile.name, "profile_sha256": profile.sha256, "ruleset_version": cfg.version,
        "content_type": ctype, "article_sha256": sha,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": status,
        "blocks": blocks, "warns": warns,
        "unresolved": unresolved, "justified": res["justified"], "unused_justifications": res["unused"],
        "problems": problems,
        "coverage": {"expected": len(expected), "covered": len(expected) - len(missing), "missing": missing},
        "metrics": lint["metrics"], "allows": lint.get("allows", []), "rules": rules_out,
    }
    # Atomic, so a host sink reading the report never sees half a file; the shape is
    # data/schemas/report.schema.json.
    write_atomic(paths["report"], json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return merged


def merge_lines(merged: dict) -> list[str]:
    """What `merge` prints: its status line, then any `missing verdicts:` and `problem:` lines."""
    cov = merged["coverage"]
    lines = [f"{merged['status']} · coverage {cov['covered']}/{cov['expected']}"
             f" · BLOCK {', '.join(merged['blocks']) or '-'} · WARN {', '.join(merged['warns']) or '-'}"
             f" · unresolved {', '.join(merged['unresolved']) or '-'}"]
    if cov["missing"]:
        lines.append(f"  missing verdicts: {', '.join(cov['missing'])}")
    return lines + [f"  problem: {p}" for p in merged["problems"]]


def saved_check(article: Path, reports_dir: Path, profile: Profile, cwd: Path) -> tuple[str, list[str]]:
    """(status, lines) of the last `merge` for this article as it is now, read from `<key>.report.json`.

    Runs and writes nothing. No report, an unreadable one, or one for another version of the article, profile or
    ruleset → INCOMPLETE with the reason, never an earlier result."""
    merged = read_json(report_paths(article, reports_dir, cwd)["report"])
    if merged is None:
        return "INCOMPLETE", ["INCOMPLETE (not run: no merged report for this draft)"]
    current = (merged.get("article_sha256") == sha256(article) and merged.get("profile_sha256") == profile.sha256
               and merged.get("ruleset_version") == load_config().version)
    if not current:
        return "INCOMPLETE", ["INCOMPLETE (stale: the last merge checked another version of the draft, or ran "
                              "under another profile or ruleset; run the check again)"]
    try:
        if merged["status"] in ("PASS", "FAIL", "UNRESOLVED", "INCOMPLETE"):
            return merged["status"], merge_lines(merged)
    except (KeyError, TypeError):
        pass
    return "INCOMPLETE", ["INCOMPLETE (the merged report can't be read; run the check again)"]


def word_count(article: Path, profile: Profile) -> int:
    """The draft's length as it is now, counted as the check's `words` metric counts it."""
    doc = parse(article.read_text(encoding="utf-8"), path=str(article), profile=profile)
    return metrics.compute(doc, load_config())["words"]


def reports_dir_default(cwd: Path) -> Path:
    """Where reports go when the caller doesn't say: the project's .plainspoken/reports."""
    return cwd / ".plainspoken" / "reports"
