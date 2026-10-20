import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "profiles"


def cli(*args, cwd: Path, env: dict | None = None, input: str | None = None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_"))}
    e["PYTHONPATH"] = str(REPO / "lib")
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=cwd, capture_output=True, text=True, env=e, input=input)


class JudgeCli(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.art = self.cwd / "post.md"
        self.art.write_text("Text.\n", encoding="utf-8")

    def test_judge_input_without_lint_exits_2(self):
        r = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("check", r.stderr)

    def test_judge_input_prints_four_lines(self):
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        r = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([json.loads(x)["group"] for x in r.stdout.splitlines()], ["J1", "J2", "J3", "J4"])

    def test_judge_record_valid_and_invalid(self):
        import hashlib
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        sha = hashlib.sha256(self.art.read_bytes()).hexdigest()
        body = json.dumps({"group": "J2", "article_sha256": sha, "judged_at": "t", "verdicts": []})
        ok = cli("judge-record", "post.md", "--group", "J2", cwd=self.cwd, input="```json\n" + body + "\n```\n")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = cli("judge-record", "post.md", "--group", "J3", cwd=self.cwd, input=body)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("judge reply not recorded", bad.stderr)

    def test_judge_record_from_file_consumes_it(self):
        """E2E defect: Claude Code's shell check stops JSON in a heredoc, so replies go through a file."""
        import hashlib
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        sha = hashlib.sha256(self.art.read_bytes()).hexdigest()
        reply = Path(json.loads(cli("paths", "post.md", cwd=self.cwd).stdout)["reply"])
        reply.parent.mkdir(parents=True, exist_ok=True)
        reply.write_text(json.dumps({"group": "J2", "article_sha256": sha, "judged_at": "t", "verdicts": []}),
                         encoding="utf-8")
        ok = cli("judge-record", "post.md", "--group", "J2", "--from", str(reply), cwd=self.cwd)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertFalse(reply.exists(), "a recorded reply file is removed so the next Write starts fresh")
        written = json.loads(Path(ok.stdout.strip()).read_text(encoding="utf-8"))
        self.assertEqual(written["group"], "J2")

    def test_judge_record_from_file_rejected_reply_is_removed_too(self):
        reply = Path(json.loads(cli("paths", "post.md", cwd=self.cwd).stdout)["reply"])
        reply.parent.mkdir(parents=True, exist_ok=True)
        reply.write_text('{"group": "J3"}', encoding="utf-8")
        bad = cli("judge-record", "post.md", "--group", "J3", "--from", str(reply), cwd=self.cwd)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("judge reply not recorded", bad.stderr)
        self.assertFalse(reply.exists())

    def test_judge_record_from_another_file_leaves_it_in_place(self):
        """Only the scratch `reply` path is consumed; any other --from file is read, never deleted."""
        import hashlib
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        sha = hashlib.sha256(self.art.read_bytes()).hexdigest()
        keep = self.cwd / "keep.md"
        for body in (json.dumps({"group": "J2", "article_sha256": sha, "judged_at": "t", "verdicts": []}),
                     '{"group": "J3"}'):
            with self.subTest(body=body[:20]):
                keep.write_text(body, encoding="utf-8")
                r = cli("judge-record", "post.md", "--group", "J2", "--from", "keep.md", cwd=self.cwd)
                self.assertIn(r.returncode, (0, 1), r.stderr)
                self.assertTrue(keep.exists(), "a --from file that isn't the reply path must survive")

    def test_judge_record_from_missing_file_exits_2(self):
        r = cli("judge-record", "post.md", "--group", "J1", "--from", "nope.json", cwd=self.cwd)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("can't read the judge reply nope.json", r.stderr)


class Cli(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.art = self.cwd / "post.md"
        self.art.write_text('---\ntitle: "T"\n---\n\nWe delve into a robust tapestry.\n', encoding="utf-8")

    def test_check_block_exits_1_and_stamps_report(self):
        out = self.cwd / "lint.json"
        r = cli("check", str(self.art), "--profile", "default", "--out", str(out), cwd=self.cwd)
        self.assertEqual(r.returncode, 1, r.stderr)
        rep = json.loads(out.read_text(encoding="utf-8"))
        for key in ("article_sha256", "ruleset_version", "profile", "profile_sha256", "content_type"):
            self.assertIn(key, rep)
        self.assertEqual(rep["profile"], "default")

    def test_clean_text_exits_0(self):
        self.art.write_text("I fixed the bug on Friday and it hasn't come back.\n", encoding="utf-8")
        self.assertEqual(cli("check", str(self.art), "--profile", "default", cwd=self.cwd).returncode, 0)

    def test_no_profile_exits_2_with_one_line(self):
        r = cli("check", str(self.art), cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no profile", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertTrue(r.stderr.startswith("plainspoken:"))

    def test_bad_profile_names_file_and_key(self):
        bad = self.cwd / "bad.toml"
        bad.write_text('[profile]\nname = "x"\n[thresholds]\nem_dash_maxx = 2\n', encoding="utf-8")
        r = cli("check", str(self.art), "--profile", str(bad), cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("bad.toml", r.stderr)
        self.assertIn("em_dash_maxx", r.stderr)

    def test_unsupported_frontmatter_exits_2(self):
        self.art.write_text("---\na: &x 1\n---\n\nText.\n", encoding="utf-8")
        r = cli("check", str(self.art), "--profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("anchors", r.stderr)

    def test_merge_writes_under_dot_plainspoken(self):
        r = cli("merge", str(self.art), "--profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 1)  # no judge files yet → INCOMPLETE
        self.assertEqual(len(list((self.cwd / ".plainspoken" / "reports").glob("post-*.report.json"))), 1)
        self.assertIn("INCOMPLETE", r.stdout)

    def test_empty_plugin_profile_is_the_plugin_default(self):
        r = cli("profile", "--plugin-profile", "", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("default (plugin default)", r.stdout)

    def test_profile_summary_names_the_gate_strictness(self):
        r = cli("profile", "--profile", "default", cwd=self.cwd)
        self.assertIn("gate: watch (default)", r.stdout)
        (self.cwd / ".plainspoken").mkdir()
        (self.cwd / ".plainspoken" / "config.toml").write_text('[gate]\nstrictness = "block"\n', encoding="utf-8")
        r = cli("profile", "--profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("gate: block (project config)", r.stdout)

    def test_profile_from_project_config(self):
        (self.cwd / ".plainspoken").mkdir()
        (self.cwd / ".plainspoken" / "config.toml").write_text('[engine]\nprofile = "default"\n', encoding="utf-8")
        self.assertEqual(cli("check", str(self.art), cwd=self.cwd).returncode, 1)

    def test_content_type_social_is_stamped(self):
        out = self.cwd / "lint.json"
        cli("check", str(self.art), "--profile", "default", "--content-type", "social", "--out", str(out), cwd=self.cwd)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["content_type"], "social")

    def test_non_string_config_profile_exits_2_without_traceback(self):
        (self.cwd / ".plainspoken").mkdir()
        (self.cwd / ".plainspoken" / "config.toml").write_text("[engine]\nprofile = 5\n", encoding="utf-8")
        r = cli("check", str(self.art), cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("[engine] profile", r.stderr)


class NoTraceback(unittest.TestCase):
    """Exit 1 means "BLOCK, carry on" to /anti-ai-check, so no path may traceback (exit 1)."""

    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.art = self.cwd / "post.md"
        self.art.write_text('---\ntitle: "T"\n---\n\nI fixed the bug on Friday.\n', encoding="utf-8")

    def _one_line_exit_2(self, r, needle: str):
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertTrue(r.stderr.startswith("plainspoken:"), r.stderr)
        self.assertIn(needle, r.stderr)

    def test_check_out_unwritable_exits_2(self):
        (self.cwd / "adir").mkdir()
        (self.cwd / "afile").write_text("x", encoding="utf-8")
        for out in (self.cwd / "adir", self.cwd / "afile" / "x.json"):
            with self.subTest(out=out.name):
                r = cli("check", str(self.art), "--profile", "default", "--out", str(out), cwd=self.cwd)
                self._one_line_exit_2(r, str(out))

    def test_rules_file_missing_a_key_exits_2_naming_file_and_key(self):
        text = (REPO / "data" / "rules.toml").read_text(encoding="utf-8")
        cases = {
            "version": text.replace('version = "4.3.0"\n', "", 1),
            "lists": text.replace("[lists]", "[lists_gone]", 1),
            "rules": text.replace("[[rules]]", "[[rules_gone]]"),
            "name": text.replace('name = "Em dashes"\n', "", 1),
        }
        for key, body in cases.items():
            with self.subTest(key=key):
                self.assertNotEqual(body, text)
                bad = self.cwd / f"rules-{key}.toml"
                bad.write_text(body, encoding="utf-8")
                for cmd in ("check", "merge"):
                    r = cli(cmd, str(self.art), "--profile", "default", cwd=self.cwd,
                            env={"PLAINSPOKEN_RULES": str(bad)})
                    self._one_line_exit_2(r, bad.name)
                    self.assertIn(repr(key), r.stderr)

    def test_unexpected_exception_is_one_line_exit_2(self):
        import contextlib
        import io
        from unittest import mock

        from plainspoken import __main__ as cli_main, report
        err = io.StringIO()
        with mock.patch.object(report, "run_lint", side_effect=RuntimeError("boom\nsecond line")), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = cli_main.main(["check", str(self.art), "--profile", "default"])
        self.assertEqual(rc, 2)
        self.assertEqual(err.getvalue(), "plainspoken: internal error: RuntimeError: boom\n")


class ConfigCli(unittest.TestCase):  # `config profile-for`
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        (self.cwd / ".git").mkdir()
        prof = self.cwd / ".plainspoken" / "profiles"
        prof.mkdir(parents=True)
        (prof / "quiet.toml").write_text('[profile]\nname = "quiet"\n[rules]\ndisabled = ["2"]\n', encoding="utf-8")
        (self.cwd / "docs").mkdir()
        self.doc = self.cwd / "docs" / "post.md"
        self.doc.write_text("We delve into it.\n", encoding="utf-8")

    def project(self, toml: str) -> None:
        (self.cwd / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def test_profile_for_prints_the_match_or_exits_3(self):
        self.project('[engine]\nprofiles = [{ glob = "docs/**", profile = "profiles/quiet.toml" }]\n')
        r = cli("config", "profile-for", "docs/post.md", cwd=self.cwd)
        self.assertEqual((r.returncode, r.stdout), (0, str(self.cwd / ".plainspoken/profiles/quiet.toml") + "\n"))
        r = cli("config", "profile-for", "post.md", cwd=self.cwd / "docs")  # run from a subfolder
        self.assertEqual(r.returncode, 0, r.stderr)
        r = cli("config", "profile-for", "notes.md", cwd=self.cwd)
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        self.assertIn("no profile", r.stderr)
        self.project('[engine]\nprofile = "default"\nprofiles = [{ glob = "docs/**", profile = "quiet" }]\n')
        self.assertEqual(cli("config", "profile-for", "notes.md", cwd=self.cwd).stdout, "default\n")
        # the environment still beats the project config, as in every other command
        r = cli("config", "profile-for", "docs/post.md", cwd=self.cwd, env={"PLAINSPOKEN_PROFILE": "default"})
        self.assertEqual(r.stdout, "default\n")

    def test_profile_for_bad_config_exits_2(self):
        self.project('[engine]\nprofiles = "quiet"\n')
        r = cli("config", "profile-for", "docs/post.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("[engine] profiles", r.stderr)

    def test_profile_for_missing_path_profile_exits_2(self):  # never print a path that can't load
        self.project('[engine]\nprofiles = [{ glob = "docs/**", profile = "profiles/missing.toml" }]\n')
        r = cli("config", "profile-for", "docs/post.md", cwd=self.cwd)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("missing.toml", r.stderr)
        self.project('[engine]\nprofiles = [{ glob = "docs/**", profile = ".plainspoken/profiles/quiet.toml" }]\n')
        r = cli("config", "profile-for", "docs/post.md", cwd=self.cwd)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("drop the leading .plainspoken/", r.stderr)

    def test_check_uses_the_files_profile(self):
        self.project('[engine]\nprofile = "default"\nprofiles = [{ glob = "docs/**", profile = "quiet" }]\n')
        r = cli("check", "docs/post.md", "--no-save", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("quiet", r.stdout)
        other = self.cwd / "post.md"
        other.write_text("We delve into it.\n", encoding="utf-8")
        r = cli("check", "post.md", "--no-save", cwd=self.cwd)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
