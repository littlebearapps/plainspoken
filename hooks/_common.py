"""Shared helpers for plainspoken's hooks: stdin, targets and glob matching. Stdlib only."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))


def read_event(stream) -> dict | None:
    try:
        data = json.load(stream)
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def kaizen_root(event: dict) -> Path:
    """The project root whose kaizen ledger the nudge and the backstop read: the one `check` and `kaizen` find
    (`config.project_root`, without CLAUDE_PROJECT_DIR, which the Bash tool doesn't get) from the session's working
    folder (the event's `cwd`). The session's Bash can `cd` into an unrelated checkout, so when that root has no
    `.plainspoken` folder, the root found from CLAUDE_PROJECT_DIR is used instead."""
    from plainspoken import config
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) and event.get("cwd") else None
    given = os.environ.get("CLAUDE_PROJECT_DIR")
    root = config.project_root(Path(cwd or given or "."), {})
    if given and not (root / ".plainspoken").is_dir():
        return config.project_root(Path(given), {})
    return root


def capture_root(path: str | Path, project: Path) -> Path:
    """The project root the lint-watch capture records an edited file under: the one `check` finds from the file's
    own folder (`config.project_root`, without CLAUDE_PROJECT_DIR), never the session's moving `cwd`, so an edit is
    never recorded in another repository. `project` when the file isn't under the root found."""
    from plainspoken import config
    try:
        file = Path(path).resolve()
        root = config.project_root(file.parent, {})
        file.relative_to(root)
        return root
    except (OSError, ValueError, RuntimeError):
        return project


def parse_targets(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return ["**/*.md"]
    try:
        value = json.loads(raw)
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            return value
    except ValueError:
        pass
    parts = re.split(r"[\n,]", raw)
    return [p.strip() for p in parts if p.strip()]


def _glob_regex(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def glob_match(rel: str, pattern: str) -> bool:
    return bool(_glob_regex(pattern).match(rel.replace("\\", "/")))


def relative(path: str, project: Path) -> str | None:
    try:
        return Path(path).resolve().relative_to(project.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def clip(text: str, limit: int = 4000) -> str:
    """Fit hook output under the cap, and show that it was cut."""
    from plainspoken._util import clip as _clip  # the one clip; stdlib-only, so safe on any python3
    return _clip(text, limit)


def emit_context(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": clip(text)}}))


# --- per-session hook state -------------------------------------------------------------------------------------
# The data folder may be <project>/.plainspoken/, which a repository can commit. Nothing found there is trusted: a
# symlinked folder or state file means "no state", and writes go through a fresh mkstemp file, never a fixed name.
STATE_LIMIT = 200


def _state_path(data: Path, name: str) -> Path | None:
    """`data/name`, or None when it isn't safe: the folder or the file is a symlink, or the file resolves outside
    the folder."""
    path = data / name
    try:
        if data.is_symlink() or path.is_symlink() or path.resolve().parent != data.resolve():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return path


def read_state(data: Path, name: str) -> dict:
    """The `last` mapping (slot → last result) in `data/name`; {} when there's none, it's unsafe or unreadable, or
    it's an older shape."""
    path = _state_path(data, name)
    if path is None:
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    last = state.get("last") if isinstance(state, dict) else None
    return last if isinstance(last, dict) else {}


def _write_state(data: Path, name: str, last: dict) -> None:
    try:
        data.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    path = _state_path(data, name)
    if path is None:
        return
    try:
        fd, tmp = tempfile.mkstemp(dir=data, prefix=f"{name}.", suffix=".tmp")
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"last": last}, f)
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError):
        try:
            os.unlink(tmp)
        except OSError:
            pass


def record_state(data: Path, name: str, slot: str, key: str) -> str | None:
    """Store `key` as `slot`'s latest result and return the previous one (None when there wasn't one). Only the last
    result per slot is kept, so A→B→A reports A again; the oldest slots go past STATE_LIMIT."""
    last = read_state(data, name)
    previous = last.get(slot)
    if previous != key:
        last.pop(slot, None)
        last[slot] = key
        while len(last) > STATE_LIMIT:
            last.pop(next(iter(last)))
        _write_state(data, name, last)
    return previous if isinstance(previous, str) else None
