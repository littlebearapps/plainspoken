import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts.dev import lint_frontmatter as lf


def _skill(root: Path, name: str, text: str) -> None:
    d = root / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")


class ParseTests(unittest.TestCase):
    def test_single_line_values(self):
        fm = lf.parse_frontmatter("---\nname: check\ndescription: Lint a draft\n---\nbody\n")
        self.assertEqual(fm["name"], "check")
        self.assertEqual(fm["description"], "Lint a draft")

    def test_block_scalar_joins_lines(self):
        text = "---\nname: x\ndescription: |\n  first line\n  second line\n---\n"
        fm = lf.parse_frontmatter(text)
        self.assertEqual(fm["description"], "first line\nsecond line")

    def test_no_frontmatter_returns_empty(self):
        self.assertEqual(lf.parse_frontmatter("# just a heading\n"), {})


class LintTests(unittest.TestCase):
    def setUp(self):
        out = contextlib.redirect_stdout(io.StringIO())
        out.__enter__()
        self.addCleanup(out.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_skill_passes(self):
        _skill(self.root, "check", "---\nname: check\ndescription: Lint a draft for AI tells.\n---\nbody\n")
        self.assertEqual(lf.main(str(self.root)), 0)

    def test_over_500_lines_fails(self):
        body = "line\n" * 500
        _skill(self.root, "big", "---\nname: big\ndescription: d\n---\n" + body)
        self.assertEqual(lf.main(str(self.root)), 1)

    def test_description_plus_when_to_use_over_cap_fails(self):
        desc = "a" * 1000
        when = "b" * 537
        _skill(self.root, "long", f"---\nname: long\ndescription: {desc}\nwhen_to_use: {when}\n---\n")
        self.assertEqual(lf.main(str(self.root)), 1)

    def test_block_scalar_length_counts_all_lines(self):
        lines = "\n".join("  " + "c" * 100 for _ in range(16))  # 1,600+ chars
        _skill(self.root, "blk", f"---\nname: blk\ndescription: |\n{lines}\n---\n")
        self.assertEqual(lf.main(str(self.root)), 1)

    def test_plain_multiline_description_over_cap_fails(self):
        cont = "\n".join("  " + "d" * 100 for _ in range(16))
        _skill(self.root, "plain", f"---\nname: plain\ndescription: start\n{cont}\n---\n")
        self.assertEqual(lf.main(str(self.root)), 1)

    def test_plain_multiline_joined_with_spaces(self):
        fm = lf.parse_frontmatter("---\nname: x\ndescription: one\n  two\n  three\n---\n")
        self.assertEqual(fm["description"], "one two three")

    def test_block_scalar_indicator_with_keep_over_cap_fails(self):
        lines = "\n".join("  " + "c" * 100 for _ in range(16))
        _skill(self.root, "keep", f"---\nname: keep\ndescription: >+\n{lines}\n---\n")
        self.assertEqual(lf.main(str(self.root)), 1)

    def test_bom_prefixed_skill_passes(self):
        _skill(self.root, "bom", "\ufeff---\nname: bom\ndescription: Fine.\n---\nbody\n")
        self.assertEqual(lf.main(str(self.root)), 0)

    def test_missing_name_or_description_fails(self):
        _skill(self.root, "noname", "---\ndescription: d\n---\n")
        self.assertEqual(lf.main(str(self.root)), 1)

    def test_skill_dir_without_skill_md_fails(self):
        (self.root / "skills" / "empty").mkdir(parents=True)
        self.assertEqual(lf.main(str(self.root)), 1)

    def test_agent_missing_description_fails(self):
        (self.root / "agents").mkdir()
        (self.root / "agents" / "judge.md").write_text("---\nname: judge\n---\n", encoding="utf-8")
        self.assertEqual(lf.main(str(self.root)), 1)

    def _lint_output(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = lf.main(str(self.root))
        return rc, buf.getvalue()

    def test_colon_space_in_plain_value_fails_naming_file_and_key(self):
        _skill(self.root, "bad", "---\nname: bad\ndescription: Checks tells: a fixed lint.\n---\n")
        rc, out = self._lint_output()
        self.assertEqual(rc, 1)
        self.assertIn("bad/SKILL.md", out)
        self.assertIn("'description'", out)
        self.assertIn("colon-space", out)

    def test_trailing_colon_and_space_hash_fail(self):
        _skill(self.root, "a", "---\nname: a\ndescription: Ends with a colon:\n---\n")
        _skill(self.root, "b", "---\nname: b\ndescription: Has a # comment mid-value\n---\n")
        rc, out = self._lint_output()
        self.assertEqual(rc, 1)
        self.assertIn("ends with ':'", out)
        self.assertIn("' #'", out)

    def test_indicator_start_fails(self):
        _skill(self.root, "c", "---\nname: c\ndescription: @mention first\n---\n")
        self.assertEqual(self._lint_output()[0], 1)

    def test_quoted_value_with_colon_passes(self):
        _skill(self.root, "q", '---\nname: q\ndescription: "Checks tells: a fixed lint # ok:"\n---\n')
        self.assertEqual(self._lint_output()[0], 0)

    def test_block_scalar_and_nested_mapping_colons_pass(self):
        _skill(self.root, "n", "---\nname: n\ndescription: |\n  has: colons here\nmetadata:\n  k: v\n---\n")
        self.assertEqual(self._lint_output()[0], 0)

    def test_agent_and_output_style_colon_space_fail(self):
        (self.root / "agents").mkdir()
        (self.root / "agents" / "j.md").write_text("---\nname: j\ndescription: a: b\n---\n", encoding="utf-8")
        self.assertEqual(self._lint_output()[0], 1)
        (self.root / "agents" / "j.md").write_text("---\nname: j\ndescription: ok\n---\n", encoding="utf-8")
        (self.root / "output-styles").mkdir()
        (self.root / "output-styles" / "s.md").write_text("---\nname: s\ndescription: a: b\n---\n", encoding="utf-8")
        rc, out = self._lint_output()
        self.assertEqual(rc, 1)
        self.assertIn("s.md", out)

    def test_no_skills_or_agents_passes(self):
        self.assertEqual(lf.main(str(self.root)), 0)


if __name__ == "__main__":
    unittest.main()
