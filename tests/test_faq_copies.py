"""#208: a FAQ the page renders from frontmatter and also keeps in the body is linted once, in the body.

A frontmatter `faq_frontmatter_key` question or answer whose text the body's FAQ section holds (as whole headings or
paragraphs, compared without markup, quote style, spacing or case) is left out of the visible frontmatter, so the
lexical counts, rule 7d's FAQ answers, rule 24's curly-quote lines and the judges see it once. The body copy stays,
because its line numbers point at the body.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken.checks_lexical import text_units
from plainspoken.checks_structural import _faq_answer_sentences
from plainspoken.doc import parse
from plainspoken.registry import load_config
from plainspoken.report import lint_text, summarise
from tests._profiles import PRODUCT

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "frontmatter" / "faq_copy.md"
TEXT = FIXTURE.read_text(encoding="utf-8")
FM_END = 12  # the closing --- of the fixture's frontmatter
CFG = load_config()


def lint(text: str = TEXT) -> dict:
    return lint_text(text, PRODUCT, cfg=CFG)


class FaqCopies(unittest.TestCase):
    def test_the_copies_are_left_out_and_the_rest_is_read(self):
        doc = parse(TEXT, profile=PRODUCT)
        self.assertEqual([s.label for s in doc.faq_copies],
                         ["faqs[0].question", "faqs[0].answer", "faqs[1].question", "faqs[1].answer"])
        self.assertEqual([s.label for s in doc.visible_frontmatter], ["title", "faqs[2].question", "faqs[2].answer"])
        self.assertEqual(doc.fields_read(), ["body", "title", "faqs"])

    def test_each_copy_counts_once(self):
        doc = parse(TEXT, profile=PRODUCT)
        units = text_units(doc)
        self.assertEqual(sum(t.count("—") for _, t, _ in units), 1)  # rule 1 counts the body's dash only
        self.assertEqual(sum("reviews, photos and hours" in t for _, t, _ in units), 1)  # the rule-6 list
        answers = [s.text for s in _faq_answer_sentences(doc)]  # 7d's frontmatter FAQ answers
        self.assertEqual(answers, ["Not at all.", "I can’t promise rankings, calls or sales."])

    def test_findings_point_at_the_body(self):
        found = lint()["findings"]
        bans = [f for f in found if f["rule"] == "2"]
        self.assertEqual(len(bans), 1, bans)  # "seamless", once
        self.assertGreater(bans[0]["line"], FM_END)
        (curly,) = [f for f in found if f["rule"] == "24" and "Curly" in f["message"]]
        self.assertIn("on 2 line(s)", curly["message"])  # the body's line and the copy-free FAQ item's

    def test_an_edited_copy_is_read_again(self):
        text = TEXT.replace("finish, if the logins", "finish, if your logins", 1)  # the body copy only
        doc = parse(text, profile=PRODUCT)
        self.assertEqual([s.label for s in doc.faq_copies],
                         ["faqs[0].question", "faqs[0].answer", "faqs[1].question"])
        self.assertIn("faqs[1].answer", [s.label for s in doc.visible_frontmatter])

    def test_an_answer_the_body_splits_in_two_paragraphs_is_a_copy(self):
        text = TEXT.replace("About a week, start to finish, if", "About a week, start to finish,\n\nif", 1)
        doc = parse(text, profile=PRODUCT)
        self.assertIn("faqs[1].answer", [s.label for s in doc.faq_copies])

    def test_text_outside_the_body_faq_is_no_copy(self):
        text = TEXT.replace("## FAQ\n", "## Notes\n", 1)
        self.assertEqual(parse(text, profile=PRODUCT).faq_copies, [])

    def test_a_profile_with_no_faq_key_has_no_copies(self):
        from plainspoken import profile as _profile
        self.assertEqual(parse(TEXT, profile=_profile.default()).faq_copies, [])

    def test_the_summary_and_report_say_so(self):
        got = lint()
        self.assertEqual(got["faq_copies"], ["faqs[0].question", "faqs[0].answer", "faqs[1].question",
                                             "faqs[1].answer"])
        self.assertIn("read: body, title, faqs (4 FAQ items the body FAQ repeats, read there)", summarise(got))


class JudgeInput(unittest.TestCase):
    def test_the_judges_are_told_which_items_repeat_the_body(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copy(FIXTURE, tmp / "post.md")
        shutil.copy(REPO / "tests" / "fixtures" / "profiles" / "product_like.toml", tmp / "product_like.toml")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env["PYTHONPATH"] = str(REPO / "lib")

        def cli(*args):
            return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=tmp, env=env,
                                  capture_output=True, text=True)

        cli("check", "post.md", "--profile", "./product_like.toml")
        r = cli("judge-input", "post.md", "--profile", "./product_like.toml", "--keep", "2,24")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [json.loads(ln) for ln in r.stdout.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertEqual(line["faq_frontmatter_copies"], ["faqs[0].question", "faqs[0].answer",
                                                              "faqs[1].question", "faqs[1].answer"])


if __name__ == "__main__":
    unittest.main()
