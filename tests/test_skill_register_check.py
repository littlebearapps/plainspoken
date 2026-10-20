import unittest

from tests._skills import SkillBasics


class RegisterCheckSkill(SkillBasics, unittest.TestCase):
    NAME = "register-check"
    REQUIRED = ("Core rules", "Steps", "What to flag", "Report")
    DRAFTING = False
    REFERENCES = ("examples.md", "claude-code.md")

    def test_pasted_text_and_content_type(self):
        self.assertIn(".plainspoken/drafts/", self.text)
        self.assertIn("Write(.plainspoken/drafts/*)", self.fm["allowed-tools"])
        self.assertRegex(self.text, r"`post` and `message` → `social`")

    def test_flags_only(self):
        core = self.text.split("## Steps", 1)[0].lower()
        for needle in ("flags only", "never rewrite unless", "never send"):
            self.assertIn(needle, core)
        self.assertIn("Flags only. You decide what to send.", self.text)

    def test_reads_the_checklist_from_the_cli(self):
        self.assertRegex(self.text, r"(?:run\.py|RUN) register-checklist --kind")
