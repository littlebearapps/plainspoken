"""Owner asks a write report makes that its `needs the owner` lines don't list (issue #75).

Write's step 8 asks the owner to check nothing the engine's `needs the owner` lines don't list: a line worth the
owner's check is held `blocking` in the claims ledger (so `status` lists it) or cut. This reads a report as the model
wrote it and returns the sentences that ask anyway. It reads only a message that carries the `status` block's
`needs the owner:` line. An ask counts either way it's put: "check Jo is happy with them", or a decision handed to
the owner ("Cut that sentence if you'd rather not …", "If you only do setup, I'd change it to …").

When the line lists items, an ask about one of them is fine, so a sentence is left alone when it names a listed
claim id or shares its words, or, when it quotes no line of its own, its paragraph does (so "Please confirm you're
happy to publish it" under a paragraph about the listed claim passes). Every other ask is still caught (round 8: a
report listing one item asked about another line). The status block's own lines, the piece between `<<<PIECE` and
`PIECE>>>` (the evals' delivery) and quoted draft text are never read as asks, and a sentence naming a plainspoken
command is a tool step. Stdlib only, plus `plainspoken.reply` for the one OWNER_MARKER.
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
# A decision handed to the owner (round 8): a condition on them ("if you'd rather not", "if you only do setup",
# "unless you") in the same sentence as an edit to the draft ("cut that sentence", "I'd change it to"). A condition
# about sending more material ("if you send me the date, I can add it") isn't one, and adding isn't an edit here.
_CONDITION = re.compile(r"\b(?:if|unless)\s+you(?:['’](?:d|re|ve))?(?:\s+would)?\s+"
                        r"(?!send|give|share|supply|provide|have|find|get)\w", re.IGNORECASE)
# The edit, unless it's one the writer made or didn't ("I cut …", "I didn't change …"); an offer ("I'd change it")
# still hands the choice over.
_EDIT = re.compile(r"(?<![\w'’])(?<!\bI )(?<!I've )(?<!I have )(?<!n't )(?<!not )(?<!never )"
                   r"(?:cut|drop|remove|delete|change|swap|reword|rewrite|soften|replace|trim|lose|keep)\b",
                   re.IGNORECASE)
# A quoted span (straight or curly quotes, single or double): a line of the draft, never the report's own words. A
# single quote opens only where no word runs into it and closes only where none follows, so "you'd", "clients'
# books" and the apostrophe in 'That's a lot' stay inside or outside a quote as they should.
_QUOTED = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”|(?<![\w'’])(['‘])(?=\S)[^\n]*?(?<=\S)['’](?!\w)")
_PIECE = re.compile(r"^[ \t]*<<<PIECE[ \t]*$.*?(?:^[ \t]*PIECE>>>[ \t]*$|\Z)", re.M | re.S)  # the evals' piece
_WORD = re.compile(r"[a-z0-9][a-z0-9'’-]*[a-z0-9]")
# Words too common in a report to tie it to one claim: two shared words that aren't these mean the same line.
_COMMON = frozenset("""about after again also because been before being cant could didnt does dont each even every
from give goes gone have here into its just like line lines make more most much must need needs notes only other
over owner page piece please post said same says should since some such sure than that their them then there these
they this those through very want were what when where which while will with without would your youre youd youll
check confirm happy publish written draft claim claims""".split())
_TOOL_STEP = re.compile(r"/plainspoken:|\brun\.py\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[.!?]['\"’”)])\s+")  # a closing quote can follow the stop


def _owner_line(lines: list[str]) -> tuple[str, list[str]] | None:
    """The `needs the owner:` value and the items listed under it (each indented line straight below), or None."""
    for k, line in enumerate(lines):
        s = line.strip()
        if s.startswith(OWNER_MARKER):
            indent, items = len(line) - len(line.lstrip()), []
            for below in lines[k + 1:]:
                if not below.strip() or len(below) - len(below.lstrip()) <= indent:
                    break
                items.append(below.strip())
            return s.split(":", 1)[1].strip(), items
    return None


def _words(text: str) -> set[str]:
    """`text`'s distinctive words, lower case, apostrophes dropped and a plural `s` trimmed, for matching a claim."""
    out = set()
    for w in _WORD.findall(text.lower()):
        w = w.replace("'", "").replace("’", "")
        if len(w) >= 4 and w not in _COMMON:
            out.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def _ids(cid: str) -> list[str]:
    """A claim id and its short form: `LEDGER-AND-LEAF-SERVICES-C008` is also `C008`, as reports write it."""
    short = cid.rsplit("-", 1)[-1] if "-" in cid else ""
    return [cid] + ([short] if re.fullmatch(r"[A-Za-z]+\d+", short) else []) if cid else []


def _about(text: str, items: list[tuple[str, set[str]]]) -> bool:
    """Whether `text` names a listed claim's id (or its short form) or shares two of its distinctive words."""
    seen = _words(text)
    return any(any(re.search(r"(?<![\w-])" + re.escape(i) + r"(?![\w-])", text) for i in _ids(cid))
               or len(seen & words) >= 2 for cid, words in items)


def _item(line: str) -> tuple[str, set[str]]:
    """A listed item, `<claim id>: <claim text> (<why>)`, as (id, the claim text's distinctive words)."""
    cid, sep, rest = line.partition(": ")
    if not sep or " " in cid:
        cid, rest = "", line
    return cid, _words(re.sub(r"\s*\([^()]*\)\s*$", "", rest))


def _is_ask(sentence: str) -> bool:
    if _TOOL_STEP.search(sentence):
        return False
    prose = _QUOTED.sub(" ", sentence)
    if _CONDITION.search(prose) and _EDIT.search(prose):
        return True
    return any(p.search(prose) for p in ASKS)


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
    """The sentences of a write report that ask the owner to check something its `needs the owner` lines don't list,
    in order; [] for a report that doesn't, or a message that isn't a write report."""
    lines = _PIECE.sub("", message).splitlines()
    owner = _owner_line(lines)
    if owner is None:
        return []
    value, listed = owner
    items = [] if value == "none" else [_item(i) for i in listed]  # unknown claims can still list M items (#147)
    if (value != "none" and not value.startswith("unknown")) and not items:
        return []  # a count with no items under it: there's nothing to tell an ask about them from another
    found = []
    for paragraph in "\n".join(_prose(lines)).split("\n"):
        for sentence in _SENTENCE_END.split(paragraph.strip()):
            if not sentence or not _is_ask(sentence):
                continue
            if items and (_about(sentence, items)
                          or (not _QUOTED.search(sentence) and _about(paragraph, items))):
                continue  # about a listed claim: the ask the engine's list allows
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
