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
        self.assertEqual((d.name, d.locale, d.flags, d.extra_bans), ("default", "en-AU", frozenset(), ()))
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
