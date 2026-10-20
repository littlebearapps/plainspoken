import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.dev import check_release_version as crv


class ReleaseVersionTests(unittest.TestCase):
    def setUp(self):
        out = contextlib.redirect_stdout(io.StringIO())
        out.__enter__()
        self.addCleanup(out.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".claude-plugin").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _set(self, plugin_ver, manifest_ver):
        (self.root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "p", "version": plugin_ver}))
        (self.root / ".release-please-manifest.json").write_text(json.dumps({".": manifest_ver}))

    def test_match_passes(self):
        self._set("0.1.0", "0.1.0")
        self.assertEqual(crv.main(str(self.root)), 0)

    def test_mismatch_fails(self):
        self._set("0.1.0", "0.2.0")
        self.assertEqual(crv.main(str(self.root)), 1)

    def test_missing_version_fails(self):
        (self.root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "p"}))
        (self.root / ".release-please-manifest.json").write_text(json.dumps({".": "0.1.0"}))
        self.assertEqual(crv.main(str(self.root)), 1)


if __name__ == "__main__":
    unittest.main()


class HostManifestVersionTests(unittest.TestCase):
    def setUp(self):
        out = contextlib.redirect_stdout(io.StringIO())
        out.__enter__()
        self.addCleanup(out.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for d in (".claude-plugin", ".codex-plugin", ".hermes-plugin"):
            (self.root / d).mkdir()
        (self.root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "0.6.0"}))
        (self.root / ".release-please-manifest.json").write_text(json.dumps({".": "0.6.0"}))

    def _hosts(self, codex, hermes):
        (self.root / ".codex-plugin" / "plugin.json").write_text(json.dumps({"version": codex}))
        (self.root / ".hermes-plugin" / "plugin.yaml").write_text(f"name: p\nversion: {hermes}\n")

    def test_all_match(self):
        self._hosts("0.6.0", "0.6.0")
        self.assertEqual(crv.main(str(self.root)), 0)

    def test_codex_behind_fails(self):
        self._hosts("0.5.0", "0.6.0")
        self.assertEqual(crv.main(str(self.root)), 1)

    def test_hermes_behind_fails(self):
        self._hosts("0.6.0", "0.5.0")
        self.assertEqual(crv.main(str(self.root)), 1)

    def test_the_repo_itself_matches(self):
        self.assertEqual(crv.main(str(Path(__file__).resolve().parents[1])), 0)
