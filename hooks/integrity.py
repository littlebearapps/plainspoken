"""PostToolUse integrity: after a Write/Edit of a target file, flag prominent numbers that nothing sources.

`[integrity] mode` in .plainspoken/config.toml: `warn` (the default) feeds the findings back as context; `block` returns
a block decision on every matching edit while findings remain, telling Claude to fix them before going on (PostToolUse
can't undo the edit); `off` is silent. Files: `[integrity] paths`, else the plugin `targets` option, else `**/*.md`;
never plainspoken's own files (lib/plainspoken/integrity.py `is_internal`).

A thin caller: with a claims ledger for the file the result is the ledger's value gaps (extraction.value_gaps);
without one, the deterministic checks in lib/plainspoken/integrity.py. In warn mode only a change in a file's result
is sent again in a session. Fails open: any problem is exit 0 with at most one context line."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402

LIMIT = 2000
STATE = "integrity-state.json"


def _skipped(e: Exception) -> int:
    first = str(e).splitlines()[0] if str(e) else ""
    _common.emit_context("PostToolUse", _common.clip(f"plainspoken integrity skipped: {type(e).__name__}: {first}",
                                                     LIMIT))
    return 0


def _emit(mode: str, text: str) -> None:
    if mode == "block":
        reason = "The edit is saved, but fix this before going on.\n" + text
        print(json.dumps({"decision": "block", "reason": _common.clip(reason, LIMIT)}))
    else:
        _common.emit_context("PostToolUse", _common.clip(text, LIMIT))


def _result(path: Path, project: Path) -> str | None:
    """The message for this file, or None when there's nothing to report."""
    from plainspoken import claims, extraction, integrity
    content = path.read_text(encoding="utf-8")
    ledger_path = claims.ledger_path_for(path, project)
    if ledger_path.exists():
        gaps = extraction.value_gaps(content, claims.load_ledger(ledger_path), extraction.platform_names(project))
        rel = _common.relative(str(ledger_path), project) or ledger_path.name
        return integrity.gaps_message(path.name, rel, gaps) if gaps else None
    rows = integrity.findings(content)
    return integrity.unsourced_message(path.name, rows) if rows else None


def main() -> int:
    event = _common.read_event(sys.stdin)
    if not event:
        return 0
    return _common.for_each_edit(event, _one)


def _one(event: dict) -> int:
    tool_input = event.get("tool_input")
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(path, str) or not path:
        return 0
    try:  # the library needs Python 3.11+ (tomllib); an older python3 must not crash every Write/Edit
        from plainspoken import config, integrity  # _common puts lib/ on sys.path
        project = (Path(os.environ["CLAUDE_PROJECT_DIR"]) if os.environ.get("CLAUDE_PROJECT_DIR")
                   else config.project_root(Path(event.get("cwd") or ".")))
    except Exception as e:
        return _skipped(e)
    rel = _common.relative(path, project)
    if rel is None or integrity.is_internal(rel):
        return 0
    settings, problem = None, None
    try:
        settings = config.integrity_settings(project)
    except Exception as e:  # a malformed project config: say so, but only for files the targets option covers
        problem = e
    paths = settings["paths"] if settings else None
    targets = paths if paths is not None else _common.parse_targets(os.environ.get("CLAUDE_PLUGIN_OPTION_TARGETS"))
    if not any(_common.glob_match(rel, t) for t in targets):
        return 0
    if problem is not None:
        return _skipped(problem)
    mode = settings["mode"]
    if mode == "off":
        return 0
    try:
        text = _result(Path(path), project)
    except Exception as e:
        return _skipped(e)
    data = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or project / ".plainspoken")
    key = "QUIET" if text is None else hashlib.sha256(f"{mode}\n{text}".encode("utf-8")).hexdigest()
    previous = _common.record_state(data, STATE, f"{event.get('session_id')}|{rel}", key)
    if text is None:
        if previous not in (None, "QUIET"):
            _common.emit_context("PostToolUse",
                                 f"plainspoken integrity: {Path(path).name} has no unsourced numbers or ledger gaps now.")
        return 0
    if previous == key and mode != "block":  # block repeats: the edit stands until the findings are fixed
        return 0
    _emit(mode, text)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # never break an edit
        sys.exit(0)
