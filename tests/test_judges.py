import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plainspoken import judges, report
from tests._profiles import _FIX, PRODUCT

PRODUCT_PATH = (_FIX / "product_like.toml").resolve()


class JudgeInput(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.art = self.cwd / "post.md"
        self.art.write_text("Here's the thing. It is not just fast, it's reliable.\n", encoding="utf-8")
        self.reports = self.cwd / ".plainspoken" / "reports"
        lint = report.run_lint(self.art, PRODUCT)
        paths = report.report_paths(self.art, self.reports, self.cwd)
        paths["lint"].parent.mkdir(parents=True)
        paths["lint"].write_text(json.dumps(lint), encoding="utf-8")
        self.lint = lint

    def test_four_groups_with_contract_keys(self):
        out = judges.judge_input(self.art, PRODUCT, self.reports, self.cwd)
        self.assertEqual([o["group"] for o in out], ["J1", "J2", "J3", "J4"])
        keys = {"group", "article", "article_sha256", "content_type", "rules", "severities", "candidates", "rubric",
                "calibration_notes", "visible_frontmatter_keys", "faq_frontmatter_key", "input_digest"}
        for o in out:
            self.assertEqual(set(o) - {"human_markers"}, keys)  # no `profile` key for the judge
            self.assertEqual(o["article_sha256"], self.lint["article_sha256"])
            self.assertEqual(o["input_digest"], judges.input_digest(o))
            self.assertTrue(Path(o["rubric"]).is_absolute())
        self.assertIn("human_markers", out[3])
        self.assertNotIn("human_markers", out[0])

    def test_severities_map_every_rule(self):
        from plainspoken.registry import load_config
        cfg = load_config()
        for o in judges.judge_input(self.art, PRODUCT, self.reports, self.cwd):
            self.assertEqual(set(o["severities"]), set(o["rules"]))
            for rid, sev in o["severities"].items():
                self.assertIn(sev, ("BLOCK", "WARN"))
                self.assertEqual(sev, cfg.rules[rid].severity)

    def test_shadow_rules_never_judged(self):
        ids = {r for o in judges.judge_input(self.art, PRODUCT, self.reports, self.cwd) for r in o["rules"]}
        self.assertFalse(ids & {"28", "29", "30", "31", "32", "33"})

    def test_stale_lint_refused(self):
        self.art.write_text("Changed.\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "run `check`"):
            judges.judge_input(self.art, PRODUCT, self.reports, self.cwd)


class Record(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.art = self.cwd / "post.md"
        self.art.write_text("Text.\n", encoding="utf-8")
        self.reports = self.cwd / ".plainspoken" / "reports"
        self.reports.mkdir(parents=True)
        # judge-record finds the check's profile from the lint: here, through the project config's path
        (self.cwd / ".plainspoken" / "config.toml").write_text(
            f'[engine]\nprofile = "{PRODUCT_PATH.as_posix()}"\n', encoding="utf-8")
        self.sha = report.sha256(self.art)
        self.write_lint()

    def write_lint(self, **over) -> dict:
        lint = {**report.run_lint(self.art, PRODUCT), **over}
        p = report.report_paths(self.art, self.reports, self.cwd)["lint"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(lint), encoding="utf-8")
        self.lint = lint
        return lint

    def line(self, group: str = "J2") -> dict:
        """The line `judge-input` prints for `group` now."""
        return next(x for x in judges.judge_input(self.art, PRODUCT, self.reports, self.cwd) if x["group"] == group)

    def reply(self, **over) -> str:
        group = over.get("group", "J2")
        try:
            digest = self.line(group)["input_digest"] if group != "JR" else None
        except ValueError:  # no current lint
            digest = None
        body = {"group": "J2", "article_sha256": self.sha, "judged_at": "2026-10-10T00:00:00Z", "verdicts": [],
                "input_digest": digest}
        body.update(over)
        return json.dumps(body)

    # ---- #43: a reply is bound to the judge input `judge-input` gives for the current draft ---------------------

    def test_reply_to_the_genuine_input_records(self):
        line = judges.judge_input(self.art, PRODUCT, self.reports, self.cwd)[1]
        p = judges.record_reply(self.art, "J2", self.reply(input_digest=line["input_digest"]), self.reports, self.cwd)
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["input_digest"], line["input_digest"])

    def test_reply_without_input_digest_refused(self):
        body = json.loads(self.reply())
        del body["input_digest"]
        with self.assertRaisesRegex(ValueError, "rerun `judge-input`"):
            judges.record_reply(self.art, "J2", json.dumps(body), self.reports, self.cwd)

    def test_pasted_input_with_stale_candidates_refused(self):
        """The round-5 trace: an older J2 line with the new article hash pasted in, so its candidates are stale."""
        self.art.write_text("It is not just fast, it's reliable. Furthermore, it's cheap.\n", encoding="utf-8")
        self.write_lint()
        old = judges.judge_input(self.art, PRODUCT, self.reports, self.cwd)[1]
        self.art.write_text("It is fast and reliable.\n", encoding="utf-8")
        self.sha = report.sha256(self.art)
        self.write_lint()
        pasted = {**old, "article_sha256": self.sha}  # what the model built by hand
        with self.assertRaisesRegex(ValueError, "J2 reply's input_digest doesn't match.*rerun `judge-input`"):
            judges.record_reply(self.art, "J2", self.reply(input_digest=pasted["input_digest"]), self.reports,
                                self.cwd)

    def test_another_groups_digest_refused(self):
        with self.assertRaisesRegex(ValueError, "input_digest"):
            judges.record_reply(self.art, "J2", self.reply(input_digest=self.line("J1")["input_digest"]),
                                self.reports, self.cwd)

    def test_record_all_refuses_the_one_with_a_bad_digest(self):
        replies = [json.loads(self.reply(group=g)) for g in judges.GROUPS]
        replies[2]["input_digest"] = "0" * 64
        rows = judges.record_all(self.art, "\n".join(json.dumps(r) for r in replies), self.reports, self.cwd)
        self.assertEqual([(g, w is not None) for g, w, _ in rows],
                         [("J1", True), ("J2", True), ("J3", False), ("J4", True)])
        self.assertIn("rerun `judge-input`", rows[2][2])

    # ---- #61: the digest covers the whole line, rebuilt as judge-input would print it now ---------------------

    def test_reply_to_an_edited_line_refused(self):
        """A J2 line with its candidate dropped, or a severity changed, and a digest that matches the edited line."""
        self.art.write_text("It is not just fast, it's reliable.\n", encoding="utf-8")
        self.sha = report.sha256(self.art)
        self.write_lint()
        line = self.line("J2")
        self.assertTrue(line["candidates"])
        for field, value in (("candidates", line["candidates"][1:]),
                             ("severities", {r: "WARN" for r in line["severities"]})):
            edited = {**line, field: value}
            with self.subTest(field=field):
                self.assertNotEqual(judges.input_digest(edited), line["input_digest"])
                with self.assertRaisesRegex(ValueError, "J2 reply's input_digest doesn't match"):
                    judges.record_reply(self.art, "J2", self.reply(input_digest=judges.input_digest(edited)),
                                        self.reports, self.cwd)
        judges.record_reply(self.art, "J2", self.reply(input_digest=line["input_digest"]), self.reports, self.cwd)

    def test_line_printed_differently_now_refused(self):
        """Same lint, but judge-input would print another line now (here the rubric moved): the old digest no
        longer records, though the lint-only digest before #61 did."""
        digest = self.line("J2")["input_digest"]
        with mock.patch.object(judges, "RUBRIC", self.cwd / "moved" / "judges.md"):
            with self.assertRaisesRegex(ValueError, "input_digest doesn't match"):
                judges.record_reply(self.art, "J2", self.reply(input_digest=digest), self.reports, self.cwd)

    def test_profile_not_found_from_the_lint(self):
        (self.cwd / ".plainspoken" / "config.toml").unlink()
        with self.assertRaisesRegex(ValueError, "can't find the profile the check used.*--profile"):
            judges.record_reply(self.art, "J2", self.reply(), self.reports, self.cwd)
        judges.record_reply(self.art, "J2", self.reply(), self.reports, self.cwd, profile=str(PRODUCT_PATH))
        rows = judges.record_all(self.art, self.reply(), self.reports, self.cwd, profile=PRODUCT)
        self.assertEqual(rows[1][0], "J2")
        self.assertIsNotNone(rows[1][1], rows[1][2])

    def test_judge_files_with_the_old_digest_still_merge(self):
        """merge never reads input_digest (judge-record checks it once), so files recorded before #61 merge."""
        lint_keys = ("article_sha256", "profile_sha256", "ruleset_version", "content_type", "findings")
        for line in judges.judge_input(self.art, PRODUCT, self.reports, self.cwd):
            g = line["group"]
            old = json.dumps({"group": g, **{k: self.lint.get(k) for k in lint_keys}}, sort_keys=True,
                             ensure_ascii=False, separators=(",", ":"))
            data = {"group": g, "article_sha256": self.sha, "judged_at": "2026-10-10T00:00:00Z",
                    "input_digest": hashlib.sha256(old.encode("utf-8")).hexdigest(),
                    "profile_sha256": self.lint["profile_sha256"], "ruleset_version": self.lint["ruleset_version"],
                    "verdicts": [{"rule": r, "verdict": "pass", "severity": line["severities"][r], "evidence": []}
                                 for r in line["rules"]]}
            report.report_paths(self.art, self.reports, self.cwd)[g].write_text(json.dumps(data), encoding="utf-8")
        merged = report.merge(self.art, self.reports, PRODUCT, self.cwd)
        self.assertEqual(merged["problems"], [])
        self.assertEqual(merged["coverage"]["missing"], [])

    def test_valid_reply_written(self):
        p = judges.record_reply(self.art, "J2", self.reply(), self.reports, self.cwd)
        self.assertEqual(p, report.report_paths(self.art, self.reports, self.cwd)["J2"])
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["group"], "J2")

    def test_fenced_reply_accepted(self):
        judges.record_reply(self.art, "J2", "```json\n" + self.reply() + "\n```\n", self.reports, self.cwd)

    def test_uppercase_fence_accepted(self):
        judges.record_reply(self.art, "J2", "```JSON\n" + self.reply() + "\n```\n", self.reports, self.cwd)

    def test_prose_around_json_rejected(self):
        with self.assertRaisesRegex(ValueError, "one JSON object"):
            judges.record_reply(self.art, "J2", "Here you go:\n" + self.reply(), self.reports, self.cwd)

    def test_wrong_group_or_stale_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, "group"):
            judges.record_reply(self.art, "J2", self.reply(group="J3"), self.reports, self.cwd)
        with self.assertRaisesRegex(ValueError, "stale"):
            judges.record_reply(self.art, "J2", self.reply(article_sha256="0" * 64), self.reports, self.cwd)

    def test_verdicts_must_be_a_list(self):
        with self.assertRaisesRegex(ValueError, "verdicts"):
            judges.record_reply(self.art, "J2", self.reply(verdicts={}), self.reports, self.cwd)

    def test_jr_needs_current_justify_hash(self):
        paths = report.report_paths(self.art, self.reports, self.cwd)
        paths["justify"].parent.mkdir(parents=True, exist_ok=True)
        paths["justify"].write_text('{"article_sha256": "x", "items": []}', encoding="utf-8")
        from plainspoken.justify import file_sha
        good = self.reply(group="JR", justify_sha256=file_sha(paths["justify"]))
        judges.record_reply(self.art, "JR", good, self.reports, self.cwd)
        with self.assertRaisesRegex(ValueError, "justify"):
            judges.record_reply(self.art, "JR", self.reply(group="JR", justify_sha256="0" * 64), self.reports, self.cwd)

    # ---- judge files are bound to the lint's profile and ruleset -----------------------------------------------

    def test_recorded_file_carries_the_lint_stamps(self):
        from plainspoken.registry import load_config
        p = judges.record_reply(self.art, "J2", self.reply(), self.reports, self.cwd)
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual((data["profile_sha256"], data["ruleset_version"]), (PRODUCT.sha256, load_config().version))

    def test_jr_file_carries_the_lint_stamps_too(self):
        paths = report.report_paths(self.art, self.reports, self.cwd)
        paths["justify"].write_text('{"article_sha256": "x", "items": []}', encoding="utf-8")
        from plainspoken.justify import file_sha
        p = judges.record_reply(self.art, "JR", self.reply(group="JR", justify_sha256=file_sha(paths["justify"])),
                                self.reports, self.cwd)
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["profile_sha256"], PRODUCT.sha256)

    def test_no_current_lint_refused(self):
        report.report_paths(self.art, self.reports, self.cwd)["lint"].unlink()
        with self.assertRaisesRegex(ValueError, "no current lint"):
            judges.record_reply(self.art, "J2", self.reply(), self.reports, self.cwd)
        for over in ({"article_sha256": "0" * 64}, {"ruleset_version": "0.0.0-old"}, {"profile_sha256": None}):
            with self.subTest(over=over):
                self.write_lint(**over)
                with self.assertRaisesRegex(ValueError, "no current lint"):
                    judges.record_reply(self.art, "J2", self.reply(), self.reports, self.cwd)
