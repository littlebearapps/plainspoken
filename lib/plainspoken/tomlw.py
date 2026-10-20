"""A small TOML writer, for the files the CLI writes (`claims scaffold`) and the fragments it prints (`claims pin`).

Supports str (basic strings with escapes), int, float, bool, lists of scalars, nested tables and arrays of tables;
anything else (None, dates, bytes, sets, tuples, nested or mixed lists, non-string keys) raises TypeError. The
round-trip property `tomllib.loads(dumps(x)) == x` holds for every value it accepts (NaN aside, which never equals
itself).

Layout: each table's scalar keys come first, then its sub-tables, then its arrays of tables. A table that holds only
sub-tables gets no header of its own, so `{"claims": {"binding": {...}}}` prints as a bare `[claims.binding]` block
that can be pasted under a `[[claims]]` entry.
"""
from __future__ import annotations

import math
import re

__all__ = ["dumps"]

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _string(s: str) -> str:
    out = []
    for ch in s:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _key(k: object) -> str:
    if not isinstance(k, str):
        raise TypeError(f"TOML keys must be strings, got {type(k).__name__}")
    return k if _BARE_KEY.match(k) else _string(k)


def _scalar(v: object) -> str:
    if isinstance(v, bool):  # before int: bool is an int subclass
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"
        if math.isinf(v):
            return "inf" if v > 0 else "-inf"
        return repr(v)
    if isinstance(v, str):
        return _string(v)
    raise TypeError(f"can't write a {type(v).__name__} as TOML")


def _value(v: object) -> str:
    if isinstance(v, list):
        if any(isinstance(item, (list, dict)) for item in v):
            raise TypeError("only lists of scalars (or lists of tables) can be written as TOML")
        return "[" + ", ".join(_scalar(item) for item in v) + "]"
    return _scalar(v)


def _is_table_array(v: object) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(item, dict) for item in v)


def _emit(table: dict, path: tuple[str, ...], out: list[str], header: str | None) -> None:
    """Append `table` to `out`. `header` is None (the root), "table" or "array"."""
    scalars, tables, arrays = [], [], []
    for k, v in table.items():
        _key(k)  # refuse a non-string key wherever it sits
        if isinstance(v, dict):
            tables.append((k, v))
        elif _is_table_array(v):
            arrays.append((k, v))
        else:
            scalars.append((k, _value(v)))
    dotted = ".".join(_key(p) for p in path)
    if header == "array":
        out.append(f"[[{dotted}]]")
    elif header == "table" and (scalars or not (tables or arrays)):
        out.append(f"[{dotted}]")
    out.extend(f"{_key(k)} = {v}" for k, v in scalars)
    for k, v in tables:
        _blank(out)
        _emit(v, (*path, k), out, "table")
    for k, items in arrays:
        for item in items:
            _blank(out)
            _emit(item, (*path, k), out, "array")


def _blank(out: list[str]) -> None:
    if out and out[-1] != "":
        out.append("")


def dumps(data: dict) -> str:
    """`data` as a TOML document (ending in a newline). Raises TypeError on anything outside the supported subset."""
    if not isinstance(data, dict):
        raise TypeError(f"a TOML document is a table (dict), got {type(data).__name__}")
    out: list[str] = []
    _emit(data, (), out, None)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n" if out else ""
