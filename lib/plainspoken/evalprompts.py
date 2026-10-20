"""Self-contained judge and JR prompts for judge validation, and strict reply parsing (Phase 6 evals).

Other vendors' models have no file tools, so a validation prompt carries everything inline: the wrapper part from
`data/rubrics/judge-inline.md`, the rubric sections from `data/rubrics/judges.md`, an `Input` JSON block and the
line-numbered case text. Claude gets the same prompt, which keeps the comparison fair. A case's label, id and origin
never reach a prompt. `parse_judge` turns a reply into a label or an error with a reason: an off-schema reply is an
error, never a pass or a fail."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from plainspoken import judges, report
from plainspoken.doc import split_lines
from plainspoken.golden import LABELS, GoldenCase
from plainspoken.profile import default as default_profile
from plainspoken.registry import load_config

RUBRICS = Path(__file__).resolve().parents[2] / "data" / "rubrics"
JUDGES_MD = RUBRICS / "judges.md"
INLINE_MD = RUBRICS / "judge-inline.md"
J_GROUPS = ("J1", "J2", "J3", "J4")


def _block(path: Path, level: str, name: str) -> str:
    """The `<level> <name>` heading of `path` and everything under it, up to the next heading of that level or
    higher. `name` matches the heading's first word(s) exactly: `### 12` is not `### 12b`. KeyError if absent."""
    lines = path.read_text(encoding="utf-8").splitlines()
    head = f"{level} {name}"
    start = next((i for i, ln in enumerate(lines) if ln == head or ln.startswith(head + " ")), None)
    if start is None:
        raise KeyError(f"{path.name}: no '{head}' heading")
    stops = tuple("#" * n + " " for n in range(1, len(level) + 1))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(stops)), len(lines))
    return "\n".join(lines[start:end]).strip()


def rubric_section(name: str) -> str:
    """The `## <name>` section of judges.md, heading included (e.g. "How every judge works")."""
    return _block(JUDGES_MD, "##", name)


def rubric_entry(rule: str) -> str:
    """The `### <rule> …` entry of judges.md, heading included. KeyError for a rule with no entry (a lint-only
    rule such as 12e)."""
    return _block(JUDGES_MD, "###", rule)


def _inline_part(name: str) -> str:
    """The body of the `## <name>` part of judge-inline.md (`J` or `JR`), without its heading."""
    return _block(INLINE_MD, "##", name).split("\n", 1)[1].strip()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _numbered(text: str) -> str:
    """The text with each line prefixed `<n>: `, numbered as the lint numbers them (`doc.split_lines`)."""
    return "\n".join(f"{n}: {line}" for n, line in enumerate(split_lines(text), 1))


def _fence(body: str) -> str:
    """A backtick fence longer than any backtick run in `body`, so an excerpt holding ``` can't close it."""
    longest = max((len(run) for run in re.findall(r"`+", body)), default=0)
    return "`" * max(3, longest + 1)


def _assemble(parts: list[str], payload: dict, text: str) -> str:
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    fence = _fence(body)
    inp = f"## Input\n\n{fence}json\n{body}\n{fence}"
    return "\n\n".join([*parts, inp, "## Article\n\n" + _numbered(text)]) + "\n"


def _findings(case: GoldenCase, workdir: Path) -> list[dict]:
    """The findings of the same lint `check` runs (default profile) on the case text, written to a file in
    `workdir`."""
    path = Path(workdir) / f"{_sha(case.text)[:16]}.md"  # named by content: same text, same lint, no clash
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(case.text.encode("utf-8"))
    return report.run_lint(path, default_profile(), case.content_type)["findings"]


def _candidates(findings: list[dict], rule: str) -> list[dict]:
    """The lint's CANDIDATE findings for `rule`. Rules the default profile doesn't apply (NR-*) get none."""
    return [{k: f[k] for k in ("rule", "severity", "line", "excerpt", "message")}
            for f in findings if f["severity"] == "CANDIDATE" and f["rule"] == rule]


def judge_prompt(case: GoldenCase, workdir: Path) -> str:
    """The self-contained prompt for one J1–J4 case: the J part of judge-inline.md, "How every judge works", the
    case rule's entry, the Input block and the numbered text. `workdir` holds the temp file the lint reads. A J4
    prompt also carries `human_markers` (the lint's HM and rule-15 findings), as `judges.judge_input` gives the
    real J4 agent."""
    if case.group not in J_GROUPS:
        raise ValueError(f"judge_prompt is for J1–J4 cases, not {case.group}")
    findings = _findings(case, workdir)
    payload = {
        "group": case.group,
        "article_sha256": _sha(case.text),
        "content_type": case.content_type,
        "rules": [case.rule],
        "severities": {case.rule: load_config().rules[case.rule].severity},
        "candidates": _candidates(findings, case.rule),
    }
    if case.group == "J4":
        payload["human_markers"] = [f for f in findings if f["rule"] in ("HM", "15")]
    parts = [_inline_part("J"), rubric_section("How every judge works"), rubric_entry(case.rule)]
    return _assemble(parts, payload, case.text)


def jr_items(case: GoldenCase) -> list[dict]:
    return [{"rule": case.rule, "kind": case.kind, "reason": case.reason,
             "evidence": [dict(e) for e in case.evidence]}]


def jr_prompt(case: GoldenCase) -> str:
    """The self-contained prompt for one JR case: the JR part of judge-inline.md, the JR section, the rule's entry
    when it has one, the Input block (`justify_sha256` = sha256 of the items' canonical JSON) and the numbered
    text."""
    if case.group != "JR":
        raise ValueError(f"jr_prompt is for JR cases, not {case.group}")
    items = jr_items(case)
    canon = json.dumps(items, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = {"article_sha256": _sha(case.text), "justify_sha256": _sha(canon), "items": items}
    parts = [_inline_part("JR"), rubric_section("JR Justification review")]
    try:
        parts.append(rubric_entry(case.rule))
    except KeyError:
        pass  # a lint-only rule (12e, 7, 12f …) has no judge entry; the JR section alone applies
    return _assemble(parts, payload, case.text)


def parse_judge(reply: str, case: GoldenCase) -> tuple[str | None, str]:
    """The label a reply gives the case, as `(label, "")`, or `(None, reason)` when the reply can't be scored.

    J groups give "fail" or "pass", JR "accept" or "reject", from the one verdict for `case.rule`. The body is
    one JSON object, bare or alone in a code fence (`judges._parse`). Errors: not one JSON object; no verdicts
    list; no verdict for the rule (named "a verdict isn't a JSON object" when a non-object entry might have been
    it); more than one; a verdict value outside the group's pair. Verdicts for other rules, and entries that
    aren't objects beside the rule's verdict, are ignored, not errors: a judge that over-answers is scored on the
    rule it was asked about. A `fail` with no evidence is still a `fail` (the evidence rule is the agent's
    contract, not the label)."""
    try:
        data = judges._parse(reply)
    except ValueError:
        return None, "not one JSON object"
    verdicts = data.get("verdicts")
    if not isinstance(verdicts, list):
        return None, "no verdicts list"
    objects = [v for v in verdicts if isinstance(v, dict)]
    mine = [v for v in objects if v.get("rule") == case.rule]
    if not mine:
        if len(objects) < len(verdicts):
            return None, "a verdict isn't a JSON object"
        return None, f"no verdict for rule {case.rule}"
    if len(mine) > 1:
        return None, f"more than one verdict for rule {case.rule}"
    allowed = LABELS[case.group]
    value = mine[0].get("verdict")
    if value not in allowed:
        return None, f"verdict {value!r} isn't {' or '.join(allowed)}"
    return value, ""
