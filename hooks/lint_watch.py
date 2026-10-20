"""PostToolUse lint-watch: after a Write/Edit of a target file, feed the lint summary back to Claude.

Watch only: never blocks, always exits 0. Any problem becomes one context line (or silence for bad stdin).
Results with no BLOCK or WARN are silent, except the first one after a noisy result. Only a change in a file's result
is sent again. Every change of result, sent or silent, has its fired spans recorded in the kaizen ledger (capture
never adds context), under the project root `check` finds from the file's folder (`_common.capture_root`).

The project's `[lint_watch]` section turns it off (`mode = "off"`: nothing linted, sent or recorded) or sets the files
it watches (`paths`, which beat the plugin `targets` option). A file gets its own `[engine] profiles` entry's profile.
A config that can't be read doesn't silence it: target files get one "skipped" line naming the problem."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402


def _skipped(e: Exception) -> int:
    """Watch only: fail open with one context line naming the problem."""
    first = str(e).splitlines()[0] if str(e) else ""
    _common.emit_context("PostToolUse", f"plainspoken lint skipped: {type(e).__name__}: {first}")
    return 0


def main() -> int:
    event = _common.read_event(sys.stdin)
    if not event:
        return 0
    try:  # the library needs Python 3.11+ (tomllib); an older python3 must not crash every Write/Edit
        from plainspoken import config, report  # _common puts lib/ on sys.path
        path = (event.get("tool_input") or {}).get("file_path")
        project = (Path(os.environ["CLAUDE_PROJECT_DIR"]) if os.environ.get("CLAUDE_PROJECT_DIR")
                   else config.project_root(Path(event.get("cwd") or ".")))
    except Exception as e:
        return _skipped(e)
    rel = _common.relative(path, project) if isinstance(path, str) else None
    if rel is None:
        return 0
    try:
        watch = config.lint_watch(project)
    except (ValueError, OSError):  # a bad config: the profile below reports it, on target files only
        watch = {"mode": "on", "paths": None}
    if watch["mode"] == "off":
        return 0
    targets = watch["paths"]
    if targets is None:
        targets = _common.parse_targets(os.environ.get("CLAUDE_PLUGIN_OPTION_TARGETS"))
    if not any(_common.glob_match(rel, t) for t in targets):
        return 0
    try:
        # plugin_option="default": an unset option falls back to the plugin's declared default (an installed copy
        # gets the options, a --plugin-dir one doesn't: facts §2, §11); project config and env still win.
        profile = config.resolve_profile(None, project, os.environ, plugin_option="default", target=Path(path))
        from plainspoken import capture
        from plainspoken.registry import load_config
        cfg = load_config()
        lint = report.run_lint(Path(path), profile, cfg=cfg)
        text = report.summarise(lint)
    except Exception as e:  # watch only: fail open, one line
        return _skipped(e)
    quiet = not any(f["severity"] in ("BLOCK", "WARN") for f in lint["findings"])
    data = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or project / ".plainspoken")
    slot = f"{event.get('session_id')}|{rel}"
    key = "QUIET" if quiet else hashlib.sha256(text.encode("utf-8")).hexdigest()
    previous = _common.record_state(data, "lint-watch-state.json", slot, key)
    if previous == key:
        return 0
    # The result changed: log its fired spans (kaizen capture; never raises, at most one stderr line), under the
    # root `check` finds from the edited file's folder, so the document id and the ledger are the ones `check` and
    # `kaizen` use, whatever folder the session has `cd`-ed into.
    try:
        root = _common.capture_root(path, project)
    except Exception:  # watch only: an unresolvable root costs the capture, never the edit
        root = project
    capture.for_lint(lint, Path(path), profile, cfg, root, "lint-watch")
    previous_was_noisy = previous not in (None, "QUIET")
    if quiet:
        if previous_was_noisy:
            _common.emit_context("PostToolUse", f"plainspoken lint: {Path(path).name} has no BLOCK or WARN findings now.")
        return 0
    _common.emit_context("PostToolUse", text)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # never block an edit
        sys.exit(0)
