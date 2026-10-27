"""The register-check message-shape change (2026-10-27): the worked examples, the temporary-limit line in the control
principle and the write skill's premise check. The checklist items themselves are tested in test_register.py."""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "skills" / "register-check" / "references" / "examples.md"
PRINCIPLE = REPO / "skills" / "copy-audit" / "references" / "principle.md"


class Examples(unittest.TestCase):
    def setUp(self):
        self.text = EXAMPLES.read_text(encoding="utf-8")

    def test_a_first_contact_example_shows_the_sales_sequence(self):
        self.assertIn("observation → credentials → offer → ask", self.text)
        self.assertRegex(self.text, r"holds back the useful part to get a\s+reply")

    def test_the_example_shows_what_passes(self):
        self.assertIn("What passes:", self.text)

    def test_one_plain_no_worries_line_is_still_the_fix(self):
        self.assertIn('a plain "no worries if not"', self.text)
        self.assertIn("stacks stock reassurance", self.text)


class TemporaryLimit(unittest.TestCase):
    def test_truth_and_control_says_more_evidence_doesnt_make_an_outcome_controllable(self):
        text = PRINCIPLE.read_text(encoding="utf-8")
        section = " ".join(text.split("## Truth and control", 1)[1].split())
        self.assertIn("More evidence doesn't bring an outcome under the writer's control", section)
        self.assertIn("not until I've seen the numbers", section)


if __name__ == "__main__":
    unittest.main()
