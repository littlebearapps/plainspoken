"""The `file` adapter: a markdown copy of each proposal, `<proposals_dir>/proposals/<id>.md`, that a person decides in
by adding a line at the end. Only lines below the last `MARKER` count, so the template's own example lines never do,
and a diff that quotes the marker doesn't move it.

A decision line is `APPROVE: <name>: <reason>` or `REJECT: <name>: <reason>`, under the shared strict rule
(`adapters.parse_decision`: one plain line, allowlisted characters only). The block below the marker is read all or
nothing: every non-blank line there must be a decision line on its own, and if one isn't, nothing counts
for the proposal and `read_decisions` raises an AdapterError naming the line, so `kaizen decisions` prints it and exits
1. That is what stops a line inside a multi-line HTML comment, a `<details>` block, a code fence, a lazy `>` quote, a
setext underline or a table from counting while the rendered file hides it. When every line is a decision, each counts
in order, so the last line is the latest decision. With no second colon (`APPROVE: fine`) the name is `file`. When
`[kaizen] approvers` is set, only a line naming one of them (case-insensitively) counts, and a line with no name
doesn't; those lines are still plain decisions, so they're skipped, not errors.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from plainspoken import proposals, report
from plainspoken.adapters import INSTRUCTION, Adapter, AdapterError, is_approver, parse_decision, render

MARKER = "<!-- plainspoken: decisions go below this line -->"
NO_NAME = "file"


def split_name(rest: str) -> tuple[str | None, str]:
    """`(name, reason)` from the text after `APPROVE:`: the name is the text before its first colon, or None."""
    if ":" not in rest:
        return None, rest.strip()
    name, reason = rest.split(":", 1)
    name = " ".join(name.split())
    return (name or None), reason.strip()


def _decide(pid: str) -> list[str]:
    return ["## Decide", "", INSTRUCTION, "",
            "Add it at the very end of this file, below the marker line. Every non-blank line below the marker must "
            "be a decision line on its own; if one isn't, nothing below the marker counts and `kaizen decisions` "
            "names the line. A later line replaces an earlier one until the proposal is applied. Then run `kaizen "
            f"decisions` to record it, and `kaizen apply {pid}` to apply an approval. plainspoken never writes these "
            "lines itself.", "", MARKER]


class FileAdapter(Adapter):
    name = "file"

    def __init__(self, settings: Mapping):
        self.settings = settings
        self.approvers = list(settings.get("approvers") or [])
        self.root = Path(settings.get("root") or ".")

    def path(self, pid: str) -> Path:
        return proposals._path(pid, self.settings).with_suffix(".md")

    def _ref(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(path)

    def emit_proposal(self, p: dict) -> str:
        """Write the `.md` (keeping any decision lines already below the marker); the ref is its project path."""
        path = self.path(p["id"])
        kept = ""
        try:
            old = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            old = ""
        except (OSError, UnicodeDecodeError) as e:
            raise AdapterError(f"{path}: can't read the proposal file ({e})") from None
        if MARKER in old:
            kept = old.rpartition(MARKER)[2].lstrip("\n")  # below the last marker: the diff may quote the marker
        text = render(p, _decide(p["id"]), outward=False) + kept
        try:
            report.write_atomic(path, text)
        except OSError as e:
            raise AdapterError(f"{path}: can't write the proposal file ({e})") from None
        return self._ref(path)

    def read_decisions(self, p: dict) -> list[dict]:
        """The decisions below the marker, oldest first, or an AdapterError when any non-blank line there isn't a
        plain decision line on its own (then nothing counts for this proposal)."""
        path = self.path(p["id"])
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise AdapterError(f"{self._ref(path)} is missing, so there's nowhere to read a decision from") from None
        except (OSError, UnicodeDecodeError) as e:
            raise AdapterError(f"{path}: can't read the proposal file ({e})") from None
        if MARKER not in text:
            raise AdapterError(f"{self._ref(path)}: the marker line is gone, so no decision line can be trusted: "
                               f"put back {MARKER} and add the decision below it")
        head, _, tail = text.rpartition(MARKER)  # the last marker is the real one: a diff may quote it
        marker_line = head.count("\n") + 1  # 1-based; tail's first piece is the rest of the marker's own line
        out = []
        for i, line in enumerate(tail.split("\n")):  # "\n" only: U+2028 and friends never split a line
            if not line.strip():
                continue
            parsed = None if i == 0 else parse_decision(line)  # text on the marker's own line sits inside its comment
            if parsed is None:
                raise AdapterError(f"the decision block has a line that isn't a plain decision (line "
                                   f"{marker_line + i}) — fix it")
            verdict, rest = parsed
            name, reason = split_name(rest)
            if self.approvers and (name is None or not is_approver(name, self.approvers)):
                continue
            out.append({"verdict": verdict, "by": name or NO_NAME, "reason": reason, "at": None})
        return out
