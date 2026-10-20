import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts.dev import lint_frontmatter as lf


def _skill(root: Path, folder: str, frontmatter: str) -> None:
    d = root / "skills" / folder
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\nbody\n", encoding="utf-8")


class PortableTests(unittest.TestCase):
    """Agent Skills portability rules (agentskills.io spec, checked 2026-10-10)."""

    def setUp(self):
        out = contextlib.redirect_stdout(io.StringIO())
        self.buf = out.__enter__()
        self.addCleanup(out.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_description_over_1024_fails_even_without_when_to_use(self):
        _skill(self.root, "check", "name: check\ndescription: " + "a" * 1025)
        self.assertEqual(lf.main(str(self.root)), 1)
        self.assertIn("1024", self.buf.getvalue())

    def test_description_at_1024_passes(self):
        _skill(self.root, "check", "name: check\ndescription: " + "a" * 1024)
        self.assertEqual(lf.main(str(self.root)), 0)

    def test_name_must_match_folder(self):
        _skill(self.root, "check", "name: checker\ndescription: Lints drafts.")
        self.assertEqual(lf.main(str(self.root)), 1)
        self.assertIn("folder", self.buf.getvalue())

    def test_name_character_rules(self):
        for bad in ("Check", "-check", "check-", "ch--eck", "ch_eck", "a" * 65):
            with self.subTest(name=bad):
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                root = Path(tmp.name)
                _skill(root, bad, f"name: {bad}\ndescription: Lints drafts.")
                self.assertEqual(lf.main(str(root)), 1)

    def test_known_claude_only_fields_allowed(self):
        _skill(
            self.root,
            "kaizen",
            "name: kaizen\ndescription: Reviews the ledger.\nwhen_to_use: monthly\n"
            "disable-model-invocation: true\nargument-hint: review|calibrate",
        )
        self.assertEqual(lf.main(str(self.root)), 0)

    def test_unknown_field_fails(self):
        _skill(self.root, "check", "name: check\ndescription: Lints drafts.\ndisable_model_invocation: true")
        self.assertEqual(lf.main(str(self.root)), 1)
        self.assertIn("unknown frontmatter field", self.buf.getvalue())

    def test_agent_with_memory_fails(self):
        (self.root / "agents").mkdir()
        (self.root / "agents" / "tells-judge.md").write_text(
            "---\nname: tells-judge\ndescription: Judges drafts.\nmemory: project\n---\n", encoding="utf-8"
        )
        self.assertEqual(lf.main(str(self.root)), 1)
        self.assertIn("memory", self.buf.getvalue())


if __name__ == "__main__":
    unittest.main()
