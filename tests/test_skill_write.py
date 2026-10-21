import unittest

from tests._skills import REPO, SkillBasics

REFS = REPO / "skills" / "write" / "references"
QUESTION = "Does this sound like the author, or like an AI explaining the author?"


class WriteSkill(SkillBasics, unittest.TestCase):
    NAME = "write"
    REQUIRED = ("Core rules", "Steps", "1. Research gate", "2. Reader value", "3. Outline", "4. Anchors",
                "5. Draft, one section at a time", "6. Check", "7. Claims", "8. Report")
    DRAFTING = True
    REFERENCES = ("research-gate.md", "answer-first.md", "narrative.md", "claude-code.md", "try-this.md",
                  "confidence-labels.md")

    def test_reads_the_voice_and_maps_the_content_type(self):
        self.assertRegex(self.text, r"(?:run\.py|RUN) profile --voice --type")
        self.assertIn("`article`, `page` and `email` → `article`; `social` → `social`", self.text)

    def test_auto_trigger(self):
        self.assertNotIn("disable-model-invocation", self.fm)

    def test_core_rules(self):
        core = self.text.split("## Steps", 1)[0].lower()
        for needle in ("no sources and no brief", "stop", "never from memory", "say what you mean",
                       "list as many items as there really are", "anchors"):
            self.assertIn(needle, core)

    def test_bare_lint_is_not_step_6(self):  # #23: the drafting rule's short-piece lint doesn't apply inside write
        core = " ".join(self.text.split("## Steps", 1)[0].split())
        self.assertRegex(core, r"The bare lint on its own \(`RUN check [^`]*`\) isn't step 6")

    def step(self, n: int) -> str:
        return self.text.split(f"### {n}. ", 1)[1].split(f"### {n + 1}. ", 1)[0]

    def test_reader_value_outline_before_drafting(self):  # the stub is gone
        step = self.step(2)
        self.assertIn("/plainspoken:reader-value outline", step)
        self.assertIn("skills/reader-value/SKILL.md", step)  # manual-only: follow its steps yourself
        self.assertIn(".plainspoken/reader-value/<draft stem>.reader-value.toml", step)
        self.assertIn(".plainspoken/drafts/<short-slug>.md", step)  # the contract is named after the draft
        for status in ("READY", "PARKED", "INCOMPLETE"):
            self.assertIn(status, step)
        self.assertIn("parked, not drafted", step)
        self.assertNotIn("stub", step.lower())
        self.assertFalse((REFS / "reader-brief.md").exists())
        self.assertNotIn("reader-brief", self.text)

    def test_anchors_from_the_cli_and_missing_anchor_route(self):
        self.assertRegex(self.text, r"(?:run\.py|RUN) anchors --tag .*--skip-missing")
        step = self.text.split("### 4. Anchors", 1)[1].split("### 5.", 1)[0]
        self.assertIn("(skipped anchor", step)
        self.assertIn("say so in the report", step)
        self.assertIn("one call per section type", step)  # a for-loop is refused under Claude Code
        self.assertIn("shell loop", (REFS / "claude-code.md").read_text(encoding="utf-8"))

    def test_per_section_voice_check(self):
        self.assertIn(QUESTION, self.text)

    def test_ends_with_check(self):
        step = self.text.split("### 6. Check", 1)[1].split("### 7.", 1)[0]
        self.assertIn("/plainspoken:check", step)

    def test_claims_skill_on_the_saved_draft(self):  # the hand-off stub is gone
        step = self.step(7)
        self.assertIn("/plainspoken:claims", step)
        self.assertIn("skills/claims/SKILL.md", step)
        self.assertIn("claims status", step)
        self.assertNotIn("later version", self.text.lower())
        self.assertNotIn("in this version", self.text.lower())
        self.assertNotIn("Claims to verify", self.text)

    def test_report_lines(self):  # #24: a fixed block, the engine's lines quoted from `status`, never from memory
        step = self.text.split("### 8. Report", 1)[1]
        self.assertIn("`RUN status '<draft>' --plugin-profile '${user_config.profile}'`", step)
        block = [line.strip() for line in step.splitlines() if line.startswith("    ")]
        self.assertEqual([line.split(":", 1)[0] for line in block],
                         ["Draft", "<every line `status` printed", "Reader value", "Needs the owner", "Anchors",
                          "For kaizen"])
        self.assertIn("Reader value: <READY|PARKED|INCOMPLETE> (<contract path>)", block)
        self.assertNotIn("Claims:", step)
        self.assertNotIn("Reader brief", step)
        flat = " ".join(step.split())
        self.assertIn("copied exactly as printed, never from memory or in other words", flat)
        self.assertIn("A check or claims result that isn't PASS is never described as passed", flat)
        self.assertIn("A piece step 2 parked, or left INCOMPLETE, gets only", flat)
        self.assertIn("<every (skipped anchor …) line>", flat)  # step 4's skipped anchors are reported

    def test_unresolved_check_and_skipped_claims_are_never_silent(self):  # #24
        six, seven = " ".join(self.step(6).split()), " ".join(self.step(7).split())
        self.assertIn("an UNRESOLVED merge goes through its fix-or-justify loop first", six)
        self.assertIn("A WARN you keep without an accepted justification leaves the check UNRESOLVED", six)
        self.assertIn("Never skip this step; if it can't run, the report keeps `claims: INCOMPLETE`", seven)

    def test_a_draft_changed_after_claims_goes_back_to_claims(self):
        step = " ".join(self.step(7).split())
        self.assertIn("rerun the claims skill's steps 4 to 6 once", step)
        self.assertIn("tell the user to run `/plainspoken:claims <draft>` again", step)

    def test_other_skills_named_from_the_plugin_folder(self):
        notes = (REFS / "claude-code.md").read_text(encoding="utf-8")
        for name in ("reader-value", "claims", "check"):
            path = f"${{CLAUDE_PLUGIN_ROOT}}/skills/{name}/SKILL.md"
            self.assertIn(path, notes, name)
        for name in ("reader-value", "claims"):
            self.assertIn(f"${{CLAUDE_PLUGIN_ROOT}}/skills/{name}/SKILL.md", self.text, name)
        self.assertNotRegex(self.text + notes, r"(?<![}/])skills/(?:check|claims|reader-value)/SKILL\.md")
        self.assertIn("the one holding `lib/run.py`", notes)

    def test_manual_skills_followed_by_hand_under_claude_code(self):
        notes = (REFS / "claude-code.md").read_text(encoding="utf-8")
        for name in ("skills/reader-value/SKILL.md", "skills/claims/SKILL.md", "disable-model-invocation"):
            self.assertIn(name, notes)

    def test_reader_actions_and_evidence_labels(self):  # the deferred patterns, made generic
        self.assertIn("references/try-this.md", self.text)
        self.assertIn("references/confidence-labels.md", self.text)
        refs = REPO / "skills" / "write" / "references"
        try_this = (refs / "try-this.md").read_text(encoding="utf-8")
        for needle in ("**Try this:**", "## Tools and resources", "from the sources", "without more research"):
            self.assertIn(needle, try_this)
        labels = (refs / "confidence-labels.md").read_text(encoding="utf-8")
        for needle in ("Strong evidence", "Directional evidence", "Limited evidence", "Not assessed in depth",
                       "`opinion_or_inference`"):
            self.assertIn(needle, labels)
        for f in (try_this, labels):
            for n, line in enumerate(f.splitlines(), start=1):
                self.assertLessEqual(len(line), 118, f"line {n}")

    def test_blend_references(self):
        self.assertIn("references/answer-first.md", self.text)
        self.assertIn("references/narrative.md", self.text)
