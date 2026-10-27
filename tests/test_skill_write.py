import unittest

from tests._skills import REPO, SkillBasics

REFS = REPO / "skills" / "write" / "references"
QUESTION = "Does this sound like the author, or like an AI explaining the author?"


class WriteSkill(SkillBasics, unittest.TestCase):
    NAME = "write"
    REQUIRED = ("Core rules", "Steps", "1. Research gate", "2. Reader value", "3. Outline", "4. Anchors",
                "5. Draft, one section at a time", "6. Claims", "7. Check", "8. Report")
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

    def test_bare_lint_is_not_the_check_step(self):  # #23: the short-piece lint doesn't apply inside write
        core = " ".join(self.text.split("## Steps", 1)[0].split())
        self.assertRegex(core, r"The bare lint on its own \(`RUN check [^`]*`\) isn't step 7")

    def step(self, n: int) -> str:
        return self.text.split(f"### {n}. ", 1)[1].split(f"### {n + 1}. ", 1)[0]

    def test_length_the_sources_cant_carry_is_raised_before_drafting(self):  # #32: say so; never pad
        step = " ".join(self.step(1).split())
        self.assertIn("estimate whether the sources can carry it", step)
        self.assertIn("say so before you draft and ask for more material", step)
        self.assertIn("write it shorter and say why in the report, straight after step 8's block", step)
        self.assertNotIn("top of the report", step)  # #41: the shortfall never comes before the status block
        self.assertIn("Never pad", step)
        self.assertIn("A definition or background line the sources don't give is a new fact", step)
        gate = (REFS / "research-gate.md").read_text(encoding="utf-8")
        self.assertIn("## When the sources can't carry the length", gate)
        report = " ".join(self.text.split("### 8. Report", 1)[1].split())
        self.assertIn("Any length you give is the `words:` line's, never an estimate", report)
        self.assertIn("you say it counts body text only", report)  # #63: headings aren't in the count

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
        step = self.step(7)
        self.assertTrue(self.text.index("### 7. Check") > self.text.index("### 6. Claims"))
        self.assertIn("/plainspoken:check", step)

    def test_claims_skill_on_the_saved_draft(self):  # the hand-off stub is gone
        step = self.step(6)
        self.assertIn("/plainspoken:claims", step)
        self.assertIn("skills/claims/SKILL.md", step)
        self.assertIn("claims status", self.step(7))  # read after the check, which may have changed the draft
        self.assertNotIn("later version", self.text.lower())
        self.assertNotIn("in this version", self.text.lower())
        self.assertNotIn("Claims to verify", self.text)

    def test_report_lines(self):  # #24: a fixed block, the engine's lines quoted from `status`, never from memory
        step = self.text.split("### 8. Report", 1)[1]
        self.assertIn("`RUN status '<draft>' --plugin-profile '${user_config.profile}'`", step)
        block = [line.strip() for line in step.splitlines() if line.startswith("    ")]
        self.assertEqual([line.split(":", 1)[0] for line in block],
                         ["Draft", "<every line `status` printed", "Reader value (outline)", "Anchors", "For kaizen"])
        self.assertIn("needs the owner", block[1])  # #45: the engine's list from the ledger, not the model's
        # #108: READY is the outline contract, not a delivery pass, and only a READY line gets the deliver tail
        self.assertIn("Reader value (outline): READY (<contract path>); delivery not checked: "
                      "you run /plainspoken:reader-value deliver <draft>", block)  # the block is for a drafted piece
        self.assertNotIn("Claims:", step)
        self.assertNotIn("Reader brief", step)
        flat = " ".join(step.split())
        self.assertIn("copied exactly as printed, never from memory or in other words", flat)
        self.assertIn("A check or claims result that isn't PASS is never described as passed", flat)
        self.assertIn("A piece step 2 parked, or left INCOMPLETE, gets only", flat)
        self.assertIn("gets only `Reader value (outline): PARKED (<contract path>)` (or `INCOMPLETE`) "
                      "and the reason, with no delivery tail", flat)  # #108: the other shape, given literally
        self.assertIn("<every (skipped anchor …) line>", flat)  # step 4's skipped anchors are reported
        self.assertIn("Ask the owner to check nothing that the `needs the owner` lines don't list", flat)
        self.assertIn("hold it `blocking` or cut it, never only ask in the report", " ".join(self.step(6).split()))

    def test_report_starts_with_the_block(self):  # #41: no prose before the block, and the shortfall comes after it
        flat = " ".join(self.text.split("### 8. Report", 1)[1].split())
        self.assertIn("Start the report with this block, with no words before it", flat)
        self.assertIn("a report without it is incomplete", flat)
        self.assertIn("Then give any length shortfall (step 1)", flat)
        gate = " ".join((REFS / "research-gate.md").read_text(encoding="utf-8").split())
        self.assertIn("say why in the report, straight after its status block", gate)
        self.assertNotIn("top of the report", self.text + gate)

    def test_unresolved_check_and_skipped_claims_are_never_silent(self):  # #24
        claims, check = " ".join(self.step(6).split()), " ".join(self.step(7).split())
        self.assertIn("an UNRESOLVED merge goes through its fix-or-justify loop first", check)
        self.assertIn("A WARN you keep without an accepted justification leaves the check UNRESOLVED", check)
        self.assertIn("Never skip this step; if it can't run, the report keeps `claims: INCOMPLETE`", claims)

    def test_claims_before_the_check(self):  # #27: claims edits land before the judges read the draft
        claims, check = " ".join(self.step(6).split()), " ".join(self.step(7).split())
        self.assertIn("Claims runs before the check", claims)
        self.assertNotIn("run the check once more (step", claims)
        # a check edit costs one claims checker rerun, not a second round of four judges
        self.assertIn("If the check changed the draft, the ledger no longer matches it", check)
        self.assertIn("rerun the claims skill's steps 4 to 6 once", check)
        self.assertIn("tell the user to run `/plainspoken:claims <draft>` again", check)
        self.assertIn("list for step 6", " ".join(self.step(2).split()))

    def test_lint_only_passes_before_claims(self):  # #42: a lint fix after claims would stale the ledger
        claims, check = " ".join(self.step(6).split()), " ".join(self.step(7).split())
        self.assertIn("First make the check's lint-only passes here, so a lint fix lands before the ledger is built",
                      claims)
        self.assertLess(claims.index("lint-only passes"), claims.index("Run `/plainspoken:claims`"))
        self.assertIn("by cutting, joining, splitting or restating, at most twice", claims)
        self.assertIn("Its two lint-only passes include step 6's", check)

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

    def test_replies_answer_every_question(self):  # a reply's agenda is the incoming message
        af = (REPO / "skills" / "write" / "references" / "answer-first.md").read_text(encoding="utf-8")
        self.assertIn("## Replies", af)
        section = af.split("## Replies", 1)[1].split("\n## ", 1)[0]
        for phrase in ("each question", "acknowledge", "settle"):
            self.assertIn(phrase, section.lower(), phrase)

    def test_blend_references(self):
        self.assertIn("references/answer-first.md", self.text)
        self.assertIn("references/narrative.md", self.text)


class ReaderValueGrader(unittest.TestCase):  # #108: the smoke grader finds the relabelled line, and only that one
    def pattern(self):
        import re
        text = (REPO / "evals" / "smoke" / "write--smoke" / "graders" / "reader-value-line.md").read_text(encoding="utf-8")
        line = next(x for x in text.splitlines() if x.startswith("pattern:"))
        return re.compile(line.split(":", 1)[1].strip().strip("'"), re.I)

    def test_matches_the_outline_line(self):
        for line in ("Reader value (outline): READY (.plainspoken/reader-value/post.reader-value.toml); delivery not "
                     "checked: you run /plainspoken:reader-value deliver post.md",
                     "**Reader value (outline)**: READY (x.toml); delivery not checked: you run "
                     "/plainspoken:reader-value deliver post.md",
                     "Reader value (outline): **PARKED** (x.toml)", "reader value (outline): `INCOMPLETE` (x.toml)",
                     "Reader value (outline): PARKED (x.toml)", "Reader value (outline): INCOMPLETE (x.toml)"):
            self.assertRegex(line, self.pattern())

    def test_the_old_unscoped_line_no_longer_passes(self):
        self.assertNotRegex("Reader value: READY (x.toml)", self.pattern())

    def test_ready_without_the_deliver_tail_fails(self):
        self.assertNotRegex("Reader value (outline): READY (x.toml)", self.pattern())

    def test_the_template_echo_fails(self):
        self.assertNotRegex("Reader value (outline): <READY|PARKED|INCOMPLETE> (<contract path>)", self.pattern())
