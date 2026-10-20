"""The action-module checker: balanced, known, un-nested `<!-- module:NAME -->` markers, one module per H2 section,
start-here jump links that resolve, and no section numbers written into headings. Fixtures are invented."""
import unittest
from pathlib import Path

from plainspoken import modules

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "reader_value"


def check(name: str) -> list[dict]:
    return modules.check((FIX / name).read_text(encoding="utf-8"))


class Clean(unittest.TestCase):
    def test_all_three_modules_clean(self):
        self.assertEqual(check("modules-clean.md"), [])

    def test_no_modules_no_findings(self):
        self.assertEqual(modules.check("# Title\n\n## A section\n\nProse.\n"), [])
        self.assertEqual(modules.check(""), [])


class Negative(unittest.TestCase):
    def assert_one(self, name: str, line: int, *needles: str) -> dict:
        findings = check(name)
        self.assertEqual(len(findings), 1, findings)
        f = findings[0]
        self.assertEqual(set(f), {"line", "message"})
        self.assertEqual(f["line"], line, f)
        for needle in needles:
            self.assertIn(needle, f["message"])
        return f

    def test_unbalanced_marker(self):
        self.assert_one("modules-unbalanced.md", 3, "decision", "never closed")

    def test_closing_marker_without_opening(self):
        findings = modules.check("## A\n\nText.\n<!-- /module:decision -->\n")
        self.assertEqual([f["line"] for f in findings], [4])
        self.assertIn("no opening", findings[0]["message"])

    def test_mismatched_close(self):  # exactly one finding, not "at least one"
        findings = modules.check("## A\n<!-- module:decision -->\n| a |\n<!-- /module:action-plan -->\n")
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0]["line"], 4)
        self.assertIn("doesn't match", findings[0]["message"])

    def test_markers_inside_inline_code_are_not_markers(self):
        text = ("## A\n\nOpen a module with `<!-- module:decision -->` and close it with "
                "``<!-- /module:decision -->``.\n\nA stray `<!-- /module:start-here -->` is prose too.\n")
        self.assertEqual(modules.check(text), [])

    def test_inline_code_does_not_hide_a_real_marker(self):
        text = "## A\n<!-- module:decision --> uses `code`\n| a |\n"
        findings = modules.check(text)
        self.assertEqual([f["line"] for f in findings], [2])
        self.assertIn("never closed", findings[0]["message"])

    def test_jump_link_inside_inline_code_is_not_checked(self):
        text = ("## A\n<!-- module:start-here -->\nWrite links like `[x](#nowhere)`.\n"
                "<!-- /module:start-here -->\n")
        self.assertEqual(modules.check(text), [])

    def test_jump_link_on_the_closing_marker_line_is_checked(self):
        text = ("## A\n<!-- module:start-here -->\nJump to the steps:\n"
                "[the steps](#missing-steps) <!-- /module:start-here -->\n\n## Steps\n")
        findings = modules.check(text)
        self.assertEqual([f["line"] for f in findings], [4], findings)
        self.assertIn("#missing-steps", findings[0]["message"])

    def test_jump_link_after_the_closing_marker_is_not_the_modules(self):
        text = ("## A\n<!-- module:start-here -->\n[the steps](#steps)\n"
                "<!-- /module:start-here --> [elsewhere](#nowhere)\n\n## Steps\n")
        self.assertEqual(modules.check(text), [])

    def test_jump_link_before_the_opening_marker_is_not_the_modules(self):
        text = ("## A\n[elsewhere](#nowhere) <!-- module:start-here -->\n[the steps](#steps)\n"
                "<!-- /module:start-here -->\n\n## Steps\n")
        self.assertEqual(modules.check(text), [])

    def test_unknown_name(self):
        self.assert_one("modules-unknown.md", 3, "checklist", "start-here")

    def test_nested_modules(self):
        self.assert_one("modules-nested.md", 8, "decision", "inside", "start-here")

    def test_two_modules_in_one_section(self):
        self.assert_one("modules-two-in-section.md", 11, "action-plan", "decision", "one module per section")

    def test_broken_jump_to_anchor(self):
        self.assert_one("modules-broken-anchor.md", 8, "#three-checks")

    def test_numbered_headings(self):
        findings = check("modules-numbered-heading.md")
        self.assertEqual([f["line"] for f in findings], [3, 7])
        self.assertIn("section number", findings[0]["message"])

    def test_markers_inside_code_fences_are_ignored(self):
        self.assertEqual(modules.check("## A\n\n```\n<!-- module:decision -->\n## 1. Example\n```\n"), [])

    def test_odd_spacing_still_counts_as_a_marker(self):
        findings = modules.check("## A\n<!--module: Start Here-->\n")
        self.assertTrue(any("Start Here" in f["message"] for f in findings), findings)


class Slugs(unittest.TestCase):
    def test_github_style_slugs(self):
        self.assertEqual(modules.slug("Why drains slow down"), "why-drains-slow-down")
        self.assertEqual(modules.slug("What I'd prioritise — and what I'd skip"),
                         "what-id-prioritise--and-what-id-skip")
        self.assertEqual(modules.slug("Use `git` and [the docs](https://example.com)!"), "use-git-and-the-docs")

    def test_duplicate_headings_get_numbered_slugs(self):
        text = ("<!-- module:start-here -->\n## Start here\n[a](#notes-1)\n<!-- /module:start-here -->\n"
                "## Notes\n\n## Notes\n")
        self.assertEqual(modules.check(text), [])

    def test_explicit_id_replaces_the_slug(self):
        text = ("<!-- module:start-here -->\n## Start here\n[a](#the-plan)\n<!-- /module:start-here -->\n"
                "## The plan {#plan}\n")
        findings = modules.check(text)
        self.assertEqual([f["line"] for f in findings], [3])


if __name__ == "__main__":
    unittest.main()
