"""#208: which frontmatter fields a site renders is site data, so `[document]` lives in the project config.

The project's `visible_frontmatter_keys`, `faq_frontmatter_key` and `resource_list_headings` win over the voice
profile's, which stay as the fallback; `profile`, `doctor` and the lint's JSON say where each came from. A frontmatter
string of 3+ words that nothing reads or ignores gets a `not read:` line under the `check` summary, never a finding.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken import config, doctor
from plainspoken import profile as _profile
from plainspoken.report import lint_status, run_lint, summarise

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "profiles"
POST = ('---\ntitle: "A post"\ndescription: "What changed."\ntldr: "We delve into the robust bits here."\n'
        'note: "This line is never shown on the page."\nslug: a-post\nfaqs:\n'
        '  - question: "Is it free?"\n    answer: "Yes, and it is seamless."\n---\n\n'
        "I fixed the login bug on Friday.\n")


class DocumentConfig(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()
        (self.root / ".plainspoken").mkdir()
        self.post = self.root / "post.md"
        self.post.write_text(POST, encoding="utf-8")

    def config(self, text: str) -> None:
        (self.root / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def resolve(self, ref: str = "default") -> _profile.Profile:
        return config.resolve_profile(ref, self.root, {})

    def test_no_project_document_leaves_the_profile_as_it_was(self):
        self.config('[engine]\nprofile = "default"\n')
        prof = self.resolve()
        self.assertEqual(prof.sha256, _profile.default().sha256)
        self.assertEqual(prof.visible_frontmatter_keys, ("title", "description"))
        self.assertEqual(prof.document_from["visible_frontmatter_keys"], "profile")

    def test_the_project_wins_and_the_profile_is_the_fallback(self):
        self.config('[document]\nvisible_frontmatter_keys = ["title", "tldr"]\n')
        prof = self.resolve(str(FIX / "product_like.toml"))
        self.assertEqual(prof.visible_frontmatter_keys, ("title", "tldr"))
        self.assertEqual(prof.faq_frontmatter_key, "faqs")  # the profile's, as no project key sets it
        self.assertEqual(prof.document_from, {"visible_frontmatter_keys": "project config",
                                              "faq_frontmatter_key": "profile", "resource_list_headings": "profile"})
        (self.root / "mine.toml").write_text('[profile]\nname = "mine"\n', encoding="utf-8")
        mine = self.resolve(str(self.root / "mine.toml"))  # sets no [document] key
        self.assertEqual(mine.document_from, {"visible_frontmatter_keys": "project config"})
        self.assertIn("FAQ key: none (default)", config.document_lines(mine)[0])

    def test_every_profile_reads_the_same_fields_under_the_project(self):  # the issue: a profile changed the lint
        self.config('[document]\nvisible_frontmatter_keys = ["title", "description", "tldr"]\n'
                    'faq_frontmatter_key = "faqs"\n')
        read = {ref: run_lint(self.post, self.resolve(ref))["fields_read"]
                for ref in ("default", str(FIX / "product_like.toml"), str(FIX / "consulting_like.toml"))}
        self.assertEqual(set(map(tuple, read.values())), {("body", "title", "description", "tldr", "faqs")}, read)

    def test_the_project_values_join_the_stamp(self):
        self.config('[document]\nignored_frontmatter_keys = ["note"]\n')
        self.assertEqual(self.resolve().sha256, _profile.default().sha256)  # ignoring changes no finding
        self.config('[document]\nfaq_frontmatter_key = "faqs"\n')
        first = self.resolve().sha256
        self.assertNotEqual(first, _profile.default().sha256)
        self.config('[document]\nfaq_frontmatter_key = "questions"\n')
        self.assertNotEqual(self.resolve().sha256, first)

    def test_text_routes_get_the_project_document_too(self):
        self.config('[engine]\nprofile = "default"\n[document]\nfaq_frontmatter_key = "faqs"\n')
        self.assertEqual(config.profile_for_text(self.root, {}).faq_frontmatter_key, "faqs")
        self.assertEqual(config.profile_for_text(self.root, {"PLAINSPOKEN_PROFILE": "default"}).faq_frontmatter_key,
                         "faqs")

    def test_bad_values_fail_closed_naming_the_key(self):
        for body, needle in (('visible_frontmatter_keys = "title"', "visible_frontmatter_keys must be a list"),
                             ('faq_frontmatter_key = 3', "faq_frontmatter_key must be a string"),
                             ('resource_list_headings = ["("]', "resource_list_headings: bad regex"),
                             ('ignored_frontmatter_keys = [""]', "ignored_frontmatter_keys must be a list"),
                             ('long_sentence_headings = []', "unknown key [document] long_sentence_headings")):
            self.config(f"[document]\n{body}\n")
            with self.subTest(body=body), self.assertRaisesRegex(config.ConfigError, needle.replace("[", r"\[")):
                self.resolve()

    def test_the_user_wide_file_cant_set_it(self):
        home = self.root / "home"
        (home / ".config" / "plainspoken").mkdir(parents=True)
        (home / ".config" / "plainspoken" / "config.toml").write_text('[document]\nfaq_frontmatter_key = "x"\n',
                                                                      encoding="utf-8")
        with self.assertRaisesRegex(config.ConfigError, r"unknown section \[document\]"):
            config._user_config({"HOME": str(home)})

    def test_the_lint_json_says_where_each_value_came_from(self):
        self.config('[document]\nvisible_frontmatter_keys = ["title"]\n')
        lint = run_lint(self.post, self.resolve())
        self.assertEqual(lint["document_from"], {"visible_frontmatter_keys": "project config",
                                                 "faq_frontmatter_key": "profile",
                                                 "resource_list_headings": "profile"})

    def test_the_profile_summary_and_doctor_say_so(self):
        self.config('[document]\nvisible_frontmatter_keys = ["title", "tldr"]\nignored_frontmatter_keys = ["note"]\n')
        (line,) = config.document_lines(self.resolve())
        self.assertEqual(line, "frontmatter read: title, tldr (project config) · FAQ key: none (profile) · "
                               "resource-list headings: none (profile) · ignored: note (project config)")
        (row,) = [c for c in doctor.run_checks("claude-code", self.root, {"HOME": str(self.root)}, "default")
                  if c.name == "frontmatter"]
        self.assertEqual((row.status, row.detail), (doctor.OK, line.removeprefix("frontmatter read: ")))
        self.assertIn("frontmatter", doctor.INFO_ROWS)  # setup leaves it to doctor


class UnreadNotice(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()
        (self.root / ".plainspoken").mkdir()
        self.post = self.root / "post.md"
        self.post.write_text(POST, encoding="utf-8")

    def lint(self, document: str = "") -> dict:
        (self.root / ".plainspoken" / "config.toml").write_text(f"[document]\n{document}\n" if document else "",
                                                                 encoding="utf-8")
        return run_lint(self.post, config.resolve_profile("default", self.root, {}))

    def test_prose_keys_nothing_reads_are_named(self):
        lint = self.lint()
        self.assertEqual(lint["unread_frontmatter_keys"], ["tldr", "note"])  # slug is one word; faqs isn't a string
        self.assertIn("  not read: tldr, note (frontmatter prose;", summarise(lint, notices=True))
        self.assertNotIn("not read:", summarise(lint))  # the lint-watch hook's text never carries it

    def test_read_or_ignored_keys_are_not_named(self):
        lint = self.lint('visible_frontmatter_keys = ["title", "tldr"]\nignored_frontmatter_keys = ["note"]')
        self.assertEqual(lint["unread_frontmatter_keys"], [])
        self.assertNotIn("not read:", summarise(lint, notices=True))

    def test_the_notice_never_changes_a_finding_or_a_status(self):
        named, ignored = self.lint(), self.lint('ignored_frontmatter_keys = ["tldr", "note"]')
        self.assertEqual(named["findings"], ignored["findings"])
        self.assertEqual(lint_status(named), lint_status(ignored))
        self.assertEqual(named["profile_sha256"], ignored["profile_sha256"])

    def test_check_prints_it(self):
        (self.root / ".plainspoken" / "config.toml").write_text("", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env["PYTHONPATH"] = str(REPO / "lib")
        r = subprocess.run([sys.executable, "-m", "plainspoken", "check", "post.md", "--profile", "default",
                            "--no-save", "--no-record"], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not read: tldr, note", r.stdout)
        r = subprocess.run([sys.executable, "-m", "plainspoken", "check", "post.md", "--profile", "default",
                            "--no-save", "--no-record", "--json"], cwd=self.root, env=env, capture_output=True,
                           text=True)
        self.assertEqual(json.loads(r.stdout)["unread_frontmatter_keys"], ["tldr", "note"])


if __name__ == "__main__":
    unittest.main()
