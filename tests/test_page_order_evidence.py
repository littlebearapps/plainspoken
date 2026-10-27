"""Batch 5: decision-page order, one name per thing across a site, write reading section design for pages,
studying other organisations' pages, and intake forms. All conditional: each loads only for its job."""
import unittest

from tests._skills import REPO, flat

DESIGN = "skills/copy-audit/references/section-design.md"
EVIDENCE = "guides/evidence-method.md"


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    return text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]


class DecisionPageOrder(unittest.TestCase):  # P1
    def setUp(self):
        self.body = section(read(DESIGN), "Order sections by the reader's decision")
        self.flat = flat(self.body).lower()

    def test_reuses_outcomes_led_order_by_pointer(self):
        self.assertIn("](outcomes-led.md)", self.body)
        self.assertNotRegex(self.body, r"(?m)^\d+\. ")  # no second numbered list

    def test_the_method(self):
        for phrase in ("one job", "question it answers", "first", "next section is the action",
                       "what worry does this answer that the earlier ones don't?", "same main action",
                       "say why", "house judgement"):
            self.assertIn(phrase, self.flat, phrase)

    def test_cites_no_studies(self):
        self.assertNotRegex(self.flat, r"\bstud(?:y|ies)\b|\bresearch shows\b|%")

    def test_has_an_invented_example(self):
        self.assertIn("example", self.flat)

    def test_loads_only_for_layout(self):
        audit = flat(read("skills/copy-audit/SKILL.md"))
        self.assertIn("Only when the task includes section or page layout", audit)
        self.assertIn("Use this when the task includes page or section layout", flat(read(DESIGN)))


class OneNamePerThing(unittest.TestCase):  # I
    def setUp(self):
        self.body = flat(section(read(DESIGN), "One name per thing across a site")).lower()

    def test_the_rule(self):
        for phrase in ("two or more pages", "one plain name", "search term", "beside it", "glossary"):
            self.assertIn(phrase, self.body, phrase)

    def test_glossary_named_as_elsewhere(self):
        self.assertIn("profile --voice", self.body)
        self.assertIn("only when the user asks", self.body)

    def test_section_design_loads_for_a_multi_page_audit(self):
        audit = flat(read("skills/copy-audit/SKILL.md"))
        self.assertIn("or spans two or more pages of one site", audit)
        self.assertIn("layout, or spans two or more pages of one site", flat(read(DESIGN)))


class WritePageReadsSectionDesign(unittest.TestCase):  # P2
    def test_outline_step_points_at_section_design(self):
        text = read("skills/write/SKILL.md")
        outline = flat(text.split("### 3. Outline\n", 1)[1].split("\n### ", 1)[0])
        target = "${CLAUDE_PLUGIN_ROOT}/skills/copy-audit/references/section-design.md"
        self.assertIn(f"`{target}`", outline)
        self.assertIn("--type page", outline)
        self.assertIn("before writing H2s", outline)
        self.assertTrue((REPO / target.replace("${CLAUDE_PLUGIN_ROOT}/", "")).is_file())

    def test_only_pages_load_it(self):
        text = flat(read("skills/write/SKILL.md"))
        self.assertEqual(text.count("section-design.md"), 1)


if __name__ == "__main__":
    unittest.main()
