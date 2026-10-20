"""The shipped claims data, `data/claims.toml`: one read shared by extraction (`[extraction]`) and reader value
(`[reader_value]`). A project never edits this file; it adds to it in `.plainspoken/config.toml`."""
from __future__ import annotations

import functools
import tomllib
from pathlib import Path

__all__ = ["DATA_PATH", "load", "string_list"]

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "claims.toml"


@functools.lru_cache(maxsize=1)
def load() -> dict:
    """The parsed `data/claims.toml`. Callers read it and never change it."""
    return tomllib.loads(DATA_PATH.read_text(encoding="utf-8"))


def string_list(section: str, key: str) -> tuple[str, ...]:
    """`[section] key` as a tuple of stripped strings; a missing or malformed list raises ValueError."""
    value = load().get(section, {}).get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ValueError(f"{DATA_PATH}: [{section}] {key} must be a list of non-empty strings")
    return tuple(v.strip() for v in value)
