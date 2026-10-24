"""The manual-only doctor skill (#113) and setup's step that passes host-check warnings on."""
import unittest

from tests._skills import REPO, flat, load


def note(text: str) -> str:
    """The Codex/Hermes note at the top of a skill: its first blockquote."""
    return "\n".join(line for line in text.split("\n# ", 1)[1].splitlines() if line.startswith(">"))


class DoctorSkill(unittest.TestCase):
    def setUp(self):
        self.fm, self.text = load("doctor")
        self.flat = flat(self.text)

    def test_frontmatter(self):
        self.assertEqual(self.fm["name"], "doctor")
        self.assertEqual(self.fm["disable-model-invocation"], "true")
        self.assertEqual(self.fm["allowed-tools"], "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py doctor *)")
        self.assertLessEqual(len(self.fm["description"]), 250)
        self.assertIn("Manual only", self.fm["description"])

    def test_same_host_note_as_setup(self):
        self.assertEqual(note(self.text), note(load("setup")[1]))
        self.assertTrue(note(self.text))

    def test_steps(self):
        self.assertIn("`RUN doctor --host <host>`", self.flat)
        self.assertIn("not checked", self.flat)
        self.assertIn("WARN", self.flat)
        self.assertRegex(self.flat, r"(?i)never fix, install, enable or edit anything")
        self.assertIn("the person decides", self.flat.lower())
        self.assertRegex(self.flat, r"(?i)unverified")

    def test_setup_passes_warnings_on(self):
        text = flat(load("setup")[1])
        self.assertRegex(text, r"(?i)host-check warnings")
        self.assertRegex(text, r"(?i)don't act on them")
        self.assertTrue((REPO / "skills" / "doctor" / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
