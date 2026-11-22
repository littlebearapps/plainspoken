import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken import profile as P

FIX = Path(__file__).parent / "fixtures" / "profiles"


def write(tmp: Path, text: str, name: str = "p.toml") -> Path:
    path = tmp / name
    path.write_text(text, encoding="utf-8")
    return path


class Loading(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_default_ships_and_is_neutral(self):
        d = P.default()
        self.assertEqual((d.name, d.locale, d.flags, d.extra_bans), ("default", None, frozenset(), ()))
        self.assertEqual(d.visible_frontmatter_keys, ("title", "description"))
        self.assertEqual(len(d.sha256), 64)

    def test_fixtures_load(self):
        self.assertIn("narrative", P.load(FIX / "narrative_like.toml").flags)
        self.assertIn("effortless", P.load(FIX / "consulting_like.toml").extra_bans)
        self.assertEqual(P.load(FIX / "product_like.toml").faq_frontmatter_key, "faqs")

    def test_calibration_notes_resolve_relative_to_profile(self):
        (self.tmp / "notes.md").write_text("Analogies: technical readers need none.\n", encoding="utf-8")
        p = write(self.tmp, '[profile]\nname = "x"\n[judges]\ncalibration_notes = "notes.md"\n')
        self.assertEqual(P.load(p).calibration_notes, str((self.tmp / "notes.md").resolve()))

    def test_editing_calibration_notes_changes_the_profile_hash(self):
        notes = self.tmp / "notes.md"
        notes.write_text("Analogies: none.\n", encoding="utf-8")
        p = write(self.tmp, '[profile]\nname = "x"\n[judges]\ncalibration_notes = "notes.md"\n')
        before = P.load(p).sha256
        notes.write_text("Analogies: allowed.\n", encoding="utf-8")
        self.assertNotEqual(P.load(p).sha256, before)

    def test_name_lookup_searches_given_dirs_first(self):
        own = self.tmp / "profiles"
        own.mkdir()
        write(own, '[profile]\nname = "mine"\n', "mine.toml")
        self.assertEqual(P.load("mine", search=(own,)).name, "mine")
        self.assertEqual(P.load("default", search=(own,)).name, "default")


class FailsClosed(unittest.TestCase):
    """Never fall back silently; name the file and the key."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def assertFails(self, text: str, *needles: str):
        path = write(self.tmp, text)
        with self.assertRaises(P.ProfileError) as cm:
            P.load(path)
        msg = str(cm.exception)
        self.assertIn(str(path), msg)
        for n in needles:
            self.assertIn(n, msg)

    def test_calibration_notes_must_exist(self):
        self.assertFails('[profile]\nname = "x"\n[judges]\ncalibration_notes = "nope.md"\n', "[judges] calibration_notes")

    def test_missing_file(self):
        with self.assertRaises(P.ProfileError) as cm:
            P.load(self.tmp / "nope.toml")
        self.assertIn("nope.toml", str(cm.exception))

    def test_unknown_name(self):
        with self.assertRaises(P.ProfileError) as cm:
            P.load("no-such-profile")
        self.assertIn("no-such-profile", str(cm.exception))

    def test_invalid_toml(self):
        self.assertFails("[profile\nname = 1", "not valid TOML")

    def test_missing_name(self):
        self.assertFails("[profile]\nlocale = \"en-AU\"\n", "[profile] name")

    def test_name_with_trailing_newline_rejected(self):  # re.match + $ allowed "x\\n"
        self.assertFails('[profile]\nname = "x\\n"\n', "[profile] name")

    def test_unknown_section_and_key(self):
        self.assertFails('[profile]\nname = "x"\n[style]\n', "[style]")  # [voice] is a real section since Phase 3
        self.assertFails('[profile]\nname = "x"\nlocal = "en-AU"\n', "[profile] local")

    def test_locale_unset_loads_as_none_and_set_is_kept(self):  # #121: "unset" and "en-AU" stay apart
        self.assertIsNone(P.load(write(self.tmp, '[profile]\nname = "x"\n')).locale)
        self.assertEqual(P.load(write(self.tmp, '[profile]\nname = "x"\nlocale = "en-GB"\n')).locale, "en-GB")

    def test_default_profile_sets_no_locale(self):  # so the plugin option and the config files reach it (#121)
        import tomllib
        raw = tomllib.loads((P.PROFILES_DIR / "default.toml").read_text(encoding="utf-8"))
        self.assertNotIn("locale", raw["profile"])

    def test_unknown_flag_and_locale(self):
        self.assertFails('[profile]\nname = "x"\nflags = ["poetry"]\n', "flags", "poetry")
        self.assertFails('[profile]\nname = "x"\nlocale = "en-NZ"\n', "locale", "en-NZ")

    def test_wrong_types(self):
        self.assertFails('[profile]\nname = "x"\n[lexicon]\nextra_bans = "effortless"\n', "[lexicon] extra_bans")
        self.assertFails('[profile]\nname = "x"\n[thresholds]\nem_dash_max = "three"\n', "[thresholds] em_dash_max")

    def test_non_finite_threshold_rejected(self):  # nan/inf would switch a rule off silently
        for bad in ("nan", "inf", "-inf", "+nan"):
            with self.subTest(bad=bad):
                self.assertFails(f'[profile]\nname = "x"\n[thresholds]\nem_dash_max = {bad}\n',
                                 "[thresholds] em_dash_max", "finite")

    def test_bad_heading_regex(self):
        self.assertFails('[profile]\nname = "x"\n[document]\nlong_sentence_headings = ["("]\n',
                         "[document] long_sentence_headings")

    def test_profile_error_is_value_error(self):
        self.assertTrue(issubclass(P.ProfileError, ValueError))


class ExemptTerms(unittest.TestCase):  # #243: [lexicon] exempt_terms in a profile and in the project config
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".git").mkdir()

    def test_the_key_loads(self):
        p = P.load(write(self.tmp, '[profile]\nname = "p"\n[lexicon]\nexempt_terms = ["Elevate Partners"]\n'))
        self.assertEqual((p.exempt_terms, p.project_exempt_terms), (("Elevate Partners",), ()))
        self.assertEqual(P.load(write(self.tmp, '[profile]\nname = "p"\n')).exempt_terms, ())

    def test_a_bad_type_is_refused_naming_the_key(self):
        for value in ('"Elevate Partners"', "[1]", '[""]', '["  "]'):
            with self.subTest(value=value):
                with self.assertRaises(P.ProfileError) as cm:
                    P.load(write(self.tmp, f'[profile]\nname = "p"\n[lexicon]\nexempt_terms = {value}\n'))
                self.assertIn("[lexicon] exempt_terms", str(cm.exception))

    def test_project_terms_join_the_profile_and_its_hash(self):
        from plainspoken import config
        path = write(self.tmp, '[profile]\nname = "p"\n[lexicon]\nexempt_terms = ["Acme Robust"]\n')
        before = config.resolve_profile(str(path), self.tmp, {})
        self.assertEqual(before.sha256, P.load(path).sha256)  # no project terms: the hash is the file's
        (self.tmp / ".plainspoken").mkdir()
        cfg = self.tmp / ".plainspoken" / "config.toml"
        cfg.write_text('[lexicon]\nexempt_terms = ["Elevate Partners"]\n', encoding="utf-8")
        after = config.resolve_profile(str(path), self.tmp, {})
        self.assertEqual((after.exempt_terms, after.project_exempt_terms), (("Acme Robust",), ("Elevate Partners",)))
        self.assertNotEqual(after.sha256, before.sha256)  # an edit to the project's terms makes reports stale
        cfg.write_text('[lexicon]\nexempt_terms = ["Elevate Partners", "Seamless Co"]\n', encoding="utf-8")
        self.assertNotEqual(config.resolve_profile(str(path), self.tmp, {}).sha256, after.sha256)

    def test_the_project_section_fails_closed(self):
        from plainspoken import config
        (self.tmp / ".plainspoken").mkdir()
        cfg = self.tmp / ".plainspoken" / "config.toml"
        for body, needle in (('[lexicon]\nexempt_terms = "Elevate"\n', "[lexicon] exempt_terms"),
                             ('[lexicon]\nexempt_terms = [""]\n', "[lexicon] exempt_terms"),
                             ('[lexicon]\nextra_bans = ["x"]\n', "unknown key [lexicon] extra_bans")):
            with self.subTest(body=body):
                cfg.write_text(body, encoding="utf-8")
                with self.assertRaises(config.ConfigError) as cm:
                    config.resolve_profile("default", self.tmp, {})
                self.assertIn(needle, str(cm.exception))

    def test_a_check_through_the_cli_uses_both(self):
        import json
        import subprocess
        import sys
        (self.tmp / ".plainspoken").mkdir()
        (self.tmp / ".plainspoken" / "config.toml").write_text('[lexicon]\nexempt_terms = ["Elevate Partners"]\n',
                                                              encoding="utf-8")
        art = self.tmp / "post.md"
        art.write_text("I met Elevate Partners. They said I should elevate your brand.\n", encoding="utf-8")
        run = Path(__file__).resolve().parents[1] / "lib" / "run.py"
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.tmp)}
        out = subprocess.run([sys.executable, str(run), "check", str(art), "--profile", "default", "--json",
                              "--no-record"], capture_output=True, text=True, cwd=self.tmp, env=env)
        lint = json.loads(out.stdout)
        self.assertEqual(sorted(f["severity"] for f in lint["findings"] if f["rule"] == "2"), ["BLOCK", "INFO"])
        stamp = json.loads(subprocess.run([sys.executable, str(run), "profile", "--json", "--profile", "default"],
                                          capture_output=True, text=True, cwd=self.tmp, env=env).stdout)
        self.assertEqual(stamp["profile_sha256"], lint["profile_sha256"])  # the stamps agree, so merge can bind
        self.assertNotEqual(lint["profile_sha256"], P.default().sha256)
