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


if __name__ == "__main__":
    unittest.main()
