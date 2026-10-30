"""owner_asks: a write report that asks the owner to check something its `needs the owner` lines don't list (#75).

The incident report is the round-6 netball run's, as the trace audit quotes it: the engine printed
`needs the owner: none` and the prose still asked the person to check three lines with the club secretary. The two
round-8 reports (4Cm44E, M99Lk3, cut down) are the asks the first patterns missed: a decision handed to the owner,
and an ask about an unlisted line in a report whose owner line listed one claim."""
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


def listed(n: int, text: str = "a line held for the owner") -> str:
    items = "".join(f"  N-C{i}: {text} (blocking)\n" for i in range(1, n + 1))
    return BLOCK.replace("needs the owner: none\n", f"needs the owner: {n}\n{items}")


REPAIR = """Draft: .plainspoken/drafts/repair-cafe.md
check: PASS · coverage 41/41 · BLOCK - · WARN - · unresolved -
claims: PASS
  checker: PASS (1 warning)
needs the owner: none
words: 263 (body text; headings, tables, code and numbers not counted)
For kaizen: none

**The piece is 263 words, not 450** (body text only). Your notes cover about that much. Reaching 450 would mean \
padding or making things up. To make it longer, I'd need more material, such as:
- a quote from Mei Lin or someone who brought something in
- the date of the next session

**Changes I made to keep it accurate:**
- The opening says volunteers "will try to fix" items, not "will fix" them, because only 151 of the 212 items were \
fixed.
- I added "about 150 kilos out of the tip", which is 151 repairs × the waste team's roughly 1 kilo each. The piece \
says plainly that it rests on an estimate. Cut that sentence if you'd rather not print a figure the council didn't give.
- The opening's toaster, jeans and bike faults are examples I chose to match the most common items.

The claims checker left one warning: the passage it matched Ray's quote against didn't include the words "Ray \
said". Your notes do say Ray said it, so the quote is correctly attributed.

<<<PIECE
# Coburg Library's repair cafe has fixed 151 things since July

Mei Lin can't keep up, so the library wants more volunteers who can sew. If you can, ask at the front desk.

If you'd rather keep the old toaster, swap the element and check with Ray it's ok to bring it back.
PIECE>>>
"""
REPAIR_ASK = "Cut that sentence if you'd rather not print a figure the council didn't give."
LEDGER_LEAF = """    Draft: .plainspoken/drafts/ledger-and-leaf-services.md
    check: PASS · coverage 41/41 · BLOCK - · WARN - · unresolved -
    claims: BLOCKED
      blocking: sensitive first-hand claim: owner approval required before publication
    needs the owner: 1
      LEDGER-AND-LEAF-SERVICES-C010: In a typical clean-up, a cafe came to me nine months behind on its \
reconciliations, and it took me four weeks to bring i (owner approval)
    words: 203 (body text; headings, tables, code and numbers not counted)
    For kaizen: none

**The page is 203 words, not 450.** That count is body text only. Your notes hold about 200 words of facts, and I \
didn't add any of my own to make up the length. To reach 450, I'd need more material from you, such as:

- what each monthly package includes
- a short quote from a client, if you have one you're allowed to use

**One thing needs your OK before this goes live: the cafe clean-up.** It describes a real client's result. Please \
confirm you're happy to publish it as written. The cafe isn't named.

**The claims check passed the draft with one warning.** Every other line traces back to your notes. The warning is \
on the opening line, "I look after BAS, payroll and Xero": your notes say "Xero setup", and "look after" could read \
as ongoing Xero work. If you only do setup, I'd change it to "I look after BAS and payroll, set up Xero…".

Earlier rounds of the check tightened three lines to match your notes:
- I dropped "It's just me", because "sole trader" doesn't say that.
- I cut "as a bookkeeper" from your 11 years, because your notes don't say what role those years were in.
"""
LEDGER_LEAF_ASK = 'If you only do setup, I\'d change it to "I look after BAS and payroll, set up Xero…".'


class Incident(unittest.TestCase):
    def test_the_round_6_report_is_caught(self):
        self.assertEqual(owner_asks.unlisted(BLOCK + SHORT + ASK),
                         ["Each is a small bit of warmth in Jo's voice, so check Jo is happy with them."])

    def test_the_same_report_without_the_ask_is_clean(self):
        self.assertEqual(owner_asks.unlisted(BLOCK + SHORT), [])

    def test_an_unreadable_ledger_lists_nothing_either(self):
        text = BLOCK.replace("needs the owner: none", "needs the owner: unknown (no readable ledger)")
        self.assertEqual(len(owner_asks.unlisted(text + ASK)), 1)

    def test_the_round_8_decision_handed_to_the_owner_is_caught(self):  # 4Cm44E: no check/confirm verb
        self.assertEqual(owner_asks.unlisted(REPAIR), [REPAIR_ASK])

    def test_the_round_8_ask_beside_a_listed_claim_is_caught(self):  # M99Lk3: the hook skipped a report with items
        self.assertEqual(owner_asks.unlisted(LEDGER_LEAF), [LEDGER_LEAF_ASK])

    def test_the_round_8_reports_without_their_asks_are_clean(self):  # the confirm about C010 is the one allowed
        self.assertEqual(owner_asks.unlisted(REPAIR.replace(REPAIR_ASK, "")), [])
        self.assertEqual(owner_asks.unlisted(LEDGER_LEAF.replace(LEDGER_LEAF_ASK, "")), [])

    def test_an_indented_block_is_read_the_same(self):
        indented = "".join(f"    {line}\n" for line in BLOCK.splitlines())
        self.assertEqual(len(owner_asks.unlisted(indented + ASK)), 1)
        self.assertEqual(owner_asks.unlisted(indented + SHORT), [])


class Scope(unittest.TestCase):
    def test_a_message_without_the_status_line_is_never_read(self):  # not a write report
        self.assertEqual(owner_asks.unlisted(ASK), [])
        self.assertEqual(owner_asks.unlisted("Please check Jo is happy with the intro."), [])

    def test_an_ask_about_a_listed_claim_is_left_alone(self):  # the ask the engine's list allows
        self.assertEqual(owner_asks.unlisted(listed(1) + "\nN-C1 needs Jo to confirm she'd say it.\n"), [])
        thanks = listed(1, "Thanks, Kath and Ollie, for sorting the rosters")
        self.assertEqual(owner_asks.unlisted(thanks + "\nPlease check Jo is happy with the thanks to Kath.\n"), [])
        self.assertEqual(owner_asks.unlisted(thanks + "\nThe thanks to Kath and Ollie is new. Please confirm "
                                             "you're happy to print it.\n"), [])  # "it": the paragraph says which

    def test_an_ask_about_another_line_is_caught_beside_listed_claims(self):  # round 8: items listed, ask unlisted
        self.assertEqual(owner_asks.unlisted(listed(2) + ASK),
                         ["Each is a small bit of warmth in Jo's voice, so check Jo is happy with them."])
        thanks = listed(1, "Thanks, Kath and Ollie, for sorting the rosters")
        own_quote = "\nThe thanks to Kath is held for you. Check Jo is happy with 'That's a lot of people to reach'.\n"
        self.assertEqual(owner_asks.unlisted(thanks + own_quote),
                         ["Check Jo is happy with 'That's a lot of people to reach'."])  # it quotes its own line

    def test_a_count_with_no_items_under_it_is_left_to_the_person(self):
        self.assertEqual(owner_asks.unlisted(BLOCK.replace("needs the owner: none", "needs the owner: 2") + ASK), [])

    def test_the_piece_between_the_eval_markers_is_never_read(self):
        piece = "\n<<<PIECE\nCut the crust if you'd rather. Check Jo is happy with the times.\nPIECE>>>\n"
        self.assertEqual(owner_asks.unlisted(BLOCK + SHORT + piece), [])
        self.assertEqual(len(owner_asks.unlisted(BLOCK + piece + ASK)), 1)

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

    def test_decisions_handed_to_the_owner_are_caught(self):  # round 8: "cut it if you'd rather …"
        for s in ("Cut that sentence if you'd rather not print a figure the council didn't give.",
                  'If you only do setup, I\'d change it to "I look after BAS and payroll, set up Xero…".',
                  "If you'd prefer not to name Ray, drop the quote.",
                  "Swap the closing line for your usual sign-off if you would rather keep it formal.",
                  "Unless you're sure the hall is free, I'd remove the date.",
                  "If you don't run a waitlist, change the second paragraph."):
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
                  "I cut the three lines the notes didn't give, so nothing waits on the owner.",
                  # round-8 report lines that hand nothing over
                  "To make it longer, I'd need more material, such as:",
                  "- a short quote from a client, if you have one you're allowed to use",
                  "I dropped \"It's just me\", because \"sole trader\" doesn't say that.",
                  'The opening says volunteers "will try to fix" items, not "will fix" them.',
                  "If you send me the date of the next session, I can add it, and I'll change nothing else.",
                  "If you want it longer, give me more detail and I'll add a section.",
                  "If you'd like a longer page, I'd need what each package includes.",
                  "I kept the closing line short, because the notes end there.",
                  "If you run /plainspoken:check again after an edit, it rereads the draft.",
                  "I didn't change the quote, so if you want it word for word, it already is.",
                  "If you're wondering about the dates, I cut nothing from your notes."):
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
