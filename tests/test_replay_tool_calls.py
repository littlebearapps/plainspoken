"""The maintainer replay script (#124): counts from synthetic transcripts, and never any text or names."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.dev import replay_tool_calls

BODY = ("Hi Sam, thanks for sending the plans over on Tuesday. I had a look at the garden layout and the shed "
        "position works well for me. Could we move the meeting to Thursday at ten? I'll bring the samples.")


class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        claude = self.tmp / "claude" / "proj"
        claude.mkdir(parents=True)
        lines = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "mcp__clientmail__send_message", "input": {"to": "x", "body": BODY}},
                {"type": "tool_use", "name": "mcp__firecrawl__firecrawl_scrape", "input": {"url": "u"}},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/a"}}]}},
            "not json",
        ]
        (claude / "s.jsonl").write_text("\n".join(l if isinstance(l, str) else json.dumps(l) for l in lines),
                                        encoding="utf-8")
        codex = self.tmp / "codex" / "2026" / "10"
        codex.mkdir(parents=True)
        item = {"type": "response_item", "payload": {"type": "function_call", "name": "mcp__clientmail__send_message",
                                                     "arguments": json.dumps({"body": "Too short to check."})}}
        (codex / "r.jsonl").write_text(json.dumps(item), encoding="utf-8")

    def run_json(self, *extra):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            replay_tool_calls.main(["--claude-dir", str(self.tmp / "claude"), "--codex-dir", str(self.tmp / "codex"),
                                    "--json", *extra])
        return buf.getvalue()

    def test_counts(self):
        out = json.loads(self.run_json())
        self.assertEqual((out["files"], out["calls"]), (2, 4))
        self.assertEqual(out["decisions"], {"checked": 2, "skip-list": 1, "not-mcp": 1})
        self.assertEqual(out["candidates_by_band"], {"20-40": 1})
        self.assertEqual(out["outcomes"]["candidate"], 1)

    def test_lint_counts_and_no_text_or_names(self):
        text = self.run_json("--lint")
        for leak in ("Sam", "garden", "clientmail", "send_message", "firecrawl"):
            self.assertNotIn(leak, text)
        self.assertIn("findings_by_band", json.loads(text))


if __name__ == "__main__":
    unittest.main()
