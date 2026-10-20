"""Judge-validation metrics: confusion counts, Wilson intervals, majority vote, Fleiss' kappa (Phase 6)."""
import unittest

from plainspoken import evalmetrics as em


class TestWilson(unittest.TestCase):
    def test_wilson_known_values(self):
        lo, hi = em.wilson(8, 10)
        self.assertAlmostEqual(lo, 0.4902, places=3)
        self.assertAlmostEqual(hi, 0.9433, places=3)
        self.assertEqual(em.wilson(0, 0), (0.0, 1.0))

    def test_wilson_edges_stay_in_range(self):
        lo, hi = em.wilson(0, 5)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.0)
        lo, hi = em.wilson(5, 5)
        self.assertLess(lo, 1.0)
        self.assertEqual(hi, 1.0)

    def test_wilson_rejects_bad_counts(self):
        with self.assertRaises(ValueError):
            em.wilson(3, 2)
        with self.assertRaises(ValueError):
            em.wilson(-1, 2)


class TestConfusion(unittest.TestCase):
    def test_confusion_counts_errors_separately(self):
        pairs = [("fail", "fail"), ("fail", "pass"), ("fail", None), ("pass", "pass"), ("pass", "fail"),
                 ("pass", "pass"), ("pass", None)]
        c = em.confusion(pairs, "fail")
        self.assertEqual(c, {"tp": 1, "fn": 1, "tn": 2, "fp": 1, "errors": 2, "n": 7})

    def test_confusion_jr_positive_is_reject(self):
        c = em.confusion([("reject", "reject"), ("accept", "reject"), ("accept", "accept")], "reject")
        self.assertEqual((c["tp"], c["fp"], c["tn"], c["fn"]), (1, 1, 1, 0))

    def test_rates(self):
        r = em.rates({"tp": 8, "fn": 2, "tn": 9, "fp": 1, "errors": 0, "n": 20})
        self.assertAlmostEqual(r["tpr"]["value"], 0.8)
        self.assertEqual((r["tpr"]["k"], r["tpr"]["n"]), (8, 10))
        self.assertAlmostEqual(r["tpr"]["ci"][0], 0.4902, places=3)
        self.assertAlmostEqual(r["tnr"]["value"], 0.9)
        self.assertAlmostEqual(r["precision"]["value"], 8 / 9)
        self.assertEqual(r["precision"]["n"], 9)

    def test_rates_zero_denominator(self):
        r = em.rates({"tp": 0, "fn": 0, "tn": 0, "fp": 0, "errors": 3, "n": 3})
        for k in ("tpr", "tnr", "precision"):
            self.assertIsNone(r[k]["value"])
            self.assertEqual(tuple(r[k]["ci"]), (0.0, 1.0))
            self.assertEqual(r[k]["n"], 0)


class TestMajority(unittest.TestCase):
    def test_majority(self):
        self.assertEqual(em.majority(["fail", "fail", "pass"]), "fail")
        self.assertEqual(em.majority(["fail", None, None]), "fail")  # errors don't vote
        self.assertEqual(em.majority(["pass", "pass", "fail", None]), "pass")

    def test_majority_tie_none(self):
        self.assertIsNone(em.majority(["fail", "pass"]))
        self.assertIsNone(em.majority(["fail", "pass", None]))
        self.assertIsNone(em.majority([None, None]))
        self.assertIsNone(em.majority([]))


class TestKappa(unittest.TestCase):
    def test_fleiss_kappa_perfect_and_chance(self):
        self.assertAlmostEqual(em.fleiss_kappa([[3, 0], [0, 3], [3, 0]]), 1.0)
        self.assertAlmostEqual(em.fleiss_kappa([[4, 0], [4, 0]]), 1.0)  # one category only: full agreement
        wikipedia = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
                     [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
        self.assertAlmostEqual(em.fleiss_kappa(wikipedia), 0.210, places=3)

    def test_fleiss_kappa_bad_tables(self):
        for bad in ([], [[1, 1], [2, 1]], [[1, 0], [0, 1]], [[]]):
            with self.assertRaises(ValueError):
                em.fleiss_kappa(bad)


if __name__ == "__main__":
    unittest.main()
