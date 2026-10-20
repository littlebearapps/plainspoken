"""Text edits to `rules.toml` and profile TOML that keep comments and layout, plus version bumps, a diff and the
changelog entry (Phase 5). Calibrate runs these on a temporary copy to show a proposal's diff; only `kaizen apply`
writes the result to a real file.

An edit is a dict:
- `{"kind": "set_threshold", "table": "default", "key": k, "old": v, "new": v2}`: replace the `key = …` line in
  `[thresholds."<table>"]` (the key must already be there);
- `{"kind": "list_add", "list": name, "values": [...]}`: append to `[lists] name`, skipping values already present
  (case-insensitively, so the list never gains a near-duplicate);
- `{"kind": "rule_field", "rule": id, "field": f, "old": v | None, "new": v | None}`: replace, insert (after
  `severity`) or delete (`new` None) a field of one `[[rules]]` block; `f` is `severity`, `status` or `models`;
- `{"kind": "rule_remove", "rule": id, "old": {field: value, …}}`: delete the block and the blank line before it;
  `old` (optional) is the rule's state when the removal was proposed, checked like any `old`;
- `{"kind": "rule_add", "rule": id, "block": {field: value, …}, "lists": {name: [...]}, "thresholds": {key: n}}`:
  append a `[[rules]]` block after the last rule (`id`, then the block's fields in the ruleset's usual order), plus
  any new `[lists]` entries and `[thresholds."default"]` keys the rule reads (both optional). It refuses an id, list or
  threshold that already exists, and a lint rule this plugin has no check for;
- `{"kind": "threshold_add", "key": k, "value": n, "after": k2}`: a new `[thresholds."default"]` key for an existing
  rule's check (a narrow knob), inserted after `k2` (optional; else at the table's end). It refuses a key that
  already exists, a non-number and an `after` key that isn't there.

Everything fails closed with `EditError`: an `old` that doesn't match the current parsed value ("stale: …"), a value
of another type than the one it replaces, a line it can't find, an edit list that changes nothing, or a result that
doesn't parse with `tomllib` or load with `registry.load_config` (or, for a profile, validate as a profile). The
input text is never touched; each function returns new text.
"""
from __future__ import annotations

import decimal
import difflib
import math
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from plainspoken import profile as _profile
from plainspoken.registry import load_config
from plainspoken.tomlw import _string, _value

__all__ = ["EditError", "apply_edits", "apply_profile_edits", "bump", "set_version", "diff", "changelog_entry",
           "load_text"]

RULE_FIELDS = ("severity", "status", "models")
_SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
_BARE = re.compile(r"[A-Za-z0-9_-]+")
_PARTS = ("major", "minor", "patch")
_EXCERPT_KEYS = {"excerpt", "excerpts"}


class EditError(ValueError):
    """An edit that can't be applied safely. Nothing is written."""


def _first_line(e: BaseException) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


# ---------------------------------------------------------------------------------------------------------------
# A line-level map of a TOML document: which lines are table headers, which start a `key = value` (and how many
# lines the value spans), found with a small scanner that knows strings, comments and bracket depth. The text is
# always parsed with tomllib first, so the scanner only ever sees valid TOML.

_CODE, _STR, _COMMENT = 0, 1, 2


@dataclass(frozen=True)
class _Entry:
    kind: str                  # "header" or "key"
    start: int                 # first line index
    end: int                   # one past the last line of the value (keys) or the header line + 1
    path: tuple[str, ...]      # header: the table path; key: the table it sits in
    key: tuple[str, ...] = ()  # key entries only
    aot: int | None = None     # the array-of-tables index of the enclosing [[table]], when there is one
    eq: int = -1               # key entries: offset of the `=` within the first line


class _Doc:
    def __init__(self, text: str):
        self.text = text
        self.lines = text.splitlines(keepends=True)
        self.offsets = []
        pos = 0
        for line in self.lines:
            self.offsets.append(pos)
            pos += len(line)
        self.cls, top = _scan(text)
        self.entries = self._entries(top)

    def code(self, i: int) -> str:
        """Line i up to its comment, newline excluded."""
        line, off = self.lines[i], self.offsets[i]
        end = len(line.rstrip("\r\n"))
        for j in range(end):
            if self.cls[off + j] == _COMMENT:
                return line[:j]
        return line[:end]

    def _entries(self, top: list[bool]) -> list[_Entry]:
        tops = [i for i in range(len(self.lines)) if top[i]]
        out: list[_Entry] = []
        table: tuple[str, ...] = ()
        aot: int | None = None
        counts: dict[tuple[str, ...], int] = {}
        for n, i in enumerate(tops):
            code = self.code(i)
            stripped = code.strip()
            if not stripped:
                continue
            if stripped.startswith("["):
                is_array = stripped.startswith("[[")
                inner = stripped[2:-2] if is_array else stripped[1:-1]
                table = _split_key(inner)
                if is_array:
                    aot = counts.get(table, 0)
                    counts[table] = aot + 1
                else:
                    aot = None
                out.append(_Entry("header", i, i + 1, table, aot=aot))
                continue
            eq = next((j for j, ch in enumerate(code) if ch == "=" and self.cls[self.offsets[i] + j] == _CODE), -1)
            if eq < 0:
                raise EditError(f"line {i + 1}: can't read {stripped[:40]!r}")
            nxt = tops[n + 1] if n + 1 < len(tops) else len(self.lines)
            out.append(_Entry("key", i, nxt, table, _split_key(code[:eq]), aot, eq))
        return out

    def find_key(self, table: tuple[str, ...], key: tuple[str, ...], aot: int | None = None) -> _Entry | None:
        hits = [e for e in self.entries if e.kind == "key" and e.path == table and e.key == key and e.aot == aot]
        if len(hits) > 1:
            raise EditError(f"{'.'.join(table + key)} appears more than once")
        return hits[0] if hits else None

    def header(self, table: tuple[str, ...], aot: int | None = None) -> _Entry | None:
        return next((e for e in self.entries if e.kind == "header" and e.path == table and e.aot == aot), None)

    def table_keys(self, table: tuple[str, ...], aot: int | None = None) -> list[_Entry]:
        return [e for e in self.entries if e.kind == "key" and e.path == table and e.aot == aot]

    def newline(self, i: int) -> str:
        line = self.lines[i] if self.lines else ""
        return "\r\n" if line.endswith("\r\n") else "\n"

    def replace_lines(self, start: int, end: int, new: list[str]) -> str:
        return "".join(self.lines[:start] + new + self.lines[end:])


def _scan(text: str) -> tuple[bytearray, list[bool]]:
    """Per character: code, string or comment. Per line: does it start outside every array, inline table and
    multi-line string (a 'top-level' line, where a header or a key can begin)?"""
    n = len(text)
    cls = bytearray(n)
    top = [True]
    depth = 0
    state = ""          # "", '"', "'", '"""', "'''", "#"
    header = False
    line_start = 0
    i = 0
    while i < n:
        ch = text[i]
        if state == "":
            if ch == "#":
                state = "#"
                cls[i] = _COMMENT
            elif text.startswith('"""', i) or text.startswith("'''", i):
                state = text[i:i + 3]
                cls[i:i + 3] = bytes([_STR] * 3)
                i += 3
                continue
            elif ch in "\"'":
                state = ch
                cls[i] = _STR
            elif ch == "\n":
                top.append(depth == 0)
                header = False
                line_start = i + 1
            elif ch == "[" and depth == 0 and not header and not text[line_start:i].strip():
                header = True
            elif ch in "[{" and not header:
                depth += 1
            elif ch in "]}" and not header:
                depth -= 1
        elif state == "#":
            if ch == "\n":
                state = ""
                top.append(depth == 0)
                header = False
                line_start = i + 1
            else:
                cls[i] = _COMMENT
        elif state in ('"', "'"):
            cls[i] = _STR
            if state == '"' and ch == "\\" and i + 1 < n:
                cls[i + 1] = _STR
                i += 2
                continue
            if ch == state:
                state = ""
        else:  # a multi-line string
            cls[i] = _STR
            if state == '"""' and ch == "\\" and i + 1 < n:
                cls[i + 1] = _STR
                if text[i + 1] == "\n":
                    top.append(False)
                    line_start = i + 2
                i += 2
                continue
            if text.startswith(state, i):
                j = i + 3
                while j < n and text[j] == state[0] and j - i < 5:  # up to two quotes may sit inside the closer
                    j += 1
                cls[i:j] = bytes([_STR] * (j - i))
                state = ""
                i = j
                continue
            if ch == "\n":
                top.append(False)
                line_start = i + 1
        i += 1
    return cls, top


def _split_key(s: str) -> tuple[str, ...]:
    """A dotted key (bare, "basic" or 'literal' parts) as a tuple of strings."""
    parts: list[str] = []
    i, s = 0, s.strip()
    while True:
        while i < len(s) and s[i] in " \t":
            i += 1
        if i >= len(s):
            raise EditError(f"can't read the key {s!r}")
        if s[i] in "\"'":
            q, j = s[i], i + 1
            while j < len(s) and s[j] != q:
                j += 2 if (q == '"' and s[j] == "\\") else 1
            token = s[i:j + 1]
            try:
                parts.append(tomllib.loads(f"k = {token}")["k"])
            except tomllib.TOMLDecodeError:
                raise EditError(f"can't read the key {s!r}") from None
            i = j + 1
        else:
            m = _BARE.match(s, i)
            if not m:
                raise EditError(f"can't read the key {s!r}")
            parts.append(m.group())
            i = m.end()
        while i < len(s) and s[i] in " \t":
            i += 1
        if i >= len(s):
            return tuple(parts)
        if s[i] != ".":
            raise EditError(f"can't read the key {s!r}")
        i += 1


# ---------------------------------------------------------------------------------------------------------------
# Values

def _norm(v):
    return [_norm(x) for x in v] if isinstance(v, (list, tuple)) else v


def _same(a, b) -> bool:
    """Equal as TOML values: a bool never equals a number; an int equals the same float."""
    a, b = _norm(a), _norm(b)
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _decimals(x: float) -> int:
    exp = decimal.Decimal(repr(x)).as_tuple().exponent
    return max(0, -exp) if isinstance(exp, int) else 0


def _number(new, cur, what: str):
    """`new` written as the same kind of value as `cur` (bool, int or float). A float is rounded to the precision
    it was written at (or the old value's, if finer), so 0.46 - 0.02 is written 0.44, never 0.43999999999999995."""
    if isinstance(new, float) and not math.isfinite(new):
        raise EditError(f"{what}: expected a finite number, got {new}")
    if isinstance(cur, bool):
        if not isinstance(new, bool):
            raise EditError(f"{what}: type change (expected true or false, got {new!r})")
        return new
    if isinstance(new, bool) or not isinstance(new, (int, float)):
        raise EditError(f"{what}: type change (expected a number, got {new!r})")
    if isinstance(cur, int):
        if isinstance(new, float):
            if not new.is_integer():
                raise EditError(f"{what}: type change (expected a whole number, got {new!r})")
            new = int(new)
        return new
    new = float(new)
    written = round(new, max(_decimals(cur), _decimals(round(new, 10))))
    if not math.isclose(written, new, rel_tol=1e-9, abs_tol=0.0):  # a value finer than 10 places would be lost
        raise EditError(f"{what}: {new!r} can't be written without rounding it to {written!r}")
    return written


def _fmt(v) -> str:
    try:
        return _value(_norm(v))
    except TypeError as e:
        raise EditError(f"can't write {v!r} as TOML ({e})") from None


def _need(edit: dict, key: str):
    if key not in edit:
        raise EditError(f"{edit.get('kind', 'edit')}: missing {key!r}")
    return edit[key]


def _check_old(edit: dict, current, what: str) -> None:
    old = _need(edit, "old")
    if not _same(current, old):
        raise EditError(f"stale: {what} is {current!r}, the edit expected {old!r}")


def _parse(text: str, what: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise EditError(f"the {what} isn't valid TOML ({_first_line(e)})") from None


def _value_line(doc: _Doc, entry: _Entry, value: str, items: list | None = None) -> list[str]:
    """The entry's line(s) with the value replaced: the key, spacing and a trailing comment stay as written. A value
    written over several lines stays that way when the new value is an array (`items`): one item per line, indented
    like the old second line, with the closing line's indent and comment kept."""
    first = doc.lines[entry.start]
    nl = doc.newline(entry.end - 1) if doc.lines[entry.end - 1].endswith("\n") else ""
    head = first[:entry.eq + 1]
    if entry.end - entry.start > 1 and items is not None:
        second, last = doc.lines[entry.start + 1], doc.lines[entry.end - 1]
        indent = second[:len(second) - len(second.lstrip())] or "  "
        close = last[:len(last) - len(last.lstrip())]
        body = last.rstrip("\r\n")
        comment = body[doc.code(entry.end - 1).rindex("]") + 1:]  # the closing line's spacing and comment
        inner = doc.newline(entry.start)
        return ([head + " [" + inner] + [f"{indent}{_fmt(x)},{inner}" for x in items]
                + [f"{close}]{comment}{nl}"])
    if entry.end - entry.start == 1:
        code = doc.code(entry.start)
        rest = code[entry.eq + 1:]
        lead = rest[:len(rest) - len(rest.lstrip())] or " "
        tail = rest[len(rest.rstrip()):] + first.rstrip("\r\n")[len(code):]
        return [head + lead + value + tail + nl]
    return [head + " " + value + nl]


# ---------------------------------------------------------------------------------------------------------------
# The edits

def _set_threshold(text: str, edit: dict) -> str:
    table, key = str(_need(edit, "table")), _need(edit, "key")
    raw = _parse(text, "ruleset")
    tbl = raw.get("thresholds", {}).get(table)
    if not isinstance(tbl, dict):
        raise EditError(f"set_threshold: unknown thresholds table {table!r}")
    if not isinstance(key, str) or key not in tbl:
        raise EditError(f"set_threshold: unknown threshold {key!r} in [thresholds.{table}]")
    what = f"[thresholds.{table}] {key}"
    _check_old(edit, tbl[key], what)
    new = _number(_need(edit, "new"), tbl[key], what)
    doc = _Doc(text)
    entry = doc.find_key(("thresholds", table), (key,))
    if entry is None:
        raise EditError(f"set_threshold: can't find the line for {what}")
    return doc.replace_lines(entry.start, entry.end, _value_line(doc, entry, _fmt(new)))


def _list_add(text: str, edit: dict) -> str:
    name, values = _need(edit, "list"), _need(edit, "values")
    if not (isinstance(values, (list, tuple)) and values and all(isinstance(v, str) and v for v in values)):
        raise EditError(f"list_add: values must be a non-empty list of non-empty strings, got {values!r}")
    raw = _parse(text, "ruleset")
    current = raw.get("lists", {}).get(name) if isinstance(name, str) else None
    if not isinstance(current, list):
        raise EditError(f"list_add: unknown list {name!r}")
    seen = {str(x).casefold() for x in current}
    add = []
    for v in values:
        if v.casefold() not in seen:
            seen.add(v.casefold())
            add.append(v)
    if not add:
        return text
    doc = _Doc(text)
    entry = doc.find_key(("lists",), (name,))
    if entry is None:
        raise EditError(f"list_add: can't find the line for [lists] {name}")
    lo = doc.offsets[entry.start] + entry.eq + 1
    hi = doc.offsets[entry.end - 1] + len(doc.lines[entry.end - 1])
    sig = [j for j in range(lo, hi) if doc.cls[j] != _COMMENT and not text[j].isspace()]  # strings count
    if (len(sig) < 2 or text[sig[0]] != "[" or text[sig[-1]] != "]"
            or doc.cls[sig[0]] != _CODE or doc.cls[sig[-1]] != _CODE):
        raise EditError(f"list_add: [lists] {name} isn't written as a plain array")
    close, prev = sig[-1], sig[-2]
    close_line_start = text.rfind("\n", 0, close) + 1
    if "\n" in text[sig[0]:close] and not text[close_line_start:close].strip():
        # multi-line: one item per line, before the line holding `]`, indented like the last item
        if text[prev] == "[":
            indent = text[close_line_start:close] + "  "
        else:
            prev_line_start = text.rfind("\n", 0, prev) + 1
            prev_line = text[prev_line_start:prev]
            indent = prev_line[:len(prev_line) - len(prev_line.lstrip())]
        nl = "\r\n" if text[close_line_start - 2:close_line_start] == "\r\n" else "\n"
        block = "".join(f"{indent}{_string(v)},{nl}" for v in add)
        out = text[:close_line_start] + block + text[close_line_start:]
        if text[prev] not in ",[":
            out = out[:prev + 1] + "," + out[prev + 1:]
        return out
    items = ", ".join(_string(v) for v in add)
    sep = "" if text[prev] == "[" else (" " if text[prev] == "," else ", ")
    return text[:prev + 1] + sep + items + text[prev + 1:]


def _rule_index(raw: dict, rule) -> int:
    rules = raw.get("rules")
    hits = [k for k, r in enumerate(rules if isinstance(rules, list) else [])
            if isinstance(r, dict) and str(r.get("id")) == str(rule)]
    if len(hits) != 1:
        raise EditError(f"unknown rule {rule!r}" if not hits else f"rule {rule!r} appears {len(hits)} times")
    return hits[0]


def _rule_field(text: str, edit: dict) -> str:
    rule, fld = _need(edit, "rule"), _need(edit, "field")
    if fld not in RULE_FIELDS:
        raise EditError(f"rule_field: field must be one of {', '.join(RULE_FIELDS)}, got {fld!r}")
    raw = _parse(text, "ruleset")
    k = _rule_index(raw, rule)
    current = raw["rules"][k].get(fld)
    what = f"rule {rule} {fld}"
    _check_old(edit, current, what)
    new = _need(edit, "new")
    if new is None and fld == "severity":
        raise EditError(f"rule_field: a rule's severity can't be removed (rule {rule})")
    if new is not None:
        if fld == "models":
            if not (isinstance(new, (list, tuple)) and all(isinstance(m, str) and m for m in new)):
                raise EditError(f"rule_field: models must be a list of model ids, got {new!r}")
        elif not isinstance(new, str):
            raise EditError(f"rule_field: {fld} must be a string, got {new!r}")
    doc = _Doc(text)
    if doc.header(("rules",), k) is None:
        raise EditError(f"rule_field: can't find the [[rules]] block for rule {rule}")
    entry = doc.find_key(("rules",), (fld,), k)
    if new is None:
        if entry is None:
            return text
        return doc.replace_lines(entry.start, entry.end, [])
    if entry is not None:
        items = list(new) if isinstance(new, (list, tuple)) else None
        return doc.replace_lines(entry.start, entry.end, _value_line(doc, entry, _fmt(new), items))
    keys = doc.table_keys(("rules",), k)
    after = doc.find_key(("rules",), ("severity",), k) or (keys[-1] if keys else doc.header(("rules",), k))
    last = doc.lines[after.end - 1]
    nl = doc.newline(after.end - 1)
    first = doc.lines[after.start]
    indent = first[:len(first) - len(first.lstrip())] if after.kind == "key" else ""
    head = [] if last.endswith("\n") else [nl]  # the block was the file's unterminated last line
    return doc.replace_lines(after.end, after.end, head + [f"{indent}{fld} = {_fmt(new)}{nl}"])


def _rule_remove(text: str, edit: dict) -> str:
    rule = _need(edit, "rule")
    raw = _parse(text, "ruleset")
    k = _rule_index(raw, rule)
    old = edit.get("old")  # the rule's state when the removal was proposed; older proposals carry none
    if old is not None:
        if not isinstance(old, dict):
            raise EditError(f"rule_remove: old must be a table of rule fields, got {old!r}")
        for fld, value in sorted(old.items()):
            _check_old({"old": value}, raw["rules"][k].get(fld), f"rule {rule} {fld}")
    doc = _Doc(text)
    head = doc.header(("rules",), k)
    if head is None:
        raise EditError(f"rule_remove: can't find the [[rules]] block for rule {rule}")
    keys = doc.table_keys(("rules",), k)
    end = keys[-1].end if keys else head.end
    while end > head.end and not doc.lines[end - 1].strip():  # a key's span never ends on a blank, but be sure
        end -= 1
    start = head.start
    if start > 0 and not doc.lines[start - 1].strip():
        start -= 1
    return doc.replace_lines(start, end, [])


_FIELD_ORDER = ("name", "method", "group", "severity", "judge_may_block", "requires", "content_types", "status",
                "era", "models", "source")


def _key_name(k, what: str) -> str:
    if not (isinstance(k, str) and _BARE.fullmatch(k)):
        raise EditError(f"rule_add: {what} {k!r} isn't a plain key (letters, digits, _ and -)")
    return k


def _insert_after(doc: _Doc, after: _Entry, lines: list[str], blank: bool = False) -> str:
    """`lines` (no newlines) inserted after `after`'s last line, with the file's newline, and a blank line first when
    `blank`."""
    nl = doc.newline(after.end - 1)
    pad = [] if doc.lines[after.end - 1].endswith("\n") else [nl]  # the entry was the file's unterminated last line
    return doc.replace_lines(after.end, after.end, pad + ([nl] if blank else []) + [f"{x}{nl}" for x in lines])


def _rule_add(text: str, edit: dict) -> str:
    rule, block = _need(edit, "rule"), _need(edit, "block")
    if not (isinstance(rule, str) and rule):
        raise EditError(f"rule_add: rule must be a non-empty id string, got {rule!r}")
    if not (isinstance(block, dict) and block):
        raise EditError(f"rule_add: block must be a table of rule fields, got {block!r}")
    if str(block.get("id", rule)) != rule:
        raise EditError(f"rule_add: the block's id {block['id']!r} isn't the rule {rule!r}")
    for k in ("name", "method", "severity"):
        if k not in block:
            raise EditError(f"rule_add: the block needs {k!r}")
    new_lists, new_thresholds = edit.get("lists") or {}, edit.get("thresholds") or {}
    if not (isinstance(new_lists, dict) and isinstance(new_thresholds, dict)):
        raise EditError("rule_add: lists and thresholds must be tables")
    raw = _parse(text, "ruleset")
    if any(isinstance(r, dict) and str(r.get("id")) == rule for r in raw.get("rules", [])):
        raise EditError(f"rule_add: rule {rule} already exists")
    if "lint" in str(block.get("method")):
        from plainspoken.report import ALL_CHECKS  # deferred: report imports the checks, which import this package
        if rule not in ALL_CHECKS:
            raise EditError(f"rule_add: no lint check for rule {rule} in this plugin version: add the check first")
    # A fixed field order, so the block reads like its neighbours whatever order the proposal's JSON stored it in.
    order = sorted((k for k in block if k != "id"),
                   key=lambda k: (_FIELD_ORDER.index(k) if k in _FIELD_ORDER else len(_FIELD_ORDER), k))
    fields = [f"{_key_name(k, 'field')} = {_fmt(block[k])}" for k in order]
    have_lists = raw.get("lists", {})
    list_lines = []
    for name, values in new_lists.items():
        if _key_name(name, "list") in have_lists:
            raise EditError(f"rule_add: [lists] {name} already exists: use list_add")
        if not (isinstance(values, (list, tuple)) and values and all(isinstance(v, str) and v for v in values)):
            raise EditError(f"rule_add: [lists] {name} values must be a non-empty list of non-empty strings")
        list_lines.append(f"{name} = {_fmt(list(values))}")
    defaults = raw.get("thresholds", {}).get("default", {})
    threshold_lines = []
    for key, value in new_thresholds.items():
        if _key_name(key, "threshold") in defaults:
            raise EditError(f"rule_add: threshold {key} already exists: use set_threshold")
        if not isinstance(value, (int, float)):
            raise EditError(f"rule_add: threshold {key} must be a number or true/false, got {value!r}")
        threshold_lines.append(f"{key} = {_fmt(value)}")
    out = text
    if threshold_lines:
        doc = _Doc(out)
        keys = doc.table_keys(("thresholds", "default"))
        after = keys[-1] if keys else doc.header(("thresholds", "default"))
        if after is None:
            raise EditError('rule_add: can\'t find the [thresholds."default"] table')
        out = _insert_after(doc, after, threshold_lines)
    if list_lines:
        doc = _Doc(out)
        keys = doc.table_keys(("lists",))
        after = keys[-1] if keys else doc.header(("lists",))
        if after is None:
            raise EditError("rule_add: can't find the [lists] table")
        out = _insert_after(doc, after, list_lines)
    doc = _Doc(out)
    k = len(raw.get("rules", [])) - 1
    if k < 0:
        raise EditError("rule_add: the ruleset has no [[rules]] block to follow")
    keys = doc.table_keys(("rules",), k)
    after = keys[-1] if keys else doc.header(("rules",), k)
    if after is None:
        raise EditError("rule_add: can't find the last [[rules]] block")
    return _insert_after(doc, after, ["[[rules]]", f"id = {_string(rule)}"] + fields, blank=True)


def _threshold_add(text: str, edit: dict) -> str:
    key, value = _need(edit, "key"), _need(edit, "value")
    if not (isinstance(key, str) and _BARE.fullmatch(key)):
        raise EditError(f"threshold_add: {key!r} isn't a plain key (letters, digits, _ and -)")
    if not isinstance(value, (int, float)):
        raise EditError(f"threshold_add: {key} must be a number or true/false, got {value!r}")
    if key in _parse(text, "ruleset").get("thresholds", {}).get("default", {}):
        raise EditError(f"threshold_add: threshold {key} already exists: use set_threshold")
    doc = _Doc(text)
    after_key = edit.get("after")
    if after_key is not None:
        after = doc.find_key(("thresholds", "default"), (str(after_key),))
        if after is None:
            raise EditError(f"threshold_add: no threshold {after_key!r} to put {key} after")
    else:
        keys = doc.table_keys(("thresholds", "default"))
        after = keys[-1] if keys else doc.header(("thresholds", "default"))
        if after is None:
            raise EditError('threshold_add: can\'t find the [thresholds."default"] table')
    return _insert_after(doc, after, [f"{key} = {_fmt(value)}"])


_RULESET_EDITS = {"set_threshold": _set_threshold, "list_add": _list_add, "rule_field": _rule_field,
                  "rule_remove": _rule_remove, "rule_add": _rule_add, "threshold_add": _threshold_add}


def _check_edits(edits) -> None:
    if not isinstance(edits, (list, tuple)) or not edits:
        raise EditError("nothing to change: no edits")
    for e in edits:
        if not isinstance(e, dict):
            raise EditError(f"an edit must be a table, got {e!r}")


def _dangling_aliases(raw: dict) -> set[tuple[str, str]]:
    ids = {str(r.get("id")) for r in raw.get("rules", []) if isinstance(r, dict)}
    return {(str(a), str(b)) for a, b in raw.get("aliases", {}).items() if str(a) not in ids or str(b) not in ids}


def load_text(text: str):
    """The ruleset `text` loaded as a `registry.Config` (through a temporary file). Raises EditError when it doesn't
    load."""
    with tempfile.TemporaryDirectory(prefix="plainspoken-rulesedit-") as tmp:
        path = Path(tmp) / "rules.toml"
        path.write_text(text, encoding="utf-8")
        try:
            return load_config(path)
        except (ValueError, OSError) as e:
            raise EditError(f"the edited ruleset doesn't load: {_first_line(e)}".replace(str(path), "rules.toml")) \
                from None


def _validate_ruleset(before: str, after: str) -> None:
    raw = _parse(after, "edited ruleset")
    load_text(after)
    dangling = _dangling_aliases(raw) - _dangling_aliases(tomllib.loads(before))
    if dangling:
        a, b = sorted(dangling)[0]
        raise EditError(f"the edited ruleset leaves the alias {a} → {b} pointing at a missing rule")


def apply_edits(text: str, edits: list[dict]) -> str:
    """`text` (a rules.toml) with every edit applied in order, each against the result of the one before."""
    _check_edits(edits)
    _parse(text, "ruleset")
    out = text
    for e in edits:
        fn = _RULESET_EDITS.get(e.get("kind"))
        if fn is None:
            raise EditError(f"unknown edit kind {e.get('kind')!r} (expected one of {', '.join(_RULESET_EDITS)})")
        out = fn(out, e)
    if out == text:
        raise EditError("nothing to change: every edit is already in the ruleset")
    _validate_ruleset(text, out)
    return out


# ---------------------------------------------------------------------------------------------------------------
# Profiles

def _profile_threshold(text: str, edit: dict, defaults: dict) -> str:
    table, key = edit.get("table", "default"), _need(edit, "key")
    if table != "default":
        raise EditError(f"a profile's [thresholds] override the 'default' table only, not {table!r}")
    if not isinstance(key, str) or key not in defaults:
        raise EditError(f"set_threshold: unknown threshold {key!r}")
    raw = _parse(text, "profile")
    th = raw.get("thresholds", {})
    if not isinstance(th, dict):
        raise EditError("the profile's [thresholds] isn't a table")
    current = th.get(key, defaults[key])
    what = f"[thresholds] {key}" + ("" if key in th else " (the ruleset default)")
    _check_old(edit, current, what)
    new = _fmt(_number(_need(edit, "new"), defaults[key], f"[thresholds] {key}"))
    doc = _Doc(text)
    entry = doc.find_key(("thresholds",), (key,))
    if key in th:
        if entry is None:
            raise EditError(f"set_threshold: can't find the line for [thresholds] {key}")
        return doc.replace_lines(entry.start, entry.end, _value_line(doc, entry, new))
    head = doc.header(("thresholds",))
    if head is None:
        if "thresholds" in raw:
            raise EditError("set_threshold: the profile's thresholds aren't under a [thresholds] header")
        nl = "\r\n" if "\r\n" in text else "\n"
        body = text if not text or text.endswith("\n") else text + nl
        return body + ("" if not body or body.endswith(nl * 2) else nl) + f"[thresholds]{nl}{key} = {new}{nl}"
    keys = doc.table_keys(("thresholds",))
    after = keys[-1] if keys else head
    nl = doc.newline(after.end - 1)
    pad = [] if doc.lines[after.end - 1].endswith("\n") else [nl]
    return doc.replace_lines(after.end, after.end, pad + [f"{key} = {new}{nl}"])


def apply_profile_edits(text: str, edits: list[dict], cfg=None) -> str:
    """`text` (a profile TOML) with `set_threshold` edits written into its `[thresholds]` table. `old` is checked
    against the profile's value, or the ruleset default when the profile doesn't set it. `cfg` is the ruleset
    (default: `registry.load_config()`)."""
    _check_edits(edits)
    cfg = load_config() if cfg is None else cfg
    defaults = cfg.thresholds()
    _parse(text, "profile")
    out = text
    for e in edits:
        if e.get("kind") != "set_threshold":
            raise EditError(f"a profile takes set_threshold edits only, got {e.get('kind')!r}")
        out = _profile_threshold(out, e, defaults)
    if out == text:
        raise EditError("nothing to change: every edit is already in the profile")
    raw = _parse(out, "edited profile")
    where = Path("profile")
    try:
        # The loader's own validation (profile.load minus the file reads: the text has no folder here, so a
        # relative [judges] calibration_notes path can't be resolved, and a threshold edit can't change it).
        _profile._validate(where, raw)
        rules = raw.get("rules", {})
        cfg.check_profile(_profile.Profile(name=raw["profile"]["name"], thresholds=dict(raw.get("thresholds", {})),
                                           rules_disabled=frozenset(rules.get("disabled", [])), source=str(where)))
    except ValueError as e:
        raise EditError(f"the edited profile doesn't load: {_first_line(e)}") from None
    return out


# ---------------------------------------------------------------------------------------------------------------
# Versions, diff, changelog

def bump(version: str, part: str) -> str:
    m = _SEMVER.fullmatch(version) if isinstance(version, str) else None
    if m is None:
        raise EditError(f"not a MAJOR.MINOR.PATCH version: {version!r}")
    if part not in _PARTS:
        raise EditError(f"bump part must be one of {', '.join(_PARTS)}, got {part!r}")
    major, minor, patch = (int(x) for x in m.groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def set_version(text: str, new: str) -> str:
    """`text` with its top-level `version = "…"` line set to `new`."""
    if not (isinstance(new, str) and _SEMVER.fullmatch(new)):
        raise EditError(f"not a MAJOR.MINOR.PATCH version: {new!r}")
    raw = _parse(text, "ruleset")
    if not isinstance(raw.get("version"), str):
        raise EditError("the ruleset has no top-level version line")
    doc = _Doc(text)
    entry = doc.find_key((), ("version",))
    if entry is None:
        raise EditError("can't find the ruleset's top-level version line")
    out = doc.replace_lines(entry.start, entry.end, _value_line(doc, entry, _string(new)))
    if _parse(out, "edited ruleset").get("version") != new:
        raise EditError("the version edit didn't take")
    return out


def diff(old: str, new: str, name: str) -> str:
    """A unified diff from `a/<name>` to `b/<name>` (empty when the texts are equal)."""
    out = []
    for line in difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                     fromfile=f"a/{name}", tofile=f"b/{name}"):
        out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)


def _one_line(value, limit: int = 200) -> str:
    s = " ".join(str(value).split())
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


def _evidence(evidence) -> str:
    """Metric values and facet counts as one line. Excerpts are article text, so they never reach the changelog."""
    if not isinstance(evidence, dict):
        return _one_line(evidence) if evidence else ""
    parts = []
    for k in sorted(evidence):
        if k in _EXCERPT_KEYS:
            continue
        v = evidence[k]
        if isinstance(v, dict):
            v = ", ".join(f"{ik} {_inner(v[ik])}" for ik in sorted(v, key=str) if ik not in _EXCERPT_KEYS)
        elif isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v)
        parts.append(f"{k} {v}")
    return _one_line("; ".join(parts))


def _inner(v) -> str:
    """A second-level evidence value, flattened (`{'false_positive': 4}` → `false_positive 4`) so no Python repr
    reaches the changelog; deeper levels flatten the same way, and excerpt keys are dropped at every level."""
    if isinstance(v, dict):
        return " ".join(f"{k} {_inner(v[k])}" for k in sorted(v, key=str) if k not in _EXCERPT_KEYS)
    if isinstance(v, (list, tuple)):
        return " ".join(_inner(x) for x in v)
    return str(v)


def changelog_entry(version: str, date: str, proposal: dict, approver: str) -> str:
    """A `## <version> (<date>)` section, in the style of data/RULESET-CHANGELOG.md: the proposal id, rule and
    action (and trigger), its summary, one line of evidence, and who approved it."""
    p = proposal if isinstance(proposal, dict) else {}
    head = f"- {_one_line(p.get('id', '(no id)'), 60)}: rule {_one_line(p.get('rule', '?'), 40)}, " \
           f"{_one_line(p.get('action', '?'), 40)}"
    if p.get("trigger"):
        head += f" (trigger: {_one_line(p['trigger'], 40)})"
    if p.get("summary"):
        head += f". {_one_line(p['summary'])}"
    lines = [f"## {_one_line(version, 40)} ({_one_line(date, 40)})", "", head,
             f"- Evidence: {_evidence(p.get('evidence')) or 'none recorded'}",
             f"- Approved by {_one_line(approver, 80)}."]
    return "\n".join(lines) + "\n"
