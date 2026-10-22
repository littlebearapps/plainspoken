"""Judge input and reply recording: the CLI side of the check skill's judge step.

The judges are read-only, so the CLI writes their replies. A reply is recorded only when it is one JSON object for
the right group and the article's current hash (and, for JR, the justification file's current hash), and only
while the article has a current lint, whose profile_sha256 and ruleset_version the recorded file carries. A J1–J4
reply must also echo its input's `input_digest`, so a reply to a hand-built or stale input is refused (#43)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from plainspoken import report
from plainspoken.justify import file_sha, read_json
from plainspoken.profile import Profile
from plainspoken.registry import load_config

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = ROOT / "data" / "rubrics" / "judges.md"
GROUPS = report.GROUPS
_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*)\n\s*```\s*$", re.S | re.I)


def input_digest(lint: dict, group: str) -> str:
    """A digest of what `judge_input` builds `group`'s input from: the lint's article hash, profile, ruleset, content
    type and findings (so its candidates and human markers). `record_reply` recomputes it from the current lint, so
    a reply whose input wasn't the one `judge-input` printed for this draft never records."""
    keys = ("article_sha256", "profile_sha256", "ruleset_version", "content_type", "findings")
    canon = json.dumps({"group": group, **{k: lint.get(k) for k in keys}}, sort_keys=True, ensure_ascii=False,
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
            "input_digest": input_digest(lint, g),
        }
        if g == "J4":
            item["human_markers"] = [f for f in lint["findings"] if f["rule"] in ("HM", "15")]
        out.append(item)
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


def record_reply(article: Path, group: str, text: str, reports_dir: Path, cwd: Path) -> Path:
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
    elif data.get("input_digest") != input_digest(lint, group):
        raise ValueError(f"the {group} reply's input_digest doesn't match this draft's judge input (hand-built or "
                         f"stale input): rerun `judge-input` and give the judge its {group} line unchanged")
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


def record_all(article: Path, text: str, reports_dir: Path, cwd: Path) -> list[tuple[str, Path | None, str | None]]:
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
            out.append((g, record_reply(article, g, json.dumps(mine[0]), reports_dir, cwd), None))
        except ValueError as e:
            out.append((g, None, str(e)))
    for r in replies:
        if not isinstance(r, dict) or r.get("group") not in GROUPS:
            label = str(r.get("group")) if isinstance(r, dict) else "?"
            out.append((label, None, "not a J1–J4 reply (record JR with --group JR)" if isinstance(r, dict)
                        else "an item that isn't a JSON object"))
    return out
