"""Kaizen for text with no file (#124, shared with #125): `capture.for_text` and the linted-text overlap state.
Fixtures are synthetic."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lib"))
sys.path.insert(0, str(REPO / "hooks"))
import _common  # noqa: E402
from plainspoken import capture, config, ledger, textlint  # noqa: E402
from plainspoken.profile import load  # noqa: E402
from plainspoken.registry import load_config  # noqa: E402

STIFF = ("Additionally, we are delighted to announce our comprehensive new booking page. Moreover, it will "
         "streamline everything for you. Furthermore, it leverages the latest tools to empower every customer.")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".plainspoken").mkdir()
        patcher = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items()
                                               if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def config(self, text):
        (self.root / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def settings(self):
        return config.kaizen_settings(self.root, {})


class ForText(Base):
    def lint(self):
        return textlint.lint_text(STIFF, load("default"), cfg=load_config(), label="tool-call:x|body")

    def test_fired_events_with_a_label_id_and_no_excerpt_even_with_excerpts_on(self):
        self.config("[kaizen]\nexcerpts = true\n")
        lint = self.lint()
        capture.for_text(lint, STIFF, "tool-call:x|body", load("default"), load_config(), self.root, "lint-watch")
        events, bad = ledger.read(self.settings())
        self.assertEqual(bad, 0)
        self.assertTrue(events)
        for e in events:
            self.assertEqual(e["doc_id"], ledger.label_id("tool-call:x|body"))
            self.assertEqual(e["outcome"], "fired")
            self.assertNotIn("excerpt", e)
        raw = "".join(p.read_text(encoding="utf-8") for p in (self.root / ".plainspoken" / "ledger").glob("*.jsonl"))
        self.assertNotIn("delighted", raw)
        self.assertNotIn("Additionally", raw)

    def test_source_left_out_writes_nothing(self):
        self.config('[kaizen]\ncapture_sources = ["check"]\n')
        capture.for_text(self.lint(), STIFF, "tool-call:x|body", load("default"), load_config(), self.root,
                         "lint-watch")
        self.assertEqual(ledger.read(self.settings()), ([], 0))


class Overlap(Base):
    TEXT = ("The fence posts arrive on Monday. I'll set them in concrete on Tuesday morning. The gate goes on "
            "once they've set, probably by the weekend.")

    def test_same_text_and_large_overlap_were_linted(self):
        data = self.root / ".data"
        _common.remember_linted(data, "s1", [self.TEXT])
        self.assertTrue(_common.linted_before(data, "s1", self.TEXT))
        self.assertTrue(_common.linted_before(data, "s1", "  " + self.TEXT.upper() + " "))
        self.assertTrue(_common.linted_before(data, "s1", self.TEXT + " Thanks again."))
        self.assertFalse(_common.linted_before(data, "s1", "A different message about the garden beds and soil."))
        self.assertFalse(_common.linted_before(data, "s2", self.TEXT))

    def test_state_holds_hashes_only(self):
        data = self.root / ".data"
        _common.remember_linted(data, "s1", [self.TEXT])
        raw = (data / "linted-texts.json").read_text(encoding="utf-8")
        self.assertNotIn("fence", raw)
        json.loads(raw)


if __name__ == "__main__":
    unittest.main()
