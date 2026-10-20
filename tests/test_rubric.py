import re
import unittest
from pathlib import Path

from plainspoken import justify
from plainspoken.registry import load_config

REPO = Path(__file__).resolve().parents[1]
RUBRIC = REPO / "data" / "rubrics" / "judges.md"


class Rubric(unittest.TestCase):
    def setUp(self):
        self.text = RUBRIC.read_text(encoding="utf-8")

    def test_every_judge_rule_has_a_rubric_entry(self):
        cfg = load_config()
        sections = {block.split(None, 1)[0]: block for block in re.split(r"^## ", self.text, flags=re.M)[1:]}
        for rule in cfg.rules.values():
            if "judge" in rule.method and rule.status != "shadow":
                self.assertIn(rule.group, sections, f"no '## {rule.group}' section")
                self.assertTrue(re.search(rf"(?m)^### {re.escape(rule.id)} ", sections[rule.group]),
                                f"no rubric for rule {rule.id} under '## {rule.group}'")
        for group, block in sections.items():
            for rid in re.findall(r"(?m)^### (\S+) ", block):
                rule = cfg.rules.get(rid)
                self.assertTrue(rule is not None and "judge" in rule.method and rule.group == group,
                                f"rubric entry {rid} under '## {group}' is not a {group} judge rule")

    def test_rubric_documents_jr_and_every_kind(self):
        self.assertIn("## JR Justification review", self.text)
        jr = self.text.split("## JR Justification review", 1)[1]
        for kind in justify.KINDS:
            self.assertIn(f"`{kind}`", jr, kind)
        self.assertIn('"justify_sha256"', jr)

    def test_research_additions_present(self):
        lower = self.text.lower()
        self.assertIn("deletion test", lower)
        self.assertIn("ineffective indicators", lower)
        self.assertIn("never guess who or what wrote", lower)

    def test_no_host_specifics(self):
        # The rubric names no site, host file or house ruleset: those belong in a profile's calibration notes.
        for word in (".claude/", "rules.yaml", "voice.md", ".example", "state file"):
            self.assertNotIn(word, self.text, word)

    def test_profile_hooks_named(self):
        for needle in ("calibration_notes", "visible_frontmatter_keys", "faq_frontmatter_key", "data/rules.toml"):
            self.assertIn(needle, self.text)

    def test_severity_rule_matches_agent_and_rule_18_is_profile_neutral(self):
        self.assertIn("severity given for the rule in your input's `severities`", self.text)
        self.assertNotIn("Tools & Resources", self.text)
        self.assertIn("resource-list headings", self.text.split("### 18 ", 1)[1].split("### ", 1)[0])
