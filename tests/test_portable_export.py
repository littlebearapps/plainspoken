import tempfile
import unittest
from pathlib import Path

from scripts.dev import portable_export as pe


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "plugin"
        self.out = Path(self.tmp.name) / "out"
        d = self.root / "skills" / "kaizen"
        (d / "references").mkdir(parents=True)
        (d / "SKILL.md").write_text(
            "---\nname: kaizen\ndescription: |\n  Reviews the ledger.\n  Proposes changes.\n"
            "when_to_use: monthly\ndisable-model-invocation: true\nlicense: MIT\n---\n# Body\n",
            encoding="utf-8",
        )
        (d / "references" / "notes.md").write_text("ref\n", encoding="utf-8")

    def test_strips_claude_only_fields_and_keeps_portable_ones(self):
        pe.export(self.root, self.out)
        text = (self.out / "kaizen" / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("when_to_use", text)
        self.assertNotIn("disable-model-invocation", text)
        self.assertIn("license: MIT", text)
        self.assertIn("description: |\n  Reviews the ledger.\n  Proposes changes.\n", text)
        self.assertTrue(text.endswith("---\n# Body\n"))

    def test_copies_supporting_files(self):
        pe.export(self.root, self.out)
        self.assertEqual((self.out / "kaizen" / "references" / "notes.md").read_text(encoding="utf-8"), "ref\n")

    def test_returns_exported_dirs(self):
        self.assertEqual([p.name for p in pe.export(self.root, self.out)], ["kaizen"])

    def test_refuses_non_empty_output(self):
        self.out.mkdir()
        (self.out / "stray").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            pe.export(self.root, self.out)


if __name__ == "__main__":
    unittest.main()
