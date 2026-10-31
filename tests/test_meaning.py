"""meaning: the marker counts and the sentence diff behind `meaning-diff` (#147).

The word lists are `data/meaning.toml` (v11 of the #147 research prototype). Fixtures in `tests/fixtures/meaning/`:
the issue's reproduction (`issue-*.md`) and the research's hand-written style and meaning pairs."""
import tomllib
import unittest
from pathlib import Path

from plainspoken import meaning

FIX = Path(__file__).resolve().parent / "fixtures" / "meaning"


def keys(sentence: str) -> set:
    """The marker keys of `sentence`, without the context keys the diff uses."""
    return {k for k, n in meaning.markers(sentence, meaning.load_lexicon()).items()
            if n and not k[0].startswith("negctx")}


class Markers(unittest.TestCase):
    def test_contractions_split(self):
        self.assertEqual(keys("I won't"), {("neg", "negation"), ("commit", "i will")})
        self.assertEqual(keys("we'd love to"), set())
        self.assertEqual(keys("we can't"), {("neg", "negation")})  # can isn't a commitment modal

    def test_curly_apostrophes_count(self):
        lex = meaning.load_lexicon()
        self.assertEqual(meaning.markers("It isn’t included.", lex), meaning.markers("It isn't included.", lex))
        self.assertEqual(keys("We’ll show you around"), {("commit", "we will")})

    def test_frames_never_count(self):
        for s in ("This isn't just a cafe.", "we can't wait!", "please do not hesitate"):
            self.assertNotIn(("neg", "negation"), keys(s), s)
        self.assertEqual(keys("a must-see session"), set())
        self.assertEqual(keys("everything our community has to offer"), set())

    def test_extra_needs_a_price(self):
        self.assertEqual(keys("the extra time"), set())
        self.assertIn(("excl", "extra"), keys("travel is extra at $90 an hour"))

    def test_inclusion_needs_a_price(self):
        self.assertEqual(keys("Her talk covers farm visits"), set())
        self.assertEqual(keys("$300 a month, and that covers your ad spend"), {("incl", "covers")})

    def test_before_a_duration_is_not_a_condition(self):
        self.assertEqual(keys("After 18 months of work"), set())
        self.assertEqual(keys("before any job begins"), {("cond", "before")})
        self.assertEqual(keys("the week before."), set())  # the end of the clause: a time

    def test_tax_exclusion(self):
        self.assertEqual(keys("$1,200 plus GST"), {("excl", "plus GST/fees")})

    def test_first_person_commitment_only(self):
        self.assertEqual(keys("The run will be on 22 June"), set())
        self.assertEqual(keys("We'll show you around"), {("commit", "we will")})
        self.assertEqual(keys("I really must ask"), {("commit", "i must"), ("oblig", "must")})  # one adverb between

    def test_negation_context(self):
        lex = meaning.load_lexicon()
        self.assertEqual(meaning.markers("It isn't included in the fee.", lex)[("negctx", "negation")], 1)
        self.assertEqual(meaning.markers("The sky is not green today.", lex)[("negctx", "negation")], 0)
        self.assertEqual(meaning.markers("Come without a coat.", lex)[("negctx", "negation")], 1)  # without: always

    def test_lexicon_is_the_shipped_file(self):
        raw = tomllib.loads(meaning.DATA_PATH.read_text(encoding="utf-8"))
        lex = meaning.load_lexicon()
        self.assertEqual(raw["version"], 1)
        self.assertEqual(set(raw["negations"]), set(lex.negations))
        self.assertEqual(len(meaning.lexicon_sha256()), 64)


def _flat(changes: list[dict]) -> list[tuple[str, str, list[str]]]:
    return [(i["class"], i["change"], i["words"]) for c in changes for i in c["items"]]


def _pairs(name: str) -> list[dict]:
    return tomllib.loads((FIX / name).read_text(encoding="utf-8"))["pair"]


class Diff(unittest.TestCase):
    def read(self, name: str) -> str:
        return (FIX / name).read_text(encoding="utf-8")

    def test_issue_reproduction(self):
        changes = meaning.diff(self.read("issue-src.md"), self.read("issue-rw.md"))
        self.assertEqual([c["id"] for c in changes], ["M1", "M2", "M3"])
        joined, cut, promise = changes
        self.assertEqual(_flat([joined]), [("inclusion", "added", ["covers"])])
        self.assertEqual((joined["line"], joined["before"]), (3, "After that, management is $300 a month."))
        self.assertEqual(_flat([cut]), [("exclusion", "dropped", ["separate"]), ("negation", "dropped", ["isn't"])])
        self.assertEqual((cut["line"], cut["after"]), (0, ""))
        self.assertIn("isn't included", cut["before"])
        self.assertEqual(_flat([promise]), [("negation", "dropped", ["won't", "without"])])
        self.assertEqual(promise["after"], "I'll make the changes as I go.")

    def test_pure_join_lists_nothing(self):
        self.assertEqual(meaning.diff(self.read("issue-src.md"), self.read("issue-join.md")), [])

    def test_dropped_number_listed_reordered_not(self):
        self.assertEqual(_flat(meaning.diff(self.read("issue-src.md"), self.read("issue-drop.md"))),
                         [("number", "dropped", ["$300"])])
        self.assertEqual(meaning.diff(self.read("issue-src.md"), self.read("issue-reorder.md")), [])

    def test_moved_word_is_not_a_change(self):
        self.assertEqual(meaning.diff("Entry is free. There are 40 stalls.",
                                      "There are 40 stalls, and entry is free."), [])

    def test_qualifier_dropped(self):
        self.assertEqual(_flat(meaning.diff("I have worked with over 22 years of clients.",
                                            "I have worked for 22 years with clients.")),
                         [("qualifier", "dropped", ["over 22"])])

    def test_derived_and_counted_numbers_not_added(self):
        for before, after in (("We sorted 151 of 212 items.", "We sorted about 150 items."),
                              ("Founded by sisters Ana and Ruth Silva.", "Founded by two sisters, Ana and Ruth Silva.")):
            self.assertFalse([x for x in _flat(meaning.diff(before, after)) if x[:2] == ("number", "added")],
                             (before, after))

    def test_new_number_listed(self):
        self.assertEqual(_flat(meaning.diff("The run is on Sunday.", "The run is on Sunday at 7am.")),
                         [("number", "added", ["7"])])

    def test_style_fixtures_list_nothing(self):
        for pair in _pairs("style.toml"):
            with self.subTest(pair["id"]):
                self.assertEqual(meaning.diff(pair["before"], pair["after"]), [], pair["kind"])

    def test_change_fixtures_are_caught(self):
        for pair in _pairs("changes.toml"):
            with self.subTest(pair["id"]):
                classes = {x[0] for x in _flat(meaning.diff(pair["before"], pair["after"]))}
                self.assertIn(pair["class"], classes, pair["kind"])

    def test_code_and_frontmatter_ignored(self):
        before = ("---\ntitle: I won't change it\n---\n\nPlain words here.\n\n```\nI won't run it.\n```\n\n"
                  "<!-- I won't keep\nthis note -->\nThe end.\n")
        after = before.replace("title: I won't", "title: I will").replace("```\nI won't", "```\nI will").replace(
            "<!-- I won't", "<!-- I will")
        self.assertNotEqual(before, after)
        self.assertEqual(meaning.diff(before, after), [])

    def test_line_is_the_after_texts(self):
        (c,) = meaning.diff("# T\n\nIntro.\n\nIt isn't included in the fee.\n",
                            "# T\n\nNew first line.\n\nIntro.\n\nIt's included in the fee.\n")
        self.assertEqual(c["line"], 7)

    def test_everything_cut(self):
        changes = meaning.diff(self.read("issue-src.md"), "")
        self.assertTrue(changes)
        self.assertTrue(all(c["line"] == 0 and c["after"] == "" for c in changes))
        flat = _flat(changes)
        self.assertEqual(len(flat), len({x[:2] for x in flat}))  # each class listed once per change
        self.assertIn(("number", "dropped", ["$300"]), flat)
        self.assertIn(("exclusion", "dropped", ["separate"]), flat)

    def test_unchanged_text_lists_nothing(self):
        text = self.read("issue-src.md")
        self.assertEqual(meaning.diff(text, text), [])


if __name__ == "__main__":
    unittest.main()
