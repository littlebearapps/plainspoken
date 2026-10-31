import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken.checks_lexical import CHECKS
from plainspoken.doc import parse
from plainspoken.registry import load_config
from plainspoken.report import run_lint
from tests._profiles import PRODUCT

CFG = load_config()
CASES = {
    "28": ("Here's the thing: the cache was stale.", "The thing broke."),
    "29": ("The honest answer is nobody knows.", "He answered the phone."),
    "30": ("Let's walk through the setup.", "We walked to the shop."),
    "31": ("But here's the catch: it costs more.", "He couldn't catch the bus."),
    "32": ("The new tool can help you plan.", "I planned it myself."),
}


class ShadowRules(unittest.TestCase):
    def test_registered_as_shadow_with_sources(self):
        self.assertEqual(CFG.version, "4.4.0")
        for rid in CASES:
            rule = CFG.rules[rid]
            self.assertEqual((rule.status, rule.method), ("shadow", "lint"), rid)
            self.assertTrue(rule.source, f"{rid} needs a cited source")

    def test_fire_on_positive_not_on_negative(self):
        for rid, (pos, neg) in CASES.items():
            with self.subTest(rule=rid):
                self.assertTrue(CHECKS[rid](parse(pos, profile=PRODUCT), CFG))
                self.assertEqual(CHECKS[rid](parse(neg, profile=PRODUCT), CFG), [])

    def test_shadow_findings_are_info_and_never_block(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = tmp / "x.md"
        p.write_text("Here's the thing: the honest answer can help you.\n", encoding="utf-8")
        lint = run_lint(p, PRODUCT)
        shadow = [f for f in lint["findings"] if f["rule"] in CASES]
        self.assertTrue(shadow)
        self.assertTrue(all(f["severity"] == "INFO" and f["message"].startswith("[shadow]") for f in shadow))
        self.assertIn("28", lint["rates_per_1k"])

    def test_existing_rules_tagged(self):
        self.assertTrue(all(r.era for r in CFG.rules.values()))


class Rule33StockSignificance(unittest.TestCase):
    """Stock significance phrases, count-based like 2b (one is fine, 2+ is a WARN once promoted), shadow."""
    TWO = ("The ruling has far-reaching implications for renters. It was a pivotal moment for the council.\n")

    def test_registered_as_shadow_lint_with_its_list_and_threshold(self):
        rule = CFG.rules["33"]
        self.assertEqual((rule.status, rule.method, rule.severity), ("shadow", "lint", "WARN"))
        self.assertTrue(rule.source)
        self.assertIn("far-reaching implications", CFG.lists["stock_significance"])
        self.assertEqual(CFG.thresholds(PRODUCT)["stock_significance_warn"], 2)

    def test_one_phrase_is_fine_two_is_a_count_warn(self):
        self.assertEqual(CHECKS["33"](parse("It has far-reaching implications.", profile=PRODUCT), CFG), [])
        f = CHECKS["33"](parse(self.TWO, profile=PRODUCT), CFG)
        self.assertEqual([(x.rule, x.severity) for x in f], [("33", "WARN")])
        self.assertIn("2 (limit 1)", f[0].message)

    def test_quoted_phrases_do_not_count(self):
        body = 'The minister said: "This has far-reaching implications for every renter. It is a pivotal moment."\n'
        self.assertEqual(CHECKS["33"](parse(body, profile=PRODUCT), CFG), [])

    def test_rule33_shadow_reports_info_only(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        p = tmp / "x.md"
        p.write_text(self.TWO + "\nIt marks a significant shift. The broader implications cannot be overstated.\n",
                     encoding="utf-8")
        lint = run_lint(p, PRODUCT)
        found = [f for f in lint["findings"] if f["rule"] == "33"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "INFO")
        self.assertTrue(found[0]["message"].startswith("[shadow] Stock significance phrases"))
        self.assertIn("5 (limit 1)", found[0]["message"])
        self.assertFalse([f for f in lint["findings"] if f["severity"] in ("BLOCK", "WARN") and f["rule"] == "33"])
