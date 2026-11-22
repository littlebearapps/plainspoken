"""The read-only entry (#245): the check-only modes of five manual-only skills, startable by an agent, with no write
path, while every mode that writes stays manual."""
import re
import unittest

from tests._skills import REPO, SkillBasics, flat, load

# The five manual-only skills whose check an agent may start, and the mode word each runs under read-only.
FIVE = ("register-check", "voice", "copy-audit", "claims", "reader-value")
CLI = "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py *)"
WRITE_TOOLS = re.compile(r"\b(?:Write|Edit|MultiEdit|NotebookEdit)\b")
# What each manual skill must say an agent may run, and the writing modes it keeps manual.
AGENT_LINES = {
    "register-check": ("/plainspoken:read-only register-check", "rewrite"),
    "voice": ("/plainspoken:read-only voice", "`build` and `apply`"),
    "copy-audit": ("/plainspoken:read-only copy-audit", "rewrite"),
    "claims": ("/plainspoken:read-only claims", "scaffold"),
    "reader-value": ("/plainspoken:read-only reader-value", "`outline`"),
}


def tools(fm: dict) -> list[str]:
    """allowed-tools split on the commas between entries, not the ones inside a Bash(...) pattern."""
    return [t.strip() for t in re.split(r",\s*(?![^()]*\))", fm.get("allowed-tools", "")) if t.strip()]


class ReadOnlySkill(SkillBasics, unittest.TestCase):
    NAME = "read-only"
    REQUIRED = ("Core rules", "Modes", "Report")
    DRAFTING = False
    REFERENCES = ("claude-code.md",)

    def test_model_invocable_with_no_write_path(self):
        self.assertNotIn("disable-model-invocation", self.fm)
        self.assertEqual(tools(self.fm), [CLI])
        self.assertIsNone(WRITE_TOOLS.search(self.fm["allowed-tools"]))

    def test_description_is_tiny_and_names_the_five(self):
        desc = self.fm["description"]
        self.assertLessEqual(len(desc), 90)  # the always-on budget: see tests/test_descriptions.py
        for word in ("register", "voice", "copy", "claims", "reader-value"):
            self.assertIn(word, desc)
        self.assertRegex(desc, r"(?i)edits nothing")

    def test_each_mode_follows_the_manual_skill(self):
        body = flat(self.text)
        for name in FIVE:
            with self.subTest(mode=name):
                self.assertIn(f"`{name}", body)
                self.assertIn(f"${{CLAUDE_PLUGIN_ROOT}}/skills/{name}/SKILL.md", body)

    def test_never_runs_a_writing_step(self):
        core = flat(self.text.split("## Modes", 1)[0])
        self.assertRegex(core, r"(?i)never edit the draft")
        for cmd in ("claims scaffold", "claims pin", "claims stamp", "reader-value template"):
            self.assertIn(f"`{cmd}`", core)
        self.assertRegex(core, r"(?i)a request to fix, rewrite")
        self.assertIn("/plainspoken:<skill>", core)

    def test_the_one_saved_file_asks_the_person(self):  # the checkers' reply files: no pre-approved write
        body = flat(self.text)
        self.assertIn(".plainspoken/reports/", body)
        self.assertRegex(body, r"(?i)asks the person")
        self.assertRegex(body, r"(?i)refused")
        notes = flat((REPO / "skills" / self.NAME / "references" / "claude-code.md").read_text(encoding="utf-8"))
        self.assertIn("no write", notes.lower())
        self.assertIn("Agent tool", notes)

    def test_pasted_text_is_never_saved(self):
        body = flat(self.text)
        self.assertRegex(body, r"(?i)pasted text")
        self.assertIn("lint step was skipped", body)
        self.assertNotIn(".plainspoken/drafts/", body)

    def test_the_named_skills_report_lines_stay(self):
        report = flat(self.text.split("## Report", 1)[1])
        self.assertRegex(report, r"(?i)last line")
        self.assertIn("Read-only run: nothing was changed.", report)

    def test_no_mode_lists_the_five(self):
        self.assertRegex(flat(self.text), r"(?i)with no mode word, or another one, list the five")


class WritingModesStayManual(unittest.TestCase):
    def test_the_five_stay_manual_and_say_what_an_agent_may_run(self):
        for name in FIVE:
            fm, text = load(name)
            core = flat(text.split("**First, before any other step:**", 1)[0])
            line, kept = AGENT_LINES[name]
            with self.subTest(skill=name):
                self.assertEqual(fm.get("disable-model-invocation"), "true")
                self.assertIn("Modes an agent may run:", core)
                self.assertIn(line, core)
                self.assertIn(kept, core)
                self.assertRegex(core, r"starts? only when the person asks")
                notes = (REPO / "skills" / name / "references" / "claude-code.md").read_text(encoding="utf-8")
                self.assertIn("/plainspoken:read-only", notes)

    def test_only_one_entry_is_added(self):  # one listing for five checks keeps the always-on cost down
        auto = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md")
                      if load(p.parent.name)[0].get("disable-model-invocation") != "true")
        self.assertEqual(auto, ["check", "humanize", "plain-language", "read-only", "write"])

    def test_host_notes_name_it(self):
        for host in ("codex", "hermes"):
            text = flat((REPO / "hosts" / f"{host}.md").read_text(encoding="utf-8"))
            with self.subTest(host=host):
                self.assertTrue(re.search(r"(?i)the nine manual-only skills", text), host)
                self.assertTrue(re.search(r"`read-only`[^.]*may start on its own", text), host)


if __name__ == "__main__":
    unittest.main()
