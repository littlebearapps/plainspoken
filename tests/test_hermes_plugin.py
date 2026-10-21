import importlib.util
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
    def __init__(self):
        self.skills, self.hooks = [], {}

    def register_skill(self, name, path, description=""):
        self.skills.append((name, path, description))

    def register_hook(self, event, fn):
        self.hooks[event] = fn


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


if __name__ == "__main__":
    unittest.main()


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
        self.assertIn("plainspoken:check", got)
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
