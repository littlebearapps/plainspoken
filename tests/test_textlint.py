"""The lint entry for text with no file (#124, shared with #125): `report.lint_text` and `textlint`."""
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lib"))
from plainspoken import report, textlint  # noqa: E402
from plainspoken.profile import load  # noqa: E402
from plainspoken.registry import load_config  # noqa: E402

STIFF = ("Additionally, we are delighted to announce our comprehensive new booking page — it's seamless, robust "
         "and innovative. Moreover, it will streamline everything for you. Furthermore, it leverages the latest "
         "tools to empower every customer we serve across the region.")
PLAIN = ("The booking page is live. You pick a time, pay the deposit and get a text the day before. If the time "
         "doesn't suit, reply to the text and I'll move it. That's all there is to it for now, see you soon.")


class LintText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load("default")
        cls.cfg = load_config()

    def test_same_findings_as_the_file_lint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "draft.md"
            path.write_text(STIFF + "\n", encoding="utf-8")
            from_file = report.run_lint(path, self.profile, "social", self.cfg)
        from_text = report.lint_text(STIFF + "\n", self.profile, "social", self.cfg, label="tool:body")
        self.assertEqual(from_text["findings"], from_file["findings"])
        self.assertEqual(from_text["article"], "tool:body")
        self.assertRegex(from_text["article_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(list(from_text), list(from_file))  # the same lint shape, field for field

    def test_content_type_follows_check_stdin(self):
        from plainspoken import __main__ as cli
        self.assertEqual(textlint.SOCIAL_WORDS, cli.STDIN_SOCIAL_WORDS)
        self.assertEqual(textlint.content_type_for(PLAIN), "social")
        self.assertEqual(textlint.content_type_for("word " * 300), "article")

    def test_lint_text_wrapper_counts_and_rules(self):
        lint = textlint.lint_text(STIFF, self.profile, cfg=self.cfg, label="x")
        self.assertEqual(lint["content_type"], "social")
        counts = textlint.counts(lint)
        self.assertGreater(counts["BLOCK"], 0)
        self.assertTrue(textlint.noisy(lint))
        self.assertIn("r4a", textlint.rules(lint))
        quiet = textlint.lint_text(PLAIN, self.profile, cfg=self.cfg, label="y")
        self.assertFalse(textlint.noisy(quiet))

    def test_summary_is_short_and_capped(self):
        lint = textlint.lint_text(STIFF, self.profile, cfg=self.cfg, label="body")
        text = textlint.summary([("body", lint)] * 10, max_findings=15, max_chars=2000)
        self.assertLessEqual(len(text), 2000)
        self.assertLessEqual(sum(1 for ln in text.splitlines() if ln.lstrip().startswith(("BLOCK", "WARN"))), 15)
        self.assertIn("body", text)
        self.assertNotIn("Additionally, we are delighted", text)  # findings name the rule, not a copy of the text


if __name__ == "__main__":
    unittest.main()
