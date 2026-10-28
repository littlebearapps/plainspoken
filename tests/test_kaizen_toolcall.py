"""`kaizen report`'s tool-call section and its tuning proposals (#124), from synthetic decision rows."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lib"))
from plainspoken import config, kaizen, ledger  # noqa: E402


def row(outcome, words=50, tool="send_message"):
    return {"host": "claude-code", "tool_server_hash": "1a2b3c4d", "tool_name": tool, "field": "body",
            "words": words, "bucket": ledger.word_bucket(words), "prose": True, "outcome": outcome,
            "mode": "block-once"}


class Summary(unittest.TestCase):
    def test_counts_by_band_near_misses_and_tools(self):
        rows = [row("clean", 30), row("warned", 30), row("blocked", 150), row("resent-unchanged", 150),
                row("below-cutoff", 20), row("below-cutoff", 5), row("not-prose:code", 80)]
        s = kaizen.tool_call_summary(rows, 25)
        self.assertEqual(s["rows"], 7)
        self.assertEqual(s["near_misses"], 1)
        self.assertEqual(s["bands"]["20-40"], {"linted": 2, "findings": 1, "holds": 0, "resent_unchanged": 0})
        self.assertEqual(s["bands"]["120-200"]["holds"], 1)
        self.assertEqual(s["tools"], {"send_message": {"holds": 1, "resent_unchanged": 1}})
        self.assertEqual(s["above_cutoff"]["linted"], 2)

    def test_no_proposals_on_little_data(self):
        self.assertEqual(kaizen.tool_call_proposals(kaizen.tool_call_summary([row("blocked")] * 5, 25)), [])

    def test_raise_when_the_lowest_band_is_mostly_resent_unchanged(self):
        rows = [row("blocked", 30)] * 30 + [row("resent-unchanged", 30)] * 20
        props = kaizen.tool_call_proposals(kaizen.tool_call_summary(rows, 25))
        self.assertTrue(any(p.startswith("raise [tool_call] min_words") for p in props), props)

    def test_lower_when_near_misses_pile_up_and_just_over_finds_things(self):
        rows = [row("below-cutoff", 20)] * 25 + [row("warned", 30)] * 6 + [row("clean", 30)] * 4
        props = kaizen.tool_call_proposals(kaizen.tool_call_summary(rows, 25))
        self.assertTrue(any(p.startswith("lower [tool_call] min_words") for p in props), props)

    def test_skip_glob_for_a_tool_resent_unchanged(self):
        rows = [row("blocked", 300, "post_note")] * 10 + [row("resent-unchanged", 300, "post_note")] * 7
        props = kaizen.tool_call_proposals(kaizen.tool_call_summary(rows, 25))
        self.assertIn("add a [tool_call] skip glob for *__post_note: 7 of 10 holds were sent again unchanged", props)

    def test_lines(self):
        self.assertEqual(kaizen.tool_call_lines(kaizen.tool_call_summary([], 25)), [])
        lines = kaizen.tool_call_lines(kaizen.tool_call_summary([row("warned", 30)], 25))
        self.assertIn("tool-call check (min_words 25):", lines)


class ReportCommand(unittest.TestCase):
    def test_kaizen_report_renders_the_section_from_a_fixture_ledger(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / ".plainspoken").mkdir()
        (root / ".git").mkdir()
        settings = config.kaizen_settings(root, {})
        for r in [row("warned", 30), row("blocked", 150), row("resent-unchanged", 150)]:
            ledger.append_row(settings, "tool-calls.jsonl", r)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "PLAINSPOKEN_"))}
        done = subprocess.run([sys.executable, str(REPO / "lib" / "run.py"), "kaizen", "report"], cwd=root,
                              capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("tool-call check (min_words 25):", done.stdout)
        self.assertIn("send_message: 1 held, 1 sent again unchanged", done.stdout)
        done = subprocess.run([sys.executable, str(REPO / "lib" / "run.py"), "kaizen", "report", "--json"],
                              cwd=root, capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(done.stdout)["tool_calls"]["rows"], 3)


if __name__ == "__main__":
    unittest.main()
