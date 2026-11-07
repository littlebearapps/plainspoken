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

    def test_the_check_step_records_nothing(self):  # #207: a flags-only skill saves no report and no kaizen event
        self.assertRegex(self.text, r"RUN check FILE --content-type <mapped type> [^`]*--no-record`")

    def test_says_which_kinds_carry_r6_to_r9(self):  # #207
        flat = " ".join(self.text.split())
        self.assertIn("R6 applies to `email`, `message`, `outreach` and `follow-up`", flat)
        self.assertIn("a `post`, `page` or `article` doesn't get them", flat)
        self.assertIn("R9 applies to the same kinds as R6", flat)

    def test_reads_the_checklist_from_the_cli(self):
        self.assertRegex(self.text, r"(?:run\.py|RUN) register-checklist --kind")
