import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken import config


class UserConfig(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.env = {"HOME": str(self.home)}

    def write_user(self, text: str) -> Path:
        path = self.home / ".config" / "plainspoken" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_project(self, text: str) -> None:
        (self.project / ".plainspoken").mkdir(exist_ok=True)
        (self.project / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def test_path_honours_xdg(self):
        self.assertEqual(config.user_config_path({"HOME": "/h"}), Path("/h/.config/plainspoken/config.toml"))
        self.assertEqual(config.user_config_path({"HOME": "/h", "XDG_CONFIG_HOME": "/x"}),
                         Path("/x/plainspoken/config.toml"))

    def test_nudge_off_by_default(self):
        self.assertEqual(config.nudge_mode(self.project, self.env), "off")

    def test_nudge_from_plugin_option(self):
        self.assertEqual(config.nudge_mode(self.project, {**self.env, "CLAUDE_PLUGIN_OPTION_NUDGE": "true"}), "on")
        self.assertEqual(config.nudge_mode(self.project, {**self.env, "CLAUDE_PLUGIN_OPTION_NUDGE": "false"}), "off")
        # an unsubstituted or odd value never turns it on
        self.assertEqual(config.nudge_mode(self.project, {**self.env, "CLAUDE_PLUGIN_OPTION_NUDGE": "${x}"}), "off")

    def test_user_beats_option_and_project_beats_user(self):
        self.write_user('[nudge]\nmode = "on"\n')
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_NUDGE": "false"}
        self.assertEqual(config.nudge_mode(self.project, env), "on")
        self.write_project('[nudge]\nmode = "off"\n')
        self.assertEqual(config.nudge_mode(self.project, env), "off")

    def test_user_lint_watch_used_when_project_has_none(self):
        self.write_user('[lint_watch]\nmode = "off"\n')
        self.assertEqual(config.lint_watch(self.project, self.env)["mode"], "off")
        self.write_project('[lint_watch]\nmode = "on"\n')
        self.assertEqual(config.lint_watch(self.project, self.env)["mode"], "on")

    def test_user_config_rejects_other_sections(self):
        path = self.write_user('[engine]\nprofile = "default"\n')
        with self.assertRaises(config.ConfigError) as ctx:
            config.nudge_mode(self.project, self.env)
        self.assertIn(str(path), str(ctx.exception))

    def test_bad_nudge_mode_is_an_error(self):
        self.write_project('[nudge]\nmode = "sometimes"\n')
        with self.assertRaises(config.ConfigError):
            config.nudge_mode(self.project, self.env)


if __name__ == "__main__":
    unittest.main()


class Rule(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.env = {"HOME": str(self.home)}

    def test_off_by_default_and_each_source(self):
        self.assertFalse(config.rule_enabled(self.project, self.env))
        self.assertTrue(config.rule_enabled(self.project, {**self.env, "CLAUDE_PLUGIN_OPTION_RULE": "true"}))
        user = self.home / ".config" / "plainspoken" / "config.toml"
        user.parent.mkdir(parents=True)
        user.write_text("[rule]\nenabled = true\n", encoding="utf-8")
        self.assertTrue(config.rule_enabled(self.project, self.env))
        (self.project / ".plainspoken").mkdir()
        (self.project / ".plainspoken" / "config.toml").write_text("[rule]\nenabled = false\n", encoding="utf-8")
        self.assertFalse(config.rule_enabled(self.project, self.env))

    def test_enabled_must_be_a_bool(self):
        (self.project / ".plainspoken").mkdir()
        (self.project / ".plainspoken" / "config.toml").write_text('[rule]\nenabled = "yes"\n', encoding="utf-8")
        with self.assertRaises(config.ConfigError):
            config.rule_enabled(self.project, self.env)
