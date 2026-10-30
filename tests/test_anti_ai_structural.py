"""tests/test_anti_ai_structural.py — structural rules: rhythm, shape, markers and the 12f gate."""
import dataclasses
import unittest

from plainspoken.checks_lexical import CHECKS as LEXICAL
from plainspoken.checks_structural import CHECKS
from plainspoken.doc import parse
from plainspoken.registry import load_config
from tests._profiles import PRODUCT, NARRATIVE, CONSULTING

CFG = load_config()


def run(rule, body, profile=PRODUCT):
    return CHECKS[rule](parse(f"---\n---\n\n{body}\n", profile=profile), CFG)


def run_cfg(rule, body, cfg, profile=PRODUCT):
    return CHECKS[rule](parse(f"---\n---\n\n{body}\n", profile=profile), cfg)


def with_lists(**lists):
    return dataclasses.replace(CFG, lists={**CFG.lists, **lists})


def with_thresholds(**over):
    t = {k: dict(v) for k, v in CFG._thresholds.items()}
    t["default"].update(over)
    return dataclasses.replace(CFG, _thresholds=t)


LONG = "This sentence goes on for quite a while because it needs more than twenty five words to count as a long flowing sentence in the section."


class Structural(unittest.TestCase):
    def test_staccato_no_long_sentence_warns(self):
        body = "## A\n\nShort one here. Another short one. And a third."
        self.assertEqual([f.severity for f in run("7d", body)], ["WARN"])
        # Preflight C5: three sentences, so the section is actually assessed (two would be skipped).
        self.assertEqual(run("7d", f"## A\n\nShort one here. Another short one. {LONG}"), [])

    def test_narrative_staccato_relaxed(self):
        body = "## Match\n\n" + " ".join(["Goal kicked here."] * 6) + " This one runs to twenty one words so it clears the narrative threshold for a long sentence in narrative sections today."
        self.assertEqual(run("7d", body, profile=NARRATIVE), [])
        self.assertEqual([f.severity for f in run("7d", body)], ["WARN"])  # the same body fails the product profile's >25w check

    def test_uniform_sentence_run(self):
        body = "One two three four five. " * 5
        self.assertEqual([f.severity for f in run("7", body)], ["WARN"])

    def test_bold_first_bullets(self):
        body = "- **Security**: env config\n- **Speed**: fast\n- **Reliability**: breakers"
        self.assertEqual([f.severity for f in run("12e", body)], ["WARN"])

    def test_title_case_heading(self):
        self.assertEqual(len(run("13", "## How To Get Started With Workers\n\nText.")), 1)
        self.assertEqual(run("13", "## How Google Business Profile works\n\nText."), [])

    def test_ing_openers_consecutive_candidate(self):
        body = "Offering a lot, it works. Giving users data, it helps. Mixing speed, it wins."
        self.assertIn("CANDIDATE", {f.severity for f in run("5e", body)})

    def test_trailing_ing_candidate(self):
        f = run("19", "The tool shipped last week, highlighting the importance of observability.")
        self.assertEqual([x.severity for x in f], ["CANDIDATE"])

    def test_contraction_avoidance(self):
        body = "It is fine. Do not worry. It is not hard. I am sure. That is all. It cannot fail."
        self.assertEqual([f.severity for f in run("15", body)], ["WARN"])

    def test_human_markers_all_absent_warns(self):
        body = "The system processes requests. The system returns responses. Latency remains consistently low."
        self.assertEqual([f.severity for f in run("HM", body)], ["WARN"])
        self.assertEqual(run("HM", "I think it's fine. But not always."), [])

    def test_rhythm_remedies_fit_the_fix_rule(self):  # #30: a fix cuts, joins, splits or restates; it never adds
        staccato = run("7d", "## A\n\nShort one here. Another short one. And a third.")
        uniform = run("7", "One two three four five. " * 5)
        bursty = [f for f in run("12f", " ".join(["The cat sat on the mat."] * 60)) if f.excerpt.startswith("burstiness")]
        markers = run("HM", "The system processes requests. The system returns responses. Latency remains consistently low.")
        messages = [f.message for f in staccato + uniform + bursty + markers]
        self.assertEqual(len(messages), 4)
        self.assertTrue(staccato[0].message.endswith(
            'join two neighbours with "and" or "but" in their own words, or keep it; never pad one'))
        self.assertTrue(uniform[0].message.endswith(
            "join two neighbours or split one, in their own words, or keep it; never pad one"))
        self.assertIn("join or split sentences", bursty[0].message)
        self.assertIn("add nothing new", markers[0].message)
        for m in messages:
            self.assertNotRegex(m.lower(), r"run long|vary the rhythm|\badd (?!nothing|no )")

    def test_every_7d_message_gives_the_same_join_remedy(self):  # #73: a join padded a sentence or added a reason
        run5 = "## A\n\n" + " ".join(["Tiny one."] * 5) + " " + LONG
        faq7 = "## FAQ\n\n" + " ".join(["It is short."] * 7) + " " + LONG
        nar7 = "## Match\n\n" + " ".join(["Goal kicked here."] * 7)
        venue = "## Venue profile: Harbour Oval\n\n" + " ".join(["The stand faces west."] * 4)
        found = (run("7d", "## A\n\nShort one here. Another short one. And a third.") + run("7d", run5)
                 + run("7d", faq7) + run("7d", nar7, profile=NARRATIVE) + run("7d", venue, profile=NARRATIVE))
        self.assertEqual(len(found), 5)
        for f in found:
            self.assertIn('join two neighbours with "and" or "but" in their own words, or keep it; never pad one',
                          f.message)
            self.assertNotRegex(f.message, r"\b(?:so|because|merge)\b")  # "so" and "because" add a reason
            self.assertLessEqual(len(f.message), 140, f.message)  # the lint summary cuts a message at 140

    def test_narrative_paragraph_variation(self):
        para = " ".join(["word"] * 50)
        body = "\n\n".join([para + "."] * 4)
        self.assertEqual([f.severity for f in run("NR-5", body, profile=NARRATIVE)], ["WARN"])

    def test_12f_reports_metrics(self):
        body = " ".join(["The cat sat on the mat."] * 60)  # ruling B2: 360 words, over the 300-word floor
        sev = {f.severity for f in run("12f", body)}
        self.assertIn("BLOCK", sev)  # burstiness 0 blocks

    def test_12f_gates_on_mattr_not_raw_ttr(self):
        # 450 distinct letter-only words cycled 3× → raw TTR ≈ 0.33 (would fail 0.40),
        # but every 500-word window holds ~450 distinct words → MATTR ≈ 0.9 (passes). Decision I4.
        vocab = [a + b + c + d for a in "bcdfghjk" for b in "aeiou" for c in "lmnprst" for d in "aeiou"][:450]
        stream, lengths, sents, i, k = vocab * 3, [4, 22, 9, 31, 6, 17], [], 0, 0
        while i < len(stream):
            n = lengths[k % len(lengths)]
            sents.append(" ".join(stream[i:i + n]).capitalize() + ".")
            i, k = i + n, k + 1
        findings = run("12f", " ".join(sents))
        self.assertFalse(any(f.excerpt.startswith("mattr") for f in findings))  # ruling B3
        self.assertTrue(any(f.severity == "INFO" and "Raw TTR" in f.message for f in findings))


class StaccatoFaq(unittest.TestCase):
    """v4 (the maintainer, 2026-09-27): FAQs are checked like any other section, a little less strictly. Short answers are
    the point, so the "no sentence over 25 words" half doesn't apply; a run of short sentences still WARNs at
    staccato_faq_short_run (7) instead of 5. A `faqs:` frontmatter list, which a site may render as its FAQ, is checked
    too."""

    def test_faq_section_skips_the_no_long_sentence_half(self):
        body = "## FAQ\n\nIs it free? Yes, for now. Does it work offline? It does not."
        self.assertEqual(run("7d", body), [])
        self.assertEqual([f.severity for f in run("7d", body.replace("## FAQ", "## Notes"))], ["WARN"])

    def test_faq_heading_variants(self):
        for h in ("## FAQs", "## Frequently asked questions", "## FAQ: Google Ads"):
            self.assertEqual(run("7d", f"{h}\n\nIs it free? Yes, for now. Does it work? It does not."), [], h)

    def test_faq_short_run_warns_at_seven_not_five(self):
        six = "## FAQ\n\n" + " ".join(["It is short."] * 6) + " " + LONG
        seven = "## FAQ\n\n" + " ".join(["It is short."] * 7) + " " + LONG
        self.assertEqual(run("7d", six), [])
        self.assertEqual([f.severity for f in run("7d", seven)], ["WARN"])
        self.assertEqual([f.severity for f in run("7d", six.replace("## FAQ", "## Notes"))], ["WARN"])

    def test_ns_frontmatter_faqs_are_checked(self):
        answers = "".join(f"  - question: Question {i}?\n    answer: It is short. It is short.\n" for i in range(4))
        doc = parse(f"---\nfaqs:\n{answers}---\n\n{LONG}\n", profile=CONSULTING)
        self.assertEqual([f.severity for f in CHECKS["7d"](doc, CFG)], ["WARN"])  # 8 short answer sentences in a row
        fewer = "".join(f"  - question: Question {i}?\n    answer: It is short. {LONG}\n" for i in range(4))
        doc = parse(f"---\nfaqs:\n{fewer}---\n\n{LONG}\n", profile=CONSULTING)
        self.assertEqual(CHECKS["7d"](doc, CFG), [])


class BoldBullets(unittest.TestCase):
    def test_colon_inside_the_bold_warns(self):
        body = "- **Security:** env config\n- **Speed:** fast\n- **Reliability:** breakers"
        self.assertEqual([f.severity for f in run("12e", body)], ["WARN"])

    def test_two_is_fine_and_plain_bold_is_not_a_label(self):
        self.assertEqual(run("12e", "- **Security:** env\n- **Speed:** fast\n- plain item"), [])
        self.assertEqual(run("12e", "- **Bold** words in a row\n- **Bold** again\n- **Bold** thrice"), [])

    def test_bold_link_labels_are_the_ns_resources_format(self):
        body = ("- **[Google Search Console](https://search.google.com/search-console)** — free, and the source\n"
                "- **[PageSpeed Insights](https://pagespeed.web.dev/)**: checks speed\n"
                "- **[Rich Results Test](https://search.google.com/test/rich-results)** - checks schema\n"
                "- **[Bing Webmaster Tools](https://www.bing.com/webmasters)** — the Bing side")
        self.assertEqual(run("12e", body), [])

    def test_plain_labels_still_warn_next_to_the_rule(self):
        body = "- **Security:** env\n- **Security:** env\n- **Security:** env"
        self.assertEqual([f.severity for f in run("12e", body)], ["WARN"])

    def test_code_fences_are_ignored(self):
        body = "```md\n- **A:** x\n- **B:** y\n- **C:** z\n```"
        self.assertEqual(run("12e", body), [])


class Staccato(unittest.TestCase):
    def test_short_run_warns_even_with_a_long_sentence(self):
        body = "## A\n\n" + " ".join(["Tiny one."] * 5) + " " + LONG
        f = run("7d", body)
        self.assertEqual([x.severity for x in f], ["WARN"])
        self.assertIn("5 consecutive", f[0].message)

    def test_two_sentence_section_is_not_assessed(self):
        self.assertEqual(run("7d", "## A\n\nShort one. Another."), [])

    def test_narrative_warns_only_on_run_and_no_long_sentence(self):
        # Decision I5: the narrative profile is relaxed across the whole article — WARN needs BOTH 7+ short AND none >20w.
        short_only = "## Match\n\n" + " ".join(["Goal kicked here."] * 4)
        self.assertEqual(run("7d", short_only, profile=NARRATIVE), [])
        seven = "## Match\n\n" + " ".join(["Goal kicked here."] * 7)
        self.assertEqual([x.severity for x in run("7d", seven, profile=NARRATIVE)], ["WARN"])

    def test_narrative_venue_profile_keeps_the_over_20_check(self):
        body = "## Venue profile: Harbour Oval\n\n" + " ".join(["The stand faces west."] * 4)
        f = run("7d", body, profile=NARRATIVE)
        self.assertEqual([x.severity for x in f], ["WARN"])
        self.assertIn("20", f[0].message)

    def test_nr2_mirrors_7d_on_the_narrative_profile_only(self):
        seven = "## Match\n\n" + " ".join(["Goal kicked here."] * 7)
        self.assertEqual([x.rule for x in run("NR-2", seven, profile=NARRATIVE)], ["NR-2"])
        self.assertEqual(run("NR-2", seven), [])


class TitleCase(unittest.TestCase):
    def test_after_colon_is_sentence_start(self):
        self.assertEqual(run("13", "## Pricing: The basics\n\nText."), [])

    def test_after_a_question_mark_is_sentence_start(self):
        self.assertEqual(run("13", "## My site gets no enquiries. Why?\n\nText."), [])
        self.assertEqual(run("13", "## Is my copy generic? The swap test\n\nText."), [])

    def test_single_letter_a_is_title_case(self):
        self.assertEqual(len(run("13", "## Why A Cache Beats A Queue\n\nText.")), 1)
        self.assertEqual(len(run("13", "## Building A Better Cache\n\nText.")), 1)

    def test_real_acronyms_alone_are_not_title_case(self):
        self.assertEqual(run("13", "## Why SEO Needs GA4\n\nText."), [])
        self.assertEqual(run("13", "## Why IT and AI teams skip this\n\nText."), [])

    def test_acronyms_are_not_title_case(self):
        self.assertEqual(run("13", "## Why IT teams skip this\n\nText."), [])

    def test_inline_code_is_not_a_word(self):
        self.assertEqual(run("13", "## Using `For` loops in Workers\n\nText."), [])


class IngRules(unittest.TestCase):
    def test_trailing_ing_verbs_come_from_rules_toml(self):
        self.assertIn("highlighting", CFG.lists["trailing_ing_verbs"])
        text = "The tool shipped last week, highlighting the importance of observability."
        self.assertEqual(run_cfg("19", text, with_lists(trailing_ing_verbs=["whistling"])), [])
        self.assertEqual(len(run_cfg("19", "It shipped, whistling a merry tune all day.",
                                     with_lists(trailing_ing_verbs=["whistling"]))), 1)

    def test_multi_word_trailing_entry(self):
        self.assertEqual(len(run("19", "We cut the cache, making it far easier to debug.")), 1)

    def test_trailing_ing_in_a_quote_is_info(self):
        f = run("19", 'She said "we shipped it early, highlighting the importance of tests."')
        self.assertEqual([x.severity for x in f], ["INFO"])

    def test_ing_stop_comes_from_rules_toml(self):
        self.assertIn("nothing", CFG.lists["ing_stop"])
        body = "Nothing works here. Nothing helps there. Nothing wins."
        self.assertEqual(run("5e", body), [])
        self.assertEqual(len(run_cfg("5e", body, with_lists(ing_stop=[]))), 2)  # section count + consecutive run

    def test_two_ing_openers_are_fine(self):
        self.assertEqual(run("5e", "Offering a lot, it works. Giving users data, it helps. The end."), [])

    def test_quoted_sentences_do_not_count_as_ing_openers(self):
        quote = '> "Offering a lot, it works. Giving users data, it helps. Mixing speed, it wins." — Jane Smith'
        self.assertEqual(run("5e", quote + "\n\nThe end."), [])
        self.assertEqual(len(run("5e", quote.replace("> ", "").replace('"', "").replace(" — Jane Smith", ""))), 2)


class Markers(unittest.TestCase):
    def test_curly_contraction_is_a_marker(self):
        body = "The system processes requests. The system returns responses. Latency isn’t consistently low."
        self.assertEqual(run("HM", body), [])

    def test_capitalised_my_is_first_person(self):
        body = "My system processes requests. The system returns responses. Latency remains consistently low."
        self.assertEqual(run("HM", body), [])

    def test_curly_contractions_count_against_rule_15(self):
        body = "It is fine. Do not worry. It is not hard. I am sure. That is all. It cannot fail. " + \
               " ".join(["It’s ok."] * 9)
        self.assertEqual(run("15", body), [])


def _low_vocab():
    """712 words from a five-word vocabulary, with varied sentence lengths (burstiness ≈ 0.64)."""
    words, sents, k = ["alpha", "beta", "gamma", "delta", "omega"], [], 0
    for n in [4, 22, 9, 31, 6, 17] * 8:
        sents.append(" ".join(words[(k + j) % 5] for j in range(n)).capitalize() + ".")
        k += n
    return " ".join(sents)


def _openers_piece(paragraphs, i_openers):
    """Paragraphs of four sentences (6, 30, 10 and 22 words, so every paragraph is 68 words: paragraph SD 0).
    `i_openers` sentences open with "I"; every other sentence opens with its own word, and no body word repeats."""
    vocab = (a + b + c + d for a in "bcdfghjklm" for b in "aeiou" for c in "lmnprstvz" for d in "aeiou")
    sents = []
    for k in range(paragraphs * 4):
        n = [6, 30, 10, 22][k % 4]
        first = "I" if k < i_openers else next(vocab).capitalize()
        sents.append(" ".join([first] + [next(vocab) for _ in range(n - 1)]) + ".")
    return "\n\n".join(" ".join(sents[i:i + 4]) for i in range(0, len(sents), 4))

class SlopGate(unittest.TestCase):
    LOW_VOCAB = _low_vocab()

    def test_under_300_words_is_not_assessed(self):
        self.assertEqual(run("12f", " ".join(["The cat sat on the mat."] * 40)), [])

    def test_low_mattr_warns_while_not_blocking(self):
        f = [x for x in run_cfg("12f", self.LOW_VOCAB, with_thresholds(mattr_blocking=False)) if x.excerpt.startswith("mattr")]
        self.assertEqual([x.severity for x in f], ["WARN"])

    def test_low_mattr_blocks_once_calibrated(self):
        f = [x for x in run_cfg("12f", self.LOW_VOCAB, with_thresholds(mattr_blocking=True)) if x.excerpt.startswith("mattr")]
        self.assertEqual([x.severity for x in f], ["BLOCK"])

    def test_low_mattr_warning_names_the_most_repeated_words(self):  # v4, the maintainer, 2026-09-27
        f = [x for x in run("12f", self.LOW_VOCAB) if x.excerpt.startswith("mattr")][0]
        self.assertIn("Most repeated:", f.message)
        for w in ("alpha", "beta", "gamma"):
            self.assertIn(w, f.message)
        self.assertRegex(f.message, r"alpha ×\d+")

    def test_repeated_terms_skip_function_words_and_short_counts(self):
        from plainspoken import metrics
        body = " ".join(["The profile was suspended and the profile was restored by the team."] * 6)
        body += " A rare word appears twice. A rare word again."
        terms = metrics.repeated_words(parse(f"---\n---\n\n{body}\n", profile=CONSULTING), CFG)
        words = [w for w, _ in terms]
        self.assertEqual(words[0], "profile")
        self.assertNotIn("the", words)
        self.assertNotIn("was", words)
        self.assertNotIn("rare", words)  # 2 uses: under the minimum

    def test_slop_warning_names_only_the_tripped_metrics(self):  # #26; the opening limit is 0 + 3/48 openers (#25)
        cfg = with_thresholds(opening_top3_max=0.0, paragraph_sd_min=1000, capsule_transition_max=1.0, mattr_min=0.0)
        (f,) = [x for x in run_cfg("12f", self.LOW_VOCAB, cfg) if "slop metrics tripped" in x.message]
        self.assertEqual(f.severity, "WARN")
        self.assertRegex(f.message, r"^2 slop metrics tripped: opening repetition [\d.]+ > 0\.062; paragraph SD [\d.]+ < 1000 — cut, join or split; never pad$")
        self.assertNotIn("capsule", f.message)
        self.assertNotIn("MATTR", f.message)

    def test_short_piece_opening_limit_scales_with_length(self):  # #25
        # 340 words, 20 sentences, 5 open with "I": share 7/20 = 0.35. Over the flat 0.25, but top-3 share can't
        # fall below 3/20, so the limit is 0.25 + 0.15 = 0.40. Paragraph SD 0 alone is one trip: no WARN.
        f = run("12f", _openers_piece(5, 5))
        self.assertFalse(any("slop metrics tripped" in x.message for x in f), [x.message for x in f])

    def test_long_piece_with_the_same_opening_habit_still_warns(self):  # #25
        # 1,020 words, 60 sentences, 18 open with "I": share 20/60 = 0.33 > 0.25 + 3/60 = 0.30, plus paragraph SD 0.
        (f,) = [x for x in run("12f", _openers_piece(15, 18)) if "slop metrics tripped" in x.message]
        self.assertRegex(f.message, r"^2 slop metrics tripped: opening repetition 0\.333 > 0\.3; paragraph SD 0 < 25 — cut, join or split; never pad$")

    def test_varied_prose_has_no_burstiness_block(self):
        f = run("12f", self.LOW_VOCAB)
        self.assertFalse(any(x.excerpt.startswith("burstiness") for x in f))


class PatternRules(unittest.TestCase):
    def test_not_just_construction(self):
        self.assertEqual([x.severity for x in run("7c", "It's not just a cache, it's a lifeline.")], ["CANDIDATE"])
        self.assertEqual([x.severity for x in run("7c", 'She said "it is not just a cache, it\'s a lifeline" once.')],
                         ["INFO"])

    def test_trailing_ing_allow_marker(self):
        body = '<!-- anti-ai-allow: 19 "highlighting" quoting the changelog verbatim -->\n' \
               "The tool shipped last week, highlighting the importance of observability."
        self.assertEqual([x.severity for x in run("19", body)], ["INFO"])

    def test_trailing_ing_needs_the_comma(self):
        self.assertEqual(run("19", "Creating tests is the job I put off longest."), [])

    def test_press_release_opener(self):
        f = run("7b", "Launched 3 features across 2 sprints, the team shipped.\n\nMore text.")
        self.assertEqual([x.severity for x in f], ["CANDIDATE"])
        self.assertEqual(run("7b", "I shipped three features last month.\n\nLaunched 3 features across 2 sprints."), [])

    def test_triplets_rate(self):
        body = "I like red, green and blue. " * 3 + " ".join(["Plain words here."] * 400)
        self.assertEqual(run("6", body), [])  # 3 in 1,215 words is under 3 per 1,000
        self.assertEqual(len(run("6", "I like red, green and blue. I tried cats, dogs or fish.")), 2)

    def test_quoted_triplet_does_not_count(self):
        self.assertEqual(run("6", 'She said "we like red, green and blue here" and left.'), [])


class Paragraphs(unittest.TestCase):
    def test_uniform_paragraph_run(self):
        para = " ".join(["word"] * 40)
        body = "\n\n".join([para + "."] * 4)
        self.assertEqual([x.severity for x in run("12d", body)], ["WARN"])
        varied = "\n\n".join([" ".join(["word"] * n) + "." for n in (10, 40, 90, 25)])
        self.assertEqual(run("12d", varied), [])

    def test_faq_run_threshold(self):  # the FAQ-only knob
        para = " ".join(["word"] * 40) + "."
        four = "\n\n".join([para] * 4)
        self.assertEqual(CFG.thresholds(PRODUCT)["paragraph_uniform_faq_run"], CFG.thresholds(PRODUCT)["paragraph_uniform_run"])
        for heading in ("## FAQ", "## Notes"):  # at the shipped value a FAQ run fires like any other
            self.assertEqual([x.severity for x in run("12d", f"{heading}\n\n{four}")], ["WARN"], heading)
        loose = with_thresholds(paragraph_uniform_faq_run=6)
        self.assertEqual(run_cfg("12d", f"## FAQ\n\n{four}", loose), [])
        self.assertEqual(run_cfg("12d", f"## FAQ\n\n### Is it free?\n\n{four}", loose), [])  # an H3 under FAQ
        self.assertEqual([x.severity for x in run_cfg("12d", f"## Notes\n\n{four}", loose)], ["WARN"])
        six = "\n\n".join([para] * 6)
        (f,) = run_cfg("12d", f"## FAQ\n\n{six}", loose)
        self.assertIn("6+ consecutive paragraphs", f.message)

    def test_the_run_takes_the_threshold_of_the_section_it_starts_in(self):
        para = " ".join(["word"] * 40) + "."
        loose = with_thresholds(paragraph_uniform_faq_run=6)
        body = f"## Notes\n\n{para}\n\n{para}\n\n## FAQ\n\n{para}\n\n{para}"
        (f,) = run_cfg("12d", body, loose)  # starts in Notes, so 4 is enough
        self.assertIn("4+ consecutive paragraphs", f.message)

    def test_the_faq_test_is_the_section_facet(self):
        from plainspoken import capture
        from plainspoken.checks_structural import in_faq
        body = "## FAQ\n\n### Is it free?\n\nYes.\n\n## Notes\n\nA note.\n"
        doc = parse(f"---\n---\n\n{body}", profile=PRODUCT)
        for line in range(3, len(doc.lines) + 1):  # body lines (frontmatter is capture's own case)
            self.assertEqual(in_faq(doc, line), capture.section_of(line, doc) == "faq", line)

    def test_narrative_paragraph_variation_passes_with_short_and_long(self):
        body = "Short para here.\n\n" + " ".join(["word"] * 90) + "."
        self.assertEqual(run("NR-5", body, profile=NARRATIVE), [])
        self.assertEqual(run("NR-5", " ".join(["word"] * 50) + "."), [])  # narrative profile only


class NarrativeOpinion(unittest.TestCase):
    def test_opinion_marker(self):
        self.assertEqual([x.severity for x in run("NR-6", "The grandstand was ugly, I reckon.", profile=NARRATIVE)],
                         ["CANDIDATE"])
        self.assertEqual([x.severity for x in run("NR-6", "The grandstand opened in 1906.", profile=NARRATIVE)], ["WARN"])
        self.assertEqual(run("NR-6", "The grandstand opened in 1906."), [])


class MarkerEdges(unittest.TestCase):
    def test_table_cells_are_not_fragments(self):
        body = "The system processes requests. The system returns responses. Latency remains consistently low.\n\n" \
               "| Metric | Value |\n|---|---|\n| p95 | 20 |"
        self.assertEqual([x.severity for x in run("HM", body)], ["WARN"])

    def test_short_bullets_are_not_fragments(self):
        body = "The system processes requests. The system returns responses. Latency remains consistently low.\n\n" \
               "- Fast\n- Cheap"
        self.assertEqual([x.severity for x in run("HM", body)], ["WARN"])

    def test_quoted_expanded_forms_do_not_count(self):
        quote = '> "It is fine. Do not worry. It is not hard. I am sure. That is all." — Jane Smith'
        self.assertEqual(run("15", quote + "\n\nText."), [])


class Registry(unittest.TestCase):
    def test_check_ids(self):
        self.assertEqual(set(CHECKS), {"5e", "6", "7", "7b", "7c", "7d", "12d", "12e", "12f", "13", "15",
                                       "19", "HM", "NR-2", "NR-5", "NR-6"})
        self.assertFalse(set(CHECKS) & set(LEXICAL))
        for rid in CHECKS:
            self.assertIn(rid, CFG.rules)
            self.assertIn(CFG.rules[rid].method, ("lint", "lint+judge"))


class Task11Calibration(unittest.TestCase):
    def test_bold_labels_in_tools_and_resources_are_house_format(self):  # a Tools & Resources label
        body = ("## Tools & Resources\n\n### Sample prompts\n\n"
                "- **Test what AI says** — paste this into ChatGPT\n"
                "- **Test your service area** — paste into Claude\n"
                "- **The you-not-we flip** - paste your about intro\n")
        self.assertEqual(run("12e", body), [])

    def test_bold_labels_after_the_resources_section_still_warn(self):
        body = ("## Tools & Resources\n\n- **[A](https://a.example)** — x\n\n## FAQ\n\n"
                "- **Security:** env\n- **Speed:** fast\n- **Reliability:** breakers\n")
        self.assertEqual([f.severity for f in run("12e", body)], ["WARN"])

    def test_bold_link_label_with_brackets_in_the_url(self):  # `[^)]*` stopped at the first `)`
        body = "\n".join(f"- **[Page {i}](https://en.wikipedia.org/wiki/Foo_(bar_{i}))** — about it" for i in range(3))
        self.assertEqual(run("12e", body), [])

    def test_calibrated_mattr_floor_warns(self):  # v4 (the maintainer, 2026-09-27): the floor stays, as a WARN, not a BLOCK
        self.assertFalse(CFG.thresholds(CONSULTING)["mattr_blocking"])
        f = [x for x in run("12f", _low_vocab()) if x.excerpt.startswith("mattr")]
        self.assertEqual([x.severity for x in f], ["WARN"])

    def test_list_continuation_lines_are_not_prose_rhythm(self):  # a prompt under a bullet read as prose
        body = (LONG + "\n\n- **Prompt** — paste this:\n"
                "  *\"Read this headline. Say what it sells. Say who for. Say where. Be blunt.\"*\n"
                "  Compare the answers.\n")
        self.assertEqual(run("7", body), [])
        self.assertEqual(run("7d", body), [])


class MultiSentenceQuotes(unittest.TestCase):
    """Structural count rules skip a quotation that runs over two or more sentences."""
    CASES = {
        "5e": 'She said: "Building it was slow. Running it is slower. Fixing it is slowest. Keeping it going is '
              'worse." Then she left.',
        "6": 'She said: "We need bread for the week. We need milk, eggs and flour. We need time." Then she left.',
        "15": 'He wrote: "It is late in the day. We do not know. It does not help. That is all. We cannot stay." '
              'Then he left.',
    }

    def test_quoted_sentences_do_not_count(self):
        for rule, body in self.CASES.items():
            with self.subTest(rule=rule):
                self.assertEqual(run(rule, body), [])

    def test_the_same_sentences_unquoted_do_count(self):
        for rule, body in self.CASES.items():
            with self.subTest(rule=rule):
                self.assertTrue(run(rule, body.replace('"', "")))

    def test_a_sentence_opening_inside_the_quote_is_skipped(self):
        # Two -ing openers of my own, a third inside a quote whose closing sentence goes on after it.
        body = ('Running it was slow. Fixing it was slower. He said: "We tried to keep the whole thing going. '
                'Keeping it going is worse," and left.')
        self.assertEqual(run("5e", body), [])
        self.assertTrue(run("5e", body.replace('"', "")))
