import re
import unittest
from pathlib import Path

from scripts.dev.lint_frontmatter import parse_frontmatter

REPO = Path(__file__).resolve().parents[1]
AGENT = REPO / "agents" / "tells-judge.md"


class TellsJudge(unittest.TestCase):
    def setUp(self):
        self.text = AGENT.read_text(encoding="utf-8")
        self.fm = parse_frontmatter(self.text)

    def test_isolation(self):
        self.assertEqual(self.fm["name"], "tells-judge")
        self.assertEqual({t.strip() for t in self.fm["tools"].split(",")}, {"Read", "Grep", "Glob"})
        self.assertEqual(self.fm.get("omitClaudeMd"), "true")
        self.assertNotIn("memory", self.fm)

    def test_knows_jr_and_output_contract(self):
        self.assertIn("## JR Justification review", self.text)
        for needle in ('"group"', '"article_sha256"', '"verdicts"', '"justify_sha256"', "SubagentHandback"):
            self.assertIn(needle, self.text)

    def test_never_writes_or_suggests(self):
        self.assertIn("never edit", self.text.lower())
        self.assertIn("never suggest", self.text.lower())

    def test_jr_paragraph_names_rubric_and_notes(self):
        jr = self.text.split("## JR mode")[1]
        for needle in ("`rubric`", "`calibration_notes`", "`items`", "`justify_sha256`"):
            self.assertIn(needle, jr)

    def test_inputs_carry_severities_not_profile(self):
        inputs = self.text.split("## Inputs", 1)[1].split("## Steps", 1)[0]
        self.assertIn("`severities`", inputs)
        self.assertNotIn("`profile`", inputs)
        self.assertIn("severity given for the rule in your input", self.text)


COLD_READER = REPO / "agents" / "cold-reader.md"


class ColdReader(unittest.TestCase):
    def setUp(self):
        self.text = COLD_READER.read_text(encoding="utf-8")
        self.fm = parse_frontmatter(self.text)

    def test_isolation(self):
        self.assertEqual(self.fm["name"], "cold-reader")
        self.assertEqual({t.strip() for t in self.fm["tools"].split(",")}, {"Read"})
        self.assertEqual(self.fm.get("omitClaudeMd"), "true")
        self.assertNotIn("memory", self.fm)

    def test_reports_only(self):
        lower = self.text.lower()
        for needle in ("never rewrite", "never suggest", "you don't know who wrote"):
            self.assertIn(needle, lower)

    def test_output_contract(self):
        for key in ('"summary"', '"lost"', '"terms"', '"next"', '"quote"', '"why"'):
            self.assertIn(key, self.text)

    def test_json_only_no_fence_no_prose(self):  # the parser takes one bare JSON object
        body = self.text.split("\n---\n", 1)[1]
        self.assertIn("Reply with ONLY this JSON object (no prose, no code fence)", " ".join(body.split()))
        self.assertNotIn("```", body)  # the example itself isn't fenced, so a copy of it isn't either

    def test_named_by_plain_language(self):
        skill = (REPO / "skills" / "plain-language" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("plainspoken:cold-reader", skill)
        self.assertIn("Reader:", skill)
        self.assertIn("File:", skill)


CLAIMS_CHECKER = REPO / "agents" / "claims-checker.md"


class ClaimsChecker(unittest.TestCase):
    def setUp(self):
        self.text = CLAIMS_CHECKER.read_text(encoding="utf-8")
        self.fm = parse_frontmatter(self.text)

    def test_isolation(self):
        self.assertEqual(self.fm["name"], "claims-checker")
        self.assertEqual([t.strip() for t in self.fm["tools"].split(",")], ["Read", "Grep", "Glob"])
        self.assertEqual(self.fm.get("model"), "opus")
        self.assertEqual(self.fm.get("omitClaudeMd"), "true")
        self.assertNotIn("memory", self.fm)

    def test_points_at_the_rubric(self):
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/data/rubrics/claims.md", self.text)
        self.assertTrue((REPO / "data" / "rubrics" / "claims.md").is_file())

    def test_input_contract_and_no_author(self):
        for needle in ("`article`", "`ledger`", "`rubric`", "`regulated_matrix`", "`article_sha256`",
                       "`ledger_sha256`", "`matrix_sha256`", "SubagentHandback"):
            self.assertIn(needle, self.text)
        self.assertIn("never edit", self.text.lower())
        self.assertIn("Copy all three verbatim into your reply", self.text)
        self.assertNotRegex(self.text.lower(), r"written by|wrote (this|the) article")

    def test_rubric_classes_are_a_fixed_list(self):
        rubric = (REPO / "data" / "rubrics" / "claims.md").read_text(encoding="utf-8")
        section = rubric.split("## Classes", 1)[1].split("\n## ", 1)[0]
        rows = re.findall(r"(?m)^\| `([a-z_]+)` \|", section)
        for name in ("unsupported_claim", "entailment_gap", "unledgered_claim", "fabricated_quote", "scope_stretch",
                     "other"):
            self.assertIn(name, rows)
        self.assertEqual(rows[-1], "other")
        self.assertIn("never invent a class", section.lower())
        self.assertIn("matrix", section)

    def test_severity_names_scope_stretch(self):  # the class has a severity like the others
        rubric = (REPO / "data" / "rubrics" / "claims.md").read_text(encoding="utf-8")
        severity = " ".join(rubric.split("## Severity", 1)[1].split("\n## ", 1)[0].split())
        blocking = severity.split("**`warning`**", 1)[0]
        self.assertIn("`scope_stretch`", blocking)

    def test_a_fact_labelled_opinion_is_blocking(self):  # #45: the label doesn't make a fact about the writer safe
        rubric = " ".join((REPO / "data" / "rubrics" / "claims.md").read_text(encoding="utf-8").split())
        self.assertIn("A status is a label, not support.", rubric)
        self.assertIn("(who, what, when, where, how long, what they did)", rubric)
        self.assertIn("is `unsupported_claim`. A real opinion, value or plan", rubric)
        blocking = rubric.split("## Severity", 1)[1].split("**`warning`**", 1)[0]
        self.assertIn("a fact about the writer or the business labelled as opinion or inference", blocking)

    def test_rubric_ledger_blocking_locations_and_signoff(self):
        rubric = " ".join((REPO / "data" / "rubrics" / "claims.md").read_text(encoding="utf-8").split())
        self.assertIn("already marks `blocking` needs no finding", rubric)
        self.assertIn("every location", rubric)
        self.assertIn("worded more strongly than the claim", rubric)
        self.assertIn("`human_signoff` covers only the locations", rubric)

    def test_rubric_covers_the_contract(self):
        rubric = (REPO / "data" / "rubrics" / "claims.md").read_text(encoding="utf-8")
        for needle in ('"article"', '"article_sha256"', '"ledger_sha256"', '"matrix_sha256"', '"result"', '"findings"', '"claim_id"', '"location"', '"class"', '"severity"',
                       '"evidence"', '"why"', '"suggested_fix"', "first_hand_scope", "verbatim", "aggregator",
                       "post-date", "regulated_matrix"):
            self.assertIn(needle, rubric)


DELIVERY_CHECKER = REPO / "agents" / "delivery-checker.md"
DELIVERY_RUBRIC = REPO / "data" / "rubrics" / "delivery.md"


class DeliveryChecker(unittest.TestCase):  # the producer never awards its own pass
    def setUp(self):
        self.text = DELIVERY_CHECKER.read_text(encoding="utf-8")
        self.fm = parse_frontmatter(self.text)
        self.rubric = DELIVERY_RUBRIC.read_text(encoding="utf-8")

    def test_isolation(self):
        self.assertEqual(self.fm["name"], "delivery-checker")
        self.assertEqual([t.strip() for t in self.fm["tools"].split(",")], ["Read", "Grep", "Glob"])
        self.assertEqual(self.fm.get("model"), "opus")
        self.assertEqual(self.fm.get("omitClaudeMd"), "true")
        self.assertNotIn("memory", self.fm)

    def test_description_is_short(self):  # the always-on budget (≤ 500) has little room left
        self.assertLessEqual(len(self.fm["description"]), 160)
        self.assertIn("Read-only", self.fm["description"])

    def test_points_at_the_rubric(self):
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/data/rubrics/delivery.md", self.text)
        self.assertTrue(DELIVERY_RUBRIC.is_file())

    def test_input_contract_and_no_author(self):
        for needle in ("`article`", "`contract`", "`rubric`", "`article_sha256`", "`contract_sha256`",
                       "SubagentHandback"):
            self.assertIn(needle, self.text)
        self.assertIn("never edit", self.text.lower())
        self.assertIn("Copy both verbatim into your reply", self.text)
        self.assertNotRegex(self.text.lower(), r"written by|wrote (this|the) (article|draft)")

    def test_rubric_items_are_the_engines(self):
        import sys
        sys.path.insert(0, str(REPO / "lib"))
        from plainspoken import reader_value
        section = self.rubric.split("## The items", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(tuple(re.findall(r"(?m)^- \*\*`([a-z_]+)`\*\*", section)), reader_value.DELIVERY_ITEMS)
        gate = (REPO / "skills" / "reader-value" / "references" / "delivery-gate.md").read_text(encoding="utf-8")
        for name in reader_value.DELIVERY_ITEMS:
            self.assertIn(f"`{name}`", gate, name)

    def test_rubric_covers_the_contract(self):
        flat = " ".join(self.rubric.split())
        for needle in ('"article"', '"article_sha256"', '"contract_sha256"', '"result"', '"items"', '"item"',
                       '"verdict"', '"location"', '"evidence"', '"why"', '"fix"', "verbatim", "never decides",
                       "The CTA counts for nothing", "Independent", "plainspoken's interpretation"):
            self.assertIn(needle, flat)
        self.assertIn("aren't told who or what wrote either", flat)

    def test_rubric_lines_keep_the_file_width(self):
        for n, line in enumerate(self.rubric.splitlines(), start=1):
            self.assertLessEqual(len(line), 118, f"line {n}: {line[:60]}…")
