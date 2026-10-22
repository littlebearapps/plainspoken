"""tests/test_anti_ai_report.py — lint report, CLI exit codes, coverage merge."""
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken.justify import file_sha
from plainspoken.registry import load_config
from plainspoken.report import lint_status, merge, report_key, report_paths, run_lint
from tests._profiles import PRODUCT, NARRATIVE, CONSULTING

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "profiles"
PRODUCT_ARGS = ("--profile", str(FIX / "product_like.toml"))
REASON = "the three options are the actual choices on offer"


def _cli_env(extra: dict | None = None) -> dict:
    env = dict(os.environ, PYTHONPATH=str(REPO / "lib"))
    env.update(extra or {})
    return env


def _rdir(article: Path) -> Path:
    return article.parent / ".plainspoken" / "reports"


def _article(tmp: Path, body: str, extra_fm: str = "", name="999-test.md") -> Path:
    blog = tmp / "docs" / "blog"
    blog.mkdir(parents=True, exist_ok=True)
    p = blog / name
    p.write_text(f"---\ntitle: \"T\"\n{extra_fm}---\n\n{body}\n", encoding="utf-8")
    return p




class Lint(unittest.TestCase):
    def _tmp(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return tmp


    def test_every_lint_rule_reported_even_when_clean(self):
        tmp = self._tmp()
        lint = run_lint(_article(tmp, "I think it's fine. But not always, because reasons."), PRODUCT)
        cfg = load_config()
        expected = {r.id for r in cfg.rules_for_profile(PRODUCT) if r.method in ("lint", "lint+judge")}
        self.assertEqual(set(lint["lint_rules"]), expected)
        for key in ("article", "profile", "profile_sha256", "ruleset_version", "content_type", "article_sha256",
                    "generated", "findings", "metrics", "lint_rules"):
            self.assertIn(key, lint)
        self.assertEqual((lint["profile"], lint["profile_sha256"]), (PRODUCT.name, PRODUCT.sha256))
        self.assertEqual(len(lint["profile_sha256"]), 64)
        self.assertEqual(lint["ruleset_version"], cfg.version)
        self.assertEqual(lint["content_type"], "article")
        self.assertEqual(len(lint["article_sha256"]), 64)

    def test_lint_status(self):
        self.assertEqual(lint_status({"findings": [{"severity": "WARN"}, {"severity": "INFO"}]}), "CLEAN")
        self.assertEqual(lint_status({"findings": [{"severity": "WARN"}, {"severity": "BLOCK"}]}), "BLOCK")

    def test_cli_exit_codes(self):
        tmp = self._tmp()
        clean = _article(tmp, "I think it's fine.", name="998-a.md")
        dirty = _article(tmp, "We delve into a robust tapestry — a — b — c — d.", name="997-b.md")
        # cwd = the temp folder, not the repo: --no-save still logs fired spans to the project's kaizen ledger.
        run = lambda p: subprocess.run([sys.executable, "-m", "plainspoken", "check", str(p), "--json", "--no-save", *PRODUCT_ARGS],
                                       cwd=tmp, env=_cli_env(), capture_output=True, text=True)
        self.assertEqual(run(clean).returncode, 0)
        r = run(dirty)
        self.assertEqual(r.returncode, 1)
        self.assertIn('"rule": "2"', r.stdout)

    def test_cli_out_writes_json(self):
        tmp = self._tmp()
        p = _article(tmp, "I think it's fine.", name="995-d.md")
        out = tmp / "reports" / "995-d.lint.json"
        r = subprocess.run([sys.executable, "-m", "plainspoken", "check", str(p), "--out", str(out), *PRODUCT_ARGS],
                           cwd=REPO, env=_cli_env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("anti-AI lint", r.stdout)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["profile"], "product_like")




class HostFree(unittest.TestCase):
    def test_merge_writes_report_under_given_dir_and_no_state_file(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        art = tmp / "post.md"
        art.write_text('---\ntitle: "T"\ndomain: product.example\n---\n\nPlain text here.\n', encoding="utf-8")
        reports = tmp / ".plainspoken" / "reports"
        merged = merge(art, reports, PRODUCT)
        self.assertTrue(report_paths(art, reports, Path.cwd())["report"].exists())
        self.assertEqual(merged["article"], str(art))
        self.assertFalse(any(tmp.glob("*.state.md")))

    def test_lint_has_no_slug(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        art = tmp / "post.md"
        art.write_text('---\ntitle: "T"\ndomain: product.example\n---\n\nPlain text.\n', encoding="utf-8")
        self.assertNotIn("slug", run_lint(art, PRODUCT))

    def test_cli_has_only_check_merge_justify(self):
        out = subprocess.run([sys.executable, "-m", "plainspoken", "--help"], cwd=REPO,
                             capture_output=True, text=True, env=_cli_env())
        for gone in ("calibrate", "trend", "evidence", "digest"):
            self.assertNotIn(gone, out.stdout)


def _judges(dirp: Path, stem: str, sha: str, cfg, profile, fails: tuple = (), severity: dict | None = None,
            extra: dict | None = None) -> None:
    """One judge file per group, a verdict for every applicable judge rule. `fails` fail (with evidence),
    `severity` overrides a verdict's severity, `extra` maps group → extra verdict dicts appended as-is."""
    groups: dict[str, list] = {}
    for r in cfg.rules_for_profile(profile):
        if "judge" in r.method:
            groups.setdefault(r.group, []).append(r)
    for g, rules in groups.items():
        verdicts = []
        for r in rules:
            bad = r.id in fails
            verdicts.append({"rule": r.id, "verdict": "fail" if bad else "pass",
                             "severity": (severity or {}).get(r.id, r.severity),
                             "evidence": [{"line": 5, "quote": "x", "reason": "y"}] if bad else []})
        verdicts += (extra or {}).get(g, [])
        (dirp / f"{stem}.{g}.judge.json").write_text(json.dumps(
            {"group": g, "article_sha256": sha, "judged_at": "2026-09-26T00:00:00Z", "verdicts": verdicts,
             "profile_sha256": profile.sha256, "ruleset_version": cfg.version}))


class Merge(unittest.TestCase):
    BODY = "I think it's fine. But not always, because reasons."

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cfg = load_config()
        self.art, self.sha = self._prep(self.BODY)
        self.dir = _rdir(self.art)
        self.key = report_key(self.art, Path.cwd())

    def _prep(self, body: str, name: str = "999-test.md", profile=PRODUCT,
              inject: list | None = None) -> tuple[Path, str]:
        """Write the article and its lint JSON (plus any injected findings); return (path, sha)."""
        art = _article(self.tmp, body, name=name)
        lint = run_lint(art, profile)
        lint["findings"] += inject or []
        d = _rdir(art)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{report_key(art, Path.cwd())}.lint.json").write_text(json.dumps(lint))
        return art, lint["article_sha256"]

    def _judges(self, **kw):
        _judges(self.dir, self.key, kw.pop("sha", self.sha), self.cfg, PRODUCT, **kw)

    def _edit_judge(self, group: str, fn) -> None:
        p = self.dir / f"{self.key}.{group}.judge.json"
        d = json.loads(p.read_text())
        fn(d)
        p.write_text(json.dumps(d))

    def _justify(self, items: list[tuple[str, str, str]], sha: str | None = None, stem: str | None = None) -> Path:
        p = self.dir / f"{stem or self.key}.justify.json"
        p.write_text(json.dumps({"article_sha256": sha or self.sha,
                                 "items": [{"rule": r, "kind": k, "reason": why} for r, k, why in items]}))
        return p

    def _review(self, verdicts: dict[str, str], sha: str | None = None, stem: str | None = None,
                profile=PRODUCT) -> None:
        jp = self.dir / f"{stem or self.key}.justify.json"
        (self.dir / f"{stem or self.key}.JR.judge.json").write_text(json.dumps({
            "group": "JR", "article_sha256": sha or self.sha, "justify_sha256": file_sha(jp),
            "judged_at": "2026-09-29T00:00:00Z", "profile_sha256": profile.sha256, "ruleset_version": self.cfg.version,
            "verdicts": [{"rule": r, "verdict": v, "reason": "checked against the evidence"}
                         for r, v in verdicts.items()]}))

    def _cli_justify(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "plainspoken", "justify", str(self.art), "--reports", str(self.dir), *args],
                              cwd=REPO, env=_cli_env(), capture_output=True, text=True)

    def test_full_coverage_passes(self):
        self._judges()
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "PASS")
        self.assertEqual(m["coverage"]["missing"], [])
        self.assertEqual(m["coverage"]["covered"], m["coverage"]["expected"])
        self.assertTrue((self.dir / f"{self.key}.report.json").is_file())

    def test_cli_merge_pass_exits_0(self):
        self._judges()
        r = subprocess.run([sys.executable, "-m", "plainspoken", "merge", str(self.art), "--reports", str(self.dir),
                            *PRODUCT_ARGS], cwd=REPO, env=_cli_env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("PASS"), r.stdout)

    def test_bad_lint_with_unhashable_content_type_is_incomplete_not_a_crash(self):
        lint = self.dir / f"{self.key}.lint.json"
        lint.write_text(json.dumps({"article_sha256": "stale", "content_type": ["x"]}), encoding="utf-8")
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")

    def test_judges_from_another_profile_or_ruleset_are_stale(self):
        for key, value in (("profile_sha256", "0" * 64), ("ruleset_version", "0.0.0-old"), ("profile_sha256", None)):
            with self.subTest(key=key, value=value):
                self._judges()
                self._edit_judge("J2", lambda d: d.__setitem__(key, value) if value else d.pop(key))
                m = merge(self.art, _rdir(self.art), PRODUCT)
                self.assertEqual(m["status"], "INCOMPLETE")
                self.assertTrue(any(p.startswith("J2:") and "profile or ruleset" in p for p in m["problems"]),
                                m["problems"])

    def test_editing_calibration_notes_after_judging_is_incomplete(self):
        notes = self.tmp / "notes.md"
        notes.write_text("Analogies: none.\n", encoding="utf-8")
        prof_path = self.tmp / "mine.toml"
        prof_path.write_text((FIX / "product_like.toml").read_text(encoding="utf-8").replace(
            'name = "product_like"', 'name = "mine"') + '\n[judges]\ncalibration_notes = "notes.md"\n', encoding="utf-8")
        from plainspoken import profile as P
        mine = P.load(prof_path)
        (self.dir / f"{self.key}.lint.json").write_text(json.dumps(run_lint(self.art, mine)))
        _judges(self.dir, self.key, self.sha, self.cfg, mine)
        self.assertEqual(merge(self.art, _rdir(self.art), mine)["status"], "PASS")  # same profile: unchanged
        notes.write_text("Analogies: allowed.\n", encoding="utf-8")
        mine = P.load(prof_path)
        (self.dir / f"{self.key}.lint.json").write_text(json.dumps(run_lint(self.art, mine)))  # rerun `check` only
        m = merge(self.art, _rdir(self.art), mine)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertTrue(any(p.startswith("J1:") for p in m["problems"]), m["problems"])

    def test_jr_from_another_profile_is_stale(self):
        self._judges(fails=("7b",))
        self._justify([("7b", "voice", REASON)])
        self._review({"7b": "accept"})
        self.assertEqual(merge(self.art, _rdir(self.art), PRODUCT)["status"], "PASS")
        p = self.dir / f"{self.key}.JR.judge.json"
        p.write_text(json.dumps({**json.loads(p.read_text()), "profile_sha256": "0" * 64}))
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertTrue(any(p.startswith("JR:") and "profile or ruleset" in p for p in m["problems"]), m["problems"])

    def test_missing_group_is_incomplete(self):
        self._judges()
        (self.dir / f"{self.key}.J3.judge.json").unlink()
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertIn("5c", m["coverage"]["missing"])

    def test_missing_verdict_in_a_present_file_is_incomplete(self):
        self._judges()
        self._edit_judge("J2", lambda d: d.update(verdicts=[v for v in d["verdicts"] if v["rule"] != "21"]))
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertEqual(m["coverage"]["missing"], ["21"])

    def test_stale_judge_file_is_incomplete(self):
        self._judges(sha="0" * 64)
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertTrue(any("stale" in p for p in m["problems"]))

    def test_lint_made_with_another_profile_is_incomplete(self):
        self._judges()
        other_name = CONSULTING
        same_name_other_hash = dataclasses.replace(PRODUCT, sha256="0" * 64)
        for prof in (other_name, same_name_other_hash):
            with self.subTest(profile=prof.name, sha=prof.sha256[:8]):
                m = merge(self.art, _rdir(self.art), prof)
                self.assertEqual(m["status"], "INCOMPLETE")
                self.assertIn("lint report missing, unreadable, malformed, stale (article changed) or made with "
                              "another profile — rerun `check`", m["problems"])
                self.assertEqual((m["profile"], m["profile_sha256"]), (prof.name, prof.sha256))
        self.assertEqual(merge(self.art, _rdir(self.art), PRODUCT)["status"], "PASS")  # the matching profile still passes

    def test_lint_made_under_another_ruleset_is_incomplete(self):
        self._judges()
        lp = self.dir / f"{self.key}.lint.json"
        lint = json.loads(lp.read_text())
        lint["ruleset_version"] = "0.0.1"
        lp.write_text(json.dumps(lint))
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertTrue(any("ruleset changed" in p for p in m["problems"]), m["problems"])

    def test_merged_report_stamps_content_type(self):
        for ctype in ("article", "social"):
            with self.subTest(ctype=ctype):
                lint = run_lint(self.art, PRODUCT, ctype)
                (self.dir / f"{self.key}.lint.json").write_text(json.dumps(lint))
                self._judges()
                m = merge(self.art, _rdir(self.art), PRODUCT)
                self.assertEqual(m["content_type"], ctype)
                saved = json.loads((self.dir / f"{self.key}.report.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["content_type"], ctype)

    def test_stale_lint_file_is_incomplete(self):
        self._judges()
        lp = self.dir / f"{self.key}.lint.json"
        lint = json.loads(lp.read_text())
        lint["article_sha256"] = "0" * 64
        lp.write_text(json.dumps(lint))
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertTrue(any("stale" in p for p in m["problems"]))

    def test_malformed_judge_json_is_incomplete(self):
        self._judges()
        (self.dir / f"{self.key}.J4.judge.json").write_text("{not json")
        self.assertEqual(merge(self.art, _rdir(self.art), PRODUCT)["status"], "INCOMPLETE")

    def test_fail_without_evidence_is_incomplete(self):
        self._judges()
        self._edit_judge("J2", lambda d: [v.update(verdict="fail") for v in d["verdicts"] if v["rule"] == "21"])
        self.assertEqual(merge(self.art, _rdir(self.art), PRODUCT)["status"], "INCOMPLETE")

    def test_block_judge_fail_is_fail(self):
        self._judges(fails=("5c",))
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "FAIL")
        self.assertEqual(m["blocks"], ["5c"])

    def test_one_warn_fail_is_unresolved(self):  # fix or justify: no count threshold any more
        self._judges(fails=("7b",))
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual((m["status"], m["warns"], m["unresolved"]), ("UNRESOLVED", ["7b"], ["7b"]))

    def test_merge_never_writes_rewrite_advised(self):
        self._judges(fails=("7b", "7c", "16", "21"))
        self.assertEqual(merge(self.art, _rdir(self.art), PRODUCT)["status"], "UNRESOLVED")

    def test_accepted_justifications_resolve_the_warns(self):
        self._judges(fails=("7b", "7c", "16"))
        self._justify([("7b", "voice", REASON), ("7c", "load_bearing", REASON), ("16", "false_positive", REASON)])
        self._review({"7b": "accept", "7c": "accept", "16": "accept"})
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual((m["status"], m["unresolved"]), ("PASS", []))
        self.assertEqual([j["rule"] for j in m["justified"]], ["16", "7b", "7c"])
        self.assertEqual(m["warns"], ["16", "7b", "7c"])  # trend + calibration still see the WARN fails

    def test_rejected_justification_stays_unresolved(self):
        self._judges(fails=("7b",))
        self._justify([("7b", "voice", REASON)])
        self._review({"7b": "reject"})
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual((m["status"], m["unresolved"], m["justified"][0]["review"]), ("UNRESOLVED", ["7b"], "reject"))

    def test_justification_for_an_older_article_is_incomplete(self):
        self._judges(fails=("7b",))
        self._justify([("7b", "voice", REASON)], sha="0" * 64)
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertTrue(any("older version" in p for p in m["problems"]))

    def test_missing_review_is_incomplete(self):
        self._judges(fails=("7b",))
        self._justify([("7b", "voice", REASON)])
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertTrue(any(p.startswith("JR: review missing") for p in m["problems"]))

    def test_justification_edited_after_review_is_incomplete(self):
        self._judges(fails=("7b",))
        self._justify([("7b", "voice", REASON)])
        self._review({"7b": "accept"})
        self._justify([("7b", "voice", REASON + ", reworded after the review")])
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertTrue(any("JR: stale" in p for p in m["problems"]))

    def test_justification_cannot_clear_a_block(self):
        self._judges(fails=("5c", "7b"))
        self._justify([("5c", "voice", REASON), ("7b", "voice", REASON)])
        self._review({"7b": "accept"})
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual((m["status"], m["blocks"], m["unused_justifications"]), ("FAIL", ["5c"], ["5c"]))

    def test_bad_kind_is_incomplete(self):
        self._judges(fails=("7b",))
        self._justify([("7b", "because", REASON)])
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertTrue(any("kind must be one of" in p for p in m["problems"]))

    def test_review_verdict_for_an_unjustified_rule_is_incomplete(self):
        self._judges(fails=("7b", "7c"))
        self._justify([("7b", "voice", REASON)])
        jp = self.dir / f"{self.key}.justify.json"
        (self.dir / f"{self.key}.JR.judge.json").write_text(json.dumps({
            "group": "JR", "article_sha256": self.sha, "justify_sha256": file_sha(jp), "judged_at": "x",
            "profile_sha256": PRODUCT.sha256, "ruleset_version": self.cfg.version,
            "verdicts": [{"rule": "7b", "verdict": "accept", "reason": "ok per voice.md"},
                         {"rule": "7c", "verdict": "accept", "reason": "never justified"}]}))
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertIn("JR: bad verdict entry for rule 7c", m["problems"])

    def test_justification_for_a_passing_rule_is_listed_unused(self):
        self._judges(fails=("7b",))
        self._justify([("7b", "voice", REASON), ("21", "voice", REASON)])
        self._review({"7b": "accept"})
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual((m["status"], m["unused_justifications"]), ("PASS", ["21"]))

    def test_no_warn_fail_ignores_a_stale_justification_file(self):
        self._justify([("7b", "voice", REASON)], sha="0" * 64)
        self._judges()
        self.assertEqual(merge(self.art, _rdir(self.art), PRODUCT)["status"], "PASS")


    def test_cli_justify_template_and_review_input(self):
        cli = lambda *a: subprocess.run([sys.executable, "-m", "plainspoken", "justify", str(self.art), "--reports", str(self.dir), *a],
                                        cwd=REPO, env=_cli_env(), capture_output=True, text=True)
        r = cli("--template")
        self.assertEqual(r.returncode, 2)
        self.assertIn("run `merge` first", r.stderr)
        self._judges(fails=("7b",))
        merge(self.art, _rdir(self.art), PRODUCT)
        r = cli("--template")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout),
                         {"article_sha256": self.sha, "items": [{"rule": "7b", "kind": "", "reason": ""}]})
        self.assertEqual(cli("--review-input", *PRODUCT_ARGS).returncode, 1)  # no justify file yet
        self._justify([("7b", "voice", REASON)])
        r = cli("--review-input", *PRODUCT_ARGS)
        self.assertEqual(r.returncode, 0)
        payload = json.loads(r.stdout)
        self.assertEqual((payload["group"], [i["rule"] for i in payload["items"]]), ("JR", ["7b"]))
        self.assertEqual(payload["items"][0]["evidence"], [{"line": 5, "quote": "x", "reason": "y"}])
        self.assertTrue(os.path.isabs(payload["rubric"]) and os.path.exists(payload["rubric"]))
        self.assertIsNone(payload["calibration_notes"])
        notes = self.dir / "notes.md"
        notes.write_text("Allowances.\n", encoding="utf-8")
        prof = self.dir / "p.toml"
        prof.write_text('[profile]\nname = "x"\n[judges]\ncalibration_notes = "notes.md"\n', encoding="utf-8")
        r = cli("--review-input", "--profile", str(prof))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["calibration_notes"], str(notes.resolve()))
        r = cli("--review-input", "--profile", str(self.dir / "missing.toml"))
        self.assertEqual(r.returncode, 2)

    def test_edit_after_justify_needs_a_fresh_justification_and_jr(self):
        self._judges(fails=("7b",))
        self._justify([("7b", "voice", REASON)])
        self._review({"7b": "accept"})
        self.assertEqual(merge(self.art, _rdir(self.art), PRODUCT)["status"], "PASS")
        self.art, self.sha = self._prep("I think it's fine. But not always, because of reasons.")  # an edit
        self._judges(fails=("7b",))  # the kept WARN still fails on the new hash
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual((m["status"], m["coverage"]["missing"]), ("INCOMPLETE", []))
        self.assertEqual(m["problems"], ["justify: written for an older version of the article — rewrite it "
                                         "(`justify --template`) and rerun JR"])
        r = self._cli_justify("--template")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"article_sha256": self.sha, "items": [
            {"rule": "7b", "kind": "", "reason": ""}]})  # the stale reason is not carried forward
        self._justify([("7b", "voice", REASON)])
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertTrue(m["problems"][0].startswith("JR: stale"))  # the old round's review can't be reused
        self._review({"7b": "accept"})
        self.assertEqual(merge(self.art, _rdir(self.art), PRODUCT)["status"], "PASS")
        r = self._cli_justify("--template")  # re-templating keeps what's written for the current version
        self.assertEqual(json.loads(r.stdout)["items"], [{"rule": "7b", "kind": "voice", "reason": REASON}])

    def test_cli_justify_refuses_an_incomplete_report_and_an_empty_review(self):
        self._judges(fails=("7b",))
        (self.dir / f"{self.key}.J3.judge.json").unlink()
        merge(self.art, _rdir(self.art), PRODUCT)
        r = self._cli_justify("--template")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("plainspoken: report is INCOMPLETE — fix its inputs and merge first", r.stderr)
        self._judges(fails=("7b",))
        merge(self.art, _rdir(self.art), PRODUCT)
        self._justify([("21", "voice", REASON)])  # valid, but 21 isn't failing
        r = self._cli_justify("--review-input", *PRODUCT_ARGS)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("nothing to review", r.stderr)

    def test_cli_justify_template_write(self):  # atomic keyed write
        r = self._cli_justify("--template", "--write")
        self.assertEqual((r.returncode, r.stdout), (2, ""))  # no current report
        self._judges(fails=("7b",))
        merge(self.art, _rdir(self.art), PRODUCT)
        jp = self.dir / f"{self.key}.justify.json"
        mask = os.umask(0o022)
        try:
            r = self._cli_justify("--template", "--write")
        finally:
            os.umask(mask)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Path(r.stdout.strip()), jp)
        self.assertEqual(jp.stat().st_mode & 0o777, 0o644)  # the umask, not mkstemp's 0600
        self.assertEqual(json.loads(jp.read_text())["items"], [{"rule": "7b", "kind": "", "reason": ""}])
        self._justify([("7b", "voice", REASON)])
        r = self._cli_justify("--template", "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(jp.read_text())["items"], [{"rule": "7b", "kind": "voice", "reason": REASON}])
        self.assertEqual([p.name for p in self.dir.glob("*.tmp")], [])
        self.assertEqual(self._cli_justify("--review-input", "--write", *PRODUCT_ARGS).returncode, 2)
        r = self._cli_justify("--review-input", *PRODUCT_ARGS)
        self.assertTrue(os.path.isabs(json.loads(r.stdout)["article"]))

    def test_judge_rule_from_wrong_group_rejected(self):
        self._judges()
        self._edit_judge("J1", lambda d: d["verdicts"].append(
            {"rule": "6", "verdict": "pass", "severity": "BLOCK", "evidence": []}))
        self.assertEqual(merge(self.art, _rdir(self.art), PRODUCT)["status"], "INCOMPLETE")

    def test_unknown_rule_id_rejected(self):
        self._judges()
        self._edit_judge("J1", lambda d: d["verdicts"].append(
            {"rule": "99z", "verdict": "pass", "severity": "WARN", "evidence": []}))
        self.assertEqual(merge(self.art, _rdir(self.art), PRODUCT)["status"], "INCOMPLETE")

    def test_rule_for_another_profile_is_skipped_silently(self):  # ruling B6
        self._judges(extra={"J4": [{"rule": "NR-3", "verdict": "fail", "severity": "WARN",
                                    "evidence": [{"line": 1, "quote": "x", "reason": "y"}]}]})
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual(m["status"], "PASS")
        self.assertEqual(m["problems"], [])
        self.assertNotIn("NR-3", m["rules"])

    def test_lint_block_on_rule_22_skeleton_is_fail(self):  # yaml WARN, lint BLOCK, judge pass
        art, sha = self._prep("I think it's fine. Despite these challenges, the club continues to thrive.",
                              name="998-skel.md")
        _judges(self.dir, report_key(art, Path.cwd()), sha, self.cfg, PRODUCT)
        m = merge(art, _rdir(art), PRODUCT)
        self.assertEqual(m["status"], "FAIL")
        self.assertEqual(m["blocks"], ["22"])
        self.assertEqual((m["rules"]["22"]["verdict"], m["rules"]["22"]["severity"]), ("fail", "BLOCK"))

    def test_judge_block_honoured_for_5e(self):
        self._judges(fails=("5e",), severity={"5e": "BLOCK"})
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual((m["status"], m["blocks"]), ("FAIL", ["5e"]))

    def test_judge_block_on_other_warn_rule_does_not_escalate(self):
        self._judges(fails=("7b",), severity={"7b": "BLOCK"})
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual((m["status"], m["blocks"], m["warns"]), ("UNRESOLVED", [], ["7b"]))

    def test_lint_warn_on_a_block_rule_stays_warn(self):  # 12f MATTR is WARN while mattr_blocking is false (I4)
        art, sha = self._prep(self.BODY, name="997-mattr.md", inject=[
            {"rule": "12f", "severity": "WARN", "line": 0, "excerpt": "mattr 0.31", "message": "m", "source": "lint"}])
        _judges(self.dir, report_key(art, Path.cwd()), sha, self.cfg, PRODUCT)
        m = merge(art, _rdir(art), PRODUCT)
        self.assertEqual((m["status"], m["blocks"], m["warns"], m["unresolved"]), ("UNRESOLVED", [], ["12f"], ["12f"]))
        self._justify([("12f", "metric", REASON)], sha=sha, stem=report_key(art, Path.cwd()))
        self._review({"12f": "accept"}, sha=sha, stem=report_key(art, Path.cwd()))
        self.assertEqual(merge(art, _rdir(art), PRODUCT)["status"], "PASS")

    def test_alias_justification_resolves_its_partner(self):  # the narrative baseline already WARNs NR-5
        warn = lambda rid: {"rule": rid, "severity": "WARN", "line": 0, "excerpt": "x", "message": "m", "source": "lint"}
        for name, (base, alias) in (("996-ar2.md", ("7d", "NR-2")), ("995-ar1.md", ("1", "NR-1"))):
            with self.subTest(pair=(base, alias)):
                art, sha = self._prep(self.BODY, name=name, profile=NARRATIVE, inject=[warn(base), warn(alias)])
                _judges(self.dir, report_key(art, Path.cwd()), sha, self.cfg, NARRATIVE)
                m = merge(art, _rdir(art), NARRATIVE)
                self.assertEqual(sorted(m["warns"]), sorted(["NR-5", base, alias]))
                self.assertEqual(m["status"], "UNRESOLVED")
                self._justify([(base, "voice", REASON), ("NR-5", "format", REASON)], sha=sha, stem=report_key(art, Path.cwd()))
                self._review({base: "accept", "NR-5": "accept"}, sha=sha, stem=report_key(art, Path.cwd()),
                             profile=NARRATIVE)
                m = merge(art, _rdir(art), NARRATIVE)
                self.assertEqual((m["status"], m["unresolved"]), ("PASS", []))

    def test_rejected_rule_is_not_resolved_through_its_alias(self):
        warn = lambda rid: {"rule": rid, "severity": "WARN", "line": 0, "excerpt": "x", "message": "m", "source": "lint"}
        art, sha = self._prep(self.BODY, name="993-ar2.md", profile=NARRATIVE, inject=[warn("7d"), warn("NR-2")])
        _judges(self.dir, report_key(art, Path.cwd()), sha, self.cfg, NARRATIVE)
        self._justify([("7d", "voice", REASON), ("NR-2", "voice", REASON), ("NR-5", "format", REASON)],
                      sha=sha, stem=report_key(art, Path.cwd()))
        self._review({"7d": "reject", "NR-2": "accept", "NR-5": "accept"}, sha=sha, stem=report_key(art, Path.cwd()),
                     profile=NARRATIVE)
        m = merge(art, _rdir(art), NARRATIVE)
        self.assertEqual((m["status"], m["unresolved"]), ("UNRESOLVED", ["7d"]))

    def test_report_is_repo_relative_and_lists_allows(self):
        self._judges()
        m = merge(self.art.resolve(), _rdir(self.art), PRODUCT)
        self.assertEqual(m["article"], str(self.art))
        self.assertEqual(m["allows"], [])
        on_disk = json.loads((self.dir / f"{self.key}.report.json").read_text())
        self.assertEqual((on_disk["status"], on_disk["article_sha256"]), ("PASS", self.sha))




    def test_scare_quoted_ban_word_needs_a_j3_verdict(self):
        self.art, self.sha = self._prep('A "robust" system. ' + self.BODY)
        lint = json.loads((self.dir / f"{self.key}.lint.json").read_text())
        j3 = [r.id for r in self.cfg.rules.values() if r.group == "J3"]
        cands = [f for f in lint["findings"] if f["severity"] == "CANDIDATE" and f["rule"] in j3]
        self.assertEqual([f["rule"] for f in cands], ["2"])  # the judge-input filter in /anti-ai-check step 2
        self._judges(fails=("2",))
        m = merge(self.art, _rdir(self.art), PRODUCT)
        self.assertEqual((m["status"], m["blocks"]), ("FAIL", ["2"]))
        self._judges()
        m = merge(self.art, _rdir(self.art), PRODUCT)  # a genuine mention: J3 passes it (the short fixture's 7d WARN is unrelated)
        self.assertEqual((m["status"], m["blocks"], m["unresolved"]), ("UNRESOLVED", [], ["7d"]))












class CliBadInput(unittest.TestCase):
    """Bad input exits 2 with one line, never 1 (read as "BLOCKs, carry
    on") and never a traceback. A damaged lint or judge file is an input fault: merge gives INCOMPLETE."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=REPO, env=_cli_env(), capture_output=True, text=True)

    def _assert_exit_2(self, path: Path, needle: str):
        for cmd in ("check", "merge"):
            with self.subTest(cmd=cmd):
                extra = ["--reports", str(self.tmp / "r")] if cmd == "merge" else []
                r = self._cli(cmd, str(path), *extra, *PRODUCT_ARGS)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
                self.assertIn(needle, r.stderr)

    def test_malformed_frontmatter_yaml(self):
        p = _article(self.tmp, "Hi.", extra_fm="summary: [unclosed\n")
        self._assert_exit_2(p, "plainspoken: can't check")

    def test_directory_path(self):
        p = self.tmp / "docs" / "blog" / "993-dir.md"
        p.mkdir(parents=True)
        self._assert_exit_2(p, "IsADirectoryError")

    def test_non_utf8_article(self):
        p = _article(self.tmp, "Hi.")
        p.write_bytes(p.read_bytes().replace(b"Hi.", b"Caf\xe9."))
        self._assert_exit_2(p, "UnicodeDecodeError")

    def test_missing_file(self):
        self._assert_exit_2(self.tmp / "992-missing.md", "FileNotFoundError")

    def _merge_with_lint(self, damage) -> subprocess.CompletedProcess:
        p = _article(self.tmp, "I think it's fine. But not always, because reasons.")
        d = _rdir(p)
        d.mkdir(parents=True)
        lint = run_lint(p, PRODUCT)
        damage(d / f"{report_key(p, Path.cwd())}.lint.json", lint)
        _judges(d, report_key(p, Path.cwd()), lint["article_sha256"], load_config(), PRODUCT)
        return self._cli("merge", str(p), "--reports", str(d), *PRODUCT_ARGS)

    def test_merge_non_utf8_lint_json_is_incomplete_not_a_crash(self):
        r = self._merge_with_lint(lambda path, lint: path.write_bytes(json.dumps(lint).encode() + b"\xff"))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("INCOMPLETE", r.stdout)
        self.assertIn("rerun `check`", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_merge_lint_json_missing_keys_is_incomplete_not_a_crash(self):
        def damage(path, lint):
            del lint["lint_rules"], lint["metrics"]
            path.write_text(json.dumps(lint))
        r = self._merge_with_lint(damage)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("malformed", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_merge_non_utf8_judge_file_is_incomplete(self):
        p = _article(self.tmp, "I think it's fine. But not always, because reasons.")
        d = _rdir(p)
        d.mkdir(parents=True)
        lint = run_lint(p, PRODUCT)
        (d / f"{report_key(p, Path.cwd())}.lint.json").write_text(json.dumps(lint))
        _judges(d, report_key(p, Path.cwd()), lint["article_sha256"], load_config(), PRODUCT)
        (d / f"{report_key(p, Path.cwd())}.J2.judge.json").write_bytes(b"\xff\xfe{}")
        r = self._cli("merge", str(p), "--reports", str(d), *PRODUCT_ARGS)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("J2: judge file missing or not valid JSON", r.stdout)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()


class DraftStatus(unittest.TestCase):
    """`status`: the lines a write report quotes, read back from saved files (issue #24)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cfg = load_config()
        self.art = _article(self.tmp, Merge.BODY)
        self.dir = self.tmp / ".plainspoken" / "reports"
        self.key = report_key(self.art, self.tmp)

    def _cli(self, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in _cli_env().items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=self.tmp, env=env,
                              capture_output=True, text=True)

    def _checked(self, fails: tuple = ()) -> subprocess.CompletedProcess:
        """Lint, a full set of judge files and a merge, through the CLI; returns the merge."""
        self.assertIn(self._cli("check", str(self.art), *PRODUCT_ARGS).returncode, (0, 1))
        _judges(self.dir, self.key, file_sha(self.art), self.cfg, PRODUCT, fails=fails)
        return self._cli("merge", str(self.art), *PRODUCT_ARGS)

    def test_quotes_an_unresolved_merge_verbatim(self):
        merged = self._checked(fails=("7b",))
        self.assertTrue(merged.stdout.startswith("UNRESOLVED"), merged.stdout + merged.stderr)
        r = self._cli("status", str(self.art), *PRODUCT_ARGS)
        self.assertEqual(r.returncode, 1, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "check: " + merged.stdout.splitlines()[0])
        self.assertIn("claims: INCOMPLETE", lines)  # no ledger: the claims step never ran, and it shows
        self.assertTrue(lines[-1].startswith("reader-value contract: ") and lines[-1].endswith("(missing)"))
        self.assertFalse((self.dir / f"{self.key}.claims.json").exists())  # it writes nothing

    def test_a_passing_check_still_exits_1_without_claims(self):
        self.assertEqual(self._checked().returncode, 0)
        r = self._cli("status", str(self.art), *PRODUCT_ARGS)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith("check: PASS · coverage "), r.stdout)
        self.assertIn("claims: INCOMPLETE", r.stdout.splitlines())

    def test_no_merge_or_a_stale_one_is_incomplete(self):
        r = self._cli("status", str(self.art), *PRODUCT_ARGS)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith("check: INCOMPLETE (not run"), r.stdout)
        self._checked()
        with self.art.open("a", encoding="utf-8") as f:
            f.write("One more line.\n")
        r = self._cli("status", str(self.art), *PRODUCT_ARGS)
        self.assertTrue(r.stdout.startswith("check: INCOMPLETE (stale"), r.stdout)

    def test_names_an_existing_contract_and_refuses_a_missing_draft(self):
        contract = self.tmp / ".plainspoken" / "reader-value" / f"{self.art.stem}.reader-value.toml"
        contract.parent.mkdir(parents=True)
        contract.write_text("", encoding="utf-8")
        r = self._cli("status", str(self.art), *PRODUCT_ARGS)
        self.assertEqual(r.stdout.splitlines()[-1],
                         f"reader-value contract: .plainspoken/reader-value/{self.art.stem}.reader-value.toml")
        gone = self._cli("status", str(self.tmp / "nope.md"), *PRODUCT_ARGS)
        self.assertEqual((gone.returncode, gone.stdout), (2, ""))

    def test_needs_the_owner_comes_from_the_ledger(self):
        """A report can't say "Needs the owner: none" while the ledger holds a claim open for the owner (#45)."""
        r = self._cli("status", str(self.art), *PRODUCT_ARGS)
        self.assertIn("needs the owner: unknown (no readable ledger)", r.stdout.splitlines())
        ledger = self.tmp / ".plainspoken" / "claims" / f"{self.key}.claims.json"
        ledger.parent.mkdir(parents=True)
        claim = {"claim_id": "A-C1", "text": "before I went out on my own", "locations": [{"kind": "body"}],
                 "claim_type": "first_hand", "prominence": "medium"}
        body = {"schema_version": 1, "article_id": "A", "source_file": self.art.name, "coverage_status": "complete",
                "claims": [{**claim, "status": "opinion_or_inference"}]}
        ledger.write_text(json.dumps(body), encoding="utf-8")
        lines = self._cli("status", str(self.art), *PRODUCT_ARGS).stdout.splitlines()
        self.assertIn("needs the owner: none", lines)
        body["claims"] = [{**claim, "status": "blocking", "resolution": "Not in the brief: ask the owner."}]
        ledger.write_text(json.dumps(body), encoding="utf-8")
        lines = self._cli("status", str(self.art), *PRODUCT_ARGS).stdout.splitlines()
        at = lines.index("needs the owner: 1")
        self.assertEqual(lines[at + 1], "  A-C1: before I went out on my own (blocking)")
        self.assertIn("claims: BLOCKED", lines)
        self.assertTrue(lines[-1].startswith("reader-value contract: "))

    def test_gives_the_drafts_word_count_as_the_check_counts_it(self):
        """A report states the piece's real length from the engine, not an estimate (issue #32)."""
        want = run_lint(self.art, PRODUCT, "article", self.cfg)["metrics"]["words"]
        self.assertGreater(want, 0)
        label = " (body text; headings, tables, code and numbers not counted)"  # #63: say what it counts
        r = self._cli("status", str(self.art), *PRODUCT_ARGS)  # before any check: the count doesn't need one
        self.assertIn(f"words: {want}{label}", r.stdout.splitlines())
        with self.art.open("a", encoding="utf-8") as f:
            f.write("\nOne more short line here.\n\n## A heading of five words\n\nIn 2026, 42 more.\n")
        r = self._cli("status", str(self.art), *PRODUCT_ARGS)
        self.assertIn(f"words: {want + 7}{label}", r.stdout.splitlines())  # read from the draft as it is now
