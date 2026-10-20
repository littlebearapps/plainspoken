"""Launcher: `python3 <plugin>/lib/run.py <args>` behaves like `python3 -m plainspoken <args>`, with no PYTHONPATH.

Skills and hooks call this (the plugin root holds no bin/ directory: claude.ai and Cowork reject one)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plainspoken.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
