import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken.checks_lexical import CHECKS as LEXICAL
from plainspoken.checks_structural import CHECKS as STRUCTURAL
from plainspoken.doc import parse
from plainspoken.registry import load_config, spelling_variants
from plainspoken.report import run_lint
from tests._profiles import PRODUCT
from tests.test_anti_ai_structural import ABOVE_GATE

CFG = load_config()


class Spelling(unittest.TestCase):
    """US spellings are caught under every locale; AU ones still are."""

    def test_variants(self):
        self.assertEqual(spelling_variants("utilise"), {"utilise", "utilize"})
        self.assertEqual(spelling_variants("catalyse"), {"catalyse", "catalyze"})
        self.assertEqual(spelling_variants("delve"), {"delve"})

    def test_ban_list_catches_both(self):
        for text in ("We utilize it.", "We utilise it.", "It will revolutionize things.", "It will revolutionise things."):
            with self.subTest(text=text):
                self.assertTrue(LEXICAL["2"](parse(text, profile=PRODUCT), CFG), text)


class NotABlogPost(unittest.TestCase):
    """A non-blog input (an email, a page) is linted without blog assumptions."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def lint(self, text: str, content_type: str = "article") -> dict:
        p = self.tmp / "x.md"
        p.write_text(text, encoding="utf-8")
        return run_lint(p, PRODUCT, content_type)

    def test_empty_one_line_and_headingless_text_dont_crash(self):
        for text in ("", "Hi.", "Thanks for the chat today. I'll send the notes on Friday.\n"):
            with self.subTest(text=text):
                self.assertIsInstance(self.lint(text)["findings"], list)

    def test_social_post_has_no_section_level_warns(self):
        post = "Shipped the fix. Took a while. Worth it. Notes below.\n"
        rules = {f["rule"] for f in self.lint(post, "social")["findings"]}
        self.assertFalse(rules & {"12d", "12f", "HM", "22"}, rules)

    def test_social_uses_social_thresholds(self):
        two = "One — two — three.\n"
        self.assertEqual([f["rule"] for f in self.lint(two, "article")["findings"] if f["rule"] == "1"], [])
        self.assertEqual([f["rule"] for f in self.lint(two, "social")["findings"] if f["rule"] == "1"], ["1"])

    def test_social_staccato_is_run_only(self):
        five_short = "I went. It rained. We left. Nobody cared. That was it.\n"
        found = STRUCTURAL["7d"](parse(five_short, profile=PRODUCT, content_type="social"), CFG)
        self.assertFalse([f for f in found if "No sentence over" in f.message], found)
        self.assertEqual([f.message for f in found],
                         ['4 consecutive sentences under 8 words — join two neighbours with "and" or "but" in their '
                          'own words, or keep it; never pad one'])
        # the same text as an article still gets the no-long-sentence WARN
        art = STRUCTURAL["7d"](parse(five_short + ABOVE_GATE, profile=PRODUCT), CFG)  # #148: past the 150-word gate
        self.assertTrue([f for f in art if "No sentence over" in f.message], art)

    def test_unknown_content_type_fails(self):
        with self.assertRaises(ValueError):
            parse("Hi.", profile=PRODUCT, content_type="tweet")


class LineEndings(unittest.TestCase):
    """CRLF and a BOM give the same findings and line numbers as LF."""

    def test_crlf_and_bom_match_lf(self):
        lf = '---\ntitle: "A robust title"\n---\n\nWe utilised it.\n\nAnother — line — here — now — ok.\n'
        variants = [lf, lf.replace("\n", "\r\n"), "﻿" + lf]
        results = []
        for text in variants:
            doc = parse(text, profile=PRODUCT)
            results.append(sorted((f.rule, f.line, f.excerpt) for rid in ("1", "2") for f in LEXICAL[rid](doc, CFG)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])
        self.assertTrue(results[0])
