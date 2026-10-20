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
