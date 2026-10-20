"""tests/test_anti_ai_doc.py — markdown → sections/paragraphs/sentences, with the right things excluded."""
import unittest

from plainspoken.doc import parse, split_sentences, tokenise
from tests._profiles import PRODUCT, CONSULTING

ARTICLE = '''---
title: "Why the site is slow"
domain: consulting.example
faqs:
  - question: "Is it slow?"
    answer: "Yes — very slow. It's the images."
---

Opening paragraph here. It has two sentences.

## First section

Run `npm run build -- --dry-run` and check https://example.com/robust-thing for details.

```bash
echo "delve — robust"
```

<!-- a comment with robust in it -->
- a bullet item
- another bullet

> "This is a verbatim quote that is robust," said Someone.

## Second Section Here

Short one. Another short one.
'''


class Parse(unittest.TestCase):
    def setUp(self):
        self.doc = parse(ARTICLE, path="docs/blog/999-test.md", profile=CONSULTING)

    def test_sections_split_on_h2_with_intro(self):
        headings = [s.heading for s in self.doc.sections]
        self.assertEqual(headings, ["", "First section", "Second Section Here"])

    def test_faq_answers_are_visible_text(self):
        labels = {s.label for s in self.doc.visible_frontmatter}
        self.assertIn("faqs[0].answer", labels)
        answer = next(s for s in self.doc.visible_frontmatter if s.label == "faqs[0].answer")
        self.assertIn("—", answer.text)

    def test_code_and_urls_are_not_prose(self):
        prose = " ".join(p.text for p in self.doc.prose_paragraphs())
        self.assertNotIn("dry-run", prose)
        self.assertNotIn("example.com", prose)
        self.assertNotIn("delve", prose)
        self.assertNotIn("comment with robust", prose)

    def test_bullets_and_blockquotes_have_kinds(self):
        kinds = [p.kind for s in self.doc.sections for p in s.paragraphs]
        self.assertIn("bullet", kinds)
        self.assertIn("blockquote", kinds)

    def test_quoted_span_is_masked(self):
        bq = next(p for s in self.doc.sections for p in s.paragraphs if p.kind == "blockquote")
        self.assertNotIn("robust", self.doc.masked(bq.text))

    def test_line_numbers_point_at_source(self):
        lines = ARTICLE.splitlines()
        first = self.doc.sections[0].paragraphs[0]
        self.assertEqual(lines[first.line - 1], "Opening paragraph here. It has two sentences.")

    def test_allow_marker_parsed(self):
        doc = parse('---\ndomain: narrative.example\n---\n\n<!-- anti-ai-allow: 2 "robust" quoted from the club report -->\nA robust wall.\n')
        self.assertEqual(len(doc.allows), 1)
        self.assertEqual((doc.allows[0].rule, doc.allows[0].phrase), ("2", "robust"))
        self.assertEqual(doc.allows[0].line, 6)

    def test_html_and_svg_blocks_are_not_prose(self):
        # published articles carry raw HTML/SVG chart blocks; none of it is prose.
        doc = parse(
            '---\ndomain: consulting.example\n---\n\n'
            'Plain words before.\n\n'
            '<figure class="chart">\n'
            '<svg viewBox="0 0 10 10" role="img" aria-label="robust — x">\n'
            '  <text x="1" y="2">delve — robust tick label</text>\n'
            '</svg>\n'
            '<figcaption>Hours per month by <a href="https://example.com/x">provider</a>.</figcaption>\n'
            '</figure>\n\n'
            '<a id="faq"></a>\n'
            'Words with <span class="x">inline</span> markup after.\n'
        )
        prose = " ".join(p.text for p in doc.prose_paragraphs())
        words = [w for s in doc.all_sentences() for w in s.words]
        self.assertNotIn("robust", words)
        self.assertNotIn("delve", words)
        self.assertNotIn("—", prose)
        self.assertNotIn("<", prose)
        self.assertEqual([s.text for s in doc.all_sentences()],
                         ["Plain words before.", "Hours per month by provider.", "Words with inline markup after."])

    def test_figcaption_text_is_prose(self):
        # Ruling 3: caption text is visible, even though its line starts with "<" (035's chart caption).
        doc = parse(
            '<figure>\n<figcaption>The same $2,000 buys anywhere from 7 to 20 hours a month.\n'
            'The quote should tell you which.</figcaption>\n</figure>\n'
        )
        self.assertEqual([s.text for s in doc.all_sentences()],
                         ["The same $2,000 buys anywhere from 7 to 20 hours a month.",
                          "The quote should tell you which."])
        self.assertEqual(doc.prose_paragraphs()[0].line, 2)

    def test_inline_tag_led_line_is_prose(self):
        doc = parse('<strong>Note:</strong> this is a robust claim.\n\n'
                    '<code>npm run build</code> is the command.\n')
        self.assertEqual([s.text for s in doc.all_sentences()],
                         ["Note: this is a robust claim.", "is the command."])

    def test_inline_tag_between_words_keeps_them_apart(self):
        doc = parse('One line<br>two line and <em>emphasis</em>.\n')
        self.assertEqual([s.text for s in doc.all_sentences()], ["One line two line and emphasis."])

    def test_inline_allow_marker_keeps_the_prose(self):
        doc = parse('A robust wall. <!-- anti-ai-allow: 2 "robust" quoted from the club report -->\n')
        self.assertEqual([s.text for s in doc.all_sentences()], ["A robust wall."])
        self.assertEqual([(a.rule, a.phrase, a.line) for a in doc.allows], [("2", "robust", 1)])

    def test_allow_marker_alone_on_a_blockquote_line_applies_to_the_next_line(self):
        doc = parse('> <!-- anti-ai-allow: 2 "robust" quoted from the club report -->\n> A robust quote.\n')
        self.assertEqual([(a.rule, a.phrase, a.line) for a in doc.allows], [("2", "robust", 2)])
        self.assertEqual([(s.text, s.line) for s in doc.all_sentences()], [("A robust quote.", 2)])

    def test_camelcase_og_fields_are_visible(self):
        doc = parse('---\nogTitle: "A robust title"\nogDescription: "Delve in"\n---\n\nBody.\n', profile=PRODUCT)
        spans = {s.label: (s.text, s.line) for s in doc.visible_frontmatter}
        self.assertEqual(spans["ogTitle"], ("A robust title", 2))
        self.assertEqual(spans["ogDescription"], ("Delve in", 3))

    def test_multiline_html_blocks_are_not_prose(self):
        # Multi-line comments, wrapped <svg> attributes and <script> bodies don't start with "<".
        doc = parse(
            '---\ndomain: consulting.example\n---\n\n'
            '<!-- HASHNODE CROSS-POST METADATA\nTitle: a robust title\n-->\n\n'
            '<svg viewBox="0 0 10 10"\n     aria-label="delve into it">\n</svg>\n\n'
            '<script type="application/ld+json">\n{"headline": "robust"}\n</script>\n\n'
            'Kept. And x < 5 but y > 3.\n'
        )
        self.assertEqual([s.text for s in doc.all_sentences()], ["Kept.", "And x < 5 but y > 3."])
        self.assertEqual(doc.sections[0].paragraphs[0].line, 17)

    def test_empty_frontmatter_is_not_prose(self):
        doc = parse("---\n---\n\nBody line.\n")
        self.assertEqual([s.text for s in doc.all_sentences()], ["Body line."])


def _quoted(md: str) -> bool:
    paras = [p for p in parse(md).prose_paragraphs() if p.kind == "blockquote"]
    assert len(paras) == 1, paras
    return all(s.quoted for s in paras[0].sentences)


class Attribution(unittest.TestCase):
    """Only a real attribution on the last blockquote line marks the quote verbatim (→ INFO)."""

    def test_hyphenated_word_is_not_an_attribution(self):
        self.assertFalse(_quoted("> **Try this:** open settings and turn on Wi-Fi calling.\n"))

    def test_mid_sentence_dash_is_not_an_attribution(self):
        self.assertFalse(_quoted("> **Try this:** open the robust settings page - Google shows the status there.\n"))

    def test_list_quote_card_is_not_an_attribution(self):
        # Pricing quote cards: nested "> - " lines are list items.
        self.assertFalse(_quoted("> **Quote A - $1,800**\n> - 5-page website, mobile friendly\n> - Basic SEO\n"))
        self.assertFalse(_quoted('> **"SEO Growth Package" - $2,000/month**\n> - Link building\n'))

    def test_same_line_attribution_after_closing_quote(self):
        self.assertTrue(_quoted('> "Recommendations are always in Google\'s best interest." - Jane Smith, Example Weekly\n'))

    def test_dash_line_after_closing_quote(self):
        # A common layout: the attribution sits on its own "> - Name" line after the quote.
        self.assertTrue(_quoted('> "They are always in Google\'s best interest."\n'
                                '> - Jane Smith, [Example Weekly](https://example.com/x), January 2026\n'))

    def test_en_dash_name_on_its_own_line(self):
        self.assertTrue(_quoted("> The ground was a quagmire by three-quarter time.\n> – Jane Smith\n"))


class Sentences(unittest.TestCase):
    def test_abbreviations_and_decimals_do_not_split(self):
        s = split_sentences("LCP should be 2.5 s, e.g. on mobile. Then it's fine! Is it? Yes.")
        self.assertEqual(s, ["LCP should be 2.5 s, e.g. on mobile.", "Then it's fine!", "Is it?", "Yes."])

    def test_closing_quote_stays_with_its_sentence(self):
        # The splitter used to drop the closing quote after a full stop.
        self.assertEqual(split_sentences('He said "we ship on Friday no matter what." Then he left.'),
                         ['He said "we ship on Friday no matter what."', "Then he left."])
        self.assertEqual(split_sentences("He said “we ship on Friday no matter what.” Then he left."),
                         ["He said “we ship on Friday no matter what.”", "Then he left."])
        self.assertEqual(split_sentences("(It shipped late.) Then it broke."), ["(It shipped late.)", "Then it broke."])

    def test_quote_ending_a_sentence_stays_masked(self):
        doc = parse('---\n---\n\nHe said "we ship on Friday no matter what." Then he left.\n')
        first = doc.all_sentences()[0]
        self.assertTrue(first.text.endswith('."'))
        self.assertEqual(doc.masked(first.text).strip(), "He said")

    def test_tokenise_keeps_contractions(self):
        self.assertEqual(tokenise("It's the site's fault, isn't it?"), ["it's", "the", "site's", "fault", "isn't", "it"])


if __name__ == "__main__":
    unittest.main()


class ListContinuation(unittest.TestCase):  # a prompt under a bullet
    def test_lines_under_a_bullet_belong_to_it(self):
        doc = parse("---\ntitle: T\n---\n\n- **Test** — paste this:\n  *\"What does it do?\"*\n"
                    "  Compare the answers.\nLazy continuation line.\n\nA real paragraph.\n")
        paras = [(p.kind, p.text) for p in doc.prose_paragraphs()]
        self.assertEqual([k for k, _ in paras], ["bullet", "prose"])
        self.assertIn("Compare the answers.", paras[0][1])
        self.assertIn("Lazy continuation line.", paras[0][1])
        self.assertEqual(doc.prose_paragraphs()[0].line, 5)

    def test_a_new_bullet_or_blank_line_ends_the_item(self):
        doc = parse("---\ntitle: T\n---\n\n- one\n  more\n- two\n\nProse.\n")
        self.assertEqual([p.kind for p in doc.prose_paragraphs()], ["bullet", "bullet", "prose"])

    def test_resources_lines(self):
        doc = parse("---\ntitle: T\n---\n\n## Intro\n\nx\n\n## Tools & Resources\n\n### Free\n\n- a\n\n## FAQ\n\ny\n", profile=PRODUCT)
        self.assertEqual(doc.resources_lines(), set(range(9, 15)))


class FinalReviewDoc(unittest.TestCase):
    def test_unclosed_frontmatter_raises(self):  # was silently read as body
        from plainspoken.frontmatter import FrontmatterError
        with self.assertRaisesRegex(FrontmatterError, "unclosed frontmatter"):
            parse('---\ntitle: "T"\n\nBody text here.\n', profile=PRODUCT)

    def test_unicode_line_separators_do_not_shift_lines(self):
        text = '---\ntitle: "A\u2028B"\n---\n\nFirst line\u2028still first.\n\nThird para here.\n'
        doc = parse(text, profile=PRODUCT)
        self.assertEqual(len(doc.lines), text.count("\n"))
        paras = [p for s in doc.sections for p in s.paragraphs]
        self.assertEqual([p.line for p in paras], [5, 7])
        self.assertFalse(any("---" in p.text for p in paras), [p.text for p in paras])
        self.assertEqual(parse("a\nb\n", profile=PRODUCT).lines, ["a", "b"])

