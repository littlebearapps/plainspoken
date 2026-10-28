"""owner_asks: a write report that asks the owner to check something its `needs the owner` lines don't list (#75).

The incident report is the round-6 netball run's, as the trace audit quotes it: the engine printed
`needs the owner: none` and the prose still asked the person to check three lines with the club secretary."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lib"))
from plainspoken import owner_asks  # noqa: E402

BLOCK = """Draft: .plainspoken/drafts/netball-rosters.md
check: PASS
claims: PASS
  checker: PASS (0 warnings)
needs the owner: none
words: 295 (body text; headings, tables, code and numbers not counted)
reader-value contract: .plainspoken/reader-value/netball-rosters.reader-value.toml
Reader value (outline): READY (.plainspoken/reader-value/netball-rosters.reader-value.toml); delivery not checked: \
you run /plainspoken:reader-value deliver .plainspoken/drafts/netball-rosters.md
Anchors: none; no anchors: story, opening
For kaizen: none
"""
SHORT = "\nIt's 295 words of body text, not 500: the notes carry about that much, and I didn't pad it.\n"
ASK = ("\nLines that aren't straight from your notes: 'Thanks, Kath and Ollie.' / 'If you'd rather have paper, "
       "that's fine too.' / 'That's a lot of people to reach in a hurry.' Each is a small bit of warmth in Jo's "
       "voice, so check Jo is happy with them. Cut any that don't fit.\n")


def listed(n: int) -> str:
    items = "".join(f"  N-C{i}: a line held for the owner (blocking)\n" for i in range(1, n + 1))
    return BLOCK.replace("needs the owner: none\n", f"needs the owner: {n}\n{items}")


class Incident(unittest.TestCase):
    def test_the_round_6_report_is_caught(self):
        self.assertEqual(owner_asks.unlisted(BLOCK + SHORT + ASK),
                         ["Each is a small bit of warmth in Jo's voice, so check Jo is happy with them."])

    def test_the_same_report_without_the_ask_is_clean(self):
        self.assertEqual(owner_asks.unlisted(BLOCK + SHORT), [])

    def test_an_unreadable_ledger_lists_nothing_either(self):
        text = BLOCK.replace("needs the owner: none", "needs the owner: unknown (no readable ledger)")
        self.assertEqual(len(owner_asks.unlisted(text + ASK)), 1)

    def test_an_indented_block_is_read_the_same(self):
        indented = "".join(f"    {line}\n" for line in BLOCK.splitlines())
        self.assertEqual(len(owner_asks.unlisted(indented + ASK)), 1)
        self.assertEqual(owner_asks.unlisted(indented + SHORT), [])


class Scope(unittest.TestCase):
    def test_a_message_without_the_status_line_is_never_read(self):  # not a write report
        self.assertEqual(owner_asks.unlisted(ASK), [])
        self.assertEqual(owner_asks.unlisted("Please check Jo is happy with the intro."), [])

    def test_a_list_with_items_is_left_to_the_person(self):  # can't tell which item an ask is about
        self.assertEqual(owner_asks.unlisted(listed(1) + "\nN-C1 needs Jo to confirm she'd say it.\n"), [])
        self.assertEqual(owner_asks.unlisted(listed(2) + ASK), [])

    def test_the_status_block_itself_is_never_read_as_prose(self):
        text = BLOCK.replace("For kaizen: none", "For kaizen: r7d L3, check flagged a join; confirm with me")
        self.assertEqual(owner_asks.unlisted(text), [])


class Asks(unittest.TestCase):
    def assert_caught(self, sentence: str) -> None:
        self.assertEqual(owner_asks.unlisted(BLOCK + "\n" + sentence + "\n"), [sentence], sentence)

    def assert_clean(self, sentence: str) -> None:
        self.assertEqual(owner_asks.unlisted(BLOCK + "\n" + sentence + "\n"), [], sentence)

    def test_asks_in_other_words_are_caught(self):
        for s in ("Check you're happy with the thank-you line before it goes out.",
                  "Make sure the committee is comfortable with the line about paper.",
                  "Worth running the closing line past Jo.",
                  "Ask Jo to confirm the canteen start date.",
                  "Get the owner to sign off on the thanks.",
                  "Jo may want to check the thank-you line.",
                  "You'll want to confirm the canteen roster starts next season.",
                  "Please confirm the canteen roster starts next season.",
                  "Double-check the thanks before it goes up.",
                  "The help session line is mine, so check with Jo.",
                  "Clear the warmer lines with Jo first.",
                  "It needs Jo's OK before it goes out."):
            with self.subTest(s=s):
                self.assert_caught(s)

    def test_report_prose_that_asks_nothing_is_left_alone(self):
        for s in ("The check passed first time, and I'm happy with how the close reads.",
                  "Check passed on the first round.",
                  "I didn't check the canteen dates against anything; they're straight from your notes.",
                  "The claims checker found nothing to block.",
                  "Before it ships, check delivery with /plainspoken:reader-value deliver .plainspoken/drafts/x.md.",
                  "Cut any line that doesn't fit.",
                  "It's ok to cut any line that doesn't fit; that's okay with the notes too.",
                  "Send me more detail and I'll add it.",
                  "I cut the three lines the notes didn't give, so nothing waits on the owner."):
            with self.subTest(s=s):
                self.assert_clean(s)


class Message(unittest.TestCase):
    def test_the_message_quotes_each_ask_and_says_cut_or_hold(self):
        msg = owner_asks.message(["so check Jo is happy with them."])
        self.assertIn('"so check Jo is happy with them."', msg)
        self.assertIn("`needs the owner`", msg)
        self.assertIn("cut", msg)
        self.assertIn("`blocking`", msg)
        self.assertIn("never only ask in the report", msg)
        self.assertIn("a fix never adds a fact", msg)


if __name__ == "__main__":
    unittest.main()
