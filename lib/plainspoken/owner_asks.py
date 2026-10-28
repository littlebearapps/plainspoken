"""Owner asks a write report makes that its `needs the owner` lines don't list (issue #75).

Write's step 8 asks the owner to check nothing the engine's `needs the owner` lines don't list: a line worth the
owner's check is held `blocking` in the claims ledger (so `status` lists it) or cut. This reads a report as the model
wrote it and returns the sentences that ask anyway. It reads only a message that carries the `status` block's
`needs the owner:` line, and only when that line lists nothing (`none`, or `unknown` without a readable ledger):
with items listed it can't tell which one an ask is about, so it leaves that to the person. The status block's own
lines are never read as prose, and a sentence naming a plainspoken command is a tool step, not an ask. Stdlib only,
plus `plainspoken.reply` for the one OWNER_MARKER.
"""
from __future__ import annotations

import re

from plainspoken.reply import OWNER_MARKER

STATUS_PREFIXES = ("Draft:", "check:", "claims:", OWNER_MARKER, "words:", "reader-value contract:",
                   "Reader value (outline):", "Anchors:", "For kaizen:")
_NOT_AN_ASK = r"(?!\s*:)(?!\s+(?:passed|ran|found|said|came|returned|gave|failed|is|was)\b)"
_CHECK = r"(?:double-check|check|confirm|verify)"
ASKS = tuple(re.compile(p, re.IGNORECASE) for p in (
    # "check Jo is happy with them", "make sure the committee is comfortable with"
    r"(?<!the )(?<!a )\b(?:check|confirm|make sure|ensure|see if|see whether)\b" + _NOT_AN_ASK
    + r"[^.?!\n]{0,60}?\b(?:happy|ok|okay|comfortable|fine|all right|alright)\s+(?:with|about|to)\b",
    # an imperative at the start of a sentence or clause: "Please confirm the …", "so check with Jo"
    r"(?:^|[,;:]\s*|\b(?:so|and|but|then|just)\s+)(?:please\s+)?" + _CHECK + _NOT_AN_ASK
    + r"\s+(?:that|whether|if|the|these|those|this|it|them|each|every|any|all|with)\b",
    r"\b(?:check|confirm|clear)\s+(?:(?:it|them|this|these|those|that|the\s+[\w'’-]+(?:\s+[\w'’-]+)?)\s+)?with\s+"
    r"(?!me\b)[\w'’]",
    r"\brun(?:ning)?\b[^.?!\n]{0,40}?\bpast\b",
    r"\b(?:ask|get)\s+[^.?!\n]{1,30}?\bto\s+(?:" + _CHECK + r"|approve|sign\s+off|look\s+over|read\s+over|okay|ok)\b",
    r"\b(?:should|must|needs?\s+to|wants?\s+to|may\s+want\s+to|might\s+want\s+to)\s+(?:" + _CHECK
    + r"|approve|sign\s+off|look\s+over|read\s+over)\b",
    r"\b(?!(?:it|that|there|here|what|who|he|she|let)['’]s\b)[\w'’]+(?:'s|’s)\s+"  # "needs Jo's OK", not "it's ok"
    r"(?:ok|okay|approval|sign-off|sign\s+off|blessing|go-ahead)\b",
))
_TOOL_STEP = re.compile(r"/plainspoken:|\brun\.py\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[.!?]['\"’”)])\s+")  # a closing quote can follow the stop


def _owner_line(lines: list[str]) -> str | None:
    for line in lines:
        s = line.strip()
        if s.startswith(OWNER_MARKER):
            return s.split(":", 1)[1].strip()
    return None


def _prose(lines: list[str]) -> list[str]:
    """The message's lines outside the status block: a block line starts (after its indent) with a status prefix,
    and an indented line straight under one (a reason or a listed claim) belongs to it."""
    out, last_indent = [], None
    for line in lines:
        if not line.strip():
            last_indent = None
            out.append("")
            continue
        indent = len(line) - len(line.lstrip())
        if line.lstrip().startswith(STATUS_PREFIXES) or (last_indent is not None and indent > last_indent):
            if line.lstrip().startswith(STATUS_PREFIXES):
                last_indent = indent
            continue
        last_indent = None
        out.append(line.strip())
    return out


def unlisted(message: str) -> list[str]:
    """The sentences of a write report that ask the owner to check something while its `needs the owner` line lists
    nothing, in order; [] for a report that doesn't, or a message that isn't a write report."""
    lines = message.splitlines()
    value = _owner_line(lines)
    if value is None or not (value == "none" or value.startswith("unknown")):
        return []
    found = []
    for paragraph in "\n".join(_prose(lines)).split("\n"):
        for sentence in _SENTENCE_END.split(paragraph.strip()):
            if sentence and not _TOOL_STEP.search(sentence) and any(p.search(sentence) for p in ASKS):
                found.append(sentence)
    return found


def message(asks: list[str]) -> str:
    """What the Stop hook sends back to Claude for a report `unlisted` caught."""
    quoted = "\n".join(f'  "{a[:200]}"' for a in asks)
    return ("plainspoken: this report asks the owner to check something its `needs the owner` lines don't list:\n"
            f"{quoted}\n"
            "Write's step 8 allows no such ask. For each line you'd have them check, go back to step 6: cut it from "
            "the draft (a fix never adds a fact), or hold it in the claims ledger as `blocking` with a `resolution` "
            "naming what the owner must confirm, never only ask in the report. Then rerun the claims steps the "
            "change touched and `status`, and give the report again with the status lines as printed.")
