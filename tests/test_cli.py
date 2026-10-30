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

    def test_judge_input_holds_open_lint_lines(self):  # #74: a lint-owned WARN at the judges cost a second round
        self.art.write_text("Also the vans run late. Also the gate is shut. Also the tea is cold. Also the dog barks.\n",
                            encoding="utf-8")
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        held = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual((held.returncode, held.stdout), (1, ""), held.stderr)
        for line in ("WARN  r4b", "WARN  r7d", "WARN  rHM", "--keep"):
            self.assertIn(line, held.stderr)
        partial = cli("judge-input", "post.md", "--profile", "default", "--keep", "r4b,7d", cwd=self.cwd)
        self.assertEqual(partial.returncode, 1)
        self.assertIn("rHM", partial.stderr)
        self.assertNotIn("r4b", partial.stderr)
        kept = cli("judge-input", "post.md", "--profile", "default", "--keep", "4b,r7d", "--keep", "HM", cwd=self.cwd)
        self.assertEqual(kept.returncode, 0, kept.stderr)
        self.assertEqual([json.loads(x)["group"] for x in kept.stdout.splitlines()], ["J1", "J2", "J3", "J4"])

    def test_keep_names_only_open_lines(self):  # #162: a keep typed before the lint was read is refused
        self.art.write_text("Also the vans run late. Also the gate is shut. Also the tea is cold. Also the dog barks.\n",
                            encoding="utf-8")
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        stray = cli("judge-input", "post.md", "--profile", "default", "--keep", "4b,7d,HM,r2", cwd=self.cwd)
        self.assertEqual((stray.returncode, stray.stdout), (2, ""), stray.stderr)
        self.assertIn("--keep r2:", stray.stderr)
        self.assertIn("keep only the rules it prints", stray.stderr)
        kept = cli("judge-input", "post.md", "--profile", "default", "--keep", "4b,r7d,HM", cwd=self.cwd)
        self.assertEqual(kept.returncode, 0, kept.stderr)
        self.assertIn("kept with --keep", kept.stderr)  # the kept lines are shown even if the lint went unread
        for line in ("WARN  r4b", "WARN  r7d", "WARN  rHM"):
            self.assertIn(line, kept.stderr)
        self.art.write_text("Text.\n", encoding="utf-8")  # fixed since: last pass's keep names nothing open now
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual(cli("judge-input", "post.md", "--profile", "default", "--keep", "7d", cwd=self.cwd).returncode,
                         2)
        clean = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual((clean.returncode, clean.stderr), (0, ""))

    def test_report_only_keeps_a_block_and_never_edits(self):  # #107: skills/check/SKILL.md "Report only"
        import hashlib
        import re
        # 16 r2 BLOCKs fill the lint's 15-line BLOCK list, so the r4a BLOCK after them is hidden behind "… N more".
        lines = [f"Line {i} has to delve into the plan." for i in range(16)] + ["Furthermore, the vans run late."]
        self.art.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
        before = hashlib.sha256(self.art.read_bytes()).hexdigest()
        lint = cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual(lint.returncode, 1, lint.stderr)
        self.assertRegex(lint.stdout, r"BLOCK\s+… \d+ more")
        self.assertNotIn("r4a", lint.stdout)
        held = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual((held.returncode, held.stdout), (1, ""), held.stderr)
        listed = re.findall(r"(?m)^\s+(BLOCK|WARN)\s+(\S+)\s+L\d+", held.stderr)
        rules = sorted({rule for _, rule in listed})
        self.assertIn(("BLOCK", "r4a"), listed, "judge-input's exit-1 list names the rule the lint hid")
        kept = cli("judge-input", "post.md", "--profile", "default", "--keep", ",".join(rules), cwd=self.cwd)
        self.assertEqual(kept.returncode, 0, kept.stderr)
        inputs = [json.loads(x) for x in kept.stdout.splitlines()]
        self.assertEqual([i["group"] for i in inputs], ["J1", "J2", "J3", "J4"])
        replies = [{"group": i["group"], "article_sha256": before, "input_digest": i["input_digest"], "judged_at": "t",
                    "verdicts": [{"rule": r, "verdict": "pass", "severity": i["severities"][r], "evidence": []}
                                 for r in i["rules"]]} for i in inputs]  # all four judges pass everything
        rec = cli("judge-record", "post.md", "--all", "--from", str(self._scratch("\n".join(map(json.dumps, replies)))),
                  cwd=self.cwd)
        self.assertEqual(rec.returncode, 0, rec.stderr)
        merged = cli("merge", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual(merged.returncode, 1, merged.stderr)
        self.assertRegex(merged.stdout, r"^FAIL\b")  # a kept BLOCK can't reach PASS, whatever the judges say
        self.assertRegex(merged.stdout, r"BLOCK [^·]*\b4a\b")
        self.assertEqual(hashlib.sha256(self.art.read_bytes()).hexdigest(), before)

    def test_judge_record_valid_and_invalid(self):
        import hashlib
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        sha = hashlib.sha256(self.art.read_bytes()).hexdigest()
        body = json.dumps(self._reply("J2", sha))
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
        reply.write_text(json.dumps(self._reply("J2", sha)),
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
        for body in (json.dumps(self._reply("J2", sha)),
                     '{"group": "J3"}'):
            with self.subTest(body=body[:20]):
                keep.write_text(body, encoding="utf-8")
                r = cli("judge-record", "post.md", "--group", "J2", "--from", "keep.md", cwd=self.cwd)
                self.assertIn(r.returncode, (0, 1), r.stderr)
                self.assertTrue(keep.exists(), "a --from file that isn't the reply path must survive")

    def _reply(self, group: str, sha: str | None = None) -> dict:
        import hashlib
        sha = sha or hashlib.sha256(self.art.read_bytes()).hexdigest()
        return {"group": group, "article_sha256": sha, "input_digest": self._digest(group), "judged_at": "t",
                "verdicts": []}

    def _digest(self, group: str) -> str | None:
        """The `input_digest` judge-input gives `group` now (#43), or None (JR has none)."""
        r = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd)
        return next((json.loads(x)["input_digest"] for x in r.stdout.splitlines()
                     if json.loads(x)["group"] == group), None)

    def _scratch(self, text: str) -> Path:
        reply = Path(json.loads(cli("paths", "post.md", cwd=self.cwd).stdout)["reply"])
        reply.parent.mkdir(parents=True, exist_ok=True)
        reply.write_text(text, encoding="utf-8")
        return reply

    def test_judge_record_all_records_four_replies_from_one_file(self):
        """#28: one Write and one record call per judge round, not one pair per judge."""
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        objs = [self._reply(g) for g in ("J1", "J2", "J3", "J4")]
        layouts = {
            "one after another": "\n".join(json.dumps(o) for o in objs),
            "pretty, one fenced": "```json\n" + json.dumps(objs[0], indent=2) + "\n```\n"
                                  + "\n\n".join(json.dumps(o, indent=2) for o in objs[1:]),
            "a JSON list": json.dumps(objs),
        }
        for name, text in layouts.items():
            with self.subTest(layout=name):
                reply = self._scratch(text)
                r = cli("judge-record", "post.md", "--all", "--from", str(reply), cwd=self.cwd)
                self.assertEqual(r.returncode, 0, r.stderr)
                written = [Path(p) for p in r.stdout.split()]
                self.assertEqual([json.loads(p.read_text(encoding="utf-8"))["group"] for p in written],
                                 ["J1", "J2", "J3", "J4"])
                self.assertFalse(reply.exists(), "the scratch reply is consumed, as with --group")

    def test_judge_record_all_records_the_good_ones_and_names_the_rest(self):
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        paths = json.loads(cli("paths", "post.md", cwd=self.cwd).stdout)
        text = "\n".join(json.dumps(o) for o in (self._reply("J1"), self._reply("J2", "0" * 64),
                                                 self._reply("J3"), self._reply("J3"), self._reply("JR")))
        r = cli("judge-record", "post.md", "--all", "--from", str(self._scratch(text)), cwd=self.cwd)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(Path(paths["J1"]).is_file())
        for g in ("J2", "J3", "J4"):
            self.assertFalse(Path(paths[g]).exists(), g)
        self.assertIn("J2 reply not recorded: stale", r.stderr)
        self.assertIn("J3 reply not recorded: 2 replies", r.stderr)
        self.assertIn("J4 reply not recorded: no reply", r.stderr)
        self.assertIn("JR", r.stderr)  # JR is recorded on its own, never with --all
        self.assertFalse(Path(paths["JR"]).exists())

    def test_judge_record_all_refuses_a_hand_built_input(self):
        """#43: J1 judged a line the model built from an older input; the other three are genuine."""
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        paths = json.loads(cli("paths", "post.md", cwd=self.cwd).stdout)
        objs = [self._reply(g) for g in ("J1", "J2", "J3", "J4")]
        objs[0]["input_digest"] = objs[1]["input_digest"]  # pasted from another line
        r = cli("judge-record", "post.md", "--all", "--from", str(self._scratch("\n".join(map(json.dumps, objs)))),
                cwd=self.cwd)
        self.assertEqual(r.returncode, 1)
        self.assertIn("J1 reply not recorded: the J1 reply's input_digest doesn't match", r.stderr)
        self.assertIn("rerun `judge-input`", r.stderr)
        self.assertFalse(Path(paths["J1"]).exists())
        self.assertTrue(all(Path(paths[g]).is_file() for g in ("J2", "J3", "J4")))

    def test_judge_record_all_unparseable_file(self):
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        reply = self._scratch('{"group": "J1"} and some prose')
        r = cli("judge-record", "post.md", "--all", "--from", str(reply), cwd=self.cwd)
        self.assertEqual(r.returncode, 1)
        self.assertIn("judge replies not recorded", r.stderr)
        self.assertFalse(reply.exists())

    def test_judge_record_needs_exactly_one_of_group_and_all(self):
        for args in ((), ("--group", "J1", "--all")):
            with self.subTest(args=args):
                r = cli("judge-record", "post.md", *args, cwd=self.cwd, input="{}")
                self.assertEqual(r.returncode, 2, r.stderr)

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


class LocaleCli(unittest.TestCase):  # #121: the locale option is read, and shown with where it came from
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.cwd / ".git").mkdir()
        self.env = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")}

    def run_cli(self, *args, env=None):
        return cli(*args, cwd=self.cwd, env={**self.env, **(env or {})})

    def test_summary_names_the_locale_and_its_source(self):
        r = self.run_cli("profile", "--plugin-profile", "default", "--plugin-locale", "en-US")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("locale en-US (plugin option) · flags: none", r.stdout)
        r = self.run_cli("profile", "--plugin-profile", "default", "--plugin-locale", "${user_config.locale}")
        self.assertIn("locale en-AU (default) · flags", r.stdout)

    def test_env_beats_the_flag(self):  # hooks get CLAUDE_PLUGIN_OPTION_LOCALE; skills pass the flag
        r = self.run_cli("profile", "--profile", "default", "--plugin-locale", "en-US",
                         env={"CLAUDE_PLUGIN_OPTION_LOCALE": "en-GB"})
        self.assertIn("locale en-GB (plugin option)", r.stdout)

    def test_project_config_names_the_file(self):
        (self.cwd / ".plainspoken").mkdir()
        (self.cwd / ".plainspoken" / "config.toml").write_text('[locale]\nvariant = "en-GB"\n', encoding="utf-8")
        r = self.run_cli("profile", "--profile", "default", "--plugin-locale", "en-US")
        self.assertIn("locale en-GB (project config, .plainspoken/config.toml)", r.stdout)

    def test_bad_config_value_exits_2_naming_file_and_key(self):
        (self.cwd / ".plainspoken").mkdir()
        (self.cwd / ".plainspoken" / "config.toml").write_text('[locale]\nvariant = "en-NZ"\n', encoding="utf-8")
        r = self.run_cli("profile", "--profile", "default")
        self.assertEqual(r.returncode, 2)
        self.assertIn("[locale] variant", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_voice_prints_the_locale_line(self):
        r = self.run_cli("profile", "--voice", "--plugin-profile", "default", "--plugin-locale", "en-GB")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("locale: en-GB (plugin option)", r.stdout.splitlines())

    def test_json_stamps_unchanged(self):
        r = self.run_cli("profile", "--json", "--plugin-profile", "default", "--plugin-locale", "en-US")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(set(json.loads(r.stdout)), {"name", "path", "profile_sha256", "ruleset_version", "root"})

    def test_register_checklist_uses_the_resolved_locale(self):
        r = self.run_cli("register-checklist", "--kind", "email", "--profile", "default", "--plugin-locale", "en-US")
        self.assertEqual(r.returncode, 0, r.stderr)
        r11 = next(line for line in r.stdout.splitlines() if line.startswith("R11 "))
        self.assertIn("Is it consistently en-US?", r11)
