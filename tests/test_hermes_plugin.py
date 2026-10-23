import importlib.util
import json
import types
import unittest.mock
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_shim():
    spec = importlib.util.spec_from_file_location("_hermes_shim", REPO / ".hermes-plugin" / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCtx:
    def __init__(self, cwd="", post_ok=True):
        self.skills, self.hooks, self.posted = [], {}, []
        self.cwd, self.post_ok = cwd, post_ok

    def register_skill(self, name, path, description=""):
        self.skills.append((name, path, description))

    def register_hook(self, event, fn):
        self.hooks[event] = fn

    def session_cwd(self):
        return self.cwd

    def post_message(self, text):
        self.posted.append(text)
        return types.SimpleNamespace(ok=self.post_ok, error=None if self.post_ok else "no_conversation")


class HermesShim(unittest.TestCase):
    def setUp(self):
        self.ctx = FakeCtx()
        load_shim().register(self.ctx)

    def test_registers_every_skill_as_a_path_with_its_description(self):
        names = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md"))
        self.assertEqual([s[0] for s in self.ctx.skills], names)
        for name, path, description in self.ctx.skills:
            self.assertIsInstance(path, Path, name)
            self.assertTrue(path.is_file(), name)
            self.assertGreater(len(description), 20, name)

    def test_bootstrap_on_the_first_turn_only(self):
        hook = self.ctx.hooks["pre_llm_call"]
        context = hook(is_first_turn=True, session_id="s", user_message="hi")["context"]
        self.assertIn(str(REPO / "hosts" / "hermes.md"), context)
        self.assertIsNone(hook(is_first_turn=False))

    def test_manifest_declares_the_hook_it_registers(self):
        text = (REPO / ".hermes-plugin" / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("name: plainspoken", text)
        for event in self.ctx.hooks:
            self.assertIn(f"- {event}", text)

    def test_registers_the_gate_and_the_kaizen_nudge(self):
        self.assertEqual(set(self.ctx.hooks), {"pre_llm_call", "transform_tool_result", "pre_tool_call",
                                               "on_session_end"})


class HermesHooks(unittest.TestCase):
    def setUp(self):
        import os
        import shutil
        import tempfile
        self.project = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.project / ".plainspoken").mkdir()
        self.old_cwd = os.getcwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, self.old_cwd)
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith(("CLAUDE_", "PLAINSPOKEN_")) and k != "XDG_CONFIG_HOME"}
        env = unittest.mock.patch.dict(os.environ, {**clean, "HOME": str(self.home)}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.ctx = FakeCtx()
        load_shim().register(self.ctx)

    def test_nudge_only_when_on(self):
        hook = self.ctx.hooks["pre_llm_call"]
        self.assertIsNone(hook(is_first_turn=False, user_message="Draft an email to the parents about Friday"))
        (self.project / ".plainspoken" / "config.toml").write_text('[nudge]\nmode = "on"\n', encoding="utf-8")
        got = hook(is_first_turn=False, user_message="Draft an email to the parents about Friday")["context"]
        self.assertIn("plainspoken:write", got)
        self.assertNotIn("/plainspoken:", got)
        self.assertIsNone(hook(is_first_turn=False, user_message="what's the weather like"))

    def test_first_turn_keeps_the_pointer_and_adds_the_nudge(self):
        (self.project / ".plainspoken" / "config.toml").write_text('[nudge]\nmode = "on"\n', encoding="utf-8")
        got = self.ctx.hooks["pre_llm_call"](is_first_turn=True, user_message="humanise this paragraph")["context"]
        self.assertIn("hosts/hermes.md", got)
        self.assertIn("plainspoken:humanize", got)

    def test_lint_after_write_file_and_v4a_patch(self):
        hook = self.ctx.hooks["transform_tool_result"]
        art = self.project / "post.md"
        art.write_text("We delve into a robust tapestry.\n", encoding="utf-8")
        got = hook(tool_name="write_file", args={"path": str(art), "content": "x"}, result="Wrote post.md",
                   session_id="h1")
        self.assertTrue(got.startswith("Wrote post.md\n\n"), got)
        self.assertIn("BLOCK", got)
        other = self.project / "other.md"
        other.write_text("Moreover, it is a pivotal and seamless paradigm.\n", encoding="utf-8")
        got = hook(tool_name="patch", args={"mode": "patch", "patch": "*** Begin Patch\n*** Update File: other.md\n"
                                                                      "*** End Patch"}, result="ok", session_id="h1")
        self.assertIn("other.md", got)

    def test_other_tools_and_clean_files_leave_the_result_alone(self):
        hook = self.ctx.hooks["transform_tool_result"]
        self.assertIsNone(hook(tool_name="terminal", args={"command": "ls"}, result="a b"))
        clean = self.project / "clean.md"
        clean.write_text("I fixed the login bug on Friday.\n", encoding="utf-8")
        self.assertIsNone(hook(tool_name="write_file", args={"path": str(clean)}, result="ok", session_id="h2"))


class HermesHostCwd(unittest.TestCase):
    """Hermes runs plugins in a host process whose working folder isn't the project: lint must still find it."""

    def test_lint_finds_the_project_from_the_file(self):
        import os
        import shutil
        import tempfile
        project, elsewhere = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, project, ignore_errors=True)
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        (project / ".git").mkdir()
        (project / "docs").mkdir()
        art = project / "docs" / "post.md"
        art.write_text("We delve into a robust tapestry.\n", encoding="utf-8")
        old = os.getcwd()
        os.chdir(elsewhere)
        self.addCleanup(os.chdir, old)
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith(("CLAUDE_", "PLAINSPOKEN_")) and k != "XDG_CONFIG_HOME"}
        env = unittest.mock.patch.dict(os.environ, {**clean, "HOME": str(elsewhere)}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        ctx = FakeCtx()
        load_shim().register(ctx)
        got = ctx.hooks["transform_tool_result"](tool_name="write_file", args={"path": str(art)}, result="ok",
                                                 session_id=f"host-{project.name}")
        self.assertIn("BLOCK", got or "")


def clean_env(test: unittest.TestCase, **extra: str) -> None:
    """No Claude Code, plainspoken or Hermes variables (a CLAUDE_PROJECT_DIR would point the gate elsewhere)."""
    import os
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith(("CLAUDE_", "PLAINSPOKEN_", "PLUGIN_", "HERMES_"))
             and k not in ("XDG_CONFIG_HOME", "TERMINAL_CWD")}
    env = unittest.mock.patch.dict(os.environ, {**clean, **extra}, clear=True)
    env.start()
    test.addCleanup(env.stop)


def temp_dir(test: unittest.TestCase) -> Path:
    import shutil
    import tempfile
    path = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, path, ignore_errors=True)
    return path


class HermesGate(unittest.TestCase):
    """pre_tool_call on `terminal`: the publish gate and the write guard, as Hermes' block and a posted warn (#90)."""

    def setUp(self):
        import sys
        sys.path.insert(0, str(REPO / "lib"))
        from tests.hooks.test_publish_gate import git
        self.tmp = temp_dir(self)
        clean_env(self, HOME=str(self.tmp))
        remote, self.project = self.tmp / "remote.git", self.tmp / "proj"
        git("init", "--bare", "-q", "-b", "main", str(remote), cwd=self.tmp)
        git("clone", "-q", str(remote), str(self.project), cwd=self.tmp)
        git("checkout", "-q", "-B", "main", cwd=self.project)
        (self.project / "README").write_text("x\n", encoding="utf-8")
        git("add", ".", cwd=self.project); git("commit", "-qm", "init", cwd=self.project)
        git("push", "-q", "-u", "origin", "HEAD", cwd=self.project)
        (self.project / "docs").mkdir()
        self.art = self.project / "docs" / "post.md"
        self.art.write_text("I fixed it on Friday.\n", encoding="utf-8")
        git("add", ".", cwd=self.project); git("commit", "-qm", "post", cwd=self.project)
        self.ctx = FakeCtx(cwd=str(self.project))
        load_shim().register(self.ctx)
        self.hook = self.ctx.hooks["pre_tool_call"]

    def config(self, strictness: str) -> None:
        (self.project / ".plainspoken").mkdir(exist_ok=True)
        (self.project / ".plainspoken" / "config.toml").write_text(
            f'[gate]\nstrictness = "{strictness}"\npaths = ["docs/**/*.md"]\n', encoding="utf-8")

    def push(self, command: str = "git push", **args):
        return self.hook(tool_name="terminal", args={"command": command, **args}, session_id="h1",
                         task_id="t", tool_call_id="c1", turn_id="u1")

    def test_block_returns_hermes_block_with_the_reason(self):
        self.config("block")
        got = self.push()
        self.assertEqual(set(got), {"action", "message"})
        self.assertEqual(got["action"], "block")
        self.assertIn("docs/post.md: no plainspoken report (run plainspoken:check docs/post.md)", got["message"])
        self.assertNotIn("/plainspoken:", got["message"])
        self.assertEqual(self.ctx.posted, [])

    def test_warn_posts_to_the_person_and_lets_the_push_go(self):
        self.config("warn")
        self.assertIsNone(self.push())
        self.assertEqual(len(self.ctx.posted), 1)
        self.assertIn("run plainspoken:check docs/post.md", self.ctx.posted[0])

    def test_a_current_pass_allows(self):
        from plainspoken import profile, report
        from plainspoken.registry import load_config
        self.config("block")
        p = report.report_paths(self.art, self.project / ".plainspoken" / "reports", self.project)["report"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "PASS", "article_sha256": report.sha256(self.art),
                                 "profile_sha256": profile.default().sha256,
                                 "ruleset_version": load_config().version}), encoding="utf-8")
        self.assertIsNone(self.push())
        self.assertEqual(self.ctx.posted, [])

    def test_no_config_and_other_calls_are_silent(self):
        self.assertIsNone(self.push())
        self.config("block")
        self.assertIsNone(self.push("ls docs"))
        self.assertIsNone(self.hook(tool_name="write_file", args={"path": str(self.art), "content": "x"}))
        self.assertIsNone(self.hook(tool_name="terminal", args=None))
        self.assertEqual(self.ctx.posted, [])

    def test_no_gate_paths_posts_that_nothing_is_gated(self):  # #94: block with no [gate] paths used to be silent
        (self.project / ".plainspoken").mkdir(exist_ok=True)
        for strictness in ("warn", "block"):
            with self.subTest(strictness=strictness):
                self.ctx.posted.clear()
                (self.project / ".plainspoken" / "config.toml").write_text(
                    f'[gate]\nstrictness = "{strictness}"\n', encoding="utf-8")
                self.assertIsNone(self.push())
                self.assertEqual(self.ctx.posted, [f"plainspoken gate: strictness is {strictness} but no [gate] "
                                                   "paths are set in .plainspoken/config.toml, so nothing is gated"])
                self.assertIsNone(self.push("git status"))
                self.assertIsNone(self.push("ls docs"))
                self.assertEqual(len(self.ctx.posted), 1)
        self.ctx.posted.clear()
        (self.project / ".plainspoken" / "config.toml").write_text('[gate]\nstrictness = "watch"\n', encoding="utf-8")
        self.assertIsNone(self.push())
        self.assertEqual(self.ctx.posted, [])

    def test_workdir_wins_over_the_session_folder(self):
        self.config("block")
        ctx = FakeCtx(cwd=str(self.tmp))  # the session sits outside the project
        load_shim().register(ctx)
        self.assertIsNone(ctx.hooks["pre_tool_call"](tool_name="terminal", args={"command": "git push"}))
        got = ctx.hooks["pre_tool_call"](tool_name="terminal",
                                         args={"command": "git push", "workdir": str(self.project)})
        self.assertEqual(got["action"], "block")

    def test_terminal_cwd_when_the_session_has_none(self):
        import os
        self.config("block")
        ctx = FakeCtx(cwd="")
        load_shim().register(ctx)
        with unittest.mock.patch.dict(os.environ, {"TERMINAL_CWD": str(self.project)}):
            got = ctx.hooks["pre_tool_call"](tool_name="terminal", args={"command": "git push"})
        self.assertEqual(got["action"], "block")

    def test_write_guard_blocks_a_shell_write_to_a_reply_file(self):
        target = ".plainspoken/reports/post-1234abcd" + ".reply" + ".json"
        got = self.push(f"echo '{{}}' > {target}")
        self.assertEqual(got["action"], "block")
        self.assertIn("is written with write_file or patch, never through the shell", got["message"])
        self.assertNotIn("Write or Edit tool", got["message"])

    def test_a_failing_session_lookup_never_raises(self):  # Hermes blocks the tool when a callback raises
        def broken():
            raise RuntimeError("no session")
        self.config("block")
        ctx = FakeCtx()
        ctx.session_cwd = broken
        load_shim().register(ctx)
        self.assertIsNone(ctx.hooks["pre_tool_call"](tool_name="terminal", args={"command": "git status"}))


class HermesKaizenNudge(unittest.TestCase):
    """on_session_end: the kaizen nudge, posted to the person once per session, never returned as context (#90)."""

    PID = "KZ-20261014-abc123"

    def setUp(self):
        self.project, self.home = temp_dir(self), temp_dir(self)
        clean_env(self, HOME=str(self.home), HERMES_HOME=str(self.home / ".hermes"))
        (self.project / ".git").mkdir()
        (self.project / ".plainspoken" / "ledger").mkdir(parents=True)
        self.ctx = FakeCtx(cwd=str(self.project))
        load_shim().register(self.ctx)
        self.end = self.ctx.hooks["on_session_end"]

    def propose(self) -> None:
        folder = self.project / ".plainspoken" / "kaizen" / "proposals"
        folder.mkdir(parents=True)
        (folder / f"{self.PID}.json").write_text(json.dumps({"id": self.PID}), encoding="utf-8")

    def turn_end(self, session: str = "h1"):
        return self.end(session_id=session, task_id="t", turn_id="u", completed=True, failed=False,
                        interrupted=False, turn_exit_reason="text_response(stop)", model="m", platform="telegram")

    def test_a_waiting_proposal_is_posted_once_per_session(self):
        self.propose()
        self.assertIsNone(self.turn_end())
        self.assertEqual(self.ctx.posted, ["plainspoken: 1 kaizen proposal(s) await a decision — "
                                           "plainspoken:kaizen review"])
        self.assertIsNone(self.turn_end())
        self.assertEqual(len(self.ctx.posted), 1)
        state = self.home / ".hermes" / "plugin-data" / "plainspoken" / "kaizen-nudge-state.json"
        self.assertTrue(state.is_file())  # Hermes' plugin-data folder, not the project
        self.assertFalse((self.project / ".plainspoken" / "kaizen-nudge-state.json").exists())
        self.turn_end("h2")
        self.assertEqual(len(self.ctx.posted), 2)  # a new session hears it again

    def test_nothing_waiting_posts_nothing(self):
        self.assertIsNone(self.turn_end())
        self.assertEqual(self.ctx.posted, [])

    def test_no_session_id_does_nothing(self):  # the CLI's exit path may send a reduced payload
        self.propose()
        self.assertIsNone(self.end(completed=False, interrupted=True))
        self.assertEqual(self.ctx.posted, [])

    def test_a_refused_post_is_logged_not_raised(self):
        self.propose()
        ctx = FakeCtx(cwd=str(self.project), post_ok=False)
        load_shim().register(ctx)
        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(ctx.hooks["on_session_end"](session_id="h3"))
        self.assertIn("no_conversation", "\n".join(logs.output))
        self.assertIn("plainspoken:kaizen review", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
