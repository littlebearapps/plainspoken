"""hooks/_common.py per-session state: never follows a planted symlink, never leaves a temp file."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "hooks"))
import _common  # noqa: E402


class State(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = self.tmp / "data"
        self.victim = self.tmp / "victim.txt"
        self.victim.write_text("precious\n", encoding="utf-8")

    def test_round_trip(self):
        self.assertIsNone(_common.record_state(self.data, "s.json", "a", "1"))
        self.assertEqual(_common.record_state(self.data, "s.json", "a", "2"), "1")
        self.assertEqual(_common.read_state(self.data, "s.json"), {"a": "2"})
        self.assertEqual(list(self.data.glob("*.tmp")), [])

    def test_symlinked_state_file_is_ignored(self):
        self.data.mkdir()
        (self.data / "s.json").symlink_to(self.victim)
        self.victim.write_text('{"last": {"a": "1"}}', encoding="utf-8")
        self.assertEqual(_common.read_state(self.data, "s.json"), {})
        self.assertIsNone(_common.record_state(self.data, "s.json", "a", "2"))
        self.assertEqual(self.victim.read_text(encoding="utf-8"), '{"last": {"a": "1"}}')

    def test_symlinked_data_folder_is_ignored(self):
        real = self.tmp / "real"
        real.mkdir()
        self.data.symlink_to(real, target_is_directory=True)
        _common.record_state(self.data, "s.json", "a", "1")
        self.assertEqual(list(real.iterdir()), [])

    def test_planted_fixed_tmp_name_is_untouched(self):
        self.data.mkdir()
        (self.data / "s.tmp").symlink_to(self.victim)
        (self.data / "s.json.tmp").symlink_to(self.victim)
        _common.record_state(self.data, "s.json", "a", "1")
        self.assertEqual(self.victim.read_text(encoding="utf-8"), "precious\n")

    def test_failed_replace_removes_the_temp_file(self):
        (self.data / "s.json").mkdir(parents=True)  # os.replace onto a folder fails
        _common.record_state(self.data, "s.json", "a", "1")
        self.assertEqual(list(self.data.glob("*.tmp")), [])

    def test_limit_drops_the_oldest(self):
        for i in range(_common.STATE_LIMIT + 5):
            _common.record_state(self.data, "s.json", f"k{i}", "v")
        last = _common.read_state(self.data, "s.json")
        self.assertEqual(len(last), _common.STATE_LIMIT)
        self.assertNotIn("k0", last)


if __name__ == "__main__":
    unittest.main()
