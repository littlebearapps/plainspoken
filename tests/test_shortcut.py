"""tests/test_shortcut.py — #188: after judges who passed everything, a fix that only joins or splits two sentences
for a lint-owned rule reruns the lint and JR, not the four judges. Once a run."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken import capture, rounds, schema
from plainspoken.registry import load_config
from plainspoken.report import merge, merge_lines, report_paths, run_lint, shortcut
from tests._profiles import PRODUCT
from tests.test_cli import cli

A = "I moved the shop to Brunswick in March."
B = "The rent went up by a third that year."
C = "Most customers found the new door without trouble."
D = "Parking was the one thing people asked about."
AB = "I moved the shop to Brunswick in March, and the rent went up by a third that year."  # A and B joined
AB_SEMI = "I moved the shop to Brunswick in March; the rent went up by a third that year."
CD = "Most customers found the new door without trouble but parking was the one thing people asked about."


def _body(*sentences: str) -> str:
    return " ".join(sentences)


class Shortcut(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cfg = load_config()
        self.art = self.tmp / "post.md"
        self.dir = self.tmp / ".plainspoken" / "reports"
        self.dir.mkdir(parents=True)
        self.paths = report_paths(self.art, self.dir, self.tmp)

    def _draft(self, body: str, lint_findings: list | None = None) -> None:
        """Write the draft and a current lint for it (no findings unless given)."""
        self.art.write_text(f"{body}\n", encoding="utf-8")
        lint = run_lint(self.art, PRODUCT)
        lint["findings"] = lint_findings or []
        self.paths["lint"].write_text(json.dumps(lint), encoding="utf-8")

    def _judged(self, body: str, fails: dict[str, list[str]] | None = None, lint_findings: list | None = None) -> dict:
        """A judged round: the draft, its lint and all four judge files (each rule in `fails` failed with those
        quotes), then merge."""
        fails = fails or {}
        self._draft(body, lint_findings)
        sha = json.loads(self.paths["lint"].read_text(encoding="utf-8"))["article_sha256"]
        groups: dict[str, list] = {}
        for r in self.cfg.rules_for_profile(PRODUCT):
            if "judge" in r.method:
                groups.setdefault(r.group, []).append(r)
        for g, rules in groups.items():
            verdicts = [{"rule": r.id, "verdict": "fail" if r.id in fails else "pass", "severity": r.severity,
                         "evidence": [{"line": 1, "quote": q, "reason": "y"} for q in fails.get(r.id, [])]}
                        for r in rules]
            self.paths[g].write_text(json.dumps(
                {"group": g, "article_sha256": sha, "judged_at": "2026-11-22T00:00:00Z", "verdicts": verdicts,
                 "profile_sha256": PRODUCT.sha256, "ruleset_version": self.cfg.version}))
        return merge(self.art, self.dir, PRODUCT, cwd=self.tmp)

    def _fixed(self, body: str, lint_findings: list | None = None) -> dict:
        """A fix pass the judges don't rerun after: the new draft and its lint, then merge."""
        self._draft(body, lint_findings)
        return merge(self.art, self.dir, PRODUCT, cwd=self.tmp)

    def _cut(self) -> dict:
        return shortcut(self.art, self.dir, PRODUCT, self.tmp)

    def _carried(self, merged: dict) -> bool:
        return any(e.get("carried") for e in merged["rules"].values())

    def _warn_7d(self) -> list:
        return [{"rule": "7d", "severity": "WARN", "line": 1, "excerpt": "x", "message": "short run", "source": "lint"}]

    def test_a_join_only_fix_after_an_all_pass_round_takes_the_shortcut(self):
        first = self._judged(_body(A, B, C, D), lint_findings=self._warn_7d())
        self.assertEqual(first["status"], "UNRESOLVED")  # a kept 7d, as in round 9's second rounds
        self._draft(_body(AB, C, D))
        self.assertTrue(self._cut()["base"])
        m = merge(self.art, self.dir, PRODUCT, cwd=self.tmp)
        self.assertEqual(m["status"], "PASS")  # the judges' passes carried, the lint is clean now
        self.assertTrue(self._carried(m))
        self.assertEqual(m["coverage"]["missing"], [])
        self.assertIn("  shortcut: J1, J2, J3, J4", "\n".join(merge_lines(m)))
        self.assertEqual(schema.validate(m, schema.load("report")), [])

    def test_a_split_only_fix_takes_it_too(self):
        self._judged(_body(AB, C, D))
        self._draft(_body(A, B, C, D))
        self.assertTrue(self._cut()["base"])
        self.assertTrue(self._carried(merge(self.art, self.dir, PRODUCT, cwd=self.tmp)))

    def test_joins_with_but_a_semicolon_or_no_connector_count(self):
        for joined in (CD, "Most customers found the new door without trouble; parking was the one thing people "
                           "asked about.", "Most customers found the new door without trouble, but parking was "
                           "the one thing people asked about."):
            with self.subTest(joined=joined):
                self._judged(_body(A, B, C, D))
                self._draft(_body(A, B, joined))
                self.assertTrue(self._cut()["base"], self._cut()["why"])
                self.paths["rounds"].unlink()

    def test_a_fix_that_also_touches_a_third_sentence_does_not(self):
        self._judged(_body(A, B, C, D))
        self._draft(_body(AB, "Most customers found the new door easily.", D))
        self.assertIsNone(self._cut()["base"])
        m = merge(self.art, self.dir, PRODUCT, cwd=self.tmp)
        self.assertEqual(m["status"], "INCOMPLETE")  # the judges read a different version: rerun them
        self.assertFalse(self._carried(m))

    def test_two_joins_are_more_than_the_pair(self):
        self._judged(_body(A, B, C, D))
        self._draft(_body(AB, CD))
        self.assertIsNone(self._cut()["base"])

    def test_a_join_that_changes_a_word_or_adds_a_reason_does_not(self):
        for joined in ("I moved the shop to Brunswick in March, so the rent went up by a third that year.",
                       "I moved the shop to Brunswick in March and the rent rose by a third that year.",
                       "I moved the shop to Brunswick in March because the rent went up by a third that year."):
            with self.subTest(joined=joined):
                self._judged(_body(A, B, C, D))
                self._draft(_body(joined, C, D))
                self.assertIsNone(self._cut()["base"])
                self.paths["rounds"].unlink()

    def test_a_split_that_makes_a_question_does_not(self):  # "The result? …" is a judge's tell (rule 12)
        self._judged(_body(A, "The result, the rent went up by a third.", C))
        self._draft(_body(A, "The result? The rent went up by a third.", C))
        self.assertIsNone(self._cut()["base"])

    def test_a_round_a_judge_failed_does_not(self):  # the rule the fix is for isn't lint-owned
        self._judged(_body(A, B, C, D), {"7c": [C]})
        self._draft(_body(AB, C, D))
        self.assertIsNone(self._cut()["base"])
        self.assertFalse(self._carried(merge(self.art, self.dir, PRODUCT, cwd=self.tmp)))

    def test_a_lint_block_on_a_judged_rule_does_not(self):  # rule 2 is lint+judge: its judge owns the verdict
        block = [{"rule": "2", "severity": "BLOCK", "line": 1, "excerpt": "x", "message": "banned", "source": "lint"}]
        self.assertEqual(self._judged(_body(A, B, C, D), lint_findings=block)["status"], "FAIL")
        self._draft(_body(AB, C, D))
        self.assertIsNone(self._cut()["base"])

    def test_the_second_shortcut_forces_a_judge_pass(self):
        self._judged(_body(A, B, C, D))
        self.assertTrue(self._carried(self._fixed(_body(AB, C, D))))
        self.assertTrue(self._carried(merge(self.art, self.dir, PRODUCT, cwd=self.tmp)))  # same draft, e.g. after JR
        self._draft(_body(AB, CD))  # a second join, measured against the draft the judges read: two pairs
        self.assertIsNone(self._cut()["base"])
        self._draft(_body(AB_SEMI, C, D))  # one pair against that draft, but the run took its shortcut
        cut = self._cut()
        self.assertIsNone(cut["base"])
        self.assertTrue(cut["second"])
        self.assertIn("once", cut["why"])
        m = merge(self.art, self.dir, PRODUCT, cwd=self.tmp)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertFalse(self._carried(m))
        self._judged(_body(AB_SEMI, C, D))  # the judges read it: the final pass
        self._draft(_body(AB_SEMI, CD))  # another join-only fix still gets the judges: the run took its one shortcut
        self.assertIsNone(self._cut()["base"])

    def test_a_carried_round_is_not_a_judged_one(self):  # a late find on a joined sentence was never pre-existing
        self._judged(_body(A, B, C, D))
        self._fixed(_body(AB, C, D))
        saved = json.loads(self.paths["rounds"].read_text(encoding="utf-8"))
        self.assertEqual(len(saved["rounds"]), 1)
        self.assertEqual(len(saved["shortcuts"]), 1)
        m = self._judged(_body(AB, C, "Parking was the thing people asked about."), {"5b": [AB]})
        self.assertFalse(m["rules"]["5b"].get("pre_existing"))

    def test_the_rounds_file_still_holds_no_draft_text(self):
        self._judged(_body(A, B, C, D))
        self._fixed(_body(AB, C, D))
        raw = self.paths["rounds"].read_text(encoding="utf-8")
        for words in ("Brunswick", "rent", "customers", "shop"):
            self.assertNotIn(words, raw)

    def test_an_older_rounds_file_takes_no_shortcut(self):  # saved before #188: no exact hashes, no lint_only
        self._judged(_body(A, B, C, D))
        saved = json.loads(self.paths["rounds"].read_text(encoding="utf-8"))
        for slot in saved["rounds"]:
            slot.pop("exact")
            slot.pop("lint_only")
        self.paths["rounds"].write_text(json.dumps({"rounds": saved["rounds"]}), encoding="utf-8")
        self._draft(_body(AB, C, D))
        self.assertIsNone(self._cut()["base"])

    def test_a_judge_file_from_another_draft_does_not_carry(self):
        self._judged(_body(A, B, C, D))
        j1 = json.loads(self.paths["J1"].read_text(encoding="utf-8"))
        j1["article_sha256"] = "0" * 64
        self.paths["J1"].write_text(json.dumps(j1), encoding="utf-8")
        self._draft(_body(AB, C, D))
        self.assertIsNone(self._cut()["base"])

    def test_carried_verdicts_add_no_judge_events(self):  # no judge read this draft, so the ledger counts none
        self._judged(_body(A, B, C, D))
        m = self._fixed(_body(AB, C, D))
        events = capture.merge_events(m, None, self.cfg, self.tmp)
        self.assertEqual([e for e in events if e["event"] == "judge"], [])


class Pairs(unittest.TestCase):
    def test_fingerprint_keeps_exact_hashes(self):
        fp = rounds.fingerprint(_body(A, B))
        self.assertEqual(len(fp["exact"]), 2)
        self.assertNotEqual(rounds.fingerprint(_body(A.replace("March", "[March](x)"), B))["exact"], fp["exact"])


class Cli(unittest.TestCase):
    """The Claude Code route (--write) and the Codex and Hermes one (four JSON lines on stdout)."""

    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.art = self.cwd / "post.md"

    def _judge_all_pass(self) -> None:
        r = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        replies = []
        for x in r.stdout.splitlines():
            line = json.loads(x)
            replies.append(json.dumps({
                "group": line["group"], "article_sha256": line["article_sha256"],
                "input_digest": line["input_digest"], "judged_at": "2026-11-22T00:00:00Z",
                "verdicts": [{"rule": rule, "verdict": "pass", "severity": line["severities"][rule], "evidence": []}
                             for rule in line["rules"]]}))
        (self.cwd / "replies.json").write_text("\n".join(replies), encoding="utf-8")
        rec = cli("judge-record", "post.md", "--all", "--from", "replies.json", cwd=self.cwd)
        self.assertEqual(rec.returncode, 0, rec.stderr)
        self.assertEqual(cli("merge", "post.md", "--profile", "default", cwd=self.cwd).returncode, 0)

    def test_judge_input_exits_4_on_the_shortcut_and_merge_carries(self):
        self.art.write_text(_body(A, B, C, D) + "\n", encoding="utf-8")
        cli("meaning-diff", "post.md", "--start", cwd=self.cwd)
        self._judge_all_pass()
        self.art.write_text(_body(AB, C, D) + "\n", encoding="utf-8")
        for flags in ((), ("--write",)):  # Codex and Hermes pipe stdout; Claude Code writes the files
            r = cli("judge-input", "post.md", "--profile", "default", *flags, cwd=self.cwd)
            self.assertEqual((r.returncode, r.stdout), (4, ""), r.stderr)
            self.assertIn("shortcut", r.stderr)
            self.assertIn("anti-AI lint", r.stderr)  # the lint still ran
        self.assertEqual(list((self.cwd / ".plainspoken" / "reports").glob("*.input.json")), [])
        m = cli("merge", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual(m.returncode, 0, m.stdout + m.stderr)
        self.assertIn("shortcut:", m.stdout)
        # the second join-only fix: the judges read it, so judge-input prints their four lines again
        self.art.write_text(_body(AB_SEMI, C, D) + "\n", encoding="utf-8")
        r = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([json.loads(x)["group"] for x in r.stdout.splitlines()], ["J1", "J2", "J3", "J4"])
        self.assertIn("no shortcut", r.stderr)
        prompt = cli("agent-prompt", "tells-judge", "--line", "1", cwd=self.cwd, input=r.stdout)
        self.assertEqual(prompt.returncode, 0, prompt.stderr)

    def test_meaning_diff_start_gives_a_new_run_its_shortcut_back(self):
        self.art.write_text(_body(A, B, C, D) + "\n", encoding="utf-8")
        cli("meaning-diff", "post.md", "--start", cwd=self.cwd)
        self._judge_all_pass()
        self.art.write_text(_body(AB, C, D) + "\n", encoding="utf-8")
        self.assertEqual(cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd).returncode, 4)
        cli("meaning-diff", "post.md", "--start", cwd=self.cwd)  # a new run: no judged draft yet
        r = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
