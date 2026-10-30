"""Launcher: `python3 <plugin>/lib/run.py <args>` behaves like `python3 -m plainspoken <args>`, with no PYTHONPATH.

Skills and hooks call this (the plugin root holds no bin/ directory: claude.ai and Cowork reject one).

The engine needs Python 3.11+ (tomllib). An older python3 gets one plain line on stderr and exit 2 (exit 1 reads as
"lint BLOCK"), never a traceback, so this file stays readable by old interpreters: no f-strings, no annotations,
and no plainspoken import before the check."""
import sys

MIN_PYTHON = (3, 11)


def too_old(version=None):
    """The line to print when this python3 can't run plainspoken, else None."""
    version = sys.version_info if version is None else version
    if tuple(version[:2]) >= MIN_PYTHON:
        return None
    return "plainspoken needs Python %d.%d or newer; this python3 is %s" % (
        MIN_PYTHON + (".".join(str(part) for part in version[:3]),))


def _run():
    problem = too_old()
    if problem:
        sys.stderr.write(problem + "\n")
        return 2
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from plainspoken.__main__ import main
    return main()


if __name__ == "__main__":
    sys.exit(_run())
