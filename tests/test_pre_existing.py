"""tests/test_pre_existing.py — #200: a late judge find on text the last fix left alone is marked pre-existing."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken import rounds, schema
from plainspoken.registry import load_config
from plainspoken.report import merge, merge_lines, report_key, report_paths, run_lint
from tests._profiles import PRODUCT

A = "I moved the shop to Brunswick in March."
B = "The rent went up by a third that year."
C = "Most customers found the new door without trouble."
D = "Parking was the one thing people asked about."


def _body(*sentences: str) -> str:
    return " ".join(sentences)


class PreExisting(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cfg = load_config()
        self.art = self.tmp / "post.md"
        self.dir = self.tmp / ".plainspoken" / "reports"
        self.dir.mkdir(parents=True)
        self.paths = report_paths(self.art, self.dir, self.tmp)
        self.key = report_key(self.art, self.tmp)

    def _round(self, body: str, fails: dict[str, list[str]], *, skip: str | None = None) -> dict:
        """Write the draft, its lint and the four judge files (each rule in `fails` failed with those quotes; the
        group in `skip` left out, so the merge is INCOMPLETE), then merge."""
        self.art.write_text(f"{body}\n", encoding="utf-8")
        lint = run_lint(self.art, PRODUCT)
        lint["findings"] = []  # the judges own these verdicts here; a lint BLOCK would force a fail
        self.paths["lint"].write_text(json.dumps(lint), encoding="utf-8")
        groups: dict[str, list] = {}
        for r in self.cfg.rules_for_profile(PRODUCT):
            if "judge" in r.method:
                groups.setdefault(r.group, []).append(r)
        for g, rules in groups.items():
            self.paths[g].unlink(missing_ok=True)
            if g == skip:
                continue
            verdicts = [{"rule": r.id, "verdict": "fail" if r.id in fails else "pass", "severity": r.severity,
                         "evidence": [{"line": 1, "quote": q, "reason": "y"} for q in fails.get(r.id, [])]}
                        for r in rules]
            self.paths[g].write_text(json.dumps(
                {"group": g, "article_sha256": lint["article_sha256"], "judged_at": "2026-11-22T00:00:00Z",
                 "verdicts": verdicts, "profile_sha256": PRODUCT.sha256, "ruleset_version": self.cfg.version}))
        return merge(self.art, self.dir, PRODUCT, cwd=self.tmp)

    def _marked(self, merged: dict) -> list[str]:
        return sorted(rid for rid, e in merged["rules"].items() if e.get("pre_existing"))

    def test_first_round_marks_nothing(self):
        m = self._round(_body(A, B, C), {"5b": [B]})
        self.assertEqual(self._marked(m), [])
        self.assertFalse(any(line.startswith("  pre-existing") for line in merge_lines(m)))

    def test_a_late_find_on_an_unchanged_sentence_is_pre_existing(self):
        self._round(_body(A, B, C), {"7c": [A]})
        m = self._round(_body("I moved the shop in March.", B, C), {"5b": [C]})  # the fix changed A only
        self.assertEqual(self._marked(m), ["5b"])
        self.assertIn("  pre-existing: 5b", "\n".join(merge_lines(m)))
        self.assertEqual(m["status"], "FAIL")  # informational: a pre-existing BLOCK still blocks

    def test_a_find_on_a_changed_sentence_is_not(self):
        self._round(_body(A, B, C), {"7c": [A]})
        m = self._round(_body("I moved the shop in March.", B, C), {"5b": ["I moved the shop in March."]})
        self.assertEqual(self._marked(m), [])

    def test_a_find_the_round_before_already_made_is_not(self):  # the fix left it: that pass is spent
        self._round(_body(A, B, C), {"5b": [C]})
        m = self._round(_body("I moved the shop in March.", B, C), {"5b": [C]})
        self.assertEqual(self._marked(m), [])

    def test_the_same_rule_on_another_line_the_round_before_still_counts_as_late(self):
        self._round(_body(A, B, C), {"5b": [A]})
        m = self._round(_body("I moved the shop in March.", B, C), {"5b": [C]})
        self.assertEqual(self._marked(m), ["5b"])

    def test_a_fail_the_round_before_couldnt_place_blocks_the_mark(self):  # it may have been this sentence
        self._round(_body(A, B, C), {"5b": ["a quote that isn't in the draft"]})
        m = self._round(_body("I moved the shop in March.", B, C), {"5b": [C]})
        self.assertEqual(self._marked(m), [])

    def test_mixed_evidence_is_not_pre_existing(self):
        self._round(_body(A, B, C), {})
        m = self._round(_body("I moved the shop in March.", B, C), {"7c": [C, "I moved the shop in March."]})
        self.assertEqual(self._marked(m), [])

    def test_a_quote_that_isnt_in_the_draft_is_not(self):
        self._round(_body(A, B, C), {})
        m = self._round(_body("I moved the shop in March.", B, C), {"5b": ["Here it is at its real vintage."]})
        self.assertEqual(self._marked(m), [])

    def test_a_quote_across_two_unchanged_sentences_with_an_ellipsis(self):
        self._round(_body(A, B, C, D), {})
        m = self._round(_body("I moved the shop in March.", B, C, D),
                        {"7c": ["went up by a third that year. Most customers…", "asked about"]})
        self.assertEqual(self._marked(m), ["7c"])

    def test_merging_the_same_draft_again_keeps_the_mark(self):  # e.g. after JR
        self._round(_body(A, B, C), {})
        body = _body("I moved the shop in March.", B, C)
        self._round(body, {"5b": [C]})
        self.assertEqual(self._marked(merge(self.art, self.dir, PRODUCT, cwd=self.tmp)), ["5b"])

    def test_an_incomplete_merge_moves_no_round(self):
        self._round(_body(A, B, C), {})
        self._round(_body("I moved the shop in March.", B, C), {"5b": [C]}, skip="J3")
        saved = json.loads(self.paths["rounds"].read_text(encoding="utf-8"))
        self.assertEqual(len(saved["rounds"]), 1)  # only the first, complete round
        m = self._round(_body("I moved the shop in March.", B, C), {"5b": [C]})
        self.assertEqual(self._marked(m), ["5b"])

    def test_the_rounds_file_holds_no_draft_text(self):
        self._round(_body(A, B, C), {"5b": [B]})
        self._round(_body("I moved the shop in March.", B, C), {"5b": [C]})
        raw = self.paths["rounds"].read_text(encoding="utf-8")
        for words in ("Brunswick", "rent", "customers", "shop"):
            self.assertNotIn(words, raw)
        self.assertEqual(len(json.loads(raw)["rounds"]), 2)

    def test_a_damaged_rounds_file_is_ignored(self):
        self._round(_body(A, B, C), {})
        self.paths["rounds"].write_text("{not json", encoding="utf-8")
        m = self._round(_body("I moved the shop in March.", B, C), {"5b": [C]})
        self.assertEqual(self._marked(m), [])
        self.assertEqual(len(json.loads(self.paths["rounds"].read_text(encoding="utf-8"))["rounds"]), 1)

    def test_report_with_the_mark_matches_the_schema(self):
        self._round(_body(A, B, C), {})
        m = self._round(_body("I moved the shop in March.", B, C), {"5b": [C]})
        self.assertEqual(self._marked(m), ["5b"])
        self.assertEqual(schema.validate(m, schema.load("report")), [])

    def test_meaning_diff_start_drops_the_rounds_of_an_earlier_run(self):
        from plainspoken import meaning
        self._round(_body(A, B, C), {})
        self.assertTrue(self.paths["rounds"].is_file())
        meaning.start(self.art, self.tmp, self.dir)
        self.assertFalse(self.paths["rounds"].exists())


class Units(unittest.TestCase):
    def test_quoted_units(self):
        fp = rounds.fingerprint(_body(A, B, C))
        self.assertEqual(rounds.quoted_units("the rent went up", fp), {1})  # case and spacing don't matter
        self.assertEqual(rounds.quoted_units("in March. The rent", fp), {0, 1})
        self.assertIsNone(rounds.quoted_units("not in the draft", fp))
        self.assertIsNone(rounds.quoted_units("  …  ", fp))


if __name__ == "__main__":
    unittest.main()
