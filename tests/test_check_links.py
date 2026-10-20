import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.dev import check_links as cl

REPO = Path(__file__).resolve().parents[1]


class Links(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "skills" / "x" / "references").mkdir(parents=True)
        (self.root / "skills" / "x" / "references" / "a.md").write_text("ok\n", encoding="utf-8")
        (self.root / "lib").mkdir()
        (self.root / "lib" / "run.py").write_text("", encoding="utf-8")

    def bad(self, body: str, rel: str = "skills/x/SKILL.md") -> list[str]:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return [b.why for b in cl.scan(self.root)]

    def test_relative_link_inside_the_root_is_fine(self):
        self.assertEqual(self.bad("[a](references/a.md)\n"), [])

    def test_missing_target(self):
        self.assertEqual(self.bad("[a](references/nope.md)\n"), ["missing"])

    def test_parent_escape(self):
        self.assertEqual(self.bad("[a](../../../../etc/passwd)\n"), ["outside the plugin root"])

    def test_absolute_and_home_paths(self):
        self.assertEqual(self.bad("[a](/srv/someone/x.md) [b](~/x.md)\n"), ["outside the plugin root"] * 2)

    def test_web_mail_and_anchor_links_are_fine(self):
        self.assertEqual(self.bad("[a](https://example.com) [b](mailto:a@example.com) [c](#core-rules)\n"), [])

    def test_uppercase_schemes_are_fine(self):
        self.assertEqual(self.bad("[a](HTTP://EXAMPLE.COM) [b](Https://example.com) [c](MAILTO:a@example.com)\n"), [])

    def test_web_link_with_parentheses_is_fine(self):
        self.assertEqual(self.bad("[w](https://en.wikipedia.org/wiki/Fog_(disambiguation)) after\n"), [])

    def test_relative_link_with_parentheses_resolves(self):
        (self.root / "skills" / "x" / "references" / "notes (v2).md").write_text("ok\n", encoding="utf-8")
        (self.root / "skills" / "x" / "references" / "b_(1).md").write_text("ok\n", encoding="utf-8")
        self.assertEqual(self.bad("[a](references/b_(1).md) and [b](<references/notes (v2).md>)\n"), [])

    def test_missing_target_with_parentheses_reports_the_whole_target(self):
        self.bad("[a](references/c_(1).md)\n")
        self.assertEqual([(b.target, b.why) for b in cl.scan(self.root)], [("references/c_(1).md", "missing")])

    def test_title_after_a_target_with_parentheses(self):
        self.assertEqual(self.bad('[w](https://example.com/a_(b) "Title") [r](references/a.md \'t\')\n'), [])

    def test_other_schemes_are_outside(self):
        self.assertEqual(self.bad("[a](file:///etc/hosts)\n"), ["outside the plugin root"])

    def test_plugin_root_variable_resolves_from_the_root(self):
        self.assertEqual(self.bad("[run](${CLAUDE_PLUGIN_ROOT}/lib/run.py)\n"), [])

    def test_links_in_code_are_ignored(self):
        self.assertEqual(self.bad("```\n[a](/abs/path)\n```\n`[b](/abs)`\n"), [])

    def test_reference_definitions_are_checked(self):
        self.assertEqual(self.bad("[a][r]\n\n[r]: ../../../outside.md\n"), ["outside the plugin root"])

    def test_skipped_folders(self):
        self.assertEqual(self.bad("[a](/abs)\n", rel="evals/results/p.md"), [])

    def test_line_numbers(self):
        self.bad("\n\n[a](nope.md)\n")
        self.assertEqual([b.line for b in cl.scan(self.root)], [3])

    def test_bad_root_exits_2(self):
        self.assertEqual(cl.main([str(self.root / "missing")]), 2)

    def test_this_repo_is_clean(self):
        self.assertEqual(cl.scan(REPO), [])
