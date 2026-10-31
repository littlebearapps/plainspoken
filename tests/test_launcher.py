import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run(*args, cwd):
    env = {k: v for k, v in os.environ.items()
           if k != "PYTHONPATH" and not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_"))}
    return subprocess.run([sys.executable, str(REPO / "lib" / "run.py"), *args], cwd=cwd,
                          capture_output=True, text=True, env=env)


class Launcher(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        (self.cwd / "post.md").write_text("I fixed it on Friday.\n", encoding="utf-8")

    def test_runs_without_pythonpath(self):
        r = run("check", "post.md", "--profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_plugin_profile_is_the_fallback(self):
        r = run("check", "post.md", "--plugin-profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_project_config_beats_plugin_profile(self):
        (self.cwd / ".plainspoken" / "profiles").mkdir(parents=True)
        (self.cwd / ".plainspoken" / "profiles" / "mine.toml").write_text('[profile]\nname = "mine"\n', encoding="utf-8")
        (self.cwd / ".plainspoken" / "config.toml").write_text('[engine]\nprofile = "mine"\n', encoding="utf-8")
        r = run("profile", "--plugin-profile", "default", cwd=self.cwd)
        self.assertIn("mine", r.stdout.splitlines()[0])

    def test_profile_summary_shape(self):
        r = run("profile", "--plugin-profile", "default", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        first = r.stdout.splitlines()[0]
        self.assertTrue(first.startswith("plainspoken profile: default"), first)
        self.assertNotIn("(plugin default)", first)
        self.assertIn("ruleset 4.4.0", r.stdout)
        self.assertLess(len(r.stdout), 800)

    def test_unsubstituted_placeholder_means_plugin_default(self):
        r = run("profile", "--plugin-profile", "${user_config.profile}", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.splitlines()[0].startswith("plainspoken profile: default (plugin default) ("),
                        r.stdout)

    def test_placeholder_with_project_config_uses_project_config(self):
        (self.cwd / ".plainspoken" / "profiles").mkdir(parents=True)
        (self.cwd / ".plainspoken" / "profiles" / "mine.toml").write_text('[profile]\nname = "mine"\n', encoding="utf-8")
        (self.cwd / ".plainspoken" / "config.toml").write_text('[engine]\nprofile = "mine"\n', encoding="utf-8")
        first = run("profile", "--plugin-profile", "${user_config.profile}", cwd=self.cwd).stdout.splitlines()[0]
        self.assertIn("mine", first)
        self.assertNotIn("plugin default", first)

    def test_real_plugin_profile_used_as_given(self):
        (self.cwd / ".plainspoken" / "profiles").mkdir(parents=True)
        (self.cwd / ".plainspoken" / "profiles" / "mine.toml").write_text('[profile]\nname = "mine"\n', encoding="utf-8")
        first = run("profile", "--plugin-profile", "mine", cwd=self.cwd).stdout.splitlines()[0]
        self.assertIn("plainspoken profile: mine (", first)

    def test_placeholder_is_not_rewritten_for_profile_flag(self):
        r = run("profile", "--profile", "${user_config.profile}", cwd=self.cwd)
        self.assertEqual(r.returncode, 2)

    def test_no_profile_anywhere_exits_2(self):
        r = run("profile", cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no profile", r.stderr)
