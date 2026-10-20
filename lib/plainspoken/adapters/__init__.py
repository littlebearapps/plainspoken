"""Proposal adapters (Phase 5): send each kaizen proposal where a person can approve or reject it, and read the
person's decision back so `kaizen decisions` can record it in the ledger.

- `file` (the default) writes `<proposals_dir>/proposals/<id>.md` next to the proposal's JSON. A person adds a line
  `APPROVE: <name>: <reason>` or `REJECT: <name>: <reason>` below the marker at the end of the file.
- `github` opens one issue per proposal with `gh` and reads the issue's comments from the approvers.
- `trello` creates one card per proposal through the Trello REST API and reads the card's comments from the approvers.

Creating that issue or card is the plugin's single outward write, and it happens only when the project config selects
`github` or `trello`. Nothing in the plugin writes an `APPROVE:` or `REJECT:` line or comment: a person does.

The decision grammar is shared and strict (`parse_decision`): a github or trello comment is a
decision only when its whole body is one plain line, `APPROVE: <reason>` or `REJECT: <reason>`, with nothing but
letters, digits, spaces and a few punctuation marks (typographic quotes, dashes and the ellipsis included) after the
colon, at least one letter or digit that shows, and no stacked combining marks. Anything else (a second line,
formatting, a quote, a code span) is not a decision, so no renderer can show a person something different from what
the engine reads. An approver comment that starts `APPROVE:`/`REJECT:` but fails the rule is counted in one
"repost" note per `kaizen decisions` run, naming the proposals, until the approver posts a plain decision after it.
The file adapter applies the same rule to every non-blank line below its
marker, all or nothing: one line that isn't a plain decision means nothing counts for that proposal and
`kaizen decisions` reports the line. The reason splits once more there: the text before its first colon is the name
(`APPROVE: Robin: fine` gives by `Robin`, reason `fine`); with no second colon the name is `file`. The one
`INSTRUCTION` text states the rule everywhere a person reads it.

Only comments count, never the issue body or card description the plugin wrote, and only comments on the issue or
card the proposal names (checked against the plugin's own text there). Edited or hidden comments never count: an
approver who changes their mind posts a new comment. The engine can't prove a person typed an approval: an account
whose credentials an agent also holds could post one. `kaizen decisions` never sends anything; only calibrate does.

Each adapter checks its own settings when it's built (`get`): a missing `[kaizen.github] repo`, `[kaizen.trello]
list_id` or credential environment variable is an `AdapterError` that names the key or the variable, never a value.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from plainspoken import ledger, proposals

MINED = "mined"  # the trigger of a `kaizen mine` proposal: local file adapter only, never sent outward
DECIDABLE = ("pending", "approved")  # a rejection is final for the adapter; an approval can be withdrawn until applied


class AdapterError(ValueError):
    """An adapter can't emit or read: the message names the setting, variable or command, and never a credential."""


def first_line(e: BaseException | str) -> str:
    text = e if isinstance(e, str) else str(e)
    return (text.strip().splitlines() or [type(e).__name__ if not isinstance(e, str) else "unknown error"])[0]


DECISION_MAX = 300
MARKS_MAX = 3  # combining marks (Mn, Me) allowed on one base character: more stacks into an unreadable smear
_DECISION = re.compile(r"(APPROVE|REJECT): (.+)")
PUNCT = " . , ; : ! ? ' \" ( ) / @ + = % - ’ ‘ “ ” – — …"  # as shown to people; the typographic marks are render-safe
_PUNCT = frozenset(PUNCT.replace(" ", "") + " ")
_FILLERS = frozenset("ㅤᅟᅠﾠ")  # Hangul fillers: category Lo, but they render as nothing
_SHORTCODE = re.compile(r":[^\s:]+:")  # `:smile:` renders as an emoji on GitHub and Trello, so it's not plain text
_VERDICT = {"APPROVE": "approved", "REJECT": "rejected"}
INSTRUCTION = ("A decision is one plain line, posted as its own comment (or, in the proposal file, its own line below "
               "the marker) with nothing else in it: `APPROVE: <your name>: <reason>` or `REJECT: <your name>: "
               "<reason>` (or just `APPROVE: <reason>`). At most 300 characters, in capitals exactly as shown, a "
               f"colon and a space, then the reason: letters, digits, spaces and {PUNCT.strip()} only, with at least "
               "one letter or digit. No formatting (no markdown, HTML, code, block quotes or links), no emoji or "
               ":shortcode: emoji, no struck-out letters, no second line. Anything else isn't read as a decision.")


def outward_decide(approvers: list[str]) -> list[str]:
    """The `## Decide` block of a github issue or trello card (one text for both)."""
    return ["## Decide", "", INSTRUCTION, "",
            f"Only comments from the approvers count ({', '.join(approvers)}), and edited or hidden comments never "
            "do: to change your mind, post a new comment. A later decision replaces an earlier one until the "
            "proposal is applied. Then run `kaizen decisions` to record it; when a comment starts `APPROVE:` or "
            "`REJECT:` but isn't one plain line, it names the proposal so you can repost it. plainspoken never "
            "comments here itself."]


def _plain(ch: str) -> bool:
    """An allowlisted character. Of the marks, enclosing marks (a keycap, a circle), variation selectors (an emoji
    presentation) and overlay marks (a strike through a letter) are out: they render as an emoji or struck-out text,
    not as the letters the engine reads."""
    if ch in _PUNCT:
        return True
    cat = unicodedata.category(ch)
    if cat[0] in "LN":
        return True
    return (cat == "Mn" or cat == "Mc") and unicodedata.combining(ch) != 1 and not _variation(ch)


def _variation(ch: str) -> bool:
    o = ord(ch)
    return 0xFE00 <= o <= 0xFE0F or 0xE0100 <= o <= 0xE01EF or 0x180B <= o <= 0x180F


def _readable(rest: str) -> bool:
    """`rest` has at least one letter or digit that shows (not a Hangul filler), and no base character carries more
    than MARKS_MAX combining marks."""
    shown = False
    marks = 0
    for ch in rest:
        cat = unicodedata.category(ch)
        if cat in ("Mn", "Me"):
            marks += 1
            if marks > MARKS_MAX:
                return False
            continue
        marks = 0
        if cat[0] in "LN" and ch not in _FILLERS:
            shown = True
    return shown


def looks_like_decision(text: str) -> bool:
    """The stripped text starts `APPROVE:` or `REJECT:` (a near miss when `parse_decision` says None): the person
    meant to decide, so `kaizen decisions` tells them to repost it as one plain line."""
    return str(text).strip().startswith(("APPROVE:", "REJECT:"))


def parse_decision(text: str) -> tuple[str, str] | None:
    """`(verdict, reason)` when the whole of `text` is one decision, else None (silently: it just isn't one).

    The rule is strict on purpose, so no renderer can show a person something other than what the
    engine reads: after stripping leading blank lines and trailing spaces, tabs, `\r` and `\n`, the entire text must
    be ONE line, indented at most three spaces (four, or a tab, would render as code), at most 300 characters,
    matching `^(APPROVE|REJECT): (.+)$` (capitals, exactly that keyword, a colon and a space: `APPROVE:fine` isn't
    one). Every character after `APPROVE: ` must be a Unicode letter, digit or combining mark (categories L*, N*,
    M*), the ASCII space, or one of `. , ; : ! ? ' " ( ) / @ + = % -` and the render-safe typographic marks
    `’ ‘ “ ” – — …`. So no markdown or HTML (`< > ` [ ] \\ ~ * _ # | &`), no tab, control, format (including
    zero-width), line or paragraph separator or other whitespace, and no `:shortcode:` (an emoji on GitHub and
    Trello). The reason must show something: at least one letter or digit that isn't a Hangul filler (U+3164,
    U+115F, U+1160, U+FFA0), and no base character may carry more than three combining marks. A second line, a
    quote, a code span or any formatting means the comment is not a decision. The reason (`name: reason` for the
    file adapter) keeps its spaces collapsed."""
    body = str(text).lstrip("\r\n").rstrip(" \t\r\n")
    lead = len(body) - len(body.lstrip(" "))
    if lead > 3:  # four spaces (or a tab, which the regex refuses) render as a code block
        return None
    body = body[lead:]
    if len(body) > DECISION_MAX:
        return None
    m = _DECISION.fullmatch(body)
    if m is None:
        return None
    rest = m.group(2)
    if not all(_plain(ch) for ch in rest) or _SHORTCODE.search(rest) or not _readable(rest):
        return None
    return _VERDICT[m.group(1)], " ".join(rest.split())


def iso(value: object) -> str | None:
    """A platform timestamp (`2026-10-14T09:30:00Z`, `…00.000Z`) as the ledger's UTC seconds, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        when = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    return when.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def near_misses(misses: list[tuple[str, str | None]], found: list[dict]) -> int:
    """How many near misses `(by, at)` still want a repost: those the same approver (case-insensitively) hasn't
    followed with a plain decision since. A miss with no time is kept unless a decision of theirs has none
    either."""
    out = 0
    for by, at in misses:
        later = [d for d in found if str(d["by"]).casefold() == str(by).casefold()
                 and (at is None or d.get("at") is None or d["at"] > at)]
        out += not later
    return out


def is_approver(name: str, approvers) -> bool:
    return name.casefold() in {str(a).casefold() for a in approvers}


# --- the body every adapter shows a person ------------------------------------------------------------------------

def _value(v: object) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)


def _fence(text: str) -> str:
    run = longest = 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


def render(p: Mapping, decide: list[str], *, outward: bool, max_chars: int | None = None) -> str:
    """The proposal as markdown: summary, facts, evidence, corpus effect, the diff in a ```diff fence, then the
    `decide` lines. `outward` (github, trello) leaves stored excerpts of article text out of the body. The diff is cut
    to keep the body within `max_chars`."""
    targets = ", ".join(p.get("targets") or []) or "nothing (a review proposal: make the change by hand in a PR)"
    head = [f"**{p.get('id')}**: {p.get('summary', '')}", "",
            f"- Rule `{p.get('rule')}` · trigger {p.get('trigger')} · action {p.get('action')}",
            f"- Ruleset {p.get('ruleset_version')} (base sha256 {str(p.get('base_sha256') or '')[:12]})",
            f"- Made {p.get('created')} · can be applied to: {targets}", "", "## Evidence", ""]
    evidence = dict(p.get("evidence") or {})
    excerpts = evidence.pop("excerpts", None)
    head += [f"- {k}: {_value(v)}" for k, v in sorted(evidence.items())] or ["- (none recorded)"]
    if excerpts:
        if outward:
            head.append(f"- excerpts: {len(excerpts)} kept in the local proposal file, not sent here")
        else:
            head += ["- excerpts:"] + [f"  - {_value(x)}" for x in excerpts]
    effect = dict(p.get("effect") or {})
    head += ["", "## Effect", ""]
    corpus = effect.get("corpus")
    if isinstance(corpus, dict):
        head.append(f"- corpus: {corpus.get('files', 0)} files; before {_value(corpus.get('before', {}))}; after "
                    f"{_value(corpus.get('after', {}))}; changed: {', '.join(corpus.get('changed') or []) or 'none'}"
                    + (f"; unreadable {corpus['unreadable']}" if corpus.get("unreadable") else ""))
    else:
        head.append(f"- corpus: {_value(corpus) if corpus is not None else 'not measured'}")
    head.append(f"- golden set: {_value(effect.get('golden', 'not measured'))}")
    head += ["", "## Diff", ""]
    diff = str(p.get("diff") or "")
    tail = ["", *decide]
    if not diff:
        return "\n".join(head + ["(no edits: a review proposal)"] + tail) + "\n"
    fence = _fence(diff)
    body = "\n".join(head + [fence + "diff", diff.rstrip("\n"), fence] + tail) + "\n"
    if max_chars is None or len(body) <= max_chars:
        return body
    note = "… (diff cut here; the full diff is in the local proposal file)"
    room = max(0, max_chars - (len(body) - len(diff)) - len(note) - 2)
    cut = diff[:room].rsplit("\n", 1)[0] if "\n" in diff[:room] else diff[:room]
    return "\n".join(head + [fence + "diff", cut, note, fence] + tail) + "\n"


def title(p: Mapping, limit: int) -> str:
    """`[kaizen] <rule>: <summary>` within `limit` characters (the summary's own `rule <id>: ` lead is dropped)."""
    rule = str(p.get("rule"))
    summary = " ".join(str(p.get("summary") or "").split())
    lead = f"rule {rule}: "
    if summary.startswith(lead):
        summary = summary[len(lead):]
    out = f"[kaizen] {rule}: {summary}"
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "…"


class Adapter:
    """Emit one proposal (returning its external ref) and read the decisions made on it, oldest first.

    `skipped` counts, for the last `read_decisions`, approver comments with a decision line that were left out
    because the platform didn't say whether they had been edited or hidden (fail closed); `SKIP_NOTE` says why.
    `near` counts approver comments that start `APPROVE:`/`REJECT:` but aren't one plain line (`looks_like_decision`
    yes, `parse_decision` None) and that the same approver hasn't followed with a plain decision since, so the person
    can be told to repost (`near_misses` works it out)."""
    name = ""
    skipped = 0
    near = 0
    SKIP_NOTE = "the platform didn't say whether they were edited"

    def reset(self) -> None:
        self.skipped = self.near = 0

    def emit_proposal(self, p: dict) -> str:
        raise NotImplementedError

    def read_decisions(self, p: dict) -> list[dict]:
        raise NotImplementedError


from plainspoken.adapters import file, github, trello  # noqa: E402  (the submodules use the names above)

_KINDS = {"file": file.FileAdapter, "github": github.GitHubAdapter, "trello": trello.TrelloAdapter}


def get(settings: Mapping, runner: Callable | None = None, opener: Callable | None = None,
        env: Mapping[str, str] | None = None, name: str | None = None) -> Adapter:
    """The adapter `name` (default `settings["adapter"]`), built from the settings. Raises AdapterError when a setting
    it needs is missing."""
    name = name or settings.get("adapter") or "file"
    if name == "file":
        return file.FileAdapter(settings)
    if name == "github":
        return github.GitHubAdapter(settings, runner)
    if name == "trello":
        return trello.TrelloAdapter(settings, opener, env)
    raise AdapterError(f"[kaizen] adapter must be one of {', '.join(_KINDS)}, got {name!r}")


def describe(name: str | None, ref: str | None) -> str:
    """How a ref reads in output: `file <path>`, `github #12`, `trello card <id>`."""
    if name == "github":
        return f"github #{ref}"
    if name == "trello":
        return f"trello card {ref}"
    return f"{name or 'file'} {ref}"


class NotSaved(Exception):
    """The proposal was sent (`where` says to which issue, card or file) but the proposal file couldn't be updated
    with its ref."""

    def __init__(self, where: str, error: BaseException):
        super().__init__(f"sent to {where}, but the proposal file couldn't be updated ({first_line(error)})")
        self.where = where


def send(p: dict, settings: Mapping, adapter: Callable[[], Adapter]) -> str:
    """Emit `p` through the adapter `adapter()` returns, store the ref and adapter name in the proposal file, and
    return how it reads. The one owner of the emit-failure path: on an AdapterError (building or emitting) the
    proposal is kept with `emit_error` set and no ref, and the error is raised again. When the emit worked but the
    file can't be saved, `p` keeps the ref in memory and NotSaved is raised."""
    try:
        a = adapter()
        ref = a.emit_proposal(p)
    except AdapterError as e:
        p.pop("ref", None)
        p["emit_error"] = first_line(e)
        try:
            proposals.save(p, settings)
        except OSError:
            pass  # the proposal file already holds the proposal; only the note is lost
        raise
    p["ref"], p["adapter"] = ref, a.name
    p.pop("emit_error", None)
    where = describe(a.name, ref)
    try:
        proposals.save(p, settings)
    except OSError as e:
        raise NotSaved(where, e) from None
    return where


def unsent(settings: Mapping, events: list[dict] | None = None) -> list[dict]:
    """Stored proposals still waiting for a decision that were never sent (no ref): calibrate sends them again.
    Mined proposals (trigger `mined`) aren't here: they only ever go to the file adapter (`unsent_mined`)."""
    return [p for p in proposals.pending(settings, events) if not p.get("ref") and p.get("trigger") != MINED]


def unsent_mined(settings: Mapping, events: list[dict] | None = None) -> list[dict]:
    """Mined proposals waiting for a decision whose local `.md` was never written: `kaizen mine` writes them again."""
    return [p for p in proposals.pending(settings, events) if not p.get("ref") and p.get("trigger") == MINED]


# --- kaizen decisions ---------------------------------------------------------------------------------------------

def _key(verdict: str, by: str, reason: str) -> tuple[str, str, str]:
    return verdict, by[: ledger.MAX_FACET], (reason or "")[: ledger.MAX_REASON].strip()


def _new(found: list[dict], pid: str, events: list[dict]) -> list[dict]:
    """The decisions in `found` not yet in the ledger. Counted per (verdict, by, reason), so the same comment read
    again is never logged twice, while a decision that is repeated after a different one (approve, reject, approve)
    is logged again and stays the latest."""
    logged = Counter(_key(e["outcome"], str((e.get("facets") or {}).get("by", "")), str(e.get("reason", "")))
                     for e in events if e.get("event") == "decision" and e.get("proposal") == pid)
    seen: Counter = Counter()
    out = []
    for d in found:
        k = _key(d["verdict"], d["by"], d["reason"])
        seen[k] += 1
        if seen[k] > logged[k]:
            out.append(d)
    return out


def _event(p: Mapping, d: Mapping, now: datetime) -> dict:
    return ledger.make_event(event="decision", actor="human", outcome=d["verdict"],
                             ruleset_version=str(p.get("ruleset_version") or "unknown"),
                             profile=str(p.get("profile") or "unknown"), rule=p.get("rule"), proposal=p["id"],
                             facets={"by": d["by"][: ledger.MAX_FACET]}, reason=d["reason"] or None,
                             ts=d.get("at") or now)


def _line(pid: str, d: Mapping) -> str:
    return f"{pid} {d['verdict']} by {d['by']}" + (f": {d['reason']}" if d["reason"] else "")


def record_decisions(settings: Mapping, now: datetime, *, runner: Callable | None = None,
                     opener: Callable | None = None, env: Mapping[str, str] | None = None
                     ) -> tuple[list[str], list[str]]:
    """`kaizen decisions`: for each stored proposal that is pending, or approved and not applied, read its decisions
    from the adapter it was sent to and log the new ones as `decision` events (oldest first, at the decision's own
    time when the adapter knows it). It never sends anything: a proposal with no ref (its emit failed) is counted in
    one line, and `kaizen calibrate` sends it. Returns (output lines, error lines); an error means nothing was logged
    for that proposal."""
    if not settings.get("capture", True):
        return [], ["[kaizen] capture = false, so no decision can be recorded: turn capture on first"]
    events = ledger.read(settings)[0]
    built: dict[str, Adapter | AdapterError] = {}

    def adapter(name: str) -> Adapter:
        if name not in built:
            try:
                built[name] = get(settings, runner, opener, env, name=name)
            except AdapterError as e:
                built[name] = e
        a = built[name]
        if isinstance(a, AdapterError):
            raise a
        return a

    lines: list[str] = []
    errors: list[str] = []
    waiting = mined_waiting = 0
    near = 0
    near_ids: list[str] = []
    skipped: Counter = Counter()
    for p in proposals.stored(settings):
        pid = p["id"]
        state = proposals.status(pid, events)
        if state not in DECIDABLE:
            continue
        if not p.get("ref"):
            if p.get("trigger") == MINED:
                mined_waiting += state == "pending"
            else:
                waiting += state == "pending"
            continue
        try:
            a = adapter(str(p.get("adapter") or "file"))
            a.reset()
            found = a.read_decisions(p)
        except AdapterError as e:
            errors.append(f"{pid}: {first_line(e)}")
            continue
        skipped[a.SKIP_NOTE] += a.skipped
        near += a.near
        if a.near:
            near_ids.append(pid)
        fresh = _new(found, pid, events)
        try:
            built_events = [_event(p, d, now) for d in fresh]
            for e in built_events:
                ledger.append(e, settings)
        except ledger.LedgerError as e:
            errors.append(f"{pid}: decision not recorded: {first_line(e)}")
            continue
        events.extend(built_events)
        lines += [_line(pid, d) for d in fresh]
    for note, n in skipped.items():
        if n:
            lines.append(f"kaizen decisions: {n} comment{'s' if n != 1 else ''} skipped: {note}")
    if near:
        one = near == 1
        lines.append(f"kaizen decisions: {near} comment{'' if one else 's'} look{'s' if one else ''} like a decision "
                     f"but {'isn' if one else 'aren'}'t one plain line — repost {'it' if one else 'them'} "
                     f"({', '.join(near_ids)})")
    if waiting:
        lines.append(f"kaizen decisions: {waiting} proposal{'s' if waiting != 1 else ''} not yet sent — run "
                     "`kaizen calibrate`")
    if mined_waiting:
        lines.append(f"kaizen decisions: {mined_waiting} mined proposal{'s' if mined_waiting != 1 else ''} with no "
                     "local file yet — run `kaizen mine` again to write "
                     f"{'them' if mined_waiting != 1 else 'it'}")
    return lines, errors
