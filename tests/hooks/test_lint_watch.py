import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "lint_watch.py"
sys.path.insert(0, str(REPO / "hooks"))
import _common  # noqa: E402


def run_hook(payload, project: Path, **env_over):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    env.update({"CLAUDE_PROJECT_DIR": str(project), "CLAUDE_PLUGIN_DATA": str(project / ".data"),
                "CLAUDE_PLUGIN_OPTION_PROFILE": "default"})
    env.update(env_over)
    env = {k: v for k, v in env.items() if v is not None}
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env,
                          cwd=project)


class Glob(unittest.TestCase):
    def test_globstar(self):
        self.assertTrue(_common.glob_match("post.md", "**/*.md"))
        self.assertTrue(_common.glob_match("a/b/post.md", "**/*.md"))
        self.assertFalse(_common.glob_match("a/post.txt", "**/*.md"))
        self.assertTrue(_common.glob_match("docs/x.md", "docs/*.md"))
        self.assertFalse(_common.glob_match("docs/a/x.md", "docs/*.md"))

    def test_targets_encodings(self):
        want = ["**/*.md", "notes/*.txt"]
        self.assertEqual(_common.parse_targets(json.dumps(want)), want)
        self.assertEqual(_common.parse_targets("**/*.md\nnotes/*.txt"), want)
        self.assertEqual(_common.parse_targets("**/*.md,notes/*.txt"), want)
        self.assertEqual(_common.parse_targets(None), ["**/*.md"])


class Hook(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.art = self.project / "post.md"
        self.art.write_text("We delve into a robust tapestry.\n", encoding="utf-8")

    def event(self, path):
        return {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s1",
                "cwd": str(self.project), "tool_input": {"file_path": str(path)}}

    def test_target_file_gets_findings_and_exit_0(self):
        r = run_hook(self.event(self.art), self.project)
        self.assertEqual(r.returncode, 0, r.stderr)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("BLOCK", ctx)
        self.assertLess(len(ctx), 4000)

    def test_same_findings_twice_are_silent(self):
        run_hook(self.event(self.art), self.project)
        r = run_hook(self.event(self.art), self.project)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_non_target_is_silent(self):
        other = self.project / "notes.txt"
        other.write_text("delve\n", encoding="utf-8")
        r = run_hook(self.event(other), self.project)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_malformed_stdin_fails_open(self):
        r = run_hook("{not json", self.project)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_profile_error_is_one_context_line(self):
        r = run_hook(self.event(self.art), self.project, CLAUDE_PLUGIN_OPTION_PROFILE="no-such-profile")
        self.assertEqual(r.returncode, 0)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(ctx.startswith("plainspoken lint skipped:"), ctx)
        self.assertEqual(len(ctx.splitlines()), 1)

    def test_no_plugin_option_profile_still_lints(self):  # options may not reach hooks (facts §1)
        r = run_hook(self.event(self.art), self.project, CLAUDE_PLUGIN_OPTION_PROFILE=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("BLOCK", ctx)

    def test_targets_option_respected(self):
        r = run_hook(self.event(self.art), self.project, CLAUDE_PLUGIN_OPTION_TARGETS='["docs/**/*.md"]')
        self.assertEqual(r.stdout.strip(), "")

    def config(self, toml):
        (self.project / ".plainspoken").mkdir(exist_ok=True)
        (self.project / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def recorded(self):
        state = self.project / ".data" / "lint-watch-state.json"
        ledger_dir = self.project / ".plainspoken" / "ledger"
        return state.exists(), ledger_dir.exists() and any(ledger_dir.iterdir())

    def test_lint_watch_off(self):
        self.config('[lint_watch]\nmode = "off"\n')
        r = run_hook(self.event(self.art), self.project)
        self.assertEqual((r.returncode, r.stdout.strip(), r.stderr.strip()), (0, "", ""))
        self.assertEqual(self.recorded(), (False, False))

    def test_lint_watch_respects_paths(self):  # the project's paths beat the targets option
        self.config('[lint_watch]\npaths = ["docs/**/*.md"]\n')
        r = run_hook(self.event(self.art), self.project, CLAUDE_PLUGIN_OPTION_TARGETS='["**/*.md"]')
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        self.assertEqual(self.recorded(), (False, False))
        doc = self.project / "docs" / "post.md"
        doc.parent.mkdir()
        doc.write_text(self.art.read_text(encoding="utf-8"), encoding="utf-8")
        r = run_hook(self.event(doc), self.project)
        self.assertIn("BLOCK", json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])
        self.config('[lint_watch]\npaths = []\n')
        r = run_hook(self.event(doc), self.project)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_bad_lint_watch_config_skips_target_files_only(self):  # fail open, one line, never on other files
        self.config('[lint_watch]\nmode = "quiet"\n')
        r = run_hook(self.event(self.art), self.project)
        self.assertEqual(r.returncode, 0)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(ctx.startswith("plainspoken lint skipped: ConfigError"), ctx)
        other = self.project / "notes.txt"
        other.write_text("delve\n", encoding="utf-8")
        r = run_hook(self.event(other), self.project)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_per_file_profile(self):  # the hook lints with the file's [engine] profiles entry
        prof = self.project / ".plainspoken" / "profiles"
        prof.mkdir(parents=True)
        (prof / "quiet.toml").write_text('[profile]\nname = "quiet"\n[rules]\ndisabled = ["2"]\n',
                                         encoding="utf-8")
        self.config('[engine]\nprofile = "default"\nprofiles = [{ glob = "docs/**", profile = "quiet" }]\n')
        doc = self.project / "docs" / "post.md"
        doc.parent.mkdir()
        doc.write_text("We delve into it.\n", encoding="utf-8")
        r = run_hook(self.event(doc), self.project)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("· quiet ·", ctx)
        self.assertNotIn("delve", ctx)
        r = run_hook(self.event(self.art), self.project)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("· default ·", ctx)
        self.assertIn("delve", ctx)

    def test_hooks_json_registers_all_four_events(self):
        cfg = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        post = cfg["PostToolUse"][0]
        self.assertEqual(post["matcher"], "Write|Edit")
        h = post["hooks"][0]
        self.assertEqual((h["command"], h["args"][0]), ("python3", "${CLAUDE_PLUGIN_ROOT}/hooks/lint_watch.py"))
        self.assertNotIn("onFailure", h)
        self.assertEqual(set(cfg), {"SessionStart", "SubagentStart", "PostToolUse", "PreToolUse", "Stop",
                                    "SubagentStop", "UserPromptSubmit"})  # Stop/SubagentStop: kaizen (Phase 5);
        # UserPromptSubmit: the optional writing nudge (v0.7)
        self.assertIn("PreToolUse", cfg)
        pre = cfg["PreToolUse"][0]
        self.assertEqual(pre["matcher"], "Bash")
        g = pre["hooks"][0]
        self.assertNotIn("onFailure", g)  # opt-in gate: a failed start must not block every Bash call; the script fails closed itself
        self.assertNotIn("if", g)  # the harness filter misses `env git push`; the script filters (facts doc section 6)
        self.assertTrue(g["args"][0].endswith("/hooks/publish_gate.py"))

    def test_clean_result_is_silent(self):  # deferred minor: noise on every .md
        clean = self.project / "clean.md"
        clean.write_text("I fixed the login bug on Friday.\n", encoding="utf-8")
        r = run_hook(self.event(clean), self.project)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_a_then_b_then_a_reports_a_again(self):  # deferred minor: A→B→A dedupe
        a = "We delve into a robust tapestry.\n"
        b = "It's a game-changer. Truly seamless.\n"
        outs = []
        for text in (a, b, a):
            self.art.write_text(text, encoding="utf-8")
            outs.append(run_hook(self.event(self.art), self.project).stdout.strip())
        self.assertTrue(all(outs), outs)

    def test_back_to_clean_says_so_once(self):
        run_hook(self.event(self.art), self.project)
        self.art.write_text("I fixed the login bug on Friday.\n", encoding="utf-8")
        first = json.loads(run_hook(self.event(self.art), self.project).stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("no BLOCK or WARN findings now", first)
        self.assertEqual(run_hook(self.event(self.art), self.project).stdout.strip(), "")

    def test_old_list_shaped_state_is_ignored(self):
        (self.project / ".data").mkdir()
        (self.project / ".data" / "lint-watch-state.json").write_text('{"last": ["x"]}', encoding="utf-8")
        self.assertTrue(run_hook(self.event(self.art), self.project).stdout.strip())


class OneStateRead(unittest.TestCase):  # the hook reads its state file once per run
    def setUp(self):
        self.project = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.art = self.project / "post.md"
        self.art.write_text("We delve into a robust tapestry.\n", encoding="utf-8")

    def run_in_process(self) -> tuple[str, int]:
        import lint_watch
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env.update({"CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_PLUGIN_DATA": str(self.project / ".data"),
                    "CLAUDE_PLUGIN_OPTION_PROFILE": "default"})
        event = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s1",
                 "cwd": str(self.project), "tool_input": {"file_path": str(self.art)}}
        reads, real = [], Path.read_text

        def counting(path, *args, **kwargs):
            if path.name == "lint-watch-state.json":
                reads.append(path)
            return real(path, *args, **kwargs)

        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("sys.stdin", io.StringIO(json.dumps(event))), \
                mock.patch.object(Path, "read_text", counting), contextlib.redirect_stdout(out):
            self.assertEqual(lint_watch.main(), 0)
        return out.getvalue(), len(reads)

    def test_first_and_repeat_runs_read_the_state_once(self):
        first, reads = self.run_in_process()  # no state file yet: one attempt, which finds nothing
        self.assertIn("BLOCK", first)
        self.assertEqual(reads, 1)
        second, reads = self.run_in_process()  # the same result: one read, and silence
        self.assertEqual((second.strip(), reads), ("", 1))


class StateSafety(unittest.TestCase):  # Phase 4 review: state writes never follow a planted symlink
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.outside = Path(tempfile.mkdtemp())
        for d in (self.project, self.outside):
            self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.art = self.project / "post.md"
        self.art.write_text("We delve into a robust tapestry.\n", encoding="utf-8")
        self.victim = self.outside / "victim.txt"
        self.victim.write_text("precious\n", encoding="utf-8")
        (self.project / ".plainspoken").mkdir()

    def run_default_data(self):
        event = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s1",
                 "cwd": str(self.project), "tool_input": {"file_path": str(self.art)}}
        r = run_hook(event, self.project, CLAUDE_PLUGIN_DATA=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_planted_tmp_symlink(self):
        (self.project / ".plainspoken" / "lint-watch-state.tmp").symlink_to(self.victim)
        self.assertIn("BLOCK", self.run_default_data().stdout)
        self.assertEqual(self.victim.read_text(encoding="utf-8"), "precious\n")

    def test_planted_state_symlink(self):
        (self.project / ".plainspoken" / "lint-watch-state.json").symlink_to(self.victim)
        for _ in range(2):
            self.assertIn("BLOCK", self.run_default_data().stdout)
        self.assertEqual(self.victim.read_text(encoding="utf-8"), "precious\n")

    def test_writes_state_without_temp_leftovers(self):
        self.run_default_data()
        self.assertTrue((self.project / ".plainspoken" / "lint-watch-state.json").is_file())
        self.assertEqual(list((self.project / ".plainspoken").glob("*.tmp")), [])


BLOCK_TOMLLIB = """
import runpy, sys
class Blocker:  # what a python3 older than 3.11 looks like: no tomllib
    def find_spec(self, name, path=None, target=None):
        if name == "tomllib":
            raise ImportError("No module named 'tomllib'")
        return None
sys.meta_path.insert(0, Blocker())
sys.argv = [sys.argv[1]]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


class ImportFailure(unittest.TestCase):  # the library failing to import must not crash the hook
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)

    def run_blocked(self, path: Path):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env.update({"CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_PLUGIN_DATA": str(self.project / ".data")})
        event = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s1",
                 "cwd": str(self.project), "tool_input": {"file_path": str(path)}}
        return subprocess.run([sys.executable, "-c", BLOCK_TOMLLIB, str(HOOK)], input=json.dumps(event),
                              capture_output=True, text=True, env=env, cwd=self.project)

    def assert_fails_open(self, r):
        """The library import fails before the hook knows the file's targets, so every file gets the one line."""
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(ctx.startswith("plainspoken lint skipped: ImportError:"), ctx)
        self.assertEqual(len(ctx.splitlines()), 1)

    def test_target_file(self):
        art = self.project / "post.md"
        art.write_text("We delve into a robust tapestry.\n", encoding="utf-8")
        self.assert_fails_open(self.run_blocked(art))

    def test_non_target_file(self):
        other = self.project / "notes.txt"
        other.write_text("delve\n", encoding="utf-8")
        self.assert_fails_open(self.run_blocked(other))


class Clip(unittest.TestCase):  # deferred minor: no … marker on the 4,000-character cut
    def test_long_text_gets_a_marker(self):
        out = _common.clip("x" * 5000)
        self.assertEqual((len(out), out[-1]), (4000, "…"))

    def test_short_text_unchanged(self):
        self.assertEqual(_common.clip("short"), "short")


class CodexApplyPatch(unittest.TestCase):
    """Codex reports file edits as `apply_patch` with the patch text in tool_input.command (no file_path)."""

    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        (self.project / "a.md").write_text("We delve into a robust tapestry.\n", encoding="utf-8")
        (self.project / "b.md").write_text("Moreover, it is a pivotal and seamless paradigm.\n", encoding="utf-8")
        (self.project / "c.py").write_text("x = 1\n", encoding="utf-8")

    def event(self, patch: str):
        return {"hook_event_name": "PostToolUse", "tool_name": "apply_patch", "session_id": "c1",
                "cwd": str(self.project), "tool_input": {"command": patch}}

    def test_every_patched_target_is_linted_in_one_reply(self):
        patch = ("*** Begin Patch\n*** Update File: a.md\n@@\n-x\n+y\n*** Add File: b.md\n+text\n"
                 "*** Update File: c.py\n@@\n-x\n+y\n*** End Patch\n")
        r = run_hook(self.event(patch), self.project, CLAUDE_PROJECT_DIR=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1, r.stdout)
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("a.md", ctx)
        self.assertIn("b.md", ctx)
        self.assertNotIn("c.py", ctx)

    def test_edited_events_paths(self):
        ev = self.event("*** Begin Patch\n*** Update File: docs/x.md\n*** Move to: docs/y.md\n"
                        "*** Delete File: z.md\n*** End Patch")
        got = [e["tool_input"]["file_path"] for e in _common.edited_events(ev)]
        self.assertEqual(got, [str(self.project / "docs/x.md"), str(self.project / "docs/y.md")])

    def test_other_tools_and_shapes_are_ignored(self):
        self.assertEqual(_common.edited_events({"tool_name": "Bash", "tool_input": {"command": "ls"}}), [])
        self.assertEqual(_common.edited_events({"tool_name": "apply_patch", "tool_input": {}}), [])
