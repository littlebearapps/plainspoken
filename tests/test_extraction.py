"""extraction.py: deterministic claim candidates and ledger value gaps. Ported from a blog workspace's extraction tests
(new invented text), plus non-dollar currency, non-blog text, the shipped and project platform lists, ledger passages,
removed claims and malformed ledgers.

The failure classes the ported cases guard: an unsourced statistic in a TL;DR, numbers inside SVG text nodes that a
prose check never sees, and a statistic left in frontmatter or JSON-LD after the body stat was cut."""
import shutil
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from plainspoken.config import ConfigError
from plainspoken.extraction import (
    VALUE_KINDS,
    extract_alt_text_candidates,
    extract_candidates,
    platform_names,
    value_gaps,
)

SHIPPED_PLATFORMS = ("Google", "Bing", "ChatGPT", "OpenAI", "Perplexity", "Gemini", "Claude", "Copilot", "Meta",
                     "Facebook", "Instagram", "LinkedIn", "GA4", "Search Console", "Cloudflare", "GitHub", "Apple",
                     "Microsoft")


def values(cands, kind):
    return [c["value"] for c in cands if c["kind"] == kind]


class TldrStatistic(unittest.TestCase):
    def test_percentage_in_tldr_is_extracted(self):
        md = (
            "---\ntitle: Gutter care\n---\n\n"
            "> **TL;DR:** Roughly 62% of homeowners never clear their gutters "
            "before winter.\n\nBody prose here.\n"
        )
        tldr = [c for c in extract_candidates(md) if c["surface"] == "tldr"]
        self.assertTrue(any(c["kind"] == "statistic" and c["value"] == "62%" for c in tldr))


class ChartClaims(unittest.TestCase):
    def test_svg_text_number_is_extracted_as_chart_claim(self):
        md = (
            "Prose before.\n\n"
            '<figure><svg xmlns="http://www.w3.org/2000/svg">'
            "<text>Burst pipes 37%</text></svg>"
            "<figcaption>Winter call-outs</figcaption></figure>\n"
        )
        chart = [c for c in extract_candidates(md) if c["surface"] == "chart"]
        self.assertTrue(any(c["kind"] == "statistic" and c["value"] == "37%" for c in chart))

    def test_raw_svg_coordinates_are_not_claims(self):
        md = '<figure><svg><rect x="120" y="45" width="300"/><text>share of call-outs</text></svg></figure>'
        cands = extract_candidates(md)
        self.assertFalse([c for c in cands if c["surface"] == "chart" and c["kind"] in ("count", "statistic")])


class FrontmatterAndJsonLd(unittest.TestCase):
    def test_description_statistic_is_extracted(self):
        md = "---\ndescription: 41% of renters report a leaking tap each year.\n---\n\nBody.\n"
        fm = [c for c in extract_candidates(md) if c["surface"] == "frontmatter:description"]
        self.assertTrue(any(c["kind"] == "statistic" and c["value"] == "41%" for c in fm))

    def test_jsonld_statistic_is_extracted(self):
        md = (
            "Body.\n\n"
            '<script type="application/ld+json">\n'
            '{"@type":"FAQPage","text":"Acme Plumbing fixes most leaks at 41%"}\n'
            "</script>\n"
        )
        self.assertTrue(any(c["surface"] == "jsonld" and c["value"] == "41%" for c in extract_candidates(md)))


class BodyClaimKinds(unittest.TestCase):
    def test_count_with_magnitude_suffix(self):
        cands = extract_candidates("The app reached 900M downloads in February 2026.\n")
        self.assertIn(("count", "900M"), {(c["kind"], c["value"]) for c in cands})

    def test_currency(self):
        cands = extract_candidates("The typical spend is $2,500 per month.\n")
        self.assertTrue(any(c["kind"] == "currency" and c["value"] == "$2,500" for c in cands))

    def test_multiplier(self):
        cands = extract_candidates("That is a 3x difference in repeat bookings.\n")
        self.assertTrue(any(c["kind"] == "multiplier" and c["value"] == "3x" for c in cands))

    def test_direct_quote_is_extracted(self):
        cands = extract_candidates('The council says "there are no extra permit requirements" for minor repairs.\n')
        quotes = [c for c in cands if c["kind"] == "quote"]
        self.assertEqual(len(quotes), 1)
        self.assertIn("no extra permit requirements", quotes[0]["text"])

    def test_short_scare_quotes_are_not_quote_claims(self):
        self.assertFalse([c for c in extract_candidates('The "best" washer is subjective.\n') if c["kind"] == "quote"])

    def test_platform_behaviour_sentence(self):
        cands = extract_candidates("Google indexes JavaScript-rendered schema without issue.\n")
        self.assertTrue(any(c["kind"] == "platform_behaviour" for c in cands))

    def test_comparative_sentence(self):
        cands = extract_candidates("Perplexity cites more sources than ChatGPT.\n")
        self.assertTrue(any(c["kind"] == "comparative" for c in cands))

    def test_plain_prose_yields_nothing(self):
        self.assertEqual(extract_candidates("I went for a walk with the dog. It was raining.\n"), [])


class LineNumbers(unittest.TestCase):
    def test_line_numbers_are_one_indexed_and_correct(self):
        stat = next(c for c in extract_candidates("line one\n\nAdoption hit 49% this year.\n") if c["value"] == "49%")
        self.assertEqual(stat["line"], 3)

    def test_line_numbers_after_frontmatter_and_in_blocks(self):
        md = ("---\ntitle: A\ndescription: Up 12% on last year.\n---\n\n## Costs\n\n"
              "> **TL;DR:** About $90 a visit.\n\nA plain line.\n\nJobs rose 30% in spring.\n")
        by_value = {c["value"]: c["line"] for c in extract_candidates(md) if c["kind"] in VALUE_KINDS}
        self.assertEqual(by_value["12%"], 3)
        self.assertEqual(by_value["$90"], 8)
        self.assertEqual(by_value["30%"], 12)


class Currency(unittest.TestCase):
    """Non-dollar currency is a value, not invisible."""

    def test_symbols_and_codes(self):
        md = ("A tap washer costs £450 in London, €1.2m buys the depot, A$300 covers a call-out, "
              "the app is US$20, and the annual fee is 450 GBP.\n")
        found = values(extract_candidates(md), "currency")
        for v in ("£450", "€1.2m", "A$300", "US$20", "450 GBP"):
            self.assertIn(v, found)

    def test_other_prefixes_and_code_before_number(self):
        md = "Quotes ran AU$1,200 here, NZ$900 there, AUD 300 for parts, USD 20 for the app and 15 EUR for postage.\n"
        found = values(extract_candidates(md), "currency")
        for v in ("AU$1,200", "NZ$900", "AUD 300", "USD 20", "15 EUR"):
            self.assertIn(v, found)

    def test_code_inside_a_word_is_not_currency(self):
        self.assertEqual(values(extract_candidates("Batch EURO3 shipped and GBPX12 too.\n"), "currency"), [])


    def test_comma_grouped_number_after_a_code_gives_no_phantom_count(self):
        cands = extract_candidates("Budget EUR1,000,000 and USD2,500,000.\n")
        self.assertEqual(values(cands, "count"), ["1,000,000", "2,500,000"])  # the whole number, never "000,000"
        self.assertEqual(values(cands, "currency"), ["EUR1,000,000", "USD2,500,000"])
        self.assertEqual(value_gaps("Budget EUR1,000,000.\n", {"claims": [{"text": "Budget EUR1,000,000"}]}), [])

    def test_mid_number_magnitude_is_not_a_count(self):
        self.assertEqual(values(extract_candidates("Raised 2.5M and 1,250,000 last year.\n"), "count"),
                         ["2.5M", "1,250,000"])

    def test_symbol_and_code_amounts_follow_one_rule(self):  # currency + count for both
        for md, money, count in (("Raised $900M last year.\n", "$900M", "900M"),
                                 ("Raised EUR1.5M last year.\n", "EUR1.5M", "1.5M"),
                                 ("Raised USD 3 million last year.\n", "USD 3", "3 million"),
                                 ("Raised €2.4M last year.\n", "€2.4M", "2.4M")):
            with self.subTest(md=md):
                cands = extract_candidates(md)
                self.assertEqual((values(cands, "currency"), values(cands, "count")), ([money], [count]))
                self.assertEqual(value_gaps(md, {"claims": [{"text": md.strip()}]}), [])

    def test_count_right_after_punctuation_is_kept(self):  # the lookbehind dropped these
        for md, count in (("Signups rose,1,548 of them new.\n", "1,548"), ("It ended.900M views later.\n", "900M"),
                          ("Totals:25k users.\n", "25k"), ("(1.4M) people.\n", "1.4M")):
            with self.subTest(md=md):
                self.assertEqual(values(extract_candidates(md), "count"), [count])

class NonBlogText(unittest.TestCase):
    """An email with no frontmatter and no headings."""

    EMAIL = ("Hi Sam,\n\nThanks for the quote. The hot water job came to £450, which is 20% under the last one.\n\n"
             "Our crew can start on Monday. Acme Plumbing reduced call-out times last winter.\n\n"
             "Cheers,\nAlex\n")

    def test_email_gives_body_candidates_only(self):
        cands = extract_candidates(self.EMAIL)
        self.assertTrue(cands)
        self.assertEqual({c["surface"] for c in cands}, {"body"})
        self.assertIn("£450", values(cands, "currency"))
        self.assertIn("20%", values(cands, "statistic"))

    def test_empty_and_blank_text(self):
        self.assertEqual(extract_candidates(""), [])
        self.assertEqual(extract_candidates("\n\n   \n"), [])
        self.assertEqual(value_gaps("", {}), [])


class Platforms(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)

    def project(self, toml: str) -> None:
        (self.cwd / ".plainspoken").mkdir(exist_ok=True)
        (self.cwd / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def test_shipped_list(self):
        self.assertEqual(platform_names(self.cwd), SHIPPED_PLATFORMS)

    def test_shipped_list_is_the_default(self):
        cands = extract_candidates("Instagram requires a business account for scheduling.\n")
        self.assertTrue(any(c["kind"] == "platform_behaviour" for c in cands))

    def test_platforms_extra(self):
        self.project('[claims]\nplatforms_extra = ["Acme CRM", "Google"]\n')
        names = platform_names(self.cwd)
        self.assertEqual(names, SHIPPED_PLATFORMS + ("Acme CRM",))
        text = "Acme CRM requires a paid seat for each technician.\n"
        self.assertFalse([c for c in extract_candidates(text) if c["kind"] == "platform_behaviour"])
        hits = [c for c in extract_candidates(text, names) if c["kind"] == "platform_behaviour"]
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0]["value"].startswith("Acme CRM"))

    def test_names_are_literal_not_regex(self):
        cands = extract_candidates("Fix.it (beta) supports bulk invoices.\n", ("Fix.it (beta)",))
        self.assertTrue(any(c["kind"] == "platform_behaviour" for c in cands))
        self.assertFalse([c for c in extract_candidates("Fixxit (beta) supports it.\n", ("Fix.it (beta)",))
                          if c["kind"] == "platform_behaviour"])

    def test_empty_platform_tuple_finds_no_platform_claims(self):
        cands = extract_candidates("Google indexes JavaScript-rendered schema.\n", ())
        self.assertFalse([c for c in cands if c["kind"] == "platform_behaviour"])

    def test_blank_platform_names_are_dropped(self):
        self.assertFalse([c for c in extract_candidates("Google indexes it. A requires B.\n", ("", "  "))
                          if c["kind"] == "platform_behaviour"])
        hits = [c for c in extract_candidates("Google indexes it.\n", ("", " ", "Google"))
                if c["kind"] == "platform_behaviour"]
        self.assertEqual([c["value"] for c in hits], ["Google indexes"])

    def test_malformed_config_raises(self):
        self.project('[claims]\nplatforms_extra = "Acme CRM"\n')
        with self.assertRaises(ConfigError):
            platform_names(self.cwd)


class AltText(unittest.TestCase):
    def test_value_in_alt_text(self):
        md = '![Chart: 37% of call-outs are burst pipes](chart.png)\n\n<img src="a.png" alt="A$300 average bill">\n'
        cands = extract_alt_text_candidates(md)
        self.assertEqual({(c["surface"], c["kind"], c["value"], c["line"]) for c in cands},
                         {("alt_text", "statistic", "37%", 1), ("alt_text", "currency", "A$300", 3)})

    def test_decorative_alt_yields_nothing(self):
        self.assertEqual(extract_alt_text_candidates("![A plumber at work](a.png)\n"), [])


class ValueGaps(unittest.TestCase):
    def test_unledgered_value_is_a_gap_and_ledgered_one_is_not(self):
        md = "Most installs cost $3,000.\n\nLabour runs 40% of the bill.\n"
        ledger = {"claims": [{"text": "Most installs cost $3,000"}], "exclusions": []}
        self.assertEqual([g["value"] for g in value_gaps(md, ledger)], ["40%"])

    def test_magnitude_forms_match(self):
        self.assertEqual(value_gaps("There were 900M searches.\n", {"claims": [{"text": "900 million searches"}]}), [])

    def test_notes_and_exclusions_cover(self):
        md = "Labour runs 40% of the bill and parts cost $250.\n"
        ledger = {"claims": [{"text": "Labour share", "notes": "40% per the invoice sample"}],
                  "exclusions": [{"text": "$250", "reason": "example figure"}]}
        self.assertEqual(value_gaps(md, ledger), [])

    def test_value_in_pinned_passage_is_not_a_gap(self):
        md = "The survey found 62% of homeowners skip gutter cleaning, and 18% never check the roof.\n"
        ledger = {"claims": [{"text": "Most homeowners skip gutter cleaning", "status": "verified",
                              "binding": {"passage": "62% of respondents said they skip it",
                                          "additional_passages": [{"passage": "18% have never checked"}]}}]}
        self.assertEqual(value_gaps(md, ledger), [])

    def test_quote_in_passage_is_not_a_gap(self):
        md = 'The council says "there are no extra permit requirements" for minor repairs.\n'
        ledger = {"claims": [{"text": "Council guidance on permits",
                              "binding": {"passage": "There are no extra permit requirements for minor repairs."}}]}
        self.assertEqual(value_gaps(md, ledger), [])
        self.assertEqual([g["kind"] for g in value_gaps(md, {"claims": []})], ["quote"])

    def test_value_only_in_removed_claim_is_a_gap(self):
        md = "Labour runs 40% of the bill.\n"
        ledger = {"claims": [{"text": "Labour runs 40% of the bill", "notes": "40%", "status": "removed",
                              "binding": {"passage": "40% labour"}}]}
        self.assertEqual([g["value"] for g in value_gaps(md, ledger)], ["40%"])

    def test_malformed_ledgers_never_crash(self):
        md = "Labour runs 40% of the bill.\n"
        for ledger in (None, {}, [], "x", {"claims": None}, {"claims": "40%"}, {"claims": [None, 3, "40%"]},
                       {"claims": [{"text": None, "notes": 7, "binding": "40%"}]},
                       {"claims": [{"binding": {"passage": None, "additional_passages": "40%"}}]},
                       {"claims": [{"binding": {"additional_passages": [None, "40%", {"passage": 5}]}}]},
                       {"exclusions": None}, {"exclusions": ["40%", None, {"text": None}]},
                       {"claims": [{"status": ["removed"], "text": "nothing"}]}):
            with self.subTest(ledger=ledger):
                self.assertEqual([g["value"] for g in value_gaps(md, ledger)], ["40%"])

    def test_no_break_space_in_passage_or_article(self):
        passage = {"claims": [{"text": "Search volume", "binding": {"passage": "about 900\xa0million searches"}}]}
        self.assertEqual(value_gaps("There were 900M searches.\n", passage), [])
        self.assertEqual(value_gaps("There were 900\xa0million searches.\n", {"claims": [{"text": "900 million"}]}),
                         [])

    def test_curly_and_straight_quotes_match(self):
        curly = "The council says \u201cwe don\u2019t need extra permit paperwork\u201d for minor repairs.\n"
        straight = "The council says \"we don't need extra permit paperwork\" for minor repairs.\n"
        ledger_straight = {"claims": [{"text": "Permits", "binding": {"passage": "We don't need extra permit paperwork."}}]}
        ledger_curly = {"claims": [{"text": "Permits",
                                    "binding": {"passage": "We don\u2019t need extra permit paperwork."}}]}
        self.assertEqual(value_gaps(curly, ledger_straight), [])
        self.assertEqual(value_gaps(straight, ledger_curly), [])
        self.assertEqual([g["kind"] for g in value_gaps(curly, {})], ["quote"])

    def test_platforms_pass_through(self):  # the names given reach extraction, and only those
        text = "Acme CRM requires 2 seats and costs 40% more.\n"
        cands = extract_candidates(text, ("Acme CRM",))
        self.assertIn(("platform_behaviour", "Acme CRM requires"), {(c["kind"], c["value"]) for c in cands})
        self.assertNotIn("platform_behaviour", {c["kind"] for c in extract_candidates(text, ("Other",))})
        # value_gaps passes them on: platform claims aren't value gaps, but the value candidates still are
        self.assertEqual([g["value"] for g in value_gaps(text, {}, ("Acme CRM",))], ["40%"])
        with unittest.mock.patch("plainspoken.extraction.extract_candidates", wraps=extract_candidates) as ex:
            value_gaps(text, {}, ("Acme CRM",))
        self.assertEqual(ex.call_args.args[1], ("Acme CRM",))


class Speed(unittest.TestCase):
    """The integrity hook runs value_gaps on every write of a target file, so a long file has to stay fast."""

    def test_one_long_line_stays_linear(self):  # each match re-sliced its whole line
        unit = "Roughly 62% of jobs cost under $450, more than last year because of Google ranking. "
        for name, md in (("body", "Intro.\n\n" + unit * (600_000 // len(unit))),
                         ("tldr", "> **TL;DR:** " + unit * (600_000 // len(unit)))):
            with self.subTest(name=name):
                start = time.perf_counter()
                extract_candidates(md)
                elapsed = time.perf_counter() - start
                self.assertLess(elapsed, 0.8, f"{name}: {elapsed:.2f}s on {len(md)} characters in one line")

    def test_300kb_file(self):
        block = (
            "## Costs in 2026\n\n"
            "> **TL;DR:** Roughly 62% of jobs cost under $450.\n\n"
            'The council says "there are no extra permit requirements" for minor repairs. Labour runs 40% '
            "of the bill, parts are £120 and the app is US$20. Google indexes the booking page and "
            "Perplexity cites more sources than Bing.\n\n"
            "| Job | Cost |\n|---|---|\n| Tap | $90 |\n| Hot water | A$1,200 |\n\n"
            '<figure><svg><text>Burst pipes 37%</text></svg><figcaption>900M views</figcaption></figure>\n\n'
            "Plain prose without figures keeps the ratio honest, and a second line of it helps.\n\n"
        )
        md = "---\ntitle: Long\ndescription: Up 12% on last year.\n---\n\n" + block * (300_000 // len(block) + 1)
        self.assertGreater(len(md), 300_000)
        start = time.perf_counter()
        gaps = value_gaps(md, {"claims": [{"text": "40%"}]})
        elapsed = time.perf_counter() - start
        self.assertTrue(gaps)
        self.assertLess(elapsed, 1.0, f"value_gaps took {elapsed:.2f}s on {len(md)} characters")


class Shape(unittest.TestCase):
    def test_candidate_shape_and_kinds(self):
        md = ("---\ndescription: Up 12% with v2.1.0.\n---\n\n> **TL;DR:** Google requires 3x more.\n\n"
              "## FAQ\n\nIt costs $9 because of tax, said \"the owner of the depot today\".\n")
        cands = extract_candidates(md)
        for c in cands:
            self.assertEqual(set(c), {"surface", "kind", "text", "value", "line"})
            self.assertIn(c["kind"], VALUE_KINDS + ("comparative", "causal", "platform_behaviour", "quote"))
        self.assertIn("faq", {c["surface"] for c in cands})
        self.assertIn("version", {c["kind"] for c in cands})


if __name__ == "__main__":
    unittest.main()
