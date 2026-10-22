import unittest

from tests._skills import REPO, SkillBasics, headings

REFS = REPO / "skills" / "plain-language" / "references"


class PlainLanguageSkill(SkillBasics, unittest.TestCase):
    NAME = "plain-language"
    REQUIRED = ("Core rules", "When to use", "Steps", "The read-aloud test", "Zero-prior-knowledge test",
                "Actionability test", "Insider terms", "Layered depth", "Comprehension floor", "Report")
    DRAFTING = True
    REFERENCES = ("layered-depth.md", "insider-terms.md", "worked-examples.md", "claude-code.md",
                  "watch-outs.md", "rhythm.md")

    def test_auto_trigger(self):
        self.assertNotIn("disable-model-invocation", self.fm)

    def test_core_rules(self):
        core = self.text.split("## When to use", 1)[0].lower()
        for needle in ("reader", "wouldn't use", "gloss", "never add", "hint, never the gate", "writing about the writing"):
            self.assertIn(needle, core)

    def test_reader_comes_from_the_profile(self):
        self.assertIn("reader:", self.text)        # the first step's summary line it reads
        self.assertIn("comprehension_floor", self.text)
        self.assertRegex(self.text, r"(?:run\.py|RUN) profile --voice")  # the glossary path

    def test_cold_reader_prompt_is_two_lines(self):
        self.assertIn("Reader: <the reader line>", self.text)
        self.assertIn("File: <absolute path>", self.text)

    def test_no_global_word_list(self):  # insider words are relative to the reader
        terms = (REFS / "insider-terms.md").read_text(encoding="utf-8")
        self.assertNotRegex(terms, r"(?m)^\|.*\|.*\|$")  # no table of term -> replacement
        self.assertIn("glossary", terms)

    def test_cold_reader_named(self):
        self.assertIn("plainspoken:cold-reader", self.text)

    def test_rewrite_runs_the_lint_once(self):
        self.assertRegex(self.text, r"(?:run\.py|RUN) check")

    def test_worked_examples_are_invented(self):
        ex = (REFS / "worked-examples.md").read_text(encoding="utf-8")
        self.assertGreaterEqual(ex.count("\n### Example "), 4)
        self.assertIn("invented", ex.splitlines()[2].lower() if len(ex.splitlines()) > 2 else "")


class PlainLanguageReferences(unittest.TestCase):
    def read(self, rel):
        return (REPO / rel).read_text(encoding="utf-8")

    def test_watch_outs_patterns(self):
        h = headings(self.read("skills/plain-language/references/watch-outs.md"))
        for name in ("Method leak", "Overclaim", "Soft abstractions", "Benefit mush", "Negative framing",
                     "Audience-noun drift", "Sameness collapse", "Defining by what it isn't", "Length signals",
                     "Claims that go stale", "False reassurance", "Capacity-blindness", "Fake closure",
                     "Every call to action leads to the same place"):
            self.assertIn(name, h)

    def test_rhythm_has_guardrails(self):
        h = headings(self.read("skills/plain-language/references/rhythm.md"))
        self.assertEqual(h[:2], ["Stop-start rhythm", "Over-correction guardrails"])

    def test_locale_guide(self):
        h = headings(self.read("guides/locale-en-AU.md"))
        for name in ("Rule levels", "Proper names keep their spelling", "Posture", "Enquiry or inquiry",
                     "Money, dates and times", "Imported idioms", "The naturalness test"):
            self.assertIn(name, h)

    def test_audience_template_is_structure_only(self):
        text = self.read("templates/audience-scenarios.md")
        for name in ("Shared reader", "Who they are", "What they worry about", "Words they use and words they skip",
                     "What they've been burned by", "Objections", "Lines that land", "Evidence and honesty"):
            self.assertIn(name, headings(text))
        self.assertIn("<", text)  # placeholders, not personas

    def test_kaizen_k2_recorded(self):
        self.assertIn("## K2:", self.read("docs/kaizen-candidates.md"))
