"""Prose extraction (#124, shared with #125): what counts as writing for a person inside a string, and how much of it.

Every fixture here is synthetic; none is real mail or a real message."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from plainspoken import prose  # noqa: E402

LETTER = ("Hi Sam, thanks for sending the plans over on Tuesday. I had a look at the garden layout and the shed "
          "position works well for me. Could we move the meeting to Thursday at ten? I'll bring the samples.")


class Stripping(unittest.TestCase):
    def test_plain_prose_passes_through(self):
        got = prose.extract(LETTER)
        self.assertIsNone(got.reason)
        self.assertEqual(got.words, len(LETTER.split()))
        self.assertEqual(got.text, LETTER)

    def test_html_body_drops_tags_style_and_the_quoted_thread(self):
        html = ("<html><head><style>p { color: red; }</style></head><body><p>Hi Sam,</p><p>" + LETTER[8:] +
                "</p><div class=\"gmail_quote\"><div>On Mon, someone wrote:</div><blockquote>Old words from the "
                "earlier message that should never be linted again.</blockquote></div></body></html>")
        got = prose.extract(html)
        self.assertIsNone(got.reason)
        self.assertNotIn("<", got.text)
        self.assertNotIn("color", got.text)
        self.assertNotIn("Old words", got.text)
        self.assertIn("garden layout", got.text)

    def test_html_entities_are_unescaped(self):
        got = prose.extract("<p>Fish &amp; chips at noon. We&#39;ll see you there for the whole lunch break, then "
                            "we walk back to the office together and talk about the plan for the week.</p>")
        self.assertIn("Fish & chips", got.text)
        self.assertIn("We'll", got.text)

    def test_plain_reply_cuts_at_on_wrote_and_quoted_lines(self):
        text = LETTER + "\n\nOn Mon, 3 Mar 2026 at 9:00, Alex Example <alex@example.com> wrote:\n> The old text.\n"
        got = prose.extract(text)
        self.assertEqual(got.text.strip(), LETTER)
        self.assertEqual(prose.extract("> quoted only\n> more quoted\n" + LETTER).text.strip(), LETTER)

    def test_a_letter_that_mentions_someone_writing_is_kept(self):
        text = "On Friday my sister wrote:\n" + LETTER
        self.assertIn("garden layout", prose.extract(text).text)

    def test_outlook_header_block_and_original_message_cut(self):
        outlook = LETTER + "\n\nFrom: Alex Example\nSent: Monday, 3 March 2026 9:00 AM\nTo: Sam\nSubject: Re: plans\n\nOld."
        self.assertEqual(prose.extract(outlook).text.strip(), LETTER)
        original = LETTER + "\n\n-----Original Message-----\nOld text here."
        self.assertEqual(prose.extract(original).text.strip(), LETTER)

    def test_signature_after_dash_dash_space_is_cut(self):
        got = prose.extract(LETTER + "\n-- \nSam Example\nGarden Co\n0400 000 000")
        self.assertEqual(got.text.strip(), LETTER)

    def test_fenced_code_is_dropped(self):
        text = LETTER + "\n\n```python\nfor i in range(10):\n    print(i)\n```\n"
        got = prose.extract(text)
        self.assertNotIn("range", got.text)
        self.assertIsNone(got.reason)

    def test_markdown_table_rows_are_dropped(self):
        text = LETTER + "\n\n| a | b |\n|---|---|\n| one two three | four five six |\n"
        got = prose.extract(text)
        self.assertNotIn("|", got.text)
        self.assertEqual(got.words, len(LETTER.split()))

    def test_urls_and_email_addresses_do_not_count(self):
        text = "See https://example.com/a/b and mail sam@example.com today. That is all."
        got = prose.extract(text)
        self.assertNotIn("example.com", got.text)
        self.assertEqual(got.words, len("See and mail today. That is all.".split()))


class NotProse(unittest.TestCase):
    def test_json_string(self):
        self.assertEqual(prose.extract('{"a": 1, "b": "some words here and more"}').reason, "json")
        self.assertEqual(prose.extract('[1, 2, 3]').reason, "json")

    def test_encoded_blob(self):
        self.assertEqual(prose.extract("U3ViamVjdDogSGVsbG8KCkhpIFNhbSwgdGhhbmtzIGZvciB0aGUgcGxhbnMuIFNlZSB5b3U="
                                       "IG9uIFRodXJzZGF5Lg==").reason, "encoded")

    def test_code_without_fences(self):
        code = ("def main():\n    import os\n    x = {1: 2}\n    return x\n\nfunction go() { const a = 1; return a; }\n"
                "SELECT name FROM people WHERE id = 3;")
        self.assertEqual(prose.extract(code).reason, "code")

    def test_url_only_field_is_empty(self):
        self.assertEqual(prose.extract("https://example.com/path?x=1").reason, "empty")

    def test_bullets_without_full_stops_have_no_sentence(self):
        bullets = "- milk and bread from the shop\n- call the plumber about the leak\n- book the car service soon"
        self.assertEqual(prose.extract(bullets).reason, "no-sentence")

    def test_symbol_heavy_text(self):
        self.assertEqual(prose.extract("x1 y2 z3 4 5 6 7 8 9 10 11 a. 12 13 14").reason, "symbols")

    def test_empty(self):
        self.assertEqual(prose.extract("   ").reason, "empty")
        self.assertEqual(prose.extract("").words, 0)


class Fingerprints(unittest.TestCase):
    def test_same_text_same_hash_whatever_the_spacing_and_quotes(self):
        a = "It’s fine.  We go on Monday."
        b = "it's fine. we go on monday."
        self.assertEqual(prose.text_hash(a), prose.text_hash(b))
        self.assertRegex(prose.text_hash(a), r"^[0-9a-f]{16}$")

    def test_overlap_counts_shared_sentences(self):
        seen = set(prose.fingerprint(LETTER))
        self.assertEqual(prose.overlap(prose.fingerprint(LETTER), seen), 1.0)
        reply = LETTER + " Also, the new fence posts arrive on the second of next month, weather allowing."
        self.assertGreaterEqual(prose.overlap(prose.fingerprint(reply), seen), 0.75)
        self.assertEqual(prose.overlap(prose.fingerprint("Something else entirely is written here today."), seen),
                         0.0)
        self.assertEqual(prose.overlap((), seen), 0.0)

    def test_fingerprints_hold_no_text(self):
        for h in prose.fingerprint(LETTER):
            self.assertRegex(h, r"^[0-9a-f]{12}$")


if __name__ == "__main__":
    unittest.main()
