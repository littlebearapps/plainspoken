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
        self.assertTrue([f for f in lint["findings"] if f["rule"] == "2"], lint["findings"])

    def test_a_listed_key_missing_from_the_file_is_not_read(self):
        lint = run_lint(self.post, self._profile(["title", "subtitle"]))
        self.assertEqual(lint["fields_read"], ["body", "title"])

    def test_summary_names_the_fields_read(self):
        text = summarise(run_lint(self.post, _profile.default()))
        self.assertIn("read: body, title, description", text)

    def test_saved_lint_json_carries_fields_read(self):
        out = self.tmp / "reports" / "post.lint.json"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "PLAINSPOKEN_"))}
        env["PYTHONPATH"] = str(REPO / "lib")
        r = subprocess.run([sys.executable, "-m", "plainspoken", "check", str(self.post), "--out", str(out),
                            "--profile", "default"], cwd=self.tmp, env=env, capture_output=True, text=True)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["fields_read"], ["body", "title", "description"])


if __name__ == "__main__":
    unittest.main()
