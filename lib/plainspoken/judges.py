"""Judge input and reply recording: the CLI side of the check skill's judge step.

The judges are read-only, so the CLI writes their replies. A reply is recorded only when it is one JSON object for
the right group and the article's current hash (and, for JR, the justification file's current hash), and only
while the article has a current lint, whose profile_sha256 and ruleset_version the recorded file carries. A J1–J4
reply must also echo its input's `input_digest`, a digest of the whole line `judge-input` printed. The line is
rebuilt for the current draft, so a reply to a stale input, or to a hand-built one without the current digest, is
refused (#43, #61). The judge only echoes the digest, so a record can't show that the line reached the judge
unedited: an edit that keeps the genuine digest still records (`input_digest`)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from plainspoken import config, report
from plainspoken.justify import file_sha, read_json
from plainspoken.profile import Profile
from plainspoken.registry import load_config

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = ROOT / "data" / "rubrics" / "judges.md"
GROUPS = report.GROUPS
_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*)\n\s*```\s*$", re.S | re.I)


def input_digest(line: dict) -> str:
    """A digest of one judge-input line as printed: the canonical JSON of every field but `input_digest` (#61).
    `record_reply` rebuilds the line `judge_input` would print now and compares, so a reply never records when that
    line differs from the one the judge was given. The judge only echoes the field, so it can't show that the line
    reached the judge unedited: an edit that keeps the genuine digest still records."""
    canon = json.dumps({k: v for k, v in line.items() if k != "input_digest"}, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def judge_input(article: Path, profile: Profile, reports_dir: Path, cwd: Path) -> list[dict]:
    paths = report.report_paths(article, reports_dir, cwd)
    lint = read_json(paths["lint"])
    sha = report.sha256(article)
    if lint is None or lint.get("article_sha256") != sha or lint.get("profile_sha256") != profile.sha256:
        raise ValueError(f"no current lint for {article} with profile {profile.name}: run `check` first")
    ctype = lint.get("content_type", "article")
    rules = [r for r in load_config().rules_for_profile(profile, ctype)
             if r.group and "judge" in r.method and r.status != "shadow"]
    out = []
    for g in GROUPS:
        mine = [r for r in rules if r.group == g]
        ids = [r.id for r in mine]
        item = {
            "group": g,
            "article": str(Path(article).resolve()),
            "article_sha256": sha,
            "content_type": ctype,
            "rules": ids,
            "severities": {r.id: r.severity for r in mine},  # the default; a rubric entry may set its own
            "candidates": [f for f in lint["findings"] if f["severity"] == "CANDIDATE" and f["rule"] in ids],
            "rubric": str(RUBRIC),
            "calibration_notes": profile.calibration_notes or None,
            "visible_frontmatter_keys": list(profile.visible_frontmatter_keys),
            "faq_frontmatter_key": profile.faq_frontmatter_key,
        }
        if g == "J4":
            item["human_markers"] = [f for f in lint["findings"] if f["rule"] in ("HM", "15")]
        item["input_digest"] = input_digest(item)
        out.append(item)
    return out


def open_lint(article: Path, reports_dir: Path, cwd: Path, keep: set[str] = frozenset()) -> list[dict]:
    """The current lint's findings that fail at merge whatever the judges say (#74): every BLOCK, and every WARN of
    a rule the lint owns (a `lint+judge` rule's WARN is the judge's call). Judges on a draft with one of these can't
    pass it, and fixing it after them reruns all four, so `judge-input` holds them back. A rule in `keep` (with or
    without the lint's `r` prefix) is one the writer leaves on purpose, such as a WARN they'll justify."""
    lint = read_json(report.report_paths(article, reports_dir, cwd)["lint"]) or {}
    rules = load_config().rules
    out = []
    for f in lint.get("findings", []):
        rid = f.get("rule")
        rule = rules.get(rid)
        if rid in keep or f"r{rid}" in keep or rule is None:
            continue
        if f.get("severity") == "BLOCK" or (f.get("severity") == "WARN" and rule.method == "lint"):
            out.append(f)
    return out


def _parse(text: str) -> dict:
    m = _FENCE.match(text)
    body = m.group(1) if m else text
    try:
        data = json.loads(body)
    except ValueError:
        raise ValueError("reply is not one JSON object (no prose before or after it)") from None
    if not isinstance(data, dict):
        raise ValueError("reply is not one JSON object")
    return data


def record_reply(article: Path, group: str, text: str, reports_dir: Path, cwd: Path,
                 profile: str | Profile | None = None) -> Path:
    """Validate one reply and write its judge file. `profile` is the profile the check used (a Profile, or a name or
    path as `--profile` takes it); None finds it from the lint. J1–J4 need it to rebuild the line judge-input
    prints now."""
    if group not in (*GROUPS, "JR"):
        raise ValueError(f"unknown group {group!r}")
    data = _parse(text)
    if data.get("group") != group:
        raise ValueError(f"reply is for group {data.get('group')!r}, expected {group}")
    if data.get("article_sha256") != report.sha256(article):
        raise ValueError("stale: the reply judged a different version of the article")
    if not isinstance(data.get("verdicts"), list):
        raise ValueError("reply has no verdicts list")
    paths = report.report_paths(article, reports_dir, cwd)
    lint = read_json(paths["lint"])
    if (lint is None or lint.get("article_sha256") != data["article_sha256"]
            or lint.get("ruleset_version") != load_config().version or not isinstance(lint.get("profile_sha256"), str)):
        raise ValueError(f"no current lint for {Path(article).name}: run `check` first")
    if group == "JR":
        if not paths["justify"].is_file() or data.get("justify_sha256") != file_sha(paths["justify"]):
            raise ValueError("stale: the JR reply reviewed a different justify file")
    else:
        prof = profile if isinstance(profile, Profile) else config.profile_for_lint(lint, cwd, profile)
        if prof is None or prof.sha256 != lint["profile_sha256"]:
            raise ValueError(f"can't find the profile the check used ({lint.get('profile')}): pass it with --profile")
        try:
            line = next(x for x in judge_input(article, prof, reports_dir, cwd) if x["group"] == group)
        except (KeyError, TypeError):  # a hash-current lint can still be hand-damaged
            raise ValueError(f"no current lint for {Path(article).name}: run `check` first") from None
        if data.get("input_digest") != line["input_digest"]:
            raise ValueError(f"the {group} reply's input_digest doesn't match this draft's judge input (hand-built "
                             f"or stale input): rerun `judge-input` and give the judge its {group} line unchanged")
    # Bound to the profile and ruleset the lint used: merge treats a judge file from another one as stale.
    data["profile_sha256"], data["ruleset_version"] = lint["profile_sha256"], lint["ruleset_version"]
    paths[group].parent.mkdir(parents=True, exist_ok=True)
    report.write_atomic(paths[group], json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return paths[group]


_FENCE_LINE = re.compile(r"(?m)^[ \t]*```[ \t]*(?:json)?[ \t]*$", re.I)


def parse_replies(text: str) -> list:
    """The replies in one file: a JSON list, or JSON values one after another (code-fence lines are dropped).
    Raises ValueError when anything else is in the file, so a reply with prose around it is never half-read."""
    body = _FENCE_LINE.sub("", text).strip()
    try:
        data = json.loads(body)
    except ValueError:
        data, out, dec, i = None, [], json.JSONDecoder(), 0
        while i < len(body):
            try:
                obj, i = dec.raw_decode(body, i)
            except ValueError:
                raise ValueError("replies are not JSON objects one after another, or one JSON list "
                                 "(no prose between or around them)") from None
            out.append(obj)
            while i < len(body) and body[i].isspace():
                i += 1
    else:
        out = data if isinstance(data, list) else [data]
    return out


def record_all(article: Path, text: str, reports_dir: Path, cwd: Path,
               profile: str | Profile | None = None) -> list[tuple[str, Path | None, str | None]]:
    """Record J1–J4 from one file of replies, each validated as `record_reply` does, each by its own `group`.
    Returns `(group, written path or None, reason or None)` per group, J1 to J4, then one row per reply that isn't
    for J1–J4 (JR is recorded on its own). A bad reply never stops the others. Raises ValueError when the file
    can't be parsed at all."""
    replies = parse_replies(text)
    out: list[tuple[str, Path | None, str | None]] = []
    for g in GROUPS:
        mine = [r for r in replies if isinstance(r, dict) and r.get("group") == g]
        if len(mine) != 1:
            out.append((g, None, f"{len(mine)} replies for {g} in the file" if mine else "no reply for it in the file"))
            continue
        try:
            out.append((g, record_reply(article, g, json.dumps(mine[0]), reports_dir, cwd, profile), None))
        except ValueError as e:
            out.append((g, None, str(e)))
    for r in replies:
        if not isinstance(r, dict) or r.get("group") not in GROUPS:
            label = str(r.get("group")) if isinstance(r, dict) else "?"
            out.append((label, None, "not a J1–J4 reply (record JR with --group JR)" if isinstance(r, dict)
                        else "an item that isn't a JSON object"))
    return out
