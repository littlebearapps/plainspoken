import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

from plainspoken import setup
from tests.test_cli import cli


class Edits(unittest.TestCase):
    def test_set_key_new_section_existing_section_and_replace(self):
        text = '# mine\n[engine]\nprofile = "essay"\n\n[lint_watch]\npaths = ["docs/**/*.md"]\n'
        out = setup.set_key(text, "nudge", "mode", '"on"')
        out = setup.set_key(out, "lint_watch", "mode", '"off"')
        data = tomllib.loads(out)
        self.assertEqual(data["nudge"]["mode"], "on")
        self.assertEqual(data["lint_watch"], {"paths": ["docs/**/*.md"], "mode": "off"})
        self.assertTrue(out.startswith('# mine\n[engine]\nprofile = "essay"\n'))
        again = setup.set_key(out, "nudge", "mode", '"off"')
        self.assertEqual(tomllib.loads(again)["nudge"]["mode"], "off")
        self.assertEqual(again.count("[nudge]"), 1)

    def test_unset_marked_keeps_hand_written_settings(self):
        text = '[engine]\nprofile = "essay"\n\n[lint_watch]\npaths = ["x/*.md"]\n'
        out = setup.set_key(setup.set_key(text, "nudge", "mode", '"on"'), "lint_watch", "mode", '"off"')
        self.assertEqual(setup.unset_marked(out), text)

    def test_unset_marked_on_a_file_setup_wrote_alone_is_empty(self):
        self.assertEqual(setup.unset_marked(setup.set_key("", "rule", "enabled", "true")), "")


class Command(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.project / ".git").mkdir()
        # XDG_CONFIG_HOME beats HOME (CI runners set it), so pin both to the temp home
        self.env = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")}

    def run_setup(self, *args):
        return cli("setup", *args, cwd=self.project, env=self.env)

    def test_project_scope_writes_project_config_and_status_shows_it(self):
        r = self.run_setup("--host", "claude-code", "--nudge", "on", "--rule", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = tomllib.loads((self.project / ".plainspoken" / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual((data["nudge"]["mode"], data["rule"]["enabled"]), ("on", True))
        self.assertIn("writing nudge: on", r.stdout)
        self.assertIn("drafting rule: on", r.stdout)
        self.assertIn("/reload-plugins", r.stdout)

    def test_codex_says_hooks_need_trust_again_after_each_update(self):
        r = self.run_setup("--host", "codex", "--nudge", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/hooks", r.stdout)
        self.assertIn("after every plainspoken update", r.stdout)

    def test_idempotent_and_dry_run_writes_nothing(self):
        self.run_setup("--host", "codex", "--nudge", "on")
        r = self.run_setup("--host", "codex", "--nudge", "on")
        self.assertIn("nothing to change", r.stdout)
        before = (self.project / ".plainspoken" / "config.toml").read_text(encoding="utf-8")
        r = self.run_setup("--host", "codex", "--nudge", "off", "--dry-run")
        self.assertIn('mode = "off"', r.stdout)
        self.assertEqual((self.project / ".plainspoken" / "config.toml").read_text(encoding="utf-8"), before)

    def test_user_scope_and_remove(self):
        r = self.run_setup("--host", "hermes", "--scope", "user", "--nudge", "on", "--lint-watch", "on")
        self.assertEqual(r.returncode, 0, r.stderr)
        user = self.home / ".config" / "plainspoken" / "config.toml"
        self.assertEqual(tomllib.loads(user.read_text(encoding="utf-8"))["nudge"]["mode"], "on")
        self.assertIn("new Hermes session", r.stdout)
        r = self.run_setup("--host", "hermes", "--scope", "user", "--remove")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(user.exists())

    def test_rule_is_refused_off_claude_code(self):
        r = self.run_setup("--host", "codex", "--rule", "on")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Claude Code", r.stderr)

    def test_chat_hosts_print_paste_text_and_write_nothing(self):
        for host, where in (("claude-ai", "personal preferences"), ("chatgpt", "Custom instructions")):
            r = self.run_setup("--host", host)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(where, r.stdout)
            self.assertIn("never add a fact", r.stdout)
        self.assertFalse((self.project / ".plainspoken").exists())

    def test_broken_config_is_left_alone(self):
        (self.project / ".plainspoken").mkdir()
        (self.project / ".plainspoken" / "config.toml").write_text("[nudge\n", encoding="utf-8")
        r = self.run_setup("--host", "claude-code", "--nudge", "on")
        self.assertEqual(r.returncode, 2)
        self.assertEqual((self.project / ".plainspoken" / "config.toml").read_text(encoding="utf-8"), "[nudge\n")


if __name__ == "__main__":
    unittest.main()
