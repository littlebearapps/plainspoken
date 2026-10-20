import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._skills import REPO, SkillBasics, files, headings

RUN = REPO / "lib" / "run.py"


class AdaptSkill(SkillBasics, unittest.TestCase):
    NAME = "adapt"
    REQUIRED = ("Core rules", "Inputs", "Steps", "Platforms", "Surfaces", "Report")
    DRAFTING = True
    REFERENCES = ("platforms.md", "framing-by-surface.md", "claude-code.md")

    def test_pasted_text_content_type_and_anchors(self):
        self.assertIn("pasted", self.text.lower())
        self.assertRegex(self.text, r"newsletter or a web page → `article`")
        self.assertRegex(self.text, r"(?:run\.py|RUN) anchors --tag \S+ --limit \d --skip-missing")
        self.assertRegex(self.text, r"(?:run\.py|RUN) profile --voice --type")

    def test_drafts_only(self):
        core = self.text.split("## Inputs", 1)[0].lower()
        for needle in ("drafts only", "never post", "rewriting, not reformatting", "no new facts"):
            self.assertIn(needle, core)
        self.assertIn(".plainspoken/drafts/", self.text)
        self.assertIn("Write(.plainspoken/drafts/*)", self.fm["allowed-tools"])

    def test_checks_and_measures_each_variant(self):
        self.assertRegex(self.text, r"(?:run\.py|RUN) check .*--content-type social")
        self.assertRegex(self.text, r"(?:run\.py|RUN) length")

    def test_platform_limits_are_dated_and_sourced(self):
        text = (REPO / "skills" / "adapt" / "references" / "platforms.md").read_text(encoding="utf-8")
        sections = text.split("\n## ")[1:]
        self.assertGreaterEqual(len(sections), 5)
        for s in sections:
            name = s.splitlines()[0]
            self.assertRegex(s, r"Checked: (20\d\d-\d\d-\d\d, https://\S+|unconfirmed)", name)

    def test_every_surface_is_in_the_chooser_and_the_skill(self):
        refs = (REPO / "skills" / "adapt" / "references" / "framing-by-surface.md").read_text(encoding="utf-8")
        surfaces = [h for h in headings(refs) if h != "Choosing the surface"]
        chooser = refs.split("## Choosing the surface", 1)[1].split("\n## ", 1)[0]
        listed = self.text.split("## Surfaces", 1)[1].split("\n## ", 1)[0].lower()
        bullet = self.text.split("- For a web page:", 1)[1].split("\n- ", 1)[0].split("\n## ", 1)[0]
        inputs = " ".join(bullet.split()).lower()
        for s in surfaces:
            self.assertRegex(chooser, rf"\? {re.escape(s.rstrip('s'))}s?\.", s)
            self.assertIn(s.lower(), listed, s)
            self.assertIn(s.lower().rstrip("s"), inputs, s)

    def test_platform_notes_say_which_lines_are_sourced(self):
        intro = (REPO / "skills" / "adapt" / "references" / "platforms.md").read_text(encoding="utf-8").split("## ")[0]
        self.assertIn("general guidance", " ".join(intro.split()))

    def test_no_posting_api_material(self):  # every file of the skill, not platforms.md alone
        paths = files(self.NAME)
        self.assertGreaterEqual(len(paths), 4)
        for f in paths:
            text = f.read_text(encoding="utf-8").lower()
            for needle in ("curl", "oauth", "api key", "access token", "bearer", "webhook"):
                self.assertNotIn(needle, text, f"{f.name}: {needle}")


class LengthCommand(unittest.TestCase):
    def run_cli(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        return subprocess.run([sys.executable, str(RUN), *args], capture_output=True, text=True, env=env)

    def test_counts(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "v.md"
            f.write_text("Two words.\nAnd three more.\n", encoding="utf-8")
            r = self.run_cli("length", str(f))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "chars 26 · words 5 · lines 2")

    def test_chars_are_graphemes(self):  # a flag, an accented letter or a family emoji is one
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "v.md"
            f.write_text("G'day \U0001F1E6\U0001F1FA cafe\u0301 \U0001F468\u200d\U0001F469\u200d\U0001F467\n",
                         encoding="utf-8")
            r = self.run_cli("length", str(f))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "chars 14 · words 4 · lines 1")

    def test_unreadable_exit_2(self):
        r = self.run_cli("length", "/nonexistent/v.md")
        self.assertEqual((r.returncode, r.stderr.startswith("plainspoken: ")), (2, True))
