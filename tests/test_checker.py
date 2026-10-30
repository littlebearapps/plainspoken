"""The isolated claims checker's CLI side: parse and verify its reply (verbatim evidence only), `claims record`,
`claims checker-input`, and how `claims status` reads the record."""
import json
import os
import re
import stat
import subprocess
import sys
import unittest
from pathlib import Path

from plainspoken import checker
from tests.test_cli_claims import FIX, PASSAGE, RUN, SRC, Project, run, sha

REPLIES = FIX / "replies"
ARTICLE = (FIX / "article.md").read_text(encoding="utf-8")
LEDGER = {"claims": [
    {"claim_id": "SHOP-001-C002", "binding": {"passage": PASSAGE,
                                              "additional_passages": [{"passage": "Survey run in March 2025."}]}},
    {"claim_id": "X", "binding": "not a table"},
    {"claim_id": "Y"},
]}


def reply(name: str) -> str:
    return (REPLIES / name).read_text(encoding="utf-8")


def finding(evidence, severity="warning"):
    return {"claim_id": None, "location": "body", "class": "entailment_gap", "severity": severity,
            "evidence": evidence, "why": "x", "suggested_fix": None}


class ParseReply(unittest.TestCase):
    def test_bare_object(self):
        data = checker.parse_reply(reply("pass-clean.txt"))
        self.assertEqual(data["result"], "PASS")
        self.assertEqual(data["findings"], [])
        self.assertFalse(data["reply_had_prose"])

    def test_prose_around_one_json_fence(self):
        data = checker.parse_reply(reply("prose-fenced.txt"))
        self.assertEqual(data["result"], "PASS")
        self.assertTrue(data["reply_had_prose"])

    def test_a_lone_fence_has_no_prose(self):
        for fence in ("```json", "```"):
            with self.subTest(fence=fence):
                data = checker.parse_reply(f"{fence}\n{reply('pass-clean.txt').strip()}\n```\n")
                self.assertFalse(data["reply_had_prose"])

    def test_ambiguous_replies_never_read_as_pass(self):
        for name, why in (("fence-then-untagged.txt", "code-fence"),        # (a) a second, untagged fence
                          ("prose-object-before-fence.txt", "another reply object"),  # (b) an object in the prose
                          ("duplicate-key.txt", "duplicate key")):          # (c) json.loads would keep the last
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, why):
                checker.parse_reply(reply(name))

    def test_other_fence_shapes(self):
        body = reply("pass-clean.txt").strip()
        for text in (f"```json\n{body}\n", f"```toml\n{body}\n```\n", f"```json\n{body}\n```\n```\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                checker.parse_reply(text)
        # prose that merely mentions a result in words is fine
        data = checker.parse_reply(f"The result is clean.\n```json\n{body}\n```\n")
        self.assertTrue(data["reply_had_prose"])

    def test_rejected(self):
        for name in ("truncated.txt", "no-object.txt", "two-fences.txt", "result-maybe.txt"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                checker.parse_reply(reply(name))
        for text in ("", "[]", '{"result": "PASS"}', '{"result": "PASS", "findings": {}}',
                     '{"result": "PASS", "findings": ["x"]}', '{"result": "PASS", "findings": []} and more',
                     '{"result": "PASS", "findings": [], "x": NaN}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                checker.parse_reply(text)


class Verify(unittest.TestCase):
    def verify(self, findings, result="PASS", article=ARTICLE, ledger=LEDGER):
        return checker.verify({"result": result, "findings": findings}, article, ledger)

    def test_clean_pass(self):
        out = checker.verify(checker.parse_reply(reply("pass-clean.txt")), ARTICLE, LEDGER)
        self.assertEqual(out["result"], "PASS")
        self.assertEqual(out["unverified_evidence"], 0)

    def test_blocking_with_verbatim_evidence(self):
        out = checker.verify(checker.parse_reply(reply("blocking-verbatim.txt")), ARTICLE, LEDGER)
        self.assertEqual(out["result"], "BLOCKED")
        self.assertTrue(out["findings"][0]["evidence_verified"])
        self.assertEqual(out["findings"][0]["class"], "entailment_gap")

    def test_paraphrased_warning_is_incomplete_and_kept(self):
        out = checker.verify(checker.parse_reply(reply("warning-paraphrase.txt")), ARTICLE, LEDGER)
        self.assertEqual(out["result"], "INCOMPLETE")
        self.assertEqual(len(out["findings"]), 1)
        self.assertFalse(out["findings"][0]["evidence_verified"])
        self.assertEqual(out["findings"][0]["class"], "first_hand_scope")
        self.assertEqual(out["unverified_evidence"], 1)

    def test_ellipsis_stitch_is_unverified(self):
        out = checker.verify(checker.parse_reply(reply("ellipsis-stitch.txt")), ARTICLE, LEDGER)
        self.assertFalse(out["findings"][0]["evidence_verified"])
        self.assertEqual(out["result"], "INCOMPLETE")
        # "A … B" where the article has "A x y z B": each half is verbatim, the stitch isn't
        self.assertFalse(self.verify([finding("In 2025, 38%... similar shops")])["findings"][0]["evidence_verified"])

    def test_an_ellipsis_the_article_really_has_verifies(self):
        for ev in ("2025, 38%... yes", "2025, 38%… yes", "2025, 38%… YES"):
            with self.subTest(ev=ev):
                article = "In 2025, 38%... yes" if "..." in ev else "In 2025, 38%… yes"
                out = self.verify([finding(ev)], article=article)
                self.assertTrue(out["findings"][0]["evidence_verified"])
                self.assertEqual(out["result"], "PASS")

    def test_either_ellipsis_form_matches_the_other(self):
        for ev, article in (("2025, 38%... yes", "In 2025, 38%\u2026 yes"),
                            ("2025, 38%\u2026 yes", "In 2025, 38%... yes")):
            with self.subTest(ev=ev):
                self.assertTrue(self.verify([finding(ev)], article=article)["findings"][0]["evidence_verified"])
        # still no stitching: an ellipsis the article doesn't have never verifies
        self.assertFalse(self.verify([finding("In 2025\u2026 similar shops")])["findings"][0]["evidence_verified"])

    def test_quotes_link_and_case_only_still_verify(self):
        out = checker.verify(checker.parse_reply(reply("normalised-evidence.txt")), ARTICLE, LEDGER)
        self.assertEqual([f["evidence_verified"] for f in out["findings"]], [True, True])
        self.assertEqual(out["result"], "PASS")
        article = "The [Home Affairs](https://example.gov/x_(y) \"title\") page says “About $100” a visit."
        self.assertTrue(self.verify([finding('home affairs page says "about $100"')], article=article)
                        ["findings"][0]["evidence_verified"])

    def test_other_differences_do_not_verify(self):
        for ev in ("In 2025 38% of the shop's bookings", "In 2025, 38 % of the shop's bookings", ""):
            with self.subTest(ev=ev):
                self.assertFalse(self.verify([finding(ev)])["findings"][0]["evidence_verified"])
        self.assertFalse(self.verify([finding(None)])["findings"][0]["evidence_verified"])

    def test_evidence_needs_three_words(self):  # one common word is found anywhere
        for ev in ("2025", "In 2025", "  38%  "):
            with self.subTest(ev=ev):
                out = self.verify([finding(ev)])
                self.assertFalse(out["findings"][0]["evidence_verified"])
                self.assertEqual(out["result"], "INCOMPLETE")
        self.assertTrue(self.verify([finding("In 2025, 38%")])["findings"][0]["evidence_verified"])

    def test_evidence_in_a_pinned_passage_verifies(self):
        out = checker.verify(checker.parse_reply(reply("passage-only.txt")), ARTICLE, LEDGER)
        self.assertTrue(out["findings"][0]["evidence_verified"])
        self.assertEqual(out["result"], "PASS")
        self.assertTrue(self.verify([finding("survey run in march 2025")])["findings"][0]["evidence_verified"])

    def test_unverified_blocking_still_blocks(self):
        out = self.verify([finding("words nowhere in the article", "blocking")], result="BLOCKED")
        self.assertEqual(out["result"], "BLOCKED")
        self.assertEqual(out["unverified_evidence"], 1)

    def test_blocked_reply_without_a_blocking_finding_is_incomplete(self):
        self.assertEqual(self.verify([], result="BLOCKED")["result"], "INCOMPLETE")
        self.assertEqual(self.verify([finding("In 2025, 38%")], result="BLOCKED")["result"], "INCOMPLETE")

    def test_bad_severity_is_rejected(self):
        for sev in ("BLOCK", "info", None):
            with self.subTest(sev=sev), self.assertRaises(ValueError):
                self.verify([finding("In 2025", sev)])

    def test_malformed_ledger_is_just_no_passages(self):
        out = self.verify([finding(PASSAGE)], ledger={"claims": "nope"})
        self.assertFalse(out["findings"][0]["evidence_verified"])


class Record(Project):
    def setUp(self):
        super().setUp()  # the fixture ledger pins PASSAGE to .plainspoken/sources/example-source.md
        self.check = Path(self.paths()["claims-check"])

    def record(self, name, article_sha=None, ledger_sha=None, matrix_sha="none"):
        """Record a fixture reply with the placeholders filled in (default: the current hashes, no matrix)."""
        text = reply(name).replace("{{article_sha256}}", article_sha or sha(self.art)).replace(
            "{{ledger_sha256}}", ledger_sha or sha(self.ledger)).replace("{{matrix_sha256}}", matrix_sha)
        path = self.root / "reply.txt"
        path.write_text(text, encoding="utf-8")
        return run("record", "article.md", "--from", str(path), cwd=self.root)

    def status(self):
        return run("status", "article.md", cwd=self.root)

    def test_clean_pass_writes_a_bound_record(self):
        r = self.record("pass-clean.txt")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS", r.stdout)
        rec = json.loads(self.check.read_text(encoding="utf-8"))
        self.assertEqual(rec["result"], "PASS")
        self.assertEqual(rec["article_sha256"], sha(self.art))
        self.assertEqual(rec["ledger_sha256"], sha(self.ledger))
        self.assertEqual(rec["rubric_sha256"], sha(checker.RUBRIC))
        self.assertEqual(rec["matrix_sha256"], "none")
        self.assertRegex(rec["recorded_at"], r"^\d{4}-\d{2}-\d{2}T.*[+-]\d{2}:\d{2}$")
        self.assertEqual(rec["unverified_evidence"], 0)
        self.assertFalse(rec["reply_had_prose"])
        s = self.status()
        self.assertEqual(s.returncode, 0, s.stdout)
        self.assertIn("checker: PASS (0 warnings)", s.stdout)

    def test_record_file_respects_the_umask(self):  # not mkstemp's 0600
        for mask in (0o022, 0o002):
            with self.subTest(umask=oct(mask)):
                old = os.umask(mask)
                try:
                    self.assertEqual(self.record("pass-clean.txt").returncode, 0)
                finally:
                    os.umask(old)
                self.assertEqual(stat.S_IMODE(self.check.stat().st_mode), 0o666 & ~mask)

    def test_prose_is_recorded(self):
        self.assertEqual(self.record("prose-fenced.txt").returncode, 0)
        self.assertTrue(json.loads(self.check.read_text(encoding="utf-8"))["reply_had_prose"])

    def test_bad_replies_exit_2_and_never_record_pass(self):
        for name in ("truncated.txt", "no-object.txt", "two-fences.txt", "result-maybe.txt",
                     "fence-then-untagged.txt", "prose-object-before-fence.txt", "duplicate-key.txt"):
            with self.subTest(name=name):
                self.assertEqual(self.record("pass-clean.txt").returncode, 0)  # an earlier PASS for these hashes
                r = self.record(name)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
                rec = json.loads(self.check.read_text(encoding="utf-8"))
                self.assertEqual(rec["result"], "INCOMPLETE")
                self.assertEqual((rec["reply_result"], rec["blocking"], rec["warnings"]), (None, 0, 0))
                s = self.status()
                self.assertEqual(s.returncode, 1)
                self.assertEqual(s.stdout.splitlines()[0], "claims: INCOMPLETE")

    def test_malformed_reply_with_stale_hashes_leaves_a_current_pass(self):
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        before = self.check.read_bytes()
        old = "sha256:" + "0" * 64
        for name in ("result-maybe.txt", "truncated.txt", "two-fences.txt"):
            for key in ("article_sha", "ledger_sha", "matrix_sha"):
                with self.subTest(name=name, key=key):
                    r = self.record(name, **{key: old})
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertIn("stale reply", r.stderr)
                    self.assertEqual(self.check.read_bytes(), before)
        self.assertEqual(self.status().returncode, 0)
        # with the current hashes, a malformed reply still replaces the PASS (fail closed)
        self.assertEqual(self.record("result-maybe.txt").returncode, 2)
        self.assertEqual(json.loads(self.check.read_text(encoding="utf-8"))["result"], "INCOMPLETE")

    def test_blocking_verbatim_blocks_status(self):
        r = self.record("blocking-verbatim.txt")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("BLOCKED", r.stdout)
        rec = json.loads(self.check.read_text(encoding="utf-8"))
        self.assertTrue(rec["findings"][0]["evidence_verified"])
        s = self.status()
        self.assertEqual(s.returncode, 1)
        self.assertEqual(s.stdout.splitlines()[0], "claims: BLOCKED")
        self.assertIn("checker: BLOCKED", s.stdout)

    def test_paraphrase_is_incomplete_and_flagged(self):
        r = self.record("warning-paraphrase.txt")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("unverified", r.stdout)
        rec = json.loads(self.check.read_text(encoding="utf-8"))
        self.assertEqual(rec["result"], "INCOMPLETE")
        self.assertEqual(rec["unverified_evidence"], 1)
        self.assertFalse(rec["findings"][0]["evidence_verified"])

    def test_normalised_and_passage_evidence_pass_with_warnings(self):
        for name, n in (("normalised-evidence.txt", 2), ("passage-only.txt", 1)):
            with self.subTest(name=name):
                r = self.record(name)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                s = self.status()
                self.assertEqual(s.returncode, 0, s.stdout)
                self.assertIn(f"checker: PASS ({n} warning{'s' if n != 1 else ''})", s.stdout)

    def test_record_shape_is_the_same_for_every_outcome(self):
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        good = set(json.loads(self.check.read_text(encoding="utf-8")))
        self.assertEqual(self.record("truncated.txt").returncode, 2)
        self.assertEqual(set(json.loads(self.check.read_text(encoding="utf-8"))), good)

    def test_old_reply_is_never_bound_to_new_hashes(self):
        r = run("checker-input", "article.md", cwd=self.root)
        block = json.loads(r.stdout)
        self.assertEqual(self.record("blocking-verbatim.txt", block["article_sha256"], block["ledger_sha256"])
                         .returncode, 1)
        before = self.check.read_bytes()
        # the article is edited and the ledger's hash refreshed, so the ledger is fresh again
        self.art.write_text(ARTICLE + "\nOne more line.\n", encoding="utf-8")
        text = self.ledger.read_text(encoding="utf-8")
        self.ledger.write_text(text.replace(block["article_sha256"], sha(self.art)), encoding="utf-8")
        self.assertEqual(run("checker-input", "article.md", cwd=self.root).returncode, 0)
        r = self.record("pass-clean.txt", block["article_sha256"], block["ledger_sha256"])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("stale reply", r.stderr)
        self.assertEqual(self.check.read_bytes(), before)  # nothing written; the old record is left as it is
        s = self.status()
        self.assertEqual(s.returncode, 1)
        self.assertIn("checker result stale", s.stdout)
        # only the ledger hash differs: still stale
        r = self.record("pass-clean.txt", ledger_sha=block["ledger_sha256"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("stale reply: its ledger_sha256", r.stderr)

    # --- the rubric and matrix are bound too ---------------------------------------------------
    def use_matrix(self, text="# Matrix\n"):
        (self.root / "rules").mkdir(exist_ok=True)
        matrix = self.root / "rules" / "matrix.md"
        matrix.write_text(text, encoding="utf-8")
        (self.root / ".plainspoken" / "config.toml").write_text('[claims]\nregulated_matrix = "rules/matrix.md"\n',
                                                                encoding="utf-8")
        return matrix

    def test_reply_with_a_missing_or_wrong_matrix_hash_is_refused(self):
        r = self.record("pass-clean.txt", matrix_sha="sha256:" + "0" * 64)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("stale reply: its matrix_sha256", r.stderr)
        self.assertFalse(self.check.exists())
        path = self.root / "reply.txt"
        path.write_text(json.dumps({"article_sha256": sha(self.art), "ledger_sha256": sha(self.ledger),
                                    "result": "PASS", "findings": []}), encoding="utf-8")
        r = run("record", "article.md", "--from", str(path), cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("carries no matrix_sha256", r.stderr)
        self.assertFalse(self.check.exists())
        matrix = self.use_matrix()
        r = self.record("pass-clean.txt")  # "none", but a matrix is configured now
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("stale reply: its matrix_sha256", r.stderr)
        r = self.record("pass-clean.txt", matrix_sha=sha(matrix))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(self.check.read_text(encoding="utf-8"))["matrix_sha256"], sha(matrix))

    def test_a_record_for_another_rubric_is_stale(self):
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        rec = json.loads(self.check.read_text(encoding="utf-8"))
        for value in ("sha256:" + "0" * 64, None):
            with self.subTest(value=value):
                changed = {**rec, "rubric_sha256": value} if value else {
                    k: v for k, v in rec.items() if k != "rubric_sha256"}
                self.check.write_text(json.dumps(changed), encoding="utf-8")
                s = self.status()
                self.assertEqual(s.returncode, 1, s.stdout)
                self.assertIn("checker result stale (rubric changed)", s.stdout)
                self.assertNotIn("checker: PASS", s.stdout)

    def claims_report(self):
        return json.loads(Path(self.paths()["claims"]).read_text(encoding="utf-8"))

    def test_missing_matrix_rewrites_the_claims_report_as_incomplete(self):
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        self.assertEqual(self.status().returncode, 0)
        self.assertEqual(self.claims_report()["status"], "PASS")
        (self.root / ".plainspoken" / "config.toml").write_text('[claims]\nregulated_matrix = "rules/gone.md"\n',
                                                                encoding="utf-8")
        s = self.status()
        self.assertEqual(s.returncode, 2, s.stdout + s.stderr)
        self.assertIn("rules/gone.md", s.stderr)
        rep = self.claims_report()  # the earlier PASS doesn't linger
        self.assertEqual(rep["status"], "INCOMPLETE")
        self.assertEqual(len(rep["reasons"]), 1)
        self.assertIn("rules/gone.md", rep["reasons"][0])
        self.assertEqual((rep["article_sha256"], rep["ledger_sha256"]), (sha(self.art), sha(self.ledger)))
        self.assertEqual(set(rep), {"status", "reasons", "article_sha256", "ledger_sha256", "counts", "article",
                                    "ledger", "gaps", "check"})

    def test_checker_suffix_only_on_a_pass(self):  # INCOMPLETE never ends "checker: PASS"
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        (self.root / SRC).unlink()  # the pin's saved source is gone; the checker record is still current
        s = self.status()
        self.assertEqual(s.returncode, 1, s.stdout)
        self.assertEqual(s.stdout.splitlines()[0], "claims: INCOMPLETE")
        self.assertNotIn("checker: PASS", s.stdout)
        rep = self.claims_report()
        self.assertEqual((rep["check"]["result"], rep["check"]["current"]), ("PASS", True))
        self.assertFalse(any(r.startswith("checker:") for r in rep["reasons"]))

    def test_a_record_for_another_matrix_is_stale(self):
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        matrix = self.use_matrix()  # a matrix configured after a check that had none
        s = self.status()
        self.assertEqual(s.returncode, 1, s.stdout)
        self.assertIn("checker result stale (matrix changed)", s.stdout)
        self.assertEqual(self.record("pass-clean.txt", matrix_sha=sha(matrix)).returncode, 0)
        self.assertEqual(self.status().returncode, 0)
        matrix.write_text("# Matrix\n\nA new class.\n", encoding="utf-8")
        s = self.status()
        self.assertEqual(s.returncode, 1, s.stdout)
        self.assertIn("checker result stale (matrix changed)", s.stdout)
        rec = json.loads(self.check.read_text(encoding="utf-8"))
        del rec["matrix_sha256"]
        self.check.write_text(json.dumps(rec), encoding="utf-8")
        self.assertIn("checker result stale (matrix changed)", self.status().stdout)

    def test_reply_without_hashes_is_refused(self):
        r = self.record("no-hashes.txt")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("stale reply", r.stderr)
        self.assertFalse(self.check.exists())

    def test_stale_ledger_refused_and_nothing_written(self):
        self.art.write_text(ARTICLE.replace("similar shops", "similar workshops"), encoding="utf-8")
        r = self.record("pass-clean.txt")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("stale", r.stdout + r.stderr)
        self.assertFalse(self.check.exists())

    def test_check_bound_to_an_old_article_is_stale(self):
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        self.art.write_text(ARTICLE + "\nOne more line.\n", encoding="utf-8")
        s = self.status()
        self.assertEqual(s.returncode, 1)
        self.assertIn("checker result stale", s.stdout)
        self.assertNotIn("checker: PASS", s.stdout)

    def test_bad_input(self):
        self.assert_bad_input(run("record", "article.md", "--from", "nope.txt", cwd=self.root), "nope.txt")
        self.assert_bad_input(run("record", "missing.md", "--from", str(REPLIES / "pass-clean.txt"), cwd=self.root),
                              "missing.md")
        self.ledger.unlink()
        self.assert_bad_input(self.record("pass-clean.txt", ledger_sha="sha256:" + "0" * 64),
                              self.ledger_for("article.md").name)
        self.assertFalse(self.check.exists())


class JudgeHold(Record):
    """#160: `judge-input` waits for a claims step that's open or stale, and never for a draft with no ledger."""

    def hold(self, article="article.md"):
        from plainspoken import claims_tools
        return claims_tools.judge_hold(self.root / article, self.root, Path(self.paths(article)["claims-check"]), None)

    def judge_input(self, *extra):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_", "CLAUDE_PROJECT_DIR"))}
        env.pop("PYTHONPATH", None)
        cmd = [sys.executable, str(RUN)]
        subprocess.run([*cmd, "check", "article.md", "--profile", "default"], cwd=self.root, capture_output=True,
                       env=env)
        held = subprocess.run([*cmd, "judge-input", "article.md", "--profile", "default"], cwd=self.root,
                              capture_output=True, text=True, env=env)
        rules = sorted(set(re.findall(r"(?m)^\s+(?:BLOCK|WARN)\s+(\S+)\s+L", held.stderr))) if held.returncode == 1 else []
        keep = ["--keep", ",".join(rules)] if rules else []
        return subprocess.run([*cmd, "judge-input", "article.md", "--profile", "default", *keep, *extra],
                              cwd=self.root, capture_output=True, text=True, env=env)

    def test_no_ledger_never_holds(self):
        (self.root / "other.md").write_text("Text.\n", encoding="utf-8")
        self.assertEqual(self.hold("other.md"), [])

    def test_a_checker_that_hasnt_reported_holds(self):  # M99Lk3: the checker still running in the background
        hold = self.hold()
        self.assertEqual(hold[0], "claims: INCOMPLETE")
        self.assertIn("checker not run", hold)

    def test_a_current_pass_lets_the_judges_start(self):
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        self.assertEqual(self.hold(), [])

    def test_a_checker_block_holds(self):
        self.assertEqual(self.record("blocking-verbatim.txt").returncode, 1)
        self.assertEqual(self.hold(), ["claims: BLOCKED", "checker: BLOCKED"])

    def test_an_edit_after_the_pass_holds(self):  # jMtx8T: edits after a claims block, judged without a recheck
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        self.art.write_text(ARTICLE + "\nOne more line.\n", encoding="utf-8")
        hold = self.hold()
        self.assertEqual(hold[0], "claims: INCOMPLETE")
        self.assertIn("checker result stale", hold)

    def test_blocked_only_on_owner_holds_lets_the_judges_start(self):
        text = self.ledger.read_text(encoding="utf-8").replace(
            'method = "booking system export"', 'method = "booking system export"\nsensitive = true')
        self.ledger.write_text(text, encoding="utf-8")
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        s = self.status()
        self.assertEqual(s.stdout.splitlines()[0], "claims: BLOCKED", s.stdout)
        self.assertIn("owner approval required", s.stdout)
        self.assertEqual(self.hold(), [])

    def test_cli_exits_3_and_ignore_claims_runs(self):
        held = self.judge_input()
        self.assertEqual((held.returncode, held.stdout), (3, ""), held.stderr)
        self.assertIn("  claims: INCOMPLETE", held.stderr)
        self.assertIn("in the foreground", held.stderr)
        self.assertIn("--ignore-claims", held.stderr)
        ignored = self.judge_input("--ignore-claims")
        self.assertEqual(ignored.returncode, 0, ignored.stderr)
        self.assertEqual(len(ignored.stdout.splitlines()), 4)
        self.assertEqual(self.record("pass-clean.txt").returncode, 0)
        ok = self.judge_input()
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(len(ok.stdout.splitlines()), 4)


class CheckerInput(Project):
    def test_prints_the_input_block(self):
        r = run("checker-input", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        block = json.loads(r.stdout)
        self.assertEqual(Path(block["article"]), self.art.resolve())
        self.assertEqual(Path(block["ledger"]), self.ledger.resolve())
        self.assertEqual(Path(block["rubric"]), checker.RUBRIC)
        self.assertEqual(block["regulated_matrix"], "none")
        self.assertEqual(block["matrix_sha256"], "none")
        self.assertEqual(block["article_sha256"], sha(self.art))
        self.assertEqual(block["ledger_sha256"], sha(self.ledger))

    def test_configured_matrix(self):
        (self.root / ".plainspoken" / "config.toml").write_text('[claims]\nregulated_matrix = "rules/matrix.md"\n',
                                                                encoding="utf-8")
        r = run("checker-input", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("matrix.md", r.stderr)
        (self.root / "rules").mkdir()
        (self.root / "rules" / "matrix.md").write_text("# Matrix\n", encoding="utf-8")
        r = run("checker-input", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        block = json.loads(r.stdout)
        self.assertEqual(Path(block["regulated_matrix"]), (self.root / "rules" / "matrix.md").resolve())
        self.assertEqual(block["matrix_sha256"], sha(self.root / "rules" / "matrix.md"))

    def test_stale_ledger_is_refused(self):
        self.art.write_text(ARTICLE + "\nNew.\n", encoding="utf-8")
        r = run("checker-input", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("stale", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_bad_input(self):
        self.assert_bad_input(run("checker-input", "nope.md", cwd=self.root), "nope.md")
        self.ledger.unlink()
        self.assert_bad_input(run("checker-input", "article.md", cwd=self.root), self.ledger_for("article.md").name)


if __name__ == "__main__":
    unittest.main()
