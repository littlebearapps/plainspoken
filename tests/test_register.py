import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken import profile as P
from plainspoken import register

REPO = Path(__file__).resolve().parents[1]
FULL = REPO / "tests" / "fixtures" / "profiles" / "voice_full.toml"
RUN = REPO / "lib" / "run.py"


def cli(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    return subprocess.run([sys.executable, str(RUN), *args], capture_output=True, text=True, env=env,
                          cwd=tempfile.gettempdir())


class Items(unittest.TestCase):
    def test_items_load_with_unique_ids(self):
        ids = [i["id"] for i in register.load_items()]
        self.assertEqual(ids, [f"R{n}" for n in range(1, 14)])

    def test_kind_filter(self):
        outreach = {i["id"] for i in register.checklist("outreach", P.default())}
        post = {i["id"] for i in register.checklist("post", P.default())}
        self.assertIn("R7", outreach)
        self.assertNotIn("R7", post)
        self.assertNotIn("R6", post)

    def test_pronoun_rule_follows_the_profile(self):
        r4 = next(i for i in register.checklist("email", P.default()) if i["id"] == "R4")
        self.assertIn("we, our, us", r4["flag_when"])

    def test_register_fills_formality(self):
        r5 = next(i for i in register.checklist("email", P.load(FULL), "email") if i["id"] == "R5")
        self.assertIn("casual-professional", r5["ask"])

    def test_placeholders_all_filled(self):
        for kind in register.KINDS:
            for item in register.checklist(kind, P.load(FULL)):
                self.assertNotIn("{", item["ask"] + item["flag_when"], item["id"])

    def test_unknown_register(self):
        with self.assertRaises(ValueError) as cm:
            register.checklist("email", P.load(FULL), "linkedin")
        self.assertIn("no register 'linkedin'", str(cm.exception))

    def test_bad_data_names_the_item(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        bad = tmp / "c.toml"
        bad.write_text('version = 1\n[[items]]\nid = "R1"\ntitle = "t"\nask = "a"\nflag_when = "f"\n'
                       'applies_to = ["telegram"]\n', encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            register.load_items(bad)
        self.assertIn("R1", str(cm.exception))
        self.assertIn("applies_to", str(cm.exception))

    def bad_items(self, body: str) -> str:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        bad = tmp / "c.toml"
        bad.write_text('version = 1\n[[items]]\nid = "R1"\ntitle = "t"\napplies_to = ["email"]\n' + body,
                       encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            register.load_items(bad)
        self.assertNotIn("KeyError", str(cm.exception))
        self.assertIn("'R1'", str(cm.exception))
        return str(cm.exception)

    def test_unknown_placeholder_names_the_item(self):
        self.assertIn("{nope}", self.bad_items('ask = "Fits {nope}?"\nflag_when = "f"\n'))
        self.assertIn("flag_when", self.bad_items('ask = "a"\nflag_when = "an open { brace"\n'))

    def test_by_pronoun_must_be_a_table(self):
        msg = self.bad_items('ask = "a"\nflag_when = "{pronoun_rule}"\nby_pronoun = "I"\n')
        self.assertIn("by_pronoun", msg)
        msg = self.bad_items('ask = "a"\nflag_when = "f"\nby_pronoun = ["I"]\n')
        self.assertIn("by_pronoun", msg)

    def test_by_pronoun_values_are_strings(self):
        msg = self.bad_items('ask = "a"\nflag_when = "{pronoun_rule}"\n'
                             '[items.by_pronoun]\nI = "x"\nwe = 2\neither = "z"\n')
        self.assertIn("by_pronoun", msg)

    def test_missing_by_pronoun(self):
        self.assertIn("by_pronoun must cover", self.bad_items('ask = "a"\nflag_when = "{pronoun_rule}"\n'))
        self.assertIn("by_pronoun must cover", self.bad_items('ask = "Is it {pronoun_rule}?"\nflag_when = "f"\n'))

    def test_duplicate_id(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        bad = tmp / "c.toml"
        one = '[[items]]\nid = "R1"\ntitle = "t"\nask = "a"\nflag_when = "f"\napplies_to = ["email"]\n'
        bad.write_text("version = 1\n" + one + one, encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            register.load_items(bad)
        self.assertIn("item 'R1': missing or duplicate id", str(cm.exception))


def _profile(test: unittest.TestCase, pronoun: str, registers: str = "") -> P.Profile:
    tmp = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    f = tmp / "p.toml"
    f.write_text(f'[profile]\nname = "p"\n[identity]\npronoun = "{pronoun}"\n{registers}', encoding="utf-8")
    return P.load(f)


def _r4(prof: P.Profile, register_name: str | None = None) -> str:
    return next(i for i in register.checklist("email", prof, register_name) if i["id"] == "R4")["flag_when"]


class Pronouns(unittest.TestCase):
    def test_we_rule(self):
        self.assertIn("a lone I stands in for a team's work", _r4(_profile(self, "we")))

    def test_either_rule(self):
        self.assertIn("the pronoun shifts within one message", _r4(_profile(self, "either")))

    def test_register_pronoun_overrides_the_profile(self):
        prof = _profile(self, "I", '[[registers]]\nname = "team"\npronoun = "we"\n'
                                   '[[registers]]\nname = "plain"\n')
        self.assertIn("we, our, us", _r4(prof))
        self.assertIn("a lone I stands in", _r4(prof, "team"))
        self.assertIn("we, our, us", _r4(prof, "plain"))  # a register without a pronoun keeps the profile's


class Cli(unittest.TestCase):
    def test_prints_items(self):
        r = cli("register-checklist", "--kind", "outreach", "--profile", "default")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("R7 First contact:", r.stdout)

    def test_unknown_kind_exit_2_one_line(self):
        r = cli("register-checklist", "--kind", "telegram", "--profile", "default")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertTrue(r.stderr.startswith("plainspoken: "))

    def test_unknown_register_exit_2_one_line(self):
        r = cli("register-checklist", "--kind", "email", "--register", "x", "--profile", str(FULL))
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertTrue(r.stderr.startswith("plainspoken: no register 'x' in profile "), r.stderr)
        self.assertEqual(r.stdout, "")

    def test_register_success(self):
        r = cli("register-checklist", "--kind", "email", "--register", "email", "--profile", str(FULL))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("R5 Formality: Does the tone fit the register (casual-professional)?", r.stdout)
