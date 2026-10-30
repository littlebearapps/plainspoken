"""The chat-reply check's decision log (`chat-replies.jsonl`) and its kaizen report lines (#125). Rows are synthetic
and hold no text."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from plainspoken import kaizen, ledger
from tests.test_textcapture import Base


class DecisionLog(Base):
    ROW = {"host": "codex", "ask": "draft", "shape": "letter", "words": 112, "bucket": "80-120", "outcome": "warned",
           "doc": "0123456789abcdef"}

    def test_rows_round_trip_and_carry_no_text(self):
        ledger.append_row(self.settings(), "chat-replies.jsonl", dict(self.ROW))
        ledger.append_row(self.settings(), "chat-replies.jsonl",
                          {**self.ROW, "shape": "-", "words": 0, "bucket": "0-20", "outcome": "no-draft", "doc": "-"})
        rows, bad = ledger.read_rows(self.settings(), "chat-replies.jsonl")
        self.assertEqual(bad, 0)
        self.assertEqual([r["outcome"] for r in rows], ["warned", "no-draft"])
        self.assertEqual(set(rows[0]), {"v", "ts", *self.ROW})

    def test_bad_rows_are_refused_quietly(self):
        for bad in ({**self.ROW, "outcome": "blocked"}, {**self.ROW, "text": "Dear Sam"}, {**self.ROW, "words": "9"},
                    {**self.ROW, "doc": "Dear Sam"}, {**self.ROW, "shape": "poem"}, {**self.ROW, "ask": "chat"},
                    {**self.ROW, "host": "cursor"}):
            ledger.append_row(self.settings(), "chat-replies.jsonl", bad)
        self.assertEqual(ledger.read_rows(self.settings(), "chat-replies.jsonl"), ([], 0))

    def test_report_lines(self):
        rows = [{**self.ROW, "outcome": o, "shape": s} for o, s in
                (("warned", "letter"), ("clean", "letter"), ("clean", "whole"), ("seen", "fence"))]
        rows.append({**self.ROW, "outcome": "no-draft", "shape": "-"})
        summary = kaizen.chat_reply_summary(rows)
        self.assertEqual(summary["outcomes"], {"warned": 1, "clean": 2, "seen": 1, "no-draft": 1})
        self.assertEqual(summary["shapes"]["letter"], {"linted": 2, "warned": 1})
        lines = kaizen.chat_reply_lines(summary)
        self.assertEqual(lines[1], "chat-reply check (5 decisions after a writing ask):")
        self.assertIn("    letter: 2 linted, 1 with findings", lines)
        self.assertEqual(kaizen.chat_reply_lines(kaizen.chat_reply_summary([])), [])

    def test_kaizen_report_shows_the_section(self):
        (self.root / ".git").mkdir(exist_ok=True)
        ledger.append_row(self.settings(), "chat-replies.jsonl", dict(self.ROW))
        run = [sys.executable, str(Path(__file__).resolve().parents[1] / "lib" / "run.py"), "kaizen", "report"]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "PLAINSPOKEN_"))}
        done = subprocess.run(run, cwd=self.root, capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("chat-reply check (1 decisions after a writing ask):", done.stdout)
        done = subprocess.run([*run, "--json"], cwd=self.root, capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(done.stdout)["chat_replies"]["outcomes"], {"warned": 1})


if __name__ == "__main__":
    unittest.main()
