import re
import unittest

from tests._skills import REPO, SkillBasics, headings

REFS = REPO / "skills" / "copy-audit" / "references"
LETTERS = "abcefghijklmnop"  # d was merged into c in the source and stays retired


class CopyAuditSkill(SkillBasics, unittest.TestCase):
    NAME = "copy-audit"
    REQUIRED = ("Core rules", "Step 0: structure first", "The 60-second audit", "The four gates", "Copy tells",
                "Public-copy checklist", "Presentation", "Report")
    DRAFTING = False
    REFERENCES = ("tells.md", "checklist.md", "claude-code.md", "principle.md", "outcomes-led.md",
                  "worked-examples.md", "section-design.md")

    def test_manual_only(self):
        self.assertEqual(self.fm["disable-model-invocation"], "true")

    def test_pasted_text_is_saved_then_audited(self):
        self.assertIn(".plainspoken/drafts/", self.text)
        self.assertIn("Write(.plainspoken/drafts/*)", self.fm["allowed-tools"])

    def test_content_type_mapping(self):
        self.assertRegex(self.text, r"`page` and `email` → `article`")
        self.assertRegex(self.text, r"`post` and `ad` → `social`")

    def test_shared_patterns_point_to_plain_language(self):  # one full copy
        tells = (REFS / "tells.md").read_text(encoding="utf-8")
        for letter in "mo":
            entry = tells.split(f"### {letter}. ", 1)[1].split("\n### ", 1)[0]
            self.assertIn("plain-language", entry)
            self.assertLessEqual(len([l for l in entry.splitlines()[1:] if l.strip()]), 2, letter)

    def test_word_level_tells_come_from_the_checker(self):
        self.assertRegex(self.text, r"(?:run\.py|RUN) check")
        self.assertIn("never from memory", self.text.lower())

    def test_report_first_line(self):
        self.assertIn("Copy audit: <file> — PASS | PARTIAL | FAIL", self.text)

    def test_tells_a_to_p(self):
        tells = (REFS / "tells.md").read_text(encoding="utf-8")
        for letter in LETTERS:
            self.assertRegex(tells, rf"(?m)^### {letter}\. ", letter)
        self.assertIn("<!-- plainspoken: quotes tells on purpose -->", "\n".join(tells.splitlines()[:8]))

    def test_checklist_has_eleven_items(self):
        items = re.findall(r"(?m)^(\d+)\. ", (REFS / "checklist.md").read_text(encoding="utf-8"))
        self.assertEqual(items, [str(n) for n in range(1, 12)])

    def test_four_gates_named(self):
        gates = self.text.split("## The four gates", 1)[1].split("\n## ", 1)[0]
        for gate in ("Voice", "Outcomes", "Plain language", "AI tells"):
            self.assertIn(gate, gates)


class CopyAuditReferences(unittest.TestCase):
    def read(self, rel):
        return (REPO / rel).read_text(encoding="utf-8")

    def test_files_and_sections(self):
        want = {
            "skills/copy-audit/references/principle.md": ("The principle", "Two layers", "The three tests",
                                                           "Truth and control"),
            "skills/copy-audit/references/outcomes-led.md": ("Outcomes lead, method follows", "Framing by surface",
                                                              "What to watch for"),
            "skills/copy-audit/references/section-design.md": ("Section shapes vary", "Items in a row vary on one axis",
                                                                "Positives lead, exclusions sit beneath",
                                                                "The heading fits the section",
                                                                "Don't build sections that force taglines",
                                                                "One main action per page",
                                                                "Say what happens next"),
            "guides/evidence-method.md": ("Evidence tiers", "Capturing a site", "Quoting", "Retiring evidence"),
        }
        for rel, names in want.items():
            h = headings(self.read(rel))
            for name in names:
                self.assertIn(name, h, f"{rel}: {name}")

    def test_worked_examples_are_invented_businesses(self):
        ex = self.read("skills/copy-audit/references/worked-examples.md")
        self.assertGreaterEqual(ex.count("\n### Example "), 4)
        self.assertIn("invented", ex.lower().split("### example", 1)[0])
        self.assertIn("Reasoning", ex)

    def test_other_sites_sentence(self):
        _, text = __import__("tests._skills", fromlist=["load"]).load("copy-audit")
        self.assertIn("borrow the logic of a pattern, never their words", text)

    def test_skill_points_to_the_references(self):
        _, text = __import__("tests._skills", fromlist=["load"]).load("copy-audit")
        for name in ("principle.md", "outcomes-led.md", "worked-examples.md", "section-design.md"):
            self.assertIn(f"references/{name}", text)
        self.assertIn("guides/evidence-method.md", text)

    def test_shared_guidance_is_summarised_not_copied(self):
        ol = self.read("skills/copy-audit/references/outcomes-led.md")
        for heading, owner in (("What to watch for", "plain-language"), ("Framing by surface", "adapt")):
            section = ol.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
            self.assertIn(owner, section)
            self.assertLessEqual(len([l for l in section.splitlines()[1:] if l.strip()]), 3, heading)

    def test_kaizen_k3_recorded(self):
        self.assertIn("## K3:", self.read("docs/kaizen-candidates.md"))

    def test_pointers_are_real_links(self):  # code-span mentions became relative links
        _, text = __import__("tests._skills", fromlist=["load"]).load("copy-audit")
        for target in ("references/section-design.md", "references/principle.md", "references/outcomes-led.md",
                       "references/worked-examples.md", "../../guides/evidence-method.md"):
            self.assertIn(f"]({target})", text, target)

    def test_tier_wording_matches_the_guide(self):  # one place = a single example, not a hypothesis
        _, text = __import__("tests._skills", fromlist=["load"]).load("copy-audit")
        self.assertNotIn("seen in one place is a hypothesis", text)
        self.assertIn("single example", text)
        self.assertIn("**Single example.**", self.read("guides/evidence-method.md"))

    def test_requested_assessment_keeps_its_finding(self):  # tell n doesn't soften a review the reader asked for
        tells = self.read("skills/copy-audit/references/tells.md")
        entry = tells.split("### n. ", 1)[1].split("\n### ", 1)[0]
        self.assertIn("asked for the assessment", entry)
        watch = self.read("skills/plain-language/references/watch-outs.md")
        section = watch.split("## Negative framing", 1)[1].split("\n## ", 1)[0]
        self.assertIn("asked for the assessment", section)

    def test_task8_review_minors(self):
        tells = self.read("skills/copy-audit/references/tells.md")
        self.assertNotRegex(tells, r"(?m)^### d\. ")  # d stays retired
        for letter in "ghk":
            entry = tells.split(f"### {letter}. ", 1)[1].split("\n### ", 1)[0]
            self.assertIn("Example:", entry, letter)
            self.assertIn("Fix:", entry, letter)
        checklist = self.read("skills/copy-audit/references/checklist.md")
        self.assertNotIn("Fails when one or more survive", checklist)
        _, text = __import__("tests._skills", fromlist=["load"]).load("copy-audit")
        step0 = text.split("## Step 0", 1)[1].split("\n## ", 1)[0]
        self.assertIn("first line", step0.lower())
