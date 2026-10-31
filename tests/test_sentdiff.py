"""sentdiff: the sentence units and hunks `kaizen diff` and `meaning-diff` share (#147)."""
import unittest

from plainspoken import sentdiff


class SentDiff(unittest.TestCase):
    def test_units_matches_kaizen_diff(self):
        text = "# Title\n\nThe first sentence runs on\nacross two lines. A second one.\n\n```\nx = 1. y = 2.\n```\n"
        units = sentdiff.units(text)
        self.assertIn(("# Title", 1, 1), units)  # a heading is a unit of its own
        self.assertIn(("The first sentence runs on across two lines.", 3, 4), units)
        self.assertIn(("A second one.", 4, 4), units)
        self.assertIn(("x = 1. y = 2.", 7, 7), units)  # a fenced line is never split

    def test_hunks_join_is_one_hunk(self):
        (h,) = sentdiff.hunks("A. B.\n", "A and b.\n")
        self.assertEqual((h["n"], h["old"], h["new"], h["old_lines"]), (1, "A. B.", "A and b.", [1, 1]))

    def test_opcodes_skip_nothing(self):
        ops = sentdiff.opcodes(["a", "b", "c"], ["a", "x", "c"])
        self.assertEqual([op[0] for op in ops], ["equal", "replace", "equal"])


if __name__ == "__main__":
    unittest.main()
