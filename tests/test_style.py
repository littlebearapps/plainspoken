import inspect
import unittest
from pathlib import Path

from plainspoken import justify

REPO = Path(__file__).resolve().parents[1]
MAX = 160


class Style(unittest.TestCase):
    def test_no_code_line_over_160(self):  # deferred minor: an overlong line in report.py
        long = [f"{p.relative_to(REPO)}:{n}" for d in ("lib", "hooks", "scripts")
                for p in sorted((REPO / d).rglob("*.py"))
                for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if len(line) > MAX]
        self.assertEqual(long, [])

    def test_justify_resolve_takes_a_report_key(self):  # deferred minor: stem → key
        params = inspect.signature(justify.resolve).parameters
        self.assertIn("key", params)
        self.assertNotIn("stem", params)
        self.assertNotIn("<stem>", justify.__doc__ or "")
