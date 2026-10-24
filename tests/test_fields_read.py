"""#110: the lint report says which fields it read (body plus the profile's visible frontmatter keys present in the
file), so a caption or alt text left out of scope is visible."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken import profile as _profile
from plainspoken.report import run_lint, summarise

REPO = Path(__file__).resolve().parents[1]
POST = ('---\ntitle: "Friday update"\ndescription: "What changed this week."\n'
        'caption: "We delve into a robust tapestry."\nalt: "A seamless paradigm on a desk."\n---\n\n'
        "I fixed the login bug on Friday.\n")


class FieldsRead(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.post = self.tmp / "post.md"
        self.post.write_text(POST, encoding="utf-8")

    def _profile(self, keys):
        text = (REPO / "data" / "profiles" / "default.toml").read_text(encoding="utf-8")
        text = text.replace('name = "default"', 'name = "multi"').replace(
            'visible_frontmatter_keys = ["title", "description"]', f"visible_frontmatter_keys = {json.dumps(keys)}")
        path = self.tmp / "multi.toml"
        path.write_text(text, encoding="utf-8")
        return _profile.load(path)

    def test_default_profile_reads_body_title_description_only(self):
        lint = run_lint(self.post, _profile.default())
        self.assertEqual(lint["fields_read"], ["body", "title", "description"])
        self.assertFalse([f for f in lint["findings"] if f["rule"] == "2"], lint["findings"])

    def test_listed_keys_are_read_and_their_words_flagged(self):
        lint = run_lint(self.post, self._profile(["title", "description", "caption", "alt"]))
        self.assertEqual(lint["fields_read"], ["body", "title", "description", "caption", "alt"])
        lines = {f["line"] for f in lint["findings"] if f["rule"] == "2"}
        self.assertTrue({4, 5} <= lines, lint["findings"])  # L4 caption, L5 alt

    def test_a_listed_key_missing_from_the_file_is_not_read(self):
        lint = run_lint(self.post, self._profile(["title", "subtitle"]))
        self.assertEqual(lint["fields_read"], ["body", "title"])

    def test_summary_names_the_fields_read(self):
        text = summarise(run_lint(self.post, _profile.default()))
        self.assertIn("read: body, title, description", text)

    def _cli(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "PLAINSPOKEN_"))}
        env["PYTHONPATH"] = str(REPO / "lib")
        return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=self.tmp, env=env,
                              capture_output=True, text=True)

    def test_saved_lint_json_carries_fields_read(self):
        out = self.tmp / "reports" / "post.lint.json"
        r = self._cli("check", str(self.post), "--out", str(out), "--profile", "default")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["fields_read"], ["body", "title", "description"])

    def test_older_lint_without_fields_read_still_works(self):
        """The field is additive: a lint from before #110 summarises without a `read:` line, and judge-input and
        merge still accept a saved lint.json that lacks it."""
        old = run_lint(self.post, _profile.default())
        del old["fields_read"]
        text = summarise(old)
        self.assertNotIn("read:", text)
        self.assertTrue(text.startswith("anti-AI lint · post.md · default · article · "), text)

        self.assertEqual(self._cli("check", "post.md", "--profile", "default").returncode, 0)  # a clean draft
        saved = next((self.tmp / ".plainspoken" / "reports").glob("post-*.lint.json"))
        data = json.loads(saved.read_text(encoding="utf-8"))
        del data["fields_read"]
        saved.write_text(json.dumps(data), encoding="utf-8")
        ji = self._cli("judge-input", "post.md", "--profile", "default")
        self.assertEqual(ji.returncode, 0, ji.stderr)
        self.assertEqual([json.loads(x)["group"] for x in ji.stdout.splitlines()], ["J1", "J2", "J3", "J4"])
        merged = self._cli("merge", "post.md", "--profile", "default")
        self.assertEqual(merged.returncode, 1, merged.stderr)  # INCOMPLETE: no judge files yet
        self.assertIn("judge file missing", merged.stdout)
        self.assertNotIn("lint report", merged.stdout)  # the old lint was read, not rejected as malformed
        self.assertNotIn("fields_read", json.loads(saved.read_text(encoding="utf-8")))  # and not re-linted over


if __name__ == "__main__":
    unittest.main()
