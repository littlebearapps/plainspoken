import os
import re
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
CHANGELOG = REPO / "data" / "RULESET-CHANGELOG.md"


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


# Register-check items are judged by a model, so there's no deterministic verdict to assert. Every item changed in a
# "## Register checklist change" section of data/RULESET-CHANGELOG.md needs at least one text it should flag and one
# it shouldn't. Each fixture names the words of the item (its ask or flag_when, as rendered) that decide it, and the
# tests below check those words are there and the item reaches the fixture's kind. Every name in them is invented.
FIXTURES = (
    {"item": "R2", "kind": "email", "flags": True, "clause": "as waiting only on more evidence",
     "text": "I can't promise the shop will reach more customers until I've had a proper look at your figures."},
    {"item": "R2", "kind": "email", "flags": False, "clause": "Does it promise only what the writer controls?",
     "text": "I'll rewrite the three service pages by Friday and send you the enquiry count each month, so you can "
             "see whether anything changes."},
    {"item": "R7", "kind": "outreach", "flags": True, "clause": "makes declining awkward",
     "text": "Hi Dana, I run a bookkeeping service nearby. I'd like an hour with you and your treasurer before the "
             "end of the month, and I'd hate for the club to miss out."},
    {"item": "R7", "kind": "outreach", "flags": True, "clause": "stacks stock reassurance",
     "text": "Hi Dana, I noticed the club's fixtures page still lists last season's dates. Happy to help. No cost, "
             "no obligation, no reply needed."},
    {"item": "R7", "kind": "outreach", "flags": True, "clause": "observation → credentials → offer → ask",
     "text": "Hi Dana, I noticed the fixtures page still lists last season's dates. I've built websites for local "
             "clubs for eight years. I offer a fixtures-page update from $150. Could we book a call on Thursday?"},
    {"item": "R7", "kind": "outreach", "flags": True, "clause": "holds back the useful part to get a reply",
     "text": "Hi Dana, I spotted three problems on the club's website that could be turning families away. Reply "
             "and I'll tell you what they are."},
    {"item": "R7", "kind": "outreach", "flags": True, "clause": "asks for more than it gives",
     "text": "Hi Dana, I love what the club does. Could you send me your membership numbers for the last three "
             "years and set up a meeting with the committee?"},
    {"item": "R7", "kind": "outreach", "flags": False, "clause": "one plain",
     "text": "Hi Dana, I'm Sam, a web designer in town. The club's fixtures page still lists last season's dates (I "
             "checked on Monday). Happy to show how I'd update it if that's useful; no worries if not."},
    {"item": "R7", "kind": "outreach", "flags": False, "clause": "or there's no ask",
     "text": "Hi Dana, I'm Sam, a parent in the under-10s. The fixtures page still lists last season's dates when I "
             "checked this morning. Just letting you know."},
    {"item": "R8", "kind": "follow-up", "flags": True, "clause": "holds back the useful part to get a reply",
     "text": "Hi Dana, following my note about the fixtures page, I've now found two more issues. Happy to share "
             "them on a call."},
    {"item": "R8", "kind": "follow-up", "flags": True, "clause": "asks for more than it gives",
     "text": "Hi Dana, a quick follow-up on the fixtures page. Could you send me the committee's contact list and "
             "the website login so I can take a proper look?"},
    {"item": "R8", "kind": "follow-up", "flags": False, "clause": "Does it stand on its own and add something?",
     "text": "Hi Dana, the club's fixtures page now shows this season's dates. The results page still shows last "
             "season's, and it's the same date field to change. Nothing needed from me."},
)


def changed_items() -> set[str]:
    """The item ids named in bold in every "## Register checklist change" section of the ruleset changelog."""
    text = CHANGELOG.read_text(encoding="utf-8")
    ids: set[str] = set()
    for section in re.split(r"(?m)^## ", text)[1:]:
        if section.startswith("Register checklist change ("):
            ids |= set(re.findall(r"\*\*(R\d+)\b", section))
    return ids


def rendered(item_id: str, kind: str) -> dict | None:
    return next((i for i in register.checklist(kind, P.default()) if i["id"] == item_id), None)


class Fixtures(unittest.TestCase):
    def test_this_change_is_recorded(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        self.assertIn("## Register checklist change (2026-10-27; ruleset version unchanged)", text)
        self.assertLessEqual({"R2", "R7", "R8"}, changed_items())

    def test_every_changed_item_has_a_flag_and_a_no_flag_fixture(self):
        for iid in sorted(changed_items()):
            got = {f["flags"] for f in FIXTURES if f["item"] == iid}
            self.assertEqual(got, {True, False}, f"{iid} needs one should-flag and one shouldn't-flag fixture")

    def test_each_fixture_names_words_the_item_has(self):
        for f in FIXTURES:
            item = rendered(f["item"], f["kind"])
            self.assertIsNotNone(item, f"{f['item']} doesn't apply to {f['kind']}")
            self.assertIn(f["clause"], item["ask"] + " " + item["flag_when"], f["item"])

    def test_one_plain_easy_no_line_stays_fine(self):
        r7 = rendered("R7", "outreach")["flag_when"]
        self.assertIn('one plain "no worries if not" is fine', r7)
        self.assertNotIn("has no easy no", r7)  # replaced by the shape test
