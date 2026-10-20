import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from plainspoken import profile as P
from plainspoken import voice

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures"
FULL = FIX / "profiles" / "voice_full.toml"
SAMPLES = [FIX / "voice" / "sample-a.md", FIX / "voice" / "sample-b.md"]
RUN = REPO / "lib" / "run.py"


def cli(*args, cwd=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    return subprocess.run([sys.executable, str(RUN), *args], capture_output=True, text=True, env=env,
                          cwd=cwd or tempfile.gettempdir())


class Schema(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, body: str) -> Path:
        p = self.tmp / "p.toml"
        p.write_text('[profile]\nname = "p"\n' + body, encoding="utf-8")
        return p

    def assertRejected(self, body: str, *needles: str):
        with self.assertRaises(P.ProfileError) as cm:
            P.load(self.write(body))
        for n in needles:
            self.assertIn(n, str(cm.exception))

    def test_default_profile_has_reader_and_pronoun(self):
        d = P.default()
        self.assertEqual(d.pronoun, "I")
        self.assertTrue(d.reader_persona)
        self.assertEqual(d.comprehension_floor, 7)

    def test_full_voice_profile_loads(self):
        p = P.load(FULL)
        self.assertEqual([a.id for a in p.anchors], ["opening-1", "explainer-1"])
        self.assertEqual(p.registers[0].name, "email")
        self.assertEqual(p.voice["voice"]["tone"]["formal_casual"], 0.7)
        self.assertEqual(p.voice["lexicon"]["starters"], ["Right,"])

    def test_unknown_voice_key_names_file_and_key(self):
        self.assertRejected("[reader]\npersonna = \"x\"\n", "p.toml", "[reader] personna")

    def test_bad_pronoun(self):
        self.assertRejected('[identity]\npronoun = "they"\n', "[identity] pronoun")

    def test_tone_out_of_range(self):
        self.assertRejected("[voice.tone]\nformal_casual = 1.5\n", "formal_casual")

    def test_floor_out_of_range(self):
        self.assertRejected("[reader]\ncomprehension_floor = 13\n", "comprehension_floor")

    def test_bad_blend(self):
        self.assertRejected('[blends]\narticle = "listicle"\n', "[blends] article")

    def test_anchor_needs_exactly_one_of_text_or_path(self):
        self.assertRejected('[[anchors]]\nid = "a"\ntags = ["x"]\n', "anchors", "text or path")
        self.assertRejected('[[anchors]]\nid = "a"\ntags = ["x"]\ntext = "t"\npath = "f.md"\n', "text or path")

    def test_anchor_empty_text_or_path(self):
        self.assertRejected('[[anchors]]\nid = "a"\ntags = ["x"]\ntext = ""\n', "empty")
        self.assertRejected('[[anchors]]\nid = "a"\ntags = ["x"]\npath = ""\n', "empty")
        self.assertRejected('[[anchors]]\nid = "a"\ntags = ["x"]\ntext = "  \\n "\n', "empty")

    def test_anchor_absolute_path(self):
        self.assertRejected('[[anchors]]\nid = "a"\ntags = ["x"]\npath = "/etc/hosts"\n', "relative")

    def test_glossary_must_be_relative(self):
        for bad in ("/etc/hosts", "~/glossary.md", "C:\\\\glossary.md", "\\\\server\\\\g.md"):
            self.assertRejected(f'[reader]\nglossary = "{bad}"\n', "[reader] glossary", "relative")
        self.assertRejected('[reader]\nglossary = ""\n', "[reader] glossary")
        p = P.load(self.write('[reader]\nglossary = "../shared/glossary.md"\n'))
        self.assertEqual(p.voice["reader"]["glossary"], "../shared/glossary.md")

    def test_duplicate_anchor_ids(self):
        one = '[[anchors]]\nid = "a"\ntags = ["x"]\ntext = "t"\n'
        self.assertRejected(one + one, "duplicate", "'a'")

    def test_anchor_needs_tags(self):
        self.assertRejected('[[anchors]]\nid = "a"\ntags = []\ntext = "t"\n', "tags")

    def test_register_requires_name(self):
        self.assertRejected('[[registers]]\nformality = "x"\n', "registers", "name")

    def test_bad_line_range(self):
        self.assertRejected('[[anchors]]\nid = "a"\ntags = ["x"]\npath = "f.md"\nlines = [5, 2]\n', "lines")

    def test_missing_anchor_file_does_not_break_loading(self):
        p = P.load(self.write('[[anchors]]\nid = "gone"\ntags = ["opening"]\npath = "nope.md"\n'))
        self.assertEqual(p.anchors[0].id, "gone")


class Anchors(unittest.TestCase):
    def test_tag_filter_and_limit(self):
        got = voice.anchors_for(P.load(FULL), "opening", 3)
        self.assertEqual([(a.id, t) for a, t in got],
                         [("opening-1", "The wheel came in with a wobble you could see from the door.")])

    def test_lines_range_slices_the_file(self):
        (a, text), = voice.anchors_for(P.load(FULL), "explainer", 3)
        expected = "\n".join(SAMPLES[0].read_text(encoding="utf-8").splitlines()[0:2])
        self.assertEqual(text, expected)

    def test_no_tag_means_all_in_order(self):
        self.assertEqual([a.id for a, _ in voice.anchors_for(P.load(FULL), None, 10)], ["opening-1", "explainer-1"])

    def test_missing_file_names_the_anchor(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        f = tmp / "p.toml"
        f.write_text('[profile]\nname = "p"\n[[anchors]]\nid = "gone"\ntags = ["o"]\npath = "nope.md"\n', encoding="utf-8")
        with self.assertRaises(voice.VoiceError) as cm:
            voice.anchors_for(P.load(f), "o", 3)
        self.assertIn("'gone'", str(cm.exception))

    def test_cli_missing_file_exit_2_one_line(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        f = tmp / "p.toml"
        f.write_text('[profile]\nname = "p"\n[[anchors]]\nid = "gone"\ntags = ["o"]\npath = "nope.md"\n', encoding="utf-8")
        r = cli("anchors", "--tag", "o", "--profile", str(f))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertTrue(r.stderr.startswith("plainspoken: "))
        self.assertIn("'gone'", r.stderr)

    def test_cli_skip_missing_keeps_the_readable_ones(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        f = tmp / "p.toml"
        f.write_text('[profile]\nname = "p"\n'
                     '[[anchors]]\nid = "gone"\ntags = ["o"]\npath = "nope.md"\n'
                     '[[anchors]]\nid = "here"\ntags = ["o"]\ntext = "Still here."\n', encoding="utf-8")
        r = cli("anchors", "--tag", "o", "--skip-missing", "--profile", str(f))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--- anchor here (o)", r.stdout)
        self.assertIn("(skipped anchor 'gone':", r.stdout)

    def test_cli_none_tagged_exit_0(self):
        r = cli("anchors", "--tag", "closing", "--profile", str(FULL))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(no anchors tagged 'closing'", r.stdout)

    def test_cli_prints_header_and_text(self):
        r = cli("anchors", "--tag", "opening", "--profile", str(FULL))
        self.assertIn("--- anchor opening-1 (opening) from shop newsletter, March", r.stdout)
        self.assertIn("wobble you could see from the door", r.stdout)


class AnchorConfinement(unittest.TestCase):
    """An anchor file must be a regular file inside the profile's project, and not too big."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.proj = self.tmp / "proj"
        (self.proj / ".git").mkdir(parents=True)
        (self.proj / ".plainspoken" / "profiles").mkdir(parents=True)
        (self.proj / "voice").mkdir()
        (self.proj / "voice" / "ok.md").write_text("Inside the project.\n", encoding="utf-8")
        (self.tmp / "secret.md").write_text("outside the project\n", encoding="utf-8")

    def profile(self, path: str) -> Path:
        f = self.proj / ".plainspoken" / "profiles" / "p.toml"
        f.write_text('[profile]\nname = "p"\n'
                     f'[[anchors]]\nid = "bad"\ntags = ["o"]\npath = {json.dumps(path)}\n'
                     '[[anchors]]\nid = "good"\ntags = ["o"]\npath = "../../voice/ok.md"\n', encoding="utf-8")
        return f

    def assertRefused(self, path: str, needle: str):
        f = self.profile(path)
        with self.assertRaises(voice.VoiceError) as cm:
            voice.anchors_for(P.load(f), "o", 3)
        self.assertIn("'bad'", str(cm.exception))
        self.assertIn(needle, str(cm.exception))
        found, skipped = voice.anchors_lenient(P.load(f), "o", 3)
        self.assertEqual([a.id for a, _ in found], ["good"])
        self.assertEqual(len(skipped), 1)
        self.assertIn("'bad'", skipped[0])

    def test_parent_path_inside_the_project_still_works(self):
        got = voice.anchors_for(P.load(self.profile("../../voice/ok.md")), "o", 3)
        self.assertEqual([t for _, t in got], ["Inside the project."] * 2)

    def test_path_outside_the_project_refused(self):
        self.assertRefused("../../../secret.md", "outside the project")

    def test_an_ancestor_claude_project_dir_does_not_widen_the_project(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.tmp)}):
            self.assertRefused("../../../secret.md", f"outside the project {self.proj.resolve()}")
        r = subprocess.run([sys.executable, str(RUN), "anchors", "--tag", "o", "--profile",
                            str(self.profile("../../../secret.md"))], capture_output=True, text=True,
                           env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.tmp)}, cwd=self.tmp)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("'bad'", r.stderr)

    def test_no_project_confines_to_the_profile_folder(self):  # fails safe
        loose = self.tmp / "loose"
        (loose / "samples").mkdir(parents=True)
        (loose / "samples" / "s.md").write_text("A sample.\n", encoding="utf-8")
        (loose / "p.toml").write_text('[profile]\nname = "p"\n[[anchors]]\nid = "s"\ntags = ["o"]\n'
                                      'path = "samples/s.md"\n[[anchors]]\nid = "up"\ntags = ["o"]\n'
                                      'path = "../secret.md"\n', encoding="utf-8")
        found, skipped = voice.anchors_lenient(P.load(loose / "p.toml"), "o", 3)
        self.assertEqual([a.id for a, _ in found], ["s"])
        self.assertEqual(len(skipped), 1)
        self.assertIn("outside the project", skipped[0])

    def test_symlink_out_of_the_project_refused(self):
        (self.proj / "voice" / "link.md").symlink_to(self.tmp / "secret.md")
        self.assertRefused("../../voice/link.md", "outside the project")

    def test_directory_refused(self):
        self.assertRefused("../../voice", "not a regular file")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs mkfifo")
    def test_fifo_refused_without_blocking(self):
        os.mkfifo(self.proj / "voice" / "pipe.md")
        self.assertRefused("../../voice/pipe.md", "not a regular file")

    def test_too_big_refused(self):
        (self.proj / "voice" / "big.md").write_bytes(b"a" * (voice.MAX_ANCHOR_BYTES + 1))
        self.assertRefused("../../voice/big.md", "too big")

    def test_nul_byte_names_the_anchor(self):
        self.assertEqual(P.load(self.profile("a\x00b.md")).anchors[0].path, "a\x00b.md")  # TOML allows it
        self.assertRefused("a\x00b.md", "can't read")

    def test_cli_outside_root_exit_2_and_skip_missing(self):
        f = self.profile("../../../secret.md")
        r = cli("anchors", "--tag", "o", "--profile", str(f))
        self.assertEqual(r.returncode, 2)
        self.assertIn("'bad'", r.stderr)
        self.assertNotIn("outside the project\n", r.stdout)
        r = cli("anchors", "--tag", "o", "--skip-missing", "--profile", str(f))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(skipped anchor 'bad':", r.stdout)
        self.assertIn("--- anchor good (o)", r.stdout)

    def test_cli_nul_byte_with_skip_missing(self):
        r = cli("anchors", "--tag", "o", "--skip-missing", "--profile", str(self.profile("a\x00b.md")))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(skipped anchor 'bad':", r.stdout)

    def test_cli_limit_below_one_exit_2(self):
        for limit in ("0", "-1"):
            r = cli("anchors", "--limit", limit, "--profile", str(FULL))
            self.assertEqual(r.returncode, 2, limit)
            self.assertEqual(len(r.stderr.strip().splitlines()), 1)
            self.assertTrue(r.stderr.startswith("plainspoken: --limit"))


class Stats(unittest.TestCase):
    def test_fields(self):
        st = voice.stats(SAMPLES)
        for key in ("sentence_mean", "sentence_sd", "burstiness", "long_share", "short_share", "words", "files"):
            self.assertIn(key, st)
        self.assertEqual(st["files"], 2)
        self.assertGreaterEqual(st["words"], 300)

    def test_output_is_a_valid_rhythm_table(self):
        r = cli("voice-stats", *map(str, SAMPLES))
        self.assertEqual(r.returncode, 0, r.stderr)
        rhythm = tomllib.loads(r.stdout)["rhythm"]
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "p.toml").write_text('[profile]\nname = "p"\n' + r.stdout, encoding="utf-8")
        self.assertEqual(P.load(tmp / "p.toml").voice["rhythm"]["sentence_mean"], rhythm["sentence_mean"])

    def test_too_little_text_exit_2(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "s.md").write_text("Short one. Another.\n", encoding="utf-8")
        r = cli("voice-stats", str(tmp / "s.md"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("need 300", r.stderr)

    def test_unreadable_exit_2(self):
        r = cli("voice-stats", "/nonexistent/x.md")
        self.assertEqual((r.returncode, r.stderr.startswith("plainspoken: ")), (2, True))


class Summary(unittest.TestCase):
    def test_profile_command_prints_reader_and_anchor_counts(self):
        r = cli("profile", "--profile", str(FULL))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("writer: A solo bike mechanic who writes about fixing things properly. (pronoun I) · "
                      "reader: a commuter who rides every day", r.stdout)
        self.assertIn("anchors: 2 (body 1, explainer 1, opening 1)", r.stdout)
        self.assertIn("registers: email", r.stdout)

    def test_profile_voice_prints_what_the_skills_need(self):
        r = cli("profile", "--voice", "--type", "email", "--profile", str(FULL))
        self.assertEqual(r.returncode, 0, r.stderr)
        for needle in ("writer: A solo bike mechanic", "(pronoun I)", "Name the part, the tool and the number.",
                       "Blunt take first", "formal_casual 0.7 (Talks like the shop counter", "sentence mean 15.5",
                       'starters "Right,"', "formatting (email): Plain text. One ask.",
                       "Opening with a dictionary definition.", "glossary: ", "glossary.md"):
            self.assertIn(needle, r.stdout)
        self.assertNotIn("formatting (article)", r.stdout)

    def test_avoid_topics_are_joined_with_semicolons(self):  # a topic can hold a comma
        prof = P.load(FULL)
        prof.voice.setdefault("avoid", {})["topics"] = ["politics, religion and the like", "competitors by name"]
        lines = voice.voice_lines(prof)
        self.assertIn("avoid topics: politics, religion and the like; competitors by name", lines)
        prof.voice["avoid"]["topics"] = []
        self.assertIn("avoid topics: none", voice.voice_lines(prof))

    def test_profile_voice_without_type_prints_every_blend(self):
        r = cli("profile", "--voice", "--profile", str(FULL))
        self.assertIn("blend (article): answer-first", r.stdout)
        self.assertIn("blend (social): narrative", r.stdout)

    def test_profile_voice_bad_type_exit_2_one_line(self):
        r = cli("profile", "--voice", "--type", "fax", "--profile", str(FULL))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertTrue(r.stderr.startswith("plainspoken: "))
