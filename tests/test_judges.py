import json
import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken import judges, report
from tests._profiles import PRODUCT


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
                "calibration_notes", "visible_frontmatter_keys", "faq_frontmatter_key"}
        for o in out:
            self.assertEqual(set(o) - {"human_markers"}, keys)  # no `profile` key for the judge
            self.assertEqual(o["article_sha256"], self.lint["article_sha256"])
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
        self.sha = report.sha256(self.art)
        self.write_lint()

    def write_lint(self, **over) -> dict:
        lint = {**report.run_lint(self.art, PRODUCT), **over}
        p = report.report_paths(self.art, self.reports, self.cwd)["lint"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(lint), encoding="utf-8")
        return lint

    def reply(self, **over) -> str:
        body = {"group": "J2", "article_sha256": self.sha, "judged_at": "2026-10-10T00:00:00Z", "verdicts": []}
        body.update(over)
        return json.dumps(body)

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
