import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lib"))
sys.path.insert(0, str(REPO / "hooks"))
import _gate  # noqa: E402
import publish_gate  # noqa: E402


class ExceptionFallback(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        (self.project / ".plainspoken").mkdir()

    def run_main(self, config_text: str, env_strictness: str | None = None, **patches) -> dict:
        (self.project / ".plainspoken" / "config.toml").write_text(config_text, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env["CLAUDE_PROJECT_DIR"] = str(self.project)
        if env_strictness:
            env["CLAUDE_PLUGIN_OPTION_STRICTNESS"] = env_strictness
        payload = json.dumps({"tool_input": {"command": "git push"}, "cwd": str(self.project)})
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, env, clear=True))
            stack.enter_context(mock.patch("sys.stdin", io.StringIO(payload)))
            stack.enter_context(mock.patch.object(_gate, "check", side_effect=RuntimeError("boom")))
            for target, effect in patches.items():
                stack.enter_context(mock.patch(target.replace("__", "."), side_effect=effect))
            stack.enter_context(contextlib.redirect_stdout(out))
            publish_gate.main()
        return json.loads(out.getvalue()) if out.getvalue().strip() else {}

    def test_crash_after_warn_is_a_warning(self):
        out = self.run_main('[gate]\npaths = ["**/*.md"]\nstrictness = "warn"\n')
        self.assertIn("gate error", out["systemMessage"])

    def test_crash_after_block_is_a_deny(self):
        out = self.run_main('[gate]\npaths = ["**/*.md"]\nstrictness = "block"\n')
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_crash_before_the_settings_are_known_is_never_a_deny(self):
        out = self.run_main('[gate]\nstrictness = "block"\n',
                            plainspoken__config__gate_strictness_safe=RuntimeError("early"))
        self.assertNotIn("hookSpecificOutput", out)
        self.assertIn("gate error", out["systemMessage"])

    def test_crash_before_the_settings_are_known_denies_when_the_plugin_option_is_block(self):
        out = self.run_main('[gate]\nstrictness = "warn"\n', env_strictness="block",
                            plainspoken__config__gate_strictness_safe=RuntimeError("early"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("gate error", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_sys_path_is_extended_once_at_import(self):  # not on every main() call
        before = list(sys.path)
        for _ in range(3):
            self.run_main('[gate]\npaths = ["**/*.md"]\nstrictness = "warn"\n')
        self.assertEqual(sys.path, before)


class StrictnessSafe(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        (self.project / ".plainspoken").mkdir()
        self.cfg = self.project / ".plainspoken" / "config.toml"

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads any file")
    def test_unreadable_config_never_raises(self):
        from plainspoken import config
        self.cfg.write_text('[gate]\nstrictness = "block"\n', encoding="utf-8")
        self.cfg.chmod(0)
        self.addCleanup(self.cfg.chmod, 0o644)
        strictness, _source, problem = config.gate_strictness_safe(self.project, {})
        self.assertEqual(strictness, "warn")
        self.assertIsNotNone(problem)
        self.assertEqual(config.gate_strictness_safe(self.project, {"CLAUDE_PLUGIN_OPTION_STRICTNESS": "block"})[0],
                         "block")
