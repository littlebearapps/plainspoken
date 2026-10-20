"""Read YAML frontmatter without PyYAML: the subset articles actually use, and nothing else.

Supported: `key: value` mappings (nested by indentation), `- item` sequences (including a sequence of
mappings, and a sequence at the same indent as its key), flow sequences `[a, "b"]` on one line, plain,
"double" and 'single' quoted scalars (quoted ones may wrap lines), `|` / `>` block scalars, comments,
booleans, null, ints and floats as PyYAML reads them. Dates stay strings.

Anything else (anchors, aliases, tags, flow mappings, tabs, a multi-line flow sequence, a nested inline
sequence `- - x`, `|+` keep chomping, duplicate keys, nesting deep enough to exhaust the stack) raises
FrontmatterError, so a check never runs on frontmatter it half-read (fail closed).
"""
from __future__ import annotations

import re

__all__ = ["FrontmatterError", "load"]


class FrontmatterError(ValueError):
    """Frontmatter the reader doesn't support. A ValueError, so the CLI exits 2."""


_KEY = re.compile(r'^(?P<key>"[^"]*"|\'[^\']*\'|[^\s#\'"\-\[\]{},&*!|>][^:#]*?)\s*:(?:\s+|$)(?P<rest>.*)$')
_BOOL = {"true": True, "yes": True, "on": True, "false": False, "no": False, "off": False}
_INT = re.compile(r"^[-+]?(?:0|[1-9][0-9_]*)$")
_FLOAT = re.compile(r"^[-+]?(?:[0-9][0-9_]*\.[0-9_]*|\.[0-9_]+)(?:[eE][-+]?[0-9]+)?$")
_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "/": "/", "0": "\0", " ": " ", "r": "\r"}


def _indent(line: str) -> int:
    if "\t" in line[: len(line) - len(line.lstrip(" \t"))]:
        raise FrontmatterError("tab indentation isn't supported")
    return len(line) - len(line.lstrip(" "))


def _blank(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def _strip_comment(text: str) -> str:
    m = re.search(r"\s#", text)
    return text[: m.start()] if m else text


def _unescape(body: str, line: int) -> str:
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = body[i + 1 : i + 2]
        if nxt in _ESCAPES:
            out.append(_ESCAPES[nxt])
            i += 2
        elif nxt in ("x", "u", "U"):
            width = {"x": 2, "u": 4, "U": 8}[nxt]
            hexpart = body[i + 2 : i + 2 + width]
            if len(hexpart) != width or not re.fullmatch(r"[0-9A-Fa-f]+", hexpart):
                raise FrontmatterError(f"line {line}: bad \\{nxt} escape")
            out.append(chr(int(hexpart, 16)))
            i += 2 + width
        else:
            raise FrontmatterError(f"line {line}: unknown escape \\{nxt}")
    return "".join(out)


def _plain(text: str):
    t = text.strip()
    if t in ("", "~") or t.lower() == "null":
        return None
    if t.lower() in _BOOL:
        return _BOOL[t.lower()]
    if _INT.match(t):
        return int(t.replace("_", ""))
    if _FLOAT.match(t):
        return float(t.replace("_", ""))
    return t


class _Reader:
    def __init__(self, text: str):
        self.lines = text.split("\n")
        self.i = 0

    # -- helpers ---------------------------------------------------------------------------------------------
    def _next_content(self, start: int) -> int:
        j = start
        while j < len(self.lines) and _blank(self.lines[j]):
            j += 1
        return j

    def _fail(self, what: str) -> FrontmatterError:
        return FrontmatterError(f"line {self.i + 1}: {what}")

    # -- scalars ---------------------------------------------------------------------------------------------
    def _scalar(self, rest: str, indent: int):
        rest = rest.strip()
        if rest[:1] in ("&", "*", "!"):
            raise self._fail("anchors, aliases and tags aren't supported")
        if rest[:1] == "{":
            raise self._fail("flow mappings ({…}) aren't supported")
        if rest[:1] == "[":
            return self._flow_seq(rest)
        if rest[:1] in ('"', "'"):
            return self._quoted(rest)
        if rest[:1] in ("|", ">"):
            return self._block_scalar(rest, indent)
        if rest.startswith("- ") or rest == "-":
            raise self._fail("a `- item` can't follow `key:` on the same line")
        value = _strip_comment(rest)
        # plain scalar continuation: more-indented lines that aren't keys or items fold with a space
        parts = [value.strip()]
        j = self.i + 1
        while j < len(self.lines) and not _blank(self.lines[j]) and _indent(self.lines[j]) > indent:
            nxt = self.lines[j].strip()
            if nxt.startswith("- ") or _KEY.match(nxt):
                break
            parts.append(_strip_comment(nxt).strip())
            j += 1
        self.i = j - 1
        return _plain(" ".join(p for p in parts if p))

    def _quoted(self, rest: str):
        q = rest[0]
        buf, start_line = rest[1:], self.i + 1
        while True:
            end = self._closing(buf, q)
            if end is not None:
                body, tail = buf[:end], buf[end + 1 :].strip()
                if tail and not tail.startswith("#"):
                    raise self._fail("text after a closing quote")
                break
            self.i += 1
            if self.i >= len(self.lines):
                raise FrontmatterError(f"line {start_line}: unclosed quote")
            nxt = self.lines[self.i].strip()
            buf = buf.rstrip() + (" " + nxt if nxt else "\n")
        if q == "'":
            return body.replace("''", "'")
        return _unescape(body, start_line)

    @staticmethod
    def _closing(buf: str, q: str) -> int | None:
        i = 0
        while i < len(buf):
            if q == '"' and buf[i] == "\\":
                i += 2
                continue
            if buf[i] == q:
                if q == "'" and buf[i + 1 : i + 2] == "'":
                    i += 2
                    continue
                return i
            i += 1
        return None

    def _flow_seq(self, rest: str) -> list:
        rest = rest.strip()
        if '"' not in rest and "'" not in rest:
            text = _strip_comment(rest).strip()
        else:  # cut at the first `]` outside quotes; only whitespace and a comment may follow it
            end = self._flow_end(rest)
            tail = rest[end + 1 :] if end is not None else ""
            if tail and not (tail.strip() == "" or (tail[0].isspace() and tail.strip().startswith("#"))):
                raise self._fail("text after a [flow list]")
            text = rest[: end + 1] if end is not None else rest
        if not text.endswith("]"):
            raise self._fail("a [flow list] must close on the same line")
        items, buf, q = [], "", ""
        for ch in text[1:-1]:
            if q:
                buf += ch
                if ch == q:
                    q = ""
            elif ch in ('"', "'"):
                q, buf = ch, buf + ch
            elif ch in "[]{}":
                raise self._fail("nested flow collections aren't supported")
            elif ch == ",":
                items.append(buf)
                buf = ""
            else:
                buf += ch
        if buf.strip():
            items.append(buf)
        out = []
        for item in items:
            s = item.strip()
            if not s:
                continue
            if s[0] in ('"', "'"):
                end = self._closing(s[1:], s[0])
                if end is None or end != len(s) - 2:
                    raise self._fail("bad quoted item in a flow list")
                out.append(s[1:-1].replace("''", "'") if s[0] == "'" else _unescape(s[1:-1], self.i + 1))
            else:
                out.append(_plain(s))
        return out

    @staticmethod
    def _flow_end(text: str) -> int | None:
        """Index of the first `]` outside quotes in a flow list that starts at text[0] == "[", else None."""
        i, q = 1, ""
        while i < len(text):
            ch = text[i]
            if q == '"' and ch == "\\":
                i += 2
                continue
            if q:
                if ch == q:
                    if q == "'" and text[i + 1 : i + 2] == "'":
                        i += 2
                        continue
                    q = ""
            elif ch in ('"', "'"):
                q = ch
            elif ch == "]":
                return i
            i += 1
        return None

    def _block_scalar(self, rest: str, indent: int) -> str:
        head = _strip_comment(rest).strip()
        m = re.fullmatch(r"([|>])([1-9]?)([+-]?)([1-9]?)", head)
        if not m:
            raise self._fail(f"bad block scalar header {head!r}")
        style, chomp = m.group(1), m.group(3)
        if chomp == "+":
            raise self._fail("keep chomping (|+ or >+) isn't supported")
        body: list[str] = []
        j = self.i + 1
        block_indent = None
        last = self.i  # index of the block's last content line
        while j < len(self.lines):
            line = self.lines[j]
            if line.strip() == "":
                body.append("")
                j += 1
                continue
            ind = _indent(line)
            if ind <= indent:
                break
            block_indent = ind if block_indent is None else block_indent
            body.append(line[block_indent:])
            last = j
            j += 1
        self.i = j - 1
        # YAML keeps the final line break only if the source has one after the last content line
        has_break = last < len(self.lines) - 1
        while body and body[-1] == "":
            body.pop()
        if style == "|":
            text = "\n".join(body)
        else:
            text, para = "", []
            for line in body:
                if line == "":
                    text += " ".join(para) + "\n"
                    para = []
                else:
                    para.append(line)
            text += " ".join(para)
        if chomp == "-" or not has_break:
            return text
        return text + "\n" if text else text

    # -- collections ----------------------------------------------------------------------------------------
    def block(self, indent: int):
        j = self._next_content(self.i)
        if j >= len(self.lines):
            return None
        self.i = j
        line = self.lines[j]
        if _indent(line) != indent:
            raise self._fail("unexpected indentation")
        stripped = line.strip()
        if stripped == "-" or stripped.startswith("- "):
            return self.sequence(indent)
        return self.mapping(indent)

    def mapping(self, indent: int) -> dict:
        out: dict = {}
        while True:
            j = self._next_content(self.i)
            if j >= len(self.lines) or _indent(self.lines[j]) < indent:
                return out
            self.i = j
            line = self.lines[j]
            if _indent(line) > indent:
                raise self._fail("unexpected indentation")
            m = _KEY.match(line.strip())
            if not m:
                raise self._fail("expected `key: value`")
            key = m.group("key")
            if key[:1] in ('"', "'"):
                key = key[1:-1]
            if key in out:
                raise self._fail(f"duplicate key {key!r}")
            rest = m.group("rest")
            if _strip_comment(" " + rest).strip() == "":
                k = self._next_content(j + 1)
                if k < len(self.lines) and _indent(self.lines[k]) > indent:
                    self.i = k
                    out[key] = self.block(_indent(self.lines[k]))
                elif k < len(self.lines) and _indent(self.lines[k]) == indent and (
                    self.lines[k].strip() == "-" or self.lines[k].strip().startswith("- ")
                ):
                    self.i = k
                    out[key] = self.sequence(indent)
                else:
                    out[key] = None
                    self.i = j + 1
            else:
                out[key] = self._scalar(rest, indent)
                self.i += 1

    def sequence(self, indent: int) -> list:
        out: list = []
        while True:
            j = self._next_content(self.i)
            if j >= len(self.lines) or _indent(self.lines[j]) != indent:
                return out
            stripped = self.lines[j].strip()
            if not (stripped == "-" or stripped.startswith("- ")):
                return out
            self.i = j
            rest = stripped[1:].strip()
            if rest == "-" or rest.startswith("- "):
                raise self._fail("nested inline sequences (- - x) aren't supported")
            if rest == "" or rest.startswith("#"):
                k = self._next_content(j + 1)
                if k < len(self.lines) and _indent(self.lines[k]) > indent:
                    self.i = k
                    out.append(self.block(_indent(self.lines[k])))
                else:
                    out.append(None)
                    self.i = j + 1
            elif _KEY.match(rest) and rest[:1] not in ('"', "'"):
                # "- key: value" opens a mapping: blank out the dash and read it at the key's column
                col = indent + 1
                col += len(self.lines[j][col:]) - len(self.lines[j][col:].lstrip(" "))
                self.lines[j] = " " * col + self.lines[j][col:]
                out.append(self.mapping(col))
            else:
                out.append(self._scalar(rest, indent))
                self.i += 1


def load(text: str) -> dict:
    """Parse frontmatter text (between the --- lines). An empty block is {}; a non-mapping is an error."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    reader = _Reader(text)
    j = reader._next_content(0)
    if j >= len(reader.lines):
        return {}
    first = reader.lines[j]
    if _indent(first) != 0:
        raise FrontmatterError(f"line {j + 1}: frontmatter must start at column 0")
    if first.strip().startswith("- "):
        raise FrontmatterError(f"line {j + 1}: frontmatter must be a mapping, not a list")
    try:
        value = reader.block(0)
    except RecursionError:
        raise FrontmatterError("frontmatter nests too deeply") from None
    k = reader._next_content(reader.i)
    if k < len(reader.lines):
        raise FrontmatterError(f"line {k + 1}: unexpected content")
    return value if isinstance(value, dict) else {}
