"""Finding the draft in a chat reply and the one message about it (#125). Every reply here is synthetic."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lib"))
from plainspoken import reply  # noqa: E402

LETTER_BODY = ("Hi Jo,\n\nThanks for sending the roster through. I've had a look and Saturday works for the working "
               "bee. I'll bring gloves and the spare rakes, and Sam said he can do the sausage sizzle if someone "
               "grabs bread.\n\nCheers,\nNathan")
NOTE = ("Thursday works for me. I'll bring the signed forms and the spare keys, and I can stay back after to help "
        "pack up the chairs if that helps anyone. See you at the hall around six.")
LONG_NOTE = NOTE + " Thanks again for sorting the hall booking, it made the whole thing much easier."

SHAPES = [
    ("fence", "Here's a draft:\n\n```\n" + LETTER_BODY + "\n```\n\nWant me to make it shorter?"),
    ("quote", "Sure. Try this:\n\n> Our open day is on Saturday 9 November from 10 to 2. Come and see the new "
              "classrooms, meet the teachers and have a sausage from the P&C stall. Parking is on Elm Street; the "
              "front car park is for families with prams.\n\nI kept it under 60 words for the newsletter."),
    ("letter", "Sure, here it is.\nSubject: Friday excursion\n\nHi everyone,\n\nOn Friday the Year 4 class is going "
               "to the museum. Please send a packed lunch, a hat and a water bottle. The bus leaves at 9 sharp, so "
               "drop-off is at 8:40.\n\nThanks,\nMs Lee\n\nLet me know if you want a version for the app."),
    ("variants", "Two options:\n\n**Option 1**\n\nWe're closed Monday for the public holiday and back Tuesday at "
                 "7am. If you need a script filled before then, the chemist on High Street is open from 9 to 5 "
                 "all weekend.\n\n**Option 2**\n\nHeads up: no clinic this Monday (public holiday). Back Tuesday "
                 "7am. Need a script before then? The High Street chemist is open 9 to 5 all weekend long, "
                 "including Sunday.\n"),
    ("rules", "Here's the post:\n\n---\n\nI spent Saturday at the repair cafe and watched a retired electrician "
              "bring a forty-year-old toaster back to life. Nobody paid a cent. If you've got something broken in "
              "the shed, bring it along next month and have a cuppa while you wait.\n\n---\n\nI avoided hashtags "
              "since you said LinkedIn."),
    ("framed", "Sure.\n\n" + LONG_NOTE + "\n\nWant me to make it more formal?"),
    ("whole", LONG_NOTE),
    ("fence", "```markdown\nWe're hiring a part-time bookkeeper for our Footscray office. Two days a week, "
              "flexible hours, and you'll work directly with the owner on payroll, BAS and the odd supplier "
              "dispute. Apply by 15 November.\n```"),
]

NOT_DRAFTS = [
    "The fix is below.\n\n```python\ndef add(a, b):\n    return a + b  # adds two numbers together for the caller "
    "who wants a sum of the values passed in and nothing more than that at all\n```\n",
    "Here's what changed:\n\n- The Stop hook now reads last_assistant_message\n- The lint runs on stdin\n"
    "- Findings go to systemMessage\n- Tests cover the three hosts and the fallback paths in full detail",
    "| col | a |\n|---|---|\n| one | the quick brown fox jumps over the lazy dog and keeps going for a while "
    "longer than needed to pass twenty five words in total here ok |",
    "name: roster\nday: Saturday\ntime: 9am\nplace: the hall\nbring: gloves\nfood: sausage sizzle\n"
    "contact: Jo\nnotes: the spare rakes are in the shed, and Sam can do the barbecue if someone grabs bread.",
    # the two adversarial misses from the plan: a clarifying question and a "not yet" explanation
    "I didn't draft it yet because the notes don't say when the fete is or who to contact. If you tell me the date "
    "and the contact person, I'll write the email straight away and keep it short for the parents.",
    "Quick question before I write it: is this going to parents or to staff? The tone and the detail change a lot "
    "between the two, so I'd rather check than guess and have you redo it later on.",
    "Which version do you want me to send: the short one for the group chat, or the longer one with the times and "
    "the parking details for the parents who haven't been to the hall before?",
]


class Shapes(unittest.TestCase):
    def test_each_shape_finds_its_draft(self):
        for shape, text in SHAPES:
            with self.subTest(shape=shape, text=text[:30]):
                found = reply.drafts(text, writing_ask=True)
                self.assertTrue(found, text)
                self.assertEqual({d.shape for d in found}, {shape})

    def test_variants_are_separate_drafts(self):
        found = reply.drafts(SHAPES[3][1], writing_ask=True)
        self.assertEqual(len(found), 2)
        self.assertTrue(found[0].text.startswith("We're closed Monday"))

    def test_code_tables_key_value_lists_and_change_lists_are_never_drafts(self):
        for text in NOT_DRAFTS:
            with self.subTest(text=text[:40]):
                self.assertEqual(reply.drafts(text, writing_ask=True), [])

    def test_unmarked_prose_needs_a_writing_ask(self):
        self.assertEqual(reply.drafts(SHAPES[6][1], writing_ask=False), [])
        self.assertEqual(reply.drafts(SHAPES[5][1], writing_ask=False), [])
        self.assertTrue(reply.drafts(SHAPES[0][1], writing_ask=False))  # a marked draft is found either way

    def test_the_fallback_has_a_40_word_floor(self):
        short = "Thursday works for me. I'll bring the signed forms and the spare keys, and stay back to help pack."
        self.assertLess(len(short.split()), 40)
        self.assertEqual(reply.drafts(short, writing_ask=True), [])
        self.assertTrue(reply.drafts("```\n" + short + " See you at the hall around six, Jo.\n```", True))

    def test_min_words_moves_the_floor(self):
        self.assertEqual(reply.drafts(SHAPES[0][1], writing_ask=True, min_words=200), [])

    def test_at_most_three_drafts(self):
        text = "\n\n".join(f"**Option {i}**\n\n{NOTE}" for i in range(1, 6))
        self.assertEqual(len(reply.drafts(text, writing_ask=True)), reply.MAX_DRAFTS)

    def test_the_wrapper_is_stripped_and_the_drafts_own_markdown_kept(self):
        (d,) = reply.drafts("Here it is:\n\n```text\nHi Sam,\n\nThe **working bee** is on Saturday from 9am. Bring "
                            "gloves, a hat and a water bottle, and we'll have the urn going for morning tea.\n\n"
                            "Cheers,\nJo\n```", writing_ask=True)
        self.assertNotIn("```", d.text)
        self.assertIn("**working bee**", d.text)
        (q,) = reply.drafts(SHAPES[1][1], writing_ask=True)
        self.assertFalse(q.text.startswith(">"))

    def test_kind_is_email_only_for_a_letter_shape(self):
        self.assertEqual(reply.drafts(SHAPES[0][1], True)[0].kind, "email")
        self.assertEqual(reply.drafts(SHAPES[2][1], True)[0].kind, "email")
        self.assertIsNone(reply.drafts(SHAPES[4][1], True)[0].kind)

    def test_words_are_counted(self):
        d = reply.drafts(SHAPES[6][1], True)[0]
        self.assertEqual(d.words, len(d.text.split()))


class WriteReport(unittest.TestCase):
    def test_the_status_block_marks_a_write_report(self):
        report = ("Draft: post.md (412 words)\ncheck: PASS\nclaims: 0 open\nneeds the owner: none\n\n"
                  "I tightened the opening and cut two claims the notes didn't give.")
        self.assertTrue(reply.is_write_report(report))
        self.assertFalse(reply.is_write_report(SHAPES[0][1]))
        self.assertFalse(reply.is_write_report("Nobody needs the owner: to sign this."))  # not at a line start

    def test_the_marker_is_the_one_status_prints(self):
        main = (REPO / "lib" / "plainspoken" / "__main__.py").read_text(encoding="utf-8")
        self.assertTrue("reply.OWNER_MARKER" in main)  # not assertIn: it would print the whole file
        self.assertEqual(reply.OWNER_MARKER, "needs the owner:")


def lint(*findings):
    return {"findings": [{"severity": s, "rule": r, "line": 1, "message": m} for s, r, m in findings],
            "metrics": {"words": 40}, "content_type": "social"}


class Message(unittest.TestCase):
    D = reply.Draft("x " * 112, 112, "letter", "email")

    def test_one_draft(self):
        text = reply.message([(self.D, lint(("BLOCK", "2", "Banned word: “delve”"),
                                             ("BLOCK", "4a", "Academic transition: “Furthermore”"),
                                             ("WARN", "7", "Sentences all about the same length")))],
                             "claude-code")
        lines = text.splitlines()
        self.assertEqual(lines[0], "plainspoken: the draft in this reply (email, 112 words) has 2 BLOCK, 1 WARN "
                                   "(lint only, judges not run):")
        self.assertEqual(lines[1], "  BLOCK r2   Banned word: “delve”")
        self.assertIn("/plainspoken:check", lines[-1])

    def test_caps_lines_and_characters_and_counts_the_rest(self):
        many = lint(*[("WARN", str(i), "x" * 300) for i in range(9)], ("BLOCK", "2", "Banned word: “delve”"))
        text = reply.message([(self.D, many), (self.D._replace(kind=None, words=60), many)], "codex")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), reply.MESSAGE_LINES)
        self.assertLessEqual(len(text), reply.MESSAGE_CHARS)
        self.assertIn("BLOCK r2", lines[1])  # BLOCKs first
        self.assertIn("17 more", text)
        self.assertTrue(lines[0].startswith("plainspoken: 2 drafts in this reply (112 and 60 words) have 2 BLOCK"))
        self.assertIn("$plainspoken:check", lines[-1])

    def test_never_says_the_judges_ran_and_uses_each_hosts_syntax(self):
        for host, ref in (("claude-code", "/plainspoken:check"), ("codex", "$plainspoken:check"),
                          ("hermes", "plainspoken:check")):
            text = reply.message([(self.D, lint(("WARN", "7", "Same length")))], host)
            self.assertIn(ref, text)
            self.assertIn("judges not run", text)
            self.assertNotIn("passed", text)


if __name__ == "__main__":
    unittest.main()
