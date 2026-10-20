"""tests/test_anti_ai_metrics.py — rule 12f quantified slop metrics."""
import unittest

from plainspoken import metrics
from plainspoken.doc import parse
from plainspoken.registry import load_config
from tests._profiles import PRODUCT

CFG = load_config()


class Metrics(unittest.TestCase):
    def test_ttr(self):
        self.assertAlmostEqual(metrics.ttr(["a", "b", "a", "c"]), 0.75)

    def test_mattr_equals_ttr_when_short(self):
        words = ["a", "b", "a", "c"]
        self.assertAlmostEqual(metrics.mattr(words, 500), metrics.ttr(words))

    def test_burstiness_uniform_is_zero(self):
        self.assertEqual(metrics.burstiness([10, 10, 10]), 0.0)

    def test_burstiness_varied(self):
        self.assertGreater(metrics.burstiness([3, 30, 8, 25]), 0.6)

    def test_opening_share(self):
        self.assertAlmostEqual(metrics.opening_top3_share(["The a.", "The b.", "It c.", "So d."]), 1.0)

    def test_paragraph_sd(self):
        self.assertEqual(metrics.paragraph_sd([50, 50, 50]), 0.0)


class MovingAverage(unittest.TestCase):
    def test_mattr_is_a_moving_window_not_raw_ttr(self):
        words = ["a", "b"] * 50  # raw TTR 0.02, but every 2-word window holds 2 distinct words
        self.assertAlmostEqual(metrics.ttr(words), 0.02)
        self.assertAlmostEqual(metrics.mattr(words, 2), 1.0)

    def test_mattr_averages_every_window(self):
        # windows of 2 over a a b: [a a]=0.5, [a b]=1.0 → 0.75
        self.assertAlmostEqual(metrics.mattr(["a", "a", "b"], 2), 0.75)

    def test_empty_inputs(self):
        self.assertEqual(metrics.ttr([]), 0.0)
        self.assertEqual(metrics.burstiness([]), 0.0)
        self.assertEqual(metrics.opening_top3_share([]), 0.0)
        self.assertEqual(metrics.paragraph_sd([7]), 0.0)

    def test_opening_share_ignores_leading_quote_and_emphasis(self):
        self.assertAlmostEqual(metrics.opening_top3_share(['"The a.', "**The** b.", "It c.", "So d.", "Now e."]), 0.8)


class Compute(unittest.TestCase):
    def doc(self, body, profile=PRODUCT):
        return parse(f"---\n---\n\n{body}\n", profile=profile)

    def test_keys_and_values(self):
        m = metrics.compute(self.doc("## One\n\nSo it went. The cat sat.\n\n## Two\n\nThe end came fast here."), CFG)
        self.assertEqual(set(m), {"words", "ttr", "mattr", "burstiness", "opening_top3_share",
                                  "capsule_transition_share", "paragraph_sd"})
        self.assertEqual(m["words"], 11)
        self.assertEqual(m["capsule_transition_share"], 0.5)  # "So" opens one of two H2s

    def test_tables_are_not_prose_rhythm(self):
        table = "| A | B |\n|---|---|\n| x | y |\n| z | w |"
        with_table = metrics.compute(self.doc("The cat sat on the mat today.\n\n" + table), CFG)
        without = metrics.compute(self.doc("The cat sat on the mat today."), CFG)
        self.assertEqual(with_table, without)

    def test_quotations_count_toward_metrics(self):
        m = metrics.compute(self.doc('> "Fast and cheap, every time." — Jane Smith\n\nWe agree.'), CFG)
        self.assertEqual(m["words"], 9)


    def test_academic_transition_opens_a_capsule(self):  # decision I3 vocabulary, the per-H2 form of 4b
        m = metrics.compute(self.doc("## One\n\nFurthermore, it went.\n\n## Two\n\nIn particular this.\n\n"
                                     "## Three\n\nNext.js shipped.\n\n## Four\n\nThe end."), CFG)
        self.assertEqual(m["capsule_transition_share"], 0.5)


class SlidingWindow(unittest.TestCase):
    def test_matches_the_naive_average(self):
        words = [w for i in range(60) for w in (f"w{i % 7}", f"x{i % 13}", "the")]
        naive = [metrics.ttr(words[i:i + 25]) for i in range(len(words) - 25 + 1)]
        self.assertAlmostEqual(metrics.mattr(words, 25), sum(naive) / len(naive))
