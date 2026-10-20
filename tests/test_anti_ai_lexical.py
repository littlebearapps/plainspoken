"""tests/test_anti_ai_lexical.py — lexical rules: right severity, right line, quotes/allows respected."""
import dataclasses
import unittest

from plainspoken.checks_lexical import CHECKS
from plainspoken.doc import parse
from plainspoken.registry import load_config
from tests._profiles import PRODUCT, NARRATIVE, CONSULTING

CFG = load_config()


def run(rule: str, body: str, profile=PRODUCT, fm: str = ""):
    doc = parse(f"---\n{fm}---\n\n{body}\n", profile=profile)
    return CHECKS[rule](doc, CFG)


class EmDashes(unittest.TestCase):
    def test_three_is_fine_four_blocks(self):
        self.assertEqual(run("1", "A — b — c — d."), [])
        f = run("1", "A — b — c — d — e.")
        self.assertEqual([x.severity for x in f], ["BLOCK"])

    def test_narrative_cap_is_five(self):
        self.assertEqual(run("1", "A — b — c — d — e — f.", profile=NARRATIVE), [])
        self.assertEqual(run("NR-1", "A — b — c — d — e — f.", profile=NARRATIVE), [])
        self.assertEqual(len(run("NR-1", "A — b — c — d — e — f — g.", profile=NARRATIVE)), 1)

    def test_frontmatter_faq_dashes_count(self):
        fm = 'faqs:\n  - question: "Q?"\n    answer: "One — two — three — four."\n'
        self.assertEqual(len(run("1", "Plain body — here.", fm=fm)), 1)


class BanList(unittest.TestCase):
    def test_literal_word_and_inflection_block(self):
        f = run("2", "We utilised a robust approach.")
        self.assertEqual({x.severity for x in f}, {"BLOCK"})
        self.assertEqual(len(f), 2)

    def test_qualified_word_is_candidate(self):
        f = run("2", "The search landscape changed.")
        self.assertEqual([x.severity for x in f], ["CANDIDATE"])

    def test_quoted_span_is_info_not_block(self):
        f = run("2", 'The report said "this is a robust and reliable approach overall" and moved on.')
        self.assertEqual([x.severity for x in f], ["INFO"])

    def test_allow_marker_downgrades(self):
        body = '<!-- anti-ai-allow: 2 "robust" product name -->\nRobust Widgets Pty Ltd sponsored it.'
        self.assertEqual([x.severity for x in run("2", body)], ["INFO"])


class Transitions(unittest.TestCase):
    def test_academic_blocks(self):
        self.assertEqual([x.severity for x in run("4a", "Furthermore, it broke.")], ["BLOCK"])

    def test_conversational_thresholds(self):
        three = " ".join(["However, a."] * 1 + ["Specifically, b.", "Notably, c."])
        self.assertEqual({x.severity for x in run("4a2", three)}, {"WARN"})
        six = " ".join(["Specifically, a.", "Notably, b.", "In fact, c.", "Namely, d.", "Similarly, e.", "That said, f."])
        self.assertIn("BLOCK", {x.severity for x in run("4a2", six)})

    def test_however_cap(self):
        f = run("4a2", "However, a. However, b. However, c.")
        self.assertTrue(any("However" in x.message for x in f))

    def test_density_excludes_and_but(self):
        body = " ".join(["And then a.", "But b."] * 10)
        self.assertEqual(run("4b", body), [])
        body = " ".join(["Also, a.", "Plus b.", "Still c.", "So d.", "Then e.", "Now f.", "Next g.", "Instead h.", "Here i."])
        self.assertEqual([x.severity for x in run("4b", body)], ["BLOCK"])


class Candidates(unittest.TestCase):
    def test_optimise_is_candidate_only(self):
        f = run("27", "Image optimisation cut LCP. Optimise your engagement strategy.")
        self.assertEqual({x.severity for x in f}, {"CANDIDATE"})
        self.assertEqual(len(f), 2)

    def test_ghost_citation_with_link_is_ignored(self):
        self.assertEqual(run("12b", "Studies show [Google's own data](https://x.y) that it works."), [])
        self.assertEqual([x.severity for x in run("12b", "Studies show it works.")], ["CANDIDATE"])

    def test_cutoff_disclaimer_blocks(self):
        self.assertEqual([x.severity for x in run("20", "As of my last update, it was free.")], ["BLOCK"])


class Counts(unittest.TestCase):
    def test_claude_warn_total(self):
        self.assertEqual(run("2b", "Genuinely good. Particularly fast. Essentially done."), [])
        self.assertEqual(len(run("2b", "Genuinely good. Particularly fast. Essentially done. Arguably best.")), 1)

    def test_profile_bans_only_on_the_consulting_profile(self):
        self.assertEqual(run("PB", "An effortless turnkey fix.", profile=PRODUCT), [])
        self.assertEqual(len(run("PB", "An effortless turnkey fix.", profile=CONSULTING)), 2)

    def test_curly_quotes_warn(self):
        self.assertEqual([x.severity for x in run("24", "He said “hi” today.")], ["WARN"])


def run_cfg(rule: str, body: str, cfg, profile=PRODUCT):
    doc = parse(f"---\n---\n\n{body}\n", profile=profile)
    return CHECKS[rule](doc, cfg)


def with_lists(**lists):
    return dataclasses.replace(CFG, lists={**CFG.lists, **lists})


class Inflection(unittest.TestCase):
    """Ruling B1: e-ending single words match their base form and their inflections."""

    def test_e_ending_base_form_and_inflections(self):
        for text in ("We utilise it.", "We utilised it.", "We utilises it.", "Utilising it."):
            self.assertEqual([x.severity for x in run("2", text)], ["BLOCK"], text)

    def test_e_ending_word_does_not_match_a_longer_word(self):
        self.assertEqual(run("2", "The utilisation rate."), [])


class TransitionDensityCaps(unittest.TestCase):
    """4b: one word over transition_single_max (3) is WARN; the total over 8 is BLOCK."""

    def test_single_word_over_cap_warns(self):
        f = run("4b", "Also, a. Also, b. Also, c. Also, d.")
        self.assertEqual([x.severity for x in f], ["WARN"])
        self.assertIn("also", f[0].message)
        self.assertEqual(f[0].line, 4)

    def test_single_word_at_cap_is_fine(self):
        self.assertEqual(run("4b", "Also, a. Also, b. Also, c."), [])

    def test_total_over_cap_blocks_and_single_over_cap_warns(self):
        body = " ".join(["Also, a."] * 4 + ["Plus b.", "Still c.", "So d.", "Then e.", "Now f."])
        self.assertEqual(sorted(x.severity for x in run("4b", body)), ["BLOCK", "WARN"])

    def test_bold_and_curly_openers_count(self):
        # Bold- or quote-led sentences only split cleanly at a paragraph start (doc-model behaviour).
        self.assertEqual(len(run("4b", '**Also**, a.\n\n**Also**, b.\n\n"Also," c. Also, d.')), 1)

    def test_quoted_sentences_do_not_count(self):
        body = '> Also, a. Also, b. Also, c. Also, d.\n> — Jane Smith'
        self.assertEqual(run("4b", body), [])


class TotalOnlyOpeners(unittest.TestCase):
    """v4 (the maintainer, 2026-09-27, decision I3 revisited): Then / So / Now count toward the 4b total but never
    trip the per-word WARN. They read as his voice ("Then I went for a walk.")."""

    def test_then_so_now_have_no_per_word_warn(self):
        for w in ("Then", "So", "Now"):
            self.assertEqual(run("4b", " ".join(f"{w} a{i}." for i in range(5))), [], w)

    def test_they_still_count_toward_the_total(self):
        body = " ".join(["Then a.", "Then b.", "Then c.", "Then d.", "So e.", "So f.", "Now g.", "Now h.", "Also i."])
        self.assertEqual([x.severity for x in run("4b", body)], ["BLOCK"])

    def test_other_openers_still_warn_per_word(self):
        self.assertEqual([x.severity for x in run("4b", "Also, a. Also, b. Also, c. Also, d.")], ["WARN"])


class NoDoubleCounting(unittest.TestCase):
    """One occurrence counts once per rule, even when list entries overlap."""

    def test_meanwhile_in_two_lists_counts_once_in_4b(self):
        # "meanwhile" is in conversational_transitions AND density_extra_openers.
        self.assertEqual(run("4b", "Meanwhile, a. Meanwhile, b. Meanwhile, c."), [])
        f = run("4b", "Meanwhile, a. Meanwhile, b. Meanwhile, c. Meanwhile, d.")
        self.assertEqual(len(f), 1)
        self.assertIn("opens 4 sentences", f[0].message)

    def test_prefix_entries_in_one_list_count_once(self):
        cfg = with_lists(filler_phrases=["it is important to note", "it is important to note that", "in order to"])
        body = "It is important to note that a. In order to b. In order to c."
        f = run_cfg("23", body, cfg)
        self.assertEqual(len(f), 1)
        self.assertIn("3 (limit 2)", f[0].message)
        self.assertIn("it is important to note that ×1", f[0].message)

    def test_literal_and_qualified_lists_share_the_count(self):
        cfg = with_lists(ban_qualified=CFG.lists["ban_qualified"] + ["robust"])
        self.assertEqual([x.severity for x in run_cfg("2", "A robust wall.", cfg)], ["BLOCK"])

    def test_overlapping_real_entries_count_once_per_rule(self):
        body = "It represents a paradigm shift."
        self.assertEqual(len(run("12c", body)), 1)
        self.assertEqual(len(run("5c", body)), 1)
        self.assertEqual(len(run("2", body)), 1)

    def test_identical_frontmatter_fields_count_once(self):
        fm = 'title: "A — b — c"\nogTitle: "A — b — c"\n'
        self.assertEqual(run("1", "Body — here.", fm=fm), [])


class ListsComeFromRulesYaml(unittest.TestCase):
    """Rule-10 hedges and rule-27 forms are rules.toml lists."""

    def test_lists_exist(self):
        self.assertIn("it depends", CFG.lists["hedges"])
        self.assertEqual(CFG.lists["optimise_forms"], ["optimise", "optimize", "optimisation", "optimization"])

    def test_hedges_read_from_config(self):
        self.assertEqual([x.severity for x in run("10", "It depends on the site.")], ["CANDIDATE"])
        self.assertEqual(run_cfg("10", "It depends on the site.", with_lists(hedges=["who knows"])), [])

    def test_optimise_forms_read_from_config(self):
        self.assertEqual(run_cfg("27", "Optimise it.", with_lists(optimise_forms=["tweak"])), [])
        self.assertEqual(len(run("27", "We optimised it. The optimiser ran.")), 2)


class Allows(unittest.TestCase):
    def test_allow_on_a_hard_wrapped_paragraph_line(self):
        body = 'First line is plain.\n<!-- anti-ai-allow: 2 "robust" product name -->\nRobust Widgets Pty Ltd paid.'
        self.assertEqual([x.severity for x in run("2", body)], ["INFO"])

    def test_allow_does_not_leak_to_the_next_bullet(self):
        body = '- A robust thing.\n<!-- anti-ai-allow: 2 "robust" product name -->\n- Robust Widgets paid.'
        self.assertEqual(sorted(x.severity for x in run("2", body)), ["BLOCK", "INFO"])

    def test_allow_is_rule_specific(self):
        body = '<!-- anti-ai-allow: 5c "offers" product name -->\nRobust Widgets paid.'
        self.assertEqual([x.severity for x in run("2", body)], ["BLOCK"])

    def test_blockquote_allow_marker(self):
        body = '> <!-- anti-ai-allow: 2 "robust" product name -->\n> Robust Widgets paid.'
        self.assertEqual([x.severity for x in run("2", body)], ["INFO"])


class Edges(unittest.TestCase):
    def test_curly_apostrophe_matches(self):
        self.assertEqual([x.severity for x in run("4a", "It’s worth noting that it broke.")], ["BLOCK"])

    def test_in_todays_pattern_blocks_but_quoted_is_info(self):
        self.assertEqual([x.severity for x in run("4a", "In today's market it broke.")], ["BLOCK"])
        f = run("4a", 'He wrote "in today\'s market everything is different" once.')
        self.assertEqual([x.severity for x in f], ["INFO"])

    def test_rhetorical_question_as_its_own_sentence(self):
        self.assertEqual([x.severity for x in run("12", "The result? It broke.")], ["CANDIDATE"])

    def test_ghost_citation_link_in_another_sentence_still_flags(self):
        f = run("12b", "Studies show it works. See [the docs](https://x.y) for more.")
        self.assertEqual([x.severity for x in f], ["CANDIDATE"])

    def test_frontmatter_faq_second_sentence_opener_counts(self):
        fm = 'faqs:\n  - question: "Q?"\n    answer: "Yes. However, a. Specifically, b. Notably, c."\n'
        self.assertEqual({x.severity for x in run("4a2", "Body.", fm=fm)}, {"WARN"})

    def test_profile_ban_line_points_at_the_sentence(self):
        f = run("PB", "Intro.\n\nAn effortless fix.", profile=CONSULTING)
        self.assertEqual([x.line for x in f], [6])

    def test_curly_quotes_inside_code_fences_ignored(self):
        self.assertEqual(run("24", "Plain.\n\n```\nprint(“hi”)\n```"), [])

    def test_every_rule_id_registered(self):
        self.assertEqual(set(CHECKS) - set(CFG.rules), set())
        self.assertEqual(set(CHECKS), {"1", "2", "2b", "4a", "4a2", "4b", "5b", "5c", "5d", "8", "10", "11", "12",
                                       "12b", "12c", "14", "16", "20", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31", "32", "33", "PB",
                                       "NR-1"})



QUOTE = '> "{q}" — Jane Smith'


class FixRound1PatternRules(unittest.TestCase):
    """Item 1: regex-pattern hits honour the quote exemption and allow markers, like phrase hits."""

    SKELETON = "Despite its small size, the club faces several challenges"

    def test_22_skeleton_in_attributed_quote_is_info(self):
        f = run("22", QUOTE.format(q=self.SKELETON + " every year."))
        self.assertEqual([x.severity for x in f], ["INFO"])

    def test_22_skeleton_with_allow_is_info(self):
        body = f'<!-- anti-ai-allow: 22 "{self.SKELETON}" quoting the annual report -->\n{self.SKELETON} every year.'
        self.assertEqual([x.severity for x in run("22", body)], ["INFO"])

    def test_22_skeleton_still_blocks(self):
        self.assertEqual([x.severity for x in run("22", self.SKELETON + " every year.")], ["BLOCK"])

    def test_4a_pattern_allow_is_info(self):
        body = '<!-- anti-ai-allow: 4a "In today\'s market" book title -->\nIn today\'s market is a book.'
        self.assertEqual([x.severity for x in run("4a", body)], ["INFO"])

    def test_12_in_attributed_quote_is_info(self):
        f = run("12", QUOTE.format(q="On the one hand it works, on the other it breaks."))
        self.assertEqual([x.severity for x in f], ["INFO"])

    def test_26_pattern_in_attributed_quote_is_info(self):
        f = run("26", QUOTE.format(q="Here are the top 5 reasons it failed."))
        self.assertEqual([x.severity for x in f], ["INFO"])

    def test_16_in_attributed_quote_is_info(self):
        f = run("16", QUOTE.format(q="We went from small plumbers to big builders fast."))
        self.assertEqual([x.severity for x in f], ["INFO"])


class FixRound1Headings(unittest.TestCase):
    """Item 2: H2/H3 heading text is visible text."""

    def test_banned_word_in_heading_blocks(self):
        f = run("2", "Intro.\n\n## A robust guide\n\nBody.")
        self.assertEqual([(x.severity, x.line) for x in f], [("BLOCK", 6)])

    def test_heading_dashes_count_toward_cap(self):
        self.assertEqual(run("1", "## One — two\n\n### Three — four\n\nA — b."), [])
        self.assertEqual(len(run("1", "## One — two\n\n### Three — four\n\nA — b — c.")), 1)

    def test_headings_are_not_sentence_openers(self):
        body = "## Also a heading\n\n## Also another\n\nAlso, a. Also, b. Also, c."
        self.assertEqual(run("4b", body), [])
        self.assertEqual(run("4a2", "## However it went\n\n## Specifically this\n\nNotably, x."), [])
        self.assertEqual(run("26", "## Importantly, read this\n\nBody."), [])


class FixRound1AttributionDash(unittest.TestCase):
    """Item 3: the dash that IS the attribution marker doesn't count; dashes inside the quote do."""

    def test_attribution_dashes_do_not_count(self):
        body = QUOTE.format(q="First quote here.") + "\n\n" + QUOTE.format(q="Second quote here.") + "\n\nA — b — c."
        self.assertEqual(run("1", body), [])

    def test_dashes_inside_the_quote_still_count(self):
        body = QUOTE.format(q="Fast — really fast — always.") + "\n\nA — b."
        self.assertEqual(run("1", body), [])
        body = QUOTE.format(q="Fast — really fast — always.") + "\n\nA — b — c."
        self.assertEqual(len(run("1", body)), 1)

    def test_own_line_attribution_dash_does_not_count(self):
        body = '> "Quote one here."\n> — Jane Smith\n\nA — b — c — d.'
        self.assertEqual(run("1", body), [])


class FixRound1Minors(unittest.TestCase):
    def test_12b_link_late_in_a_long_sentence(self):
        pad = " ".join(["word"] * 40)
        body = f"Studies show {pad} and the data comes from [the ABS survey](https://abs.gov.au) itself."
        self.assertEqual(run("12b", body), [])

    def test_pattern_lists_match_curly_apostrophe(self):
        self.assertEqual([x.severity for x in run("4a", "In today’s market it broke.")], ["BLOCK"])

    def test_4b_next_js_is_not_an_opener(self):
        self.assertEqual(run("4b", "Next.js is fast. Next.js is big. Next.js is here. Next.js ships."), [])
        f = run("4b", "Next, a. Next b. Next, c.\n\n**Next**, d.")
        self.assertEqual([x.severity for x in f], ["WARN"])



class FollowUp4aClauseInitial(unittest.TestCase):
    """Review 2026-09-26 (042 false positive): connective phrases BLOCK only when they open a sentence/clause."""

    def test_mid_sentence_phrase_is_warn_not_block(self):
        f = run("4a", "I build websites too, so read this with that in mind.")
        self.assertEqual([x.severity for x in f], ["WARN"])

    def test_sentence_end_as_a_result_is_warn(self):
        self.assertEqual([x.severity for x in run("4a", "The page slowed as a result.")], ["WARN"])

    def test_sentence_opening_phrase_still_blocks(self):
        self.assertEqual([x.severity for x in run("4a", "With that in mind, I rebuilt it.")], ["BLOCK"])
        self.assertEqual([x.severity for x in run("4a", "As a result, the page slowed.")], ["BLOCK"])

    def test_clause_opening_after_comma_or_and_blocks(self):
        self.assertEqual([x.severity for x in run("4a", "It broke, therefore I fixed it.")], ["BLOCK"])
        self.assertEqual([x.severity for x in run("4a", "It broke; and as a result, I fixed it.")], ["BLOCK"])

    def test_anywhere_phrases_still_block_mid_sentence(self):
        self.assertEqual([x.severity for x in run("4a", "The trick, when it comes to ads, is patience.")], ["BLOCK"])

    def test_opener_only_list_is_subset_of_academic(self):
        self.assertLessEqual(set(CFG.lists["academic_opener_only"]), set(CFG.lists["academic_transitions"]))


class FollowUpExemptTerms(unittest.TestCase):
    """Review 2026-09-26 (the maintainer approved): fixed technical terms / product names don't trip rule 2."""

    def test_product_name_is_info(self):
        f = run("2", "Dynamic Search Ads campaigns weren't part of it.")
        self.assertEqual([x.severity for x in f], ["INFO"])
        self.assertIn("exempt", f[0].message)

    def test_technical_term_is_info(self):
        self.assertEqual([x.severity for x in run("2", "I wrote a test harness for it.")], ["INFO"])
        self.assertEqual([x.severity for x in run("2", "**Dynamic content injection.** Banners push text down.")], ["INFO"])

    def test_literal_trade_is_info(self):
        self.assertEqual([x.severity for x in run("2", "A Melbourne landscaper spent $1,200.")], ["INFO"])

    def test_same_word_outside_term_still_blocks(self):
        f = run("2", "A dynamic team uses a test harness.")
        self.assertEqual(sorted(x.severity for x in f), ["BLOCK", "INFO"])


class FollowUpMinors(unittest.TestCase):
    def test_ness_inflection(self):
        self.assertEqual([x.severity for x in run("2", "The robustness held.")], ["BLOCK"])
        self.assertEqual([x.severity for x in run("2", "Seamlessness matters.")], ["BLOCK"])

    def test_elevation_is_not_caught(self):
        self.assertEqual(run("2", "The ground sits at a high elevation."), [])

    def test_bold_counts_every_line_of_a_wrapped_paragraph(self):
        body = "One **a** line\nwrapped **b** **c** **d** **e** here and more words to pad it out a bit."
        f = run("24", body)
        self.assertTrue(any("5 bold spans" in x.excerpt for x in f))

    def test_curly_quotes_in_tilde_fence_and_inline_code_ignored(self):
        self.assertEqual(run("24", "~~~\n“curly”\n~~~\nText."), [])
        self.assertEqual(run("24", "Use `“smart”` quotes in code."), [])
        self.assertEqual([x.severity for x in run("24", "Use `code` and “this”.")], ["WARN"])


class Task4CarriedMinors(unittest.TestCase):
    """Minor cases carried over from an earlier review."""

    def test_in_quote_dash_before_a_hyphen_attribution_still_counts(self):
        # (a) only the attribution-marker dash is excluded; "— Then" inside the quote is prose.
        body = '> "We tried it — Then it broke." - Jane Smith\n\nA — b — c — d.'
        self.assertEqual(len(run("1", body)), 1)  # 1 in the quote + 3 = 4, over the cap of 3

    def test_quote_then_em_dash_attribution_still_excluded(self):
        body = '> "We tried it — then it broke." — Jane Smith\n\nA — b — c.'
        self.assertEqual(run("1", body), [])  # 1 + 2 = 3; the attribution dash would make it 4
        self.assertEqual(len(run("1", body.replace("A — b — c.", "A — b — c — d."))), 1)

    def test_own_line_attribution_after_an_in_quote_dash(self):
        body = '> "We tried it — Then it broke."\n> — Jane Smith\n\nA — b — c.'
        self.assertEqual(run("1", body), [])
        self.assertEqual(len(run("1", body.replace("A — b — c.", "A — b — c — d."))), 1)

    def test_banned_word_in_a_quote_ending_a_sentence_is_info(self):
        # The closing quote now stays with its sentence, so the mask applies.
        f = run("2", 'She said "our setup is robust and cheap." Then she left.')
        self.assertEqual([x.severity for x in f], ["INFO"])
        f = run("2", "She said “our setup is robust and cheap.” Then she left.")
        self.assertEqual([x.severity for x in f], ["INFO"])

    def test_inline_code_in_headings_is_not_linted(self):
        # (b) heading titles get doc.py's inline cleaning: code spans and link targets aren't prose.
        self.assertEqual(run("2", "## Set `robust: true` in the config\n\nBody."), [])
        self.assertEqual(run("2", "## Read [the guide](https://example.com/robust-setup)\n\nBody."), [])
        self.assertEqual([x.severity for x in run("2", "## A robust `config` guide\n\nBody.")], ["BLOCK"])


# Calibration: false positives found by `calibrate` on the published corpus (one regression test each).
RESOURCES = ("## Tools & Resources\n\n### Free tools\n\n"
             "- **[Google Search Console](https://search.google.com/search-console)** — see which searches show you\n"
             "- **[Schema Markup Validator](https://validator.schema.org/)** — checks your JSON-LD\n"
             "- **[Foo page](https://en.wikipedia.org/wiki/Foo_(bar))** — a URL with brackets in it\n\n"
             "### Checklists & templates\n\n"
             "- **Weekly self-search** — see the checklist above\n"
             "- **Test your listing** — paste this prompt:\n\n"
             "### Further reading\n\n"
             "- [Core Web Vitals guide](https://consulting.example/blog/cwv/) — what Google measures\n")


class Task11Calibration(unittest.TestCase):
    def test_resource_list_separator_dashes_do_not_count(self):  # 010: 22 → 12 em dashes
        self.assertEqual(run("1", "Body prose — once.\n\n" + RESOURCES), [])
        self.assertEqual(run("NR-1", "Body prose — once.\n\n" + RESOURCES + "- **A** — b\n", profile=NARRATIVE), [])

    def test_prose_dashes_inside_resources_still_count(self):
        body = RESOURCES + "\nA note — with — four — dashes — here.\n"
        self.assertEqual([f.severity for f in run("1", body)], ["BLOCK"])

    def test_second_dash_in_a_resource_item_counts(self):
        body = RESOURCES.replace("checks your JSON-LD", "checks — really — truly — your — JSON-LD")  # 4 after the separator
        self.assertEqual([f.severity for f in run("1", body)], ["BLOCK"])

    def test_a_dash_inside_a_resource_label_counts(self):  # resource label: `[A Person — SEO services](…) — …`
        body = RESOURCES + "".join(f"- [Name — part {i}](https://x.example/{i}) — text\n" for i in range(4))
        self.assertEqual([f.severity for f in run("1", body)], ["BLOCK"])

    def test_separator_dashes_outside_the_resources_section_count(self):
        body = "## Tools I use\n\n" + "".join(f"- **Tool {i}** — does a thing\n" for i in range(4))
        self.assertEqual([f.severity for f in run("1", body)], ["BLOCK"])

    def test_quoted_single_word_mention_goes_to_the_judge(self):  # 007: `No "passionate." No "innovative."`
        f = run("2", 'One sentence. No "passionate." No "innovative." Just the facts.')
        self.assertEqual([x.severity for x in f], ["CANDIDATE"])  # J3 passes a genuine mention

    def test_banned_word_used_inside_a_short_quote_still_blocks(self):
        self.assertEqual({x.severity for x in run("2", 'They sold an "innovative approach" to me.')}, {"BLOCK"})
        self.assertEqual({x.severity for x in run("2", 'An innovative "thing" here.')}, {"BLOCK"})

    def test_instead_of_is_a_preposition_not_a_connective(self):  # "Instead of X, do Y"
        body = " ".join(f"Instead of item {i}, name the thing." for i in range(4))
        self.assertEqual(run("4b", body), [])
        body = " ".join(f"Instead, I tried item {i}." for i in range(4))
        self.assertEqual([f.severity for f in run("4b", body)], ["WARN"])


class FinalReviewScareQuotes(unittest.TestCase):
    """Quote marks must not clear a banned word; only verbatim quotations stay INFO."""

    def test_scare_quoted_use_is_a_candidate(self):
        f = run("2", 'We built a "robust" system with "seamless" onboarding.')
        self.assertEqual([x.severity for x in f], ["CANDIDATE", "CANDIDATE"])
        self.assertIn("judge J3 decides", f[0].message)

    def test_curly_scare_quotes_are_a_candidate(self):
        self.assertEqual([x.severity for x in run("2", "A “robust” system.")], ["CANDIDATE"])

    def test_a_scare_quoted_hit_is_neither_block_nor_info(self):
        # Not a lint BLOCK (a genuine mention must be able to pass) and not INFO (J3 must see it).
        f = run("2", 'A "robust" system.')
        self.assertNotIn("BLOCK", {x.severity for x in f})
        self.assertNotIn("INFO", {x.severity for x in f})

    def test_four_word_verbatim_quote_stays_info(self):
        f = run("2", 'The vendor promised "a robust platform for everyone" and then went quiet.')
        self.assertEqual([x.severity for x in f], ["INFO"])

    def test_attributed_blockquote_stays_info(self):
        f = run("2", '> "This is a robust platform."\n> — Jane Citizen')
        self.assertEqual([x.severity for x in f], ["INFO"])

    def test_allow_marker_still_downgrades_a_quoted_word(self):
        body = '<!-- anti-ai-allow: 2 "robust" quoting the client brief -->\nThey asked for "robust" twice.'
        self.assertEqual([x.severity for x in run("2", body)], ["INFO"])


def count_2b(body: str) -> int:
    f = run("2b", body)
    return int(f[0].message.split(": ")[1].split()[0]) if f else 0


OTHERS = "It was arguably the best room. It was broadly fine. It was essentially done. It was potentially great."


class MultiSentenceQuotes(unittest.TestCase):
    """A quotation that runs over two or more sentences is quoted, so its words never count."""

    def test_issue_repro_one_sentence_quote(self):
        body = 'The librarian said: "We wanted a room that is genuinely useful for kids without a workbench at home."'
        self.assertEqual(count_2b(f"{body}\n\n{OTHERS}"), 4)

    def test_issue_repro_two_sentence_quote(self):
        body = 'The librarian said: "We wanted a room that is genuinely useful. It is there particularly for kids."'
        self.assertEqual(count_2b(f"{body}\n\n{OTHERS}"), 4)

    def test_quote_closed_two_sentences_later(self):
        body = ('The librarian said: "We wanted a room that is genuinely useful. It is there particularly for kids. '
                'It is a meaningful change." Then she left.')
        self.assertEqual(count_2b(f"{body}\n\n{OTHERS}"), 4)

    def test_curly_quote_spans_sentences(self):
        body = "The librarian said: “We wanted a room that is genuinely useful. It is there particularly for kids.”"
        self.assertEqual(count_2b(f"{body}\n\n{OTHERS}"), 4)

    def test_unclosed_quote_at_paragraph_end_not_quoted(self):
        body = 'The librarian said: "We wanted a room that is genuinely useful. It is there particularly for kids.'
        self.assertEqual(count_2b(f"{body}\n\n{OTHERS}"), 6)

    def test_quote_state_resets_per_paragraph(self):
        # An unclosed quote in one paragraph must not swallow the next paragraph up to its first quote mark.
        first = 'He wrote: "This one is genuinely odd. And so is this.'
        second = 'It was particularly busy. Then she said "no thanks" and left.'
        self.assertEqual(count_2b(f"{first}\n\n{second}\n\n{OTHERS}"), 6)

    def test_words_outside_the_quote_still_count(self):
        body = ('It was genuinely a surprise when the librarian said: "We wanted a genuinely useful room. It is for kids." '
                'She was particularly proud.')
        self.assertEqual(count_2b(f"{body}\n\n{OTHERS}"), 6)
        f = run("4a", 'Furthermore, the officer said: "We will keep the pool open. Moreover, it is warm."')
        self.assertEqual([x.severity for x in f], ["BLOCK", "INFO"])

    def test_stray_inch_mark_does_not_open_a_quote(self):
        # An inch mark must not pair with a later real quote and blank the sentences between.
        body = ('He stood 6\'2" in his socks. Furthermore, he was quick. The paper called him "the best ruckman in '
                'the league".')
        self.assertIn("BLOCK", [x.severity for x in run("4a", body)])
        body = ('The 12" board is cheap. It is genuinely good and particularly light. She said "it is the best '
                'board I have owned".')
        self.assertEqual(count_2b(f"{body}\n\n{OTHERS}"), 6)

    def test_closing_quote_before_a_letter_does_not_close(self):
        # A straight quote touching a letter on its right opens or is stray; it never closes a span early.
        body = ('The librarian said: "We wanted a room that is genuinely useful. It is there "particularly" for '
                'kids."')
        self.assertEqual(count_2b(f"{body}\n\n{OTHERS}"), 4)

    def test_every_count_rule_skips_a_multi_sentence_quote(self):
        quote = ('The minutes record it word for word: "However, we met in order to vote. However, we have the '
                 'ability to fund it due to the fact that numerous people asked. However, various groups and '
                 'countless swimmers wrote in. However, it is late. However, a range of options in order to help exist. In fact, it is '
                 'in the event that it rains." The vote passed.')
        for rule in ("23", "25", "4a2", "4b"):
            with self.subTest(rule=rule):
                self.assertEqual([x for x in run(rule, quote) if x.severity != "INFO"], [])
        # A sentence that opens inside the quote and goes on after it: its opener is quoted, its tail isn't.
        tail = ('However, it rained. However, it hailed. However, it snowed. He said: "We tried to stay for the '
                'whole day. However, it is late," and left.')
        self.assertEqual(run("4b", tail), [])
        bare = quote.replace('"', "")
        for rule in ("23", "25", "4a2", "4b"):
            with self.subTest(rule=rule, quoted=False):
                self.assertTrue([x for x in run(rule, bare) if x.severity != "INFO"])


if __name__ == "__main__":
    unittest.main()
