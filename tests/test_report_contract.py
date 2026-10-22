import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken import report
from tests._profiles import PRODUCT

REPO = Path(__file__).resolve().parents[1]


def cli(*args, cwd):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_"))}
    env["PYTHONPATH"] = str(REPO / "lib")
    return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=cwd, capture_output=True, text=True, env=env)


class Width(unittest.TestCase):  # the contract doc keeps the docs' line width
    def test_lines_keep_the_file_width(self):
        text = (REPO / "docs" / "report-contract.md").read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), start=1):
            self.assertLessEqual(len(line), 118, f"line {n}: {line[:60]}…")


class Keys(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)

    def test_same_stem_different_folders_get_different_keys(self):
        a, b = self.cwd / "a" / "index.md", self.cwd / "b" / "index.md"
        ka, kb = report.report_key(a, self.cwd), report.report_key(b, self.cwd)
        self.assertNotEqual(ka, kb)
        self.assertTrue(ka.startswith("index-") and len(ka) == len("index-") + 8)

    def test_key_is_stable_for_relative_and_absolute_forms(self):
        art = self.cwd / "post.md"
        rel = Path(os.path.relpath(art, Path.cwd()))
        self.assertEqual(report.report_key(art, self.cwd), report.report_key(rel.resolve(), self.cwd))

    def test_paths_cover_every_file(self):
        p = report.report_paths(self.cwd / "post.md", self.cwd / ".plainspoken" / "reports", self.cwd)
        self.assertEqual(set(p), {"lint", "J1", "J2", "J3", "J4", "JR", "justify", "report", "reply", "claims",
                                  "claims-check", "delivery", "delivery-reply", "checked"})
        key = report.report_key(self.cwd / "post.md", self.cwd)
        self.assertEqual(p["claims"].name, f"{key}.claims.json")
        self.assertEqual(p["claims-check"].name, f"{key}.claims-check.json")
        self.assertEqual(p["delivery"].name, f"{key}.delivery.json")
        self.assertEqual(p["delivery-reply"].name, f"{key}.delivery-reply.json")
        self.assertEqual(p["J2"].name, f"{key}.J2.judge.json")
        self.assertEqual(p["report"].name, f"{key}.report.json")
        self.assertEqual(p["reply"].name, f"{key}.reply.json")
        self.assertEqual(p["checked"].name, f"{key}.checked.md")


class TwoIndexFiles(unittest.TestCase):
    """Same file name in two folders, two independent verdicts."""

    def test_check_and_merge_keep_them_apart(self):
        cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, cwd, ignore_errors=True)
        for folder, text in (("a", "I fixed it on Friday.\n"), ("b", "We delve into a robust tapestry.\n")):
            (cwd / folder).mkdir()
            (cwd / folder / "index.md").write_text(text, encoding="utf-8")
        ra = cli("check", "a/index.md", "--profile", "default", cwd=cwd)
        rb = cli("check", "b/index.md", "--profile", "default", cwd=cwd)
        self.assertEqual((ra.returncode, rb.returncode), (0, 1), ra.stderr + rb.stderr)
        lints = sorted((cwd / ".plainspoken" / "reports").glob("index-*.lint.json"))
        self.assertEqual(len(lints), 2)
        statuses = {json.loads(p.read_text(encoding="utf-8"))["article"] for p in lints}
        self.assertEqual(len(statuses), 2)


class CheckWrites(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        (self.cwd / "post.md").write_text("I fixed it on Friday.\n", encoding="utf-8")

    def test_default_writes_lint_under_dot_plainspoken(self):
        self.assertEqual(cli("check", "post.md", "--profile", "default", cwd=self.cwd).returncode, 0)
        out = json.loads(cli("paths", "post.md", cwd=self.cwd).stdout)
        self.assertTrue(Path(out["lint"]).is_file())

    def test_no_save_writes_nothing(self):
        cli("check", "post.md", "--profile", "default", "--no-save", cwd=self.cwd)
        self.assertFalse((self.cwd / ".plainspoken").exists())

    def test_reports_dir_option(self):
        cli("check", "post.md", "--profile", "default", "--reports", "r", cwd=self.cwd)
        self.assertEqual(len(list((self.cwd / "r").glob("post-*.lint.json"))), 1)


class AtomicWrites(unittest.TestCase):  # every report file goes through write_atomic, as report.json does
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        (self.cwd / ".git").mkdir()
        self.art = self.cwd / "post.md"
        self.art.write_text("I fixed it on Friday.\n", encoding="utf-8")
        self.reports = self.cwd / ".plainspoken" / "reports"
        self.paths = report.report_paths(self.art, self.reports, self.cwd)

    def _atomic(self):
        from unittest import mock
        return mock.patch.object(report, "write_atomic", wraps=report.write_atomic)

    def test_lint_json(self):
        import contextlib
        import io
        from plainspoken import __main__ as cli_main
        old = os.getcwd()
        os.chdir(self.cwd)
        self.addCleanup(os.chdir, old)
        with self._atomic() as atomic, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli_main.main(["check", "post.md", "--profile", "default"]), 0)
        self.assertIn(self.paths["lint"], [Path(c.args[0]) for c in atomic.call_args_list])
        self.assertEqual(json.loads(self.paths["lint"].read_text(encoding="utf-8"))["article_sha256"],
                         report.sha256(self.art))

    def test_judge_file(self):
        from plainspoken import judges
        self.reports.mkdir(parents=True)
        lint = report.run_lint(self.art, PRODUCT)
        self.paths["lint"].write_text(json.dumps(lint), encoding="utf-8")
        reply = json.dumps({"group": "J2", "article_sha256": report.sha256(self.art),
                            "input_digest": judges.input_digest(lint, "J2"),
                            "judged_at": "2026-10-10T00:00:00Z", "verdicts": []})
        with self._atomic() as atomic:
            out = judges.record_reply(self.art, "J2", reply, self.reports, self.cwd)
        atomic.assert_called_once()
        self.assertEqual(Path(atomic.call_args.args[0]), self.paths["J2"])
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["group"], "J2")

    def test_claims_json(self):
        from plainspoken import __main__ as cli_main
        target = self.paths["claims"]
        with self._atomic() as atomic:
            cli_main._write_claims_report(target, '{"status": "PASS"}')
        atomic.assert_called_once()
        self.assertEqual(Path(atomic.call_args.args[0]), target)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"status": "PASS"})


class Residuals(unittest.TestCase):
    def test_rules_file_with_wrong_type_names_the_key(self):
        from plainspoken.registry import load_config
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        broken = tmp / "rules2.toml"
        broken.write_text('version = "1"\nrules = 5\nlists = {}\n[thresholds.default]\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"rules2\.toml.*'rules'"):
            load_config(broken)

    def test_dash_item_after_key_is_refused(self):
        from plainspoken.frontmatter import FrontmatterError, load
        with self.assertRaises(FrontmatterError):
            load("key: - a")


# --- the report contract a host sink reads -------------------------------------------------------------------------

V040_REPORT = REPO / "tests" / "fixtures" / "report" / "v0.4.0.report.json"
REPORT_BODY = ("I broke the build on Friday. Furthermore, the tests were robust and the fix was crucial.\n\n"
               "But the second run passed, because I'd pinned the version. Not just a fix, it's a lesson.\n")


def _project(tmp: Path) -> Path:
    (tmp / ".git").mkdir()
    (tmp / "posts").mkdir()
    art = tmp / "posts" / "post.md"
    art.write_text(f"---\ntitle: \"T\"\n---\n\n{REPORT_BODY}", encoding="utf-8")
    return art


def _judge_all(art: Path, reports: Path, root: Path, profile, fails: tuple = ()) -> None:
    """A judge file per group, with a verdict for every judge rule; `fails` fail with evidence."""
    from plainspoken.registry import load_config
    cfg = load_config()
    sha = report.sha256(art)
    paths = report.report_paths(art, reports, root)
    groups: dict[str, list] = {}
    for r in cfg.rules_for_profile(profile):
        if "judge" in r.method and r.status != "shadow":
            groups.setdefault(r.group, []).append(r)
    for g, rules in groups.items():
        verdicts = [{"rule": r.id, "verdict": "fail" if r.id in fails else "pass", "severity": r.severity,
                     "evidence": [{"line": 7, "quote": "Not just a fix", "reason": "a reveal"}] if r.id in fails
                     else []} for r in rules]
        paths[g].write_text(json.dumps({"group": g, "article_sha256": sha, "judged_at": "2026-10-19T00:00:00Z",
                                        "verdicts": verdicts, "profile_sha256": profile.sha256,
                                        "ruleset_version": cfg.version}), encoding="utf-8")


class ReportContract(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.art = _project(self.root)
        self.reports = report.reports_dir_default(self.root)

    def _schema(self) -> dict:
        from plainspoken import schema
        return schema.load("report")

    def test_profile_json_stamps(self):  # item 1
        from plainspoken.registry import load_config
        prof_dir = self.root / ".plainspoken" / "profiles"
        prof_dir.mkdir(parents=True)
        mine = prof_dir / "mine.toml"
        mine.write_text('[profile]\nname = "mine"\n', encoding="utf-8")
        (prof_dir / "quiet.toml").write_text('[profile]\nname = "quiet"\n[rules]\ndisabled = ["2"]\n',
                                             encoding="utf-8")
        (self.root / ".plainspoken" / "config.toml").write_text(
            '[engine]\nprofile = "mine"\nprofiles = [{ glob = "posts/**", profile = "quiet" }]\n', encoding="utf-8")
        r = cli("profile", "--json", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(set(out), {"name", "path", "profile_sha256", "ruleset_version", "root"})
        self.assertEqual(out["name"], "mine")
        self.assertEqual(Path(out["path"]), mine)
        self.assertEqual(out["ruleset_version"], load_config().version)
        self.assertEqual(Path(out["root"]), self.root)
        self.assertRegex(out["profile_sha256"], r"^[0-9a-f]{64}$")
        # from a subfolder: the same root, so a sink can find the reports `check` and `merge` wrote
        self.assertEqual(json.loads(cli("profile", "--json", cwd=self.root / "posts").stdout)["root"],
                         str(self.root))
        # an article argument gives that file's profile, the one `check` and `merge` stamp
        per_file = json.loads(cli("profile", "--json", "posts/post.md", cwd=self.root).stdout)
        self.assertEqual(per_file["name"], "quiet")
        # editing the profile changes the stamp, so a sink can tell a report is no longer current
        mine.write_text('[profile]\nname = "mine"\n[rules]\ndisabled = ["16"]\n', encoding="utf-8")
        edited = json.loads(cli("profile", "--json", cwd=self.root).stdout)
        self.assertNotEqual(edited["profile_sha256"], out["profile_sha256"])
        # the stamp is the one `check` writes into the lint
        cli("check", "posts/post.md", cwd=self.root)
        lint = json.loads(Path(json.loads(cli("paths", "posts/post.md", cwd=self.root).stdout)["lint"])
                          .read_text(encoding="utf-8"))
        self.assertEqual((lint["profile_sha256"], lint["ruleset_version"]),
                         (per_file["profile_sha256"], per_file["ruleset_version"]))
        # --json doesn't go with --voice
        self.assertEqual(cli("profile", "--json", "--voice", cwd=self.root).returncode, 2)

    def test_merge_report_matches_schema(self):  # item 4
        from plainspoken import justify, schema
        sch = self._schema()
        lint = report.run_lint(self.art, PRODUCT)
        paths = report.report_paths(self.art, self.reports, self.root)
        self.reports.mkdir(parents=True)
        paths["lint"].write_text(json.dumps(lint), encoding="utf-8")
        # INCOMPLETE: no judge files, so lint+judge rules stay pending
        incomplete = report.merge(self.art, self.reports, PRODUCT, cwd=self.root)
        self.assertEqual(incomplete["status"], "INCOMPLETE")
        self.assertEqual(schema.validate(incomplete, sch), [])
        # every judge in, two WARN fails, one justification accepted and one rejected
        _judge_all(self.art, self.reports, self.root, PRODUCT, fails=("7b", "7c"))
        first = report.merge(self.art, self.reports, PRODUCT, cwd=self.root)
        self.assertEqual(schema.validate(first, sch), [])
        reason = "the contrast is the point of the paragraph"
        paths["justify"].write_text(json.dumps({"article_sha256": lint["article_sha256"], "items": [
            {"rule": "7b", "kind": "voice", "reason": reason}, {"rule": "7c", "kind": "load_bearing", "reason": reason},
            {"rule": "16", "kind": "voice", "reason": reason}]}), encoding="utf-8")
        paths["JR"].write_text(json.dumps({
            "group": "JR", "article_sha256": lint["article_sha256"], "justify_sha256": justify.file_sha(paths["justify"]),
            "judged_at": "2026-10-19T00:00:00Z", "profile_sha256": PRODUCT.sha256, "ruleset_version": lint["ruleset_version"],
            "verdicts": [{"rule": "7b", "verdict": "accept", "reason": "checked"},
                         {"rule": "7c", "verdict": "reject", "reason": "checked"}]}), encoding="utf-8")
        merged = report.merge(self.art, self.reports, PRODUCT, cwd=self.root)
        self.assertEqual(len(merged["justified"]), 2, merged["problems"])
        on_disk = json.loads(paths["report"].read_text(encoding="utf-8"))
        self.assertEqual(schema.validate(on_disk, sch), [])
        # the schema pins the shape: a damaged report fails it
        bad = dict(on_disk, status="MAYBE")
        bad["rules"] = {**on_disk["rules"], "x": {"source": "lint", "verdict": "pass"}}
        errors = schema.validate(bad, sch)
        self.assertTrue(any(e.startswith("status:") for e in errors), errors)
        self.assertTrue(any(e.startswith("rules.x:") for e in errors), errors)

    def test_v040_report_fixture_validates(self):  # a v0.4.0 report still reads
        """tests/fixtures/report/v0.4.0.report.json is the `<key>.report.json` the installed v0.4.0 plugin's own
        `report.merge` wrote (2026-10-19): `check`-equivalent lint, hand-built J1–J4 replies with two WARN fails,
        a justify file and a JR review accepting one and rejecting one, and an allow marker. Not hand-edited."""
        from plainspoken import schema
        data = json.loads(V040_REPORT.read_text(encoding="utf-8"))
        self.assertEqual((data["ruleset_version"], data["status"]), ("4.1.0", "FAIL"))
        self.assertEqual(schema.validate(data, self._schema()), [])

    def test_merge_writes_atomically(self):  # item 3
        from unittest import mock
        self.reports.mkdir(parents=True)
        paths = report.report_paths(self.art, self.reports, self.root)
        paths["lint"].write_text(json.dumps(report.run_lint(self.art, PRODUCT)), encoding="utf-8")
        with mock.patch.object(report, "write_atomic", wraps=report.write_atomic) as atomic, \
                mock.patch.object(Path, "write_text", side_effect=AssertionError("merge used write_text")):
            report.merge(self.art, self.reports, PRODUCT, cwd=self.root)
        atomic.assert_called_once()
        self.assertEqual(Path(atomic.call_args.args[0]), paths["report"])
        self.assertEqual(json.loads(paths["report"].read_text(encoding="utf-8"))["status"], "INCOMPLETE")

    def test_schema_enums_track_the_engine(self):  # a new content type or kind must update the schema too
        from plainspoken import justify
        from plainspoken.doc import CONTENT_TYPES
        sch = self._schema()
        self.assertEqual(sch["properties"]["content_type"]["enum"], list(CONTENT_TYPES))
        self.assertEqual(sch["$defs"]["justified"]["properties"]["kind"]["enum"], list(justify.KINDS))

    def test_evidence_that_isnt_a_list_is_a_bad_verdict(self):  # so a merged report always matches the schema
        from plainspoken import schema
        self.reports.mkdir(parents=True)
        paths = report.report_paths(self.art, self.reports, self.root)
        paths["lint"].write_text(json.dumps(report.run_lint(self.art, PRODUCT)), encoding="utf-8")
        _judge_all(self.art, self.reports, self.root, PRODUCT)
        j1 = json.loads(paths["J1"].read_text(encoding="utf-8"))
        j1["verdicts"][0]["evidence"] = "fine"
        paths["J1"].write_text(json.dumps(j1), encoding="utf-8")
        merged = report.merge(self.art, self.reports, PRODUCT, cwd=self.root)
        self.assertEqual(merged["status"], "INCOMPLETE")
        self.assertTrue(any(p.startswith("J1: bad verdict entry") for p in merged["problems"]), merged["problems"])
        self.assertEqual(schema.validate(merged, self._schema()), [])
