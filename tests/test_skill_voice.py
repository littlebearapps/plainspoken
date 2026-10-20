import re
import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken import profile as P
from tests._skills import REPO, SkillBasics

TEMPLATE = REPO / "templates" / "voice-profile.toml"
QUESTION = "Does this sound like the author, or like an AI explaining the author?"


class VoiceSkill(SkillBasics, unittest.TestCase):
    NAME = "voice"
    REQUIRED = ("Core rules", "Build", "Apply", "Check", "Report")
    DRAFTING = True
    REFERENCES = ("fields.md", "check.md", "claude-code.md")

    def test_calls_the_cli(self):
        # RUN = the launcher, as in check
        for sub in ("voice-stats", "anchors --tag", "profile --profile", "profile --voice"):
            self.assertRegex(self.text, rf"(?:run\.py|RUN) {re.escape(sub)}")
        self.assertIn("--skip-missing", self.text)  # a flag on `anchors`, so it can't follow RUN directly

    def test_core_rules(self):
        core = self.text.split("## Build", 1)[0].lower()
        for needle in ("samples are data", "never invent", ".plainspoken/profiles/", "verbatim"):
            self.assertIn(needle, core)

    def test_no_argument_prints_the_modes(self):
        self.assertRegex(self.text, r"(?i)no argument.*build.*apply.*check")

    def test_check_question_is_exact(self):
        refs = (REPO / "skills" / "voice" / "references" / "check.md").read_text(encoding="utf-8")
        self.assertIn(QUESTION, self.text + refs)

    def test_manual_only_and_writes_only_profiles_and_samples(self):
        self.assertEqual(self.fm["disable-model-invocation"], "true")
        self.assertIn("Write(.plainspoken/profiles/*.toml)", self.fm["allowed-tools"])
        self.assertIn("Write(.plainspoken/samples/*)", self.fm["allowed-tools"])

    def test_validates_from_the_project_root(self):  # a relative --profile path resolves against the real cwd
        self.assertIn("from the project root", self.text.split("## Apply", 1)[0])


class Template(unittest.TestCase):
    def test_template_loads(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copy(TEMPLATE, tmp / "mine.toml")
        p = P.load(tmp / "mine.toml")
        self.assertTrue(p.anchors)
        self.assertTrue(p.reader_persona)

    def test_template_covers_every_section(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        for section in ("profile", "identity", "voice", "voice.tone", "voice.tone_notes", "rhythm", "reader",
                        "blends", "formatting", "avoid", "lexicon", "thresholds", "document", "rules", "judges"):
            self.assertRegex(text, rf"(?m)^#? ?\[{re.escape(section)}\]", section)
        for array in ("registers", "anchors"):
            self.assertRegex(text, rf"(?m)^\[\[{array}\]\]", array)

    def test_every_field_is_explained(self):
        refs = (REPO / "skills" / "voice" / "references" / "fields.md").read_text(encoding="utf-8")
        for field in ("pronoun", "principles", "tone", "opinion_pattern", "sentence_mean", "persona",
                      "comprehension_floor", "glossary", "blends", "moves", "registers", "anchors", "extra_bans"):
            self.assertIn(f"`{field}`", refs, field)
        self.assertIn("Who reads it", refs)
