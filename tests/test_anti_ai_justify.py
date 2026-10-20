"""tests/test_anti_ai_justify.py — fix or justify: justification + JR review files (2026-09-29)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken import justify

REASON = "the three options are the actual choices on offer"


def _tmp(case: unittest.TestCase) -> Path:
    tmp = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


class ValidateJustify(unittest.TestCase):
    def test_valid_file_has_no_errors(self):
        data = {"article_sha256": "a" * 64, "items": [{"rule": "7b", "kind": "voice", "reason": REASON}]}
        self.assertEqual(justify.validate_justify(data), [])

    def test_every_shape_error_is_named(self):
        data = {"items": [{"rule": "7b", "kind": "because", "reason": "fine"},
                          {"rule": "7b", "kind": "voice", "reason": REASON}, {"kind": "voice"}]}
        errors = justify.validate_justify(data)
        self.assertTrue(any("article_sha256 missing" in e for e in errors))
        self.assertTrue(any("kind must be one of" in e for e in errors))
        self.assertTrue(any("real sentence" in e for e in errors))
        self.assertTrue(any("justified twice" in e for e in errors))
        self.assertTrue(any("without a rule" in e for e in errors))

    def test_reason_must_be_one_line(self):  # the spec's reason is one sentence on one line
        data = {"article_sha256": "a" * 64, "items": [{"rule": "7b", "kind": "voice", "reason": REASON + "\nand more"}]}
        self.assertEqual(justify.validate_justify(data), ["justify: rule 7b: reason must be one line"])

    def test_items_must_be_a_list(self):
        self.assertIn("justify: items must be a list",
                      justify.validate_justify({"article_sha256": "a" * 64, "items": "7b"}))


class ValidateReview(unittest.TestCase):
    def _review(self, *verdicts):
        return {"verdicts": [{"rule": r, "verdict": v, "reason": "checked the evidence"} for r, v in verdicts]}

    def test_one_verdict_per_rule_is_valid(self):
        self.assertEqual(justify.validate_review(self._review(("7b", "accept"), ("7c", "reject")), {"7b", "7c"}), [])

    def test_validate_review_names_missing_extra_duplicate_and_bad_verdicts(self):
        errors = justify.validate_review(
            self._review(("7b", "accept"), ("7b", "accept"), ("21", "accept"), ("7c", "maybe")), {"7b", "7c", "16"})
        self.assertIn("JR: bad verdict entry for rule 7b", errors)   # the duplicate
        self.assertIn("JR: bad verdict entry for rule 21", errors)   # not given to JR
        self.assertIn("JR: bad verdict entry for rule 7c", errors)   # not accept/reject
        self.assertIn("JR: no verdict for rule 16", errors)

    def test_validate_review_needs_a_reason(self):
        data = {"verdicts": [{"rule": "7b", "verdict": "accept", "reason": "  "}]}
        self.assertEqual(justify.validate_review(data, {"7b"}), ["JR: bad verdict entry for rule 7b",
                                                                  "JR: no verdict for rule 7b"])

    def test_no_verdicts_list(self):
        self.assertEqual(justify.validate_review({}, {"7b"}), ["JR: no verdicts list"])


class Resolve(unittest.TestCase):
    def test_nothing_read_without_a_failing_warn(self):
        d = _tmp(self)
        (d / "999-t.justify.json").write_text("{garbage")
        self.assertEqual(justify.resolve(d, "999-t", "a" * 64, []),
                         {"accepted": set(), "justified": [], "unused": [], "problems": []})

    def test_missing_file_resolves_nothing_and_is_not_a_problem(self):
        got = justify.resolve(_tmp(self), "999-t", "a" * 64, ["7b"])
        self.assertEqual((got["accepted"], got["problems"]), (set(), []))

    def test_unreadable_file_is_a_problem(self):
        d = _tmp(self)
        (d / "999-t.justify.json").write_text("{garbage")
        self.assertTrue(justify.resolve(d, "999-t", "a" * 64, ["7b"])["problems"][0].startswith("justify: file unreadable"))

    def test_accept_and_reject(self):
        d, sha = _tmp(self), "a" * 64
        jp = d / "999-t.justify.json"
        jp.write_text(json.dumps({"article_sha256": sha, "items": [
            {"rule": "7b", "kind": "voice", "reason": REASON}, {"rule": "7c", "kind": "voice", "reason": REASON}]}))
        (d / "999-t.JR.judge.json").write_text(json.dumps({
            "group": "JR", "article_sha256": sha, "justify_sha256": justify.file_sha(jp), "judged_at": "x",
            "verdicts": [{"rule": "7b", "verdict": "accept", "reason": "true of the evidence"},
                         {"rule": "7c", "verdict": "reject", "reason": "generic reason"}]}))
        got = justify.resolve(d, "999-t", sha, ["7b", "7c"])
        self.assertEqual(got["accepted"], {"7b"})
        self.assertEqual([(j["rule"], j["review"]) for j in got["justified"]], [("7b", "accept"), ("7c", "reject")])
        self.assertEqual(got["problems"], [])


class TemplateAndReviewInput(unittest.TestCase):
    REPORT = {"article": "docs/blog/999-t.md", "article_sha256": "a" * 64, "warns": ["12d", "7b"],
              "unresolved": ["12d", "7b"],
              "rules": {"7b": {"evidence": [{"line": 5, "quote": "x", "reason": "y"}], "findings": []},
                        "12d": {"findings": [{"rule": "12d", "severity": "WARN", "line": 0, "excerpt": "e",
                                              "message": "m"},
                                             {"rule": "12d", "severity": "INFO", "line": 0, "excerpt": "i",
                                              "message": "n"}]}}}

    def test_template_lists_unresolved_rules_with_blank_kind_and_reason(self):
        self.assertEqual(justify.template(self.REPORT), {"article_sha256": "a" * 64, "items": [
            {"rule": "12d", "kind": "", "reason": ""}, {"rule": "7b", "kind": "", "reason": ""}]})

    def test_template_lists_every_failing_warn_and_carries_current_reasons(self):
        report = dict(self.REPORT, unresolved=["12d"])  # 7b was JR-accepted last round
        existing = {"article_sha256": "a" * 64, "items": [{"rule": "7b", "kind": "voice", "reason": REASON},
                                                            {"rule": "21", "kind": "voice", "reason": REASON}]}
        self.assertEqual(justify.template(report, existing), {"article_sha256": "a" * 64, "items": [
            {"rule": "12d", "kind": "", "reason": ""}, {"rule": "7b", "kind": "voice", "reason": REASON}]})

    def test_template_never_carries_a_stale_file(self):
        existing = {"article_sha256": "0" * 64, "items": [{"rule": "7b", "kind": "voice", "reason": REASON}]}
        self.assertEqual(justify.template(self.REPORT, existing), justify.template(self.REPORT))
        self.assertEqual(justify.template(self.REPORT, {"article_sha256": "a" * 64, "items": "7b"}),
                         justify.template(self.REPORT))  # a malformed file carries nothing

    def test_review_input_carries_evidence_and_skips_non_failing_rules(self):
        data = {"article_sha256": "a" * 64, "items": [
            {"rule": "7b", "kind": "voice", "reason": REASON}, {"rule": "12d", "kind": "metric", "reason": REASON},
            {"rule": "21", "kind": "voice", "reason": REASON}]}
        got = justify.review_input(self.REPORT, data, "b" * 64)
        self.assertEqual((got["group"], got["justify_sha256"]), ("JR", "b" * 64))
        self.assertEqual([i["rule"] for i in got["items"]], ["7b", "12d"])
        self.assertEqual(got["items"][0]["evidence"], [{"line": 5, "quote": "x", "reason": "y"}])
        self.assertEqual([f["severity"] for f in got["items"][1]["evidence"]], ["WARN"])  # INFO dropped


