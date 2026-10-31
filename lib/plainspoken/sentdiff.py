"""Sentence units and sentence-level hunks, shared by `kaizen diff` (`overrides`) and `meaning-diff` (`meaning`).

`units` splits a text into (sentence, first line, last line); `hunks` lists the changed runs of sentences between two
texts; `opcodes` is the `difflib.SequenceMatcher` call both use (no autojunk, so a repeated sentence is never junk).
"""
from __future__ import annotations

import difflib
import re

from plainspoken import capture
from plainspoken.doc import split_sentences

_BLOCK_LINE = re.compile(r"^\s*(#|```|~~~|\|)")  # a line that is a unit of its own (heading, fence, table row)
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")  # a code fence; the lines between two are code
_ITEM_LINE = re.compile(r"^\s*([-*+]\s|\d+[.)]\s|>)")  # a line that starts a new paragraph (list item, quote)


def opcodes(old: list[str], new: list[str]) -> list[tuple[str, int, int, int, int]]:
    """`difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()`."""
    return difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()


def units(text: str) -> list[tuple[str, int, int]]:
    """(sentence, first line, last line) for each sentence of `text`. A paragraph's lines are joined before it's
    split, so a sentence wrapped over two lines is one unit. Frontmatter lines, headings, table rows and every line
    of a fenced code block (fences included) are units of their own; a list item or quote line starts a new
    paragraph. A sentence the splitter returns reshaped (not found in its paragraph) spans the rest of the
    paragraph, so its lines are never placed short of where it sits."""
    lines = text.splitlines()
    fm_end = capture.frontmatter_end(lines)
    units: list[tuple[str, int, int]] = []
    para: list[tuple[int, str]] = []

    def flush() -> None:
        if not para:
            return
        joined, starts = "", []
        for ln, t in para:
            if joined:
                joined += " "
            starts.append((len(joined), ln))
            joined += t.strip()

        def line_at(offset: int) -> int:
            return [ln for start, ln in starts if start <= offset][-1]
        pos = 0
        for s in split_sentences(joined):
            i = joined.find(s, pos)
            if i < 0:  # the splitter reshaped it: cover the rest of the paragraph rather than guess a line
                units.append((s, line_at(pos), para[-1][0]))
                continue
            end = i + len(s)
            units.append((s, line_at(i), line_at(max(i, end - 1))))
            pos = end
        para.clear()

    fence: str | None = None  # the opening fence (``` or ~~~) while inside a fenced code block
    for n, raw in enumerate(lines, start=1):
        m = _FENCE.match(raw)
        if fence is not None or m:
            flush()  # a fenced line is code, never prose to join and split: each is a unit of its own
            if raw.strip():
                units.append((raw.strip(), n, n))
            if m and (fence is None or m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)):
                fence = m.group(1) if fence is None else None
        elif n <= fm_end or _BLOCK_LINE.match(raw):
            flush()
            if raw.strip():
                units.append((raw.strip(), n, n))
        elif not raw.strip():
            flush()
        else:
            if _ITEM_LINE.match(raw):
                flush()
            para.append((n, raw))
    flush()
    return units


def hunks(old_text: str, new_text: str) -> list[dict]:
    old, new = units(old_text), units(new_text)
    out = []
    for tag, i1, i2, j1, j2 in opcodes([u[0] for u in old], [u[0] for u in new]):
        if tag == "equal":
            continue
        if i2 > i1:
            span = [old[i1][1], old[i2 - 1][2]]
        else:  # an insertion: the line of the old sentence it goes before (the last line at the end)
            at = old[i1][1] if i1 < len(old) else (old[-1][2] if old else 0)
            span = [at, at]
        out.append({"n": len(out) + 1, "old": " ".join(u[0] for u in old[i1:i2]),
                    "new": " ".join(u[0] for u in new[j1:j2]), "old_lines": span})
    return out
