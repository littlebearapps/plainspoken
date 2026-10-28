"""The tool-call check's decision log (`tool-calls.jsonl`) and its `tool_call` friction kind (#124). Rows are
synthetic and hold no text."""
import unittest

from plainspoken import ledger
from tests.test_textcapture import Base


class DecisionLog(Base):
    ROW = {"host": "claude-code", "tool_server_hash": "1a2b3c4d", "tool_name": "send_message", "field": "body",
           "words": 52, "bucket": "40-60", "prose": True, "outcome": "warned", "mode": "warn"}

    def test_rows_round_trip_and_carry_no_text(self):
        ledger.append_row(self.settings(), "tool-calls.jsonl", dict(self.ROW))
        ledger.append_row(self.settings(), "tool-calls.jsonl", {**self.ROW, "outcome": "not-prose:code"})
        rows, bad = ledger.read_rows(self.settings(), "tool-calls.jsonl")
        self.assertEqual(bad, 0)
        self.assertEqual([r["outcome"] for r in rows], ["warned", "not-prose:code"])
        self.assertEqual(set(rows[0]), {"v", "ts", *self.ROW})

    def test_bad_rows_are_refused_quietly(self):
        for bad in ({**self.ROW, "outcome": "shouted"}, {**self.ROW, "text": "Dear Sam"}, {**self.ROW, "words": "9"},
                    {**self.ROW, "tool_server_hash": "clientname"}):
            ledger.append_row(self.settings(), "tool-calls.jsonl", bad)
        ledger.append_row(self.settings(), "other.jsonl", dict(self.ROW))
        self.assertEqual(ledger.read_rows(self.settings(), "tool-calls.jsonl"), ([], 0))
        self.assertFalse((self.root / ".plainspoken" / "ledger" / "other.jsonl").exists())

    def test_capture_off_writes_nothing(self):
        self.config("[kaizen]\ncapture = false\n")
        ledger.append_row(self.settings(), "tool-calls.jsonl", dict(self.ROW))
        self.assertFalse((self.root / ".plainspoken" / "ledger").exists())

    def test_bucket(self):
        self.assertEqual([ledger.word_bucket(n) for n in (5, 20, 39, 40, 119, 200, 399, 400, 9000)],
                         ["0-20", "20-40", "20-40", "40-60", "80-120", "200-400", "200-400", "400+", "400+"])

    def test_tool_call_friction_kind(self):
        ledger.friction("tool_call", "tool-call", "ProfileError: no profile named x", self.settings())
        rows, bad = ledger.read_friction(self.settings())
        self.assertEqual((len(rows), bad, rows[0]["kind"]), (1, 0, "tool_call"))


if __name__ == "__main__":
    unittest.main()
