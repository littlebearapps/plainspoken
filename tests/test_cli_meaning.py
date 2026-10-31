"""`plainspoken meaning-diff` (#147): the saved baseline, the saved result bound to both texts, and its lines."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken import meaning, report

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "meaning"


def cli(*args, cwd: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_"))}
    env["PYTHONPATH"] = str(REPO / "lib")
    return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=cwd, capture_output=True, text=True,
                          env=env)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Command(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.src = (FIX / "issue-src.md").read_text(encoding="utf-8")
        self.rw = (FIX / "issue-rw.md").read_text(encoding="utf-8")
        self.art = self.cwd / "email.md"
        self.art.write_text(self.src, encoding="utf-8")
        self.paths = report.report_paths(self.art, self.cwd / ".plainspoken" / "reports", self.cwd)

    def test_start_then_compare(self):
        r = cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "meaning-diff: baseline saved for email.md")
        self.assertEqual(self.paths["before"].read_text(encoding="utf-8"), self.src)
        self.art.write_text(self.rw, encoding="utf-8")
        r = cli("meaning-diff", "email.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual([x.split(" ", 1)[0] for x in lines if x.startswith("M")], ["M1", "M2", "M3"])
        self.assertIn('M3 line 3: dropped "won\'t", "without"', r.stdout)
        self.assertEqual(lines[-1], meaning.FOOTER)
        rec = json.loads(self.paths["meaning"].read_text(encoding="utf-8"))
        self.assertEqual((rec["before_sha256"], rec["after_sha256"]), (sha(self.src), sha(self.rw)))
        self.assertEqual(rec["lexicon_sha256"], meaning.lexicon_sha256())
        self.assertEqual(rec["article"], "email.md")
        self.assertEqual(len(rec["changes"]), 3)

    def test_json(self):
        cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.art.write_text(self.rw, encoding="utf-8")
        r = cli("meaning-diff", "email.md", "--json", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c["id"] for c in json.loads(r.stdout)["changes"]], ["M1", "M2", "M3"])

    def test_before_flag(self):
        old = self.cwd / "old.md"
        old.write_text(self.src, encoding="utf-8")
        self.art.write_text(self.rw, encoding="utf-8")
        r = cli("meaning-diff", "email.md", "--before", "old.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('dropped "won\'t", "without"', r.stdout)
        self.assertFalse(self.paths["meaning"].exists())  # two files given: nothing saved for status

    def test_no_baseline_is_exit_2(self):
        r = cli("meaning-diff", "email.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no baseline for email.md: run meaning-diff email.md --start before the first edit", r.stderr)

    def test_missing_file_is_exit_2(self):
        r = cli("meaning-diff", "nope.md", "--start", cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("nope.md", r.stderr)

    def test_not_utf8_is_exit_2(self):
        self.art.write_bytes(b"caf\xe9 is free\n")
        r = cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("UnicodeDecodeError", r.stderr)
        self.assertFalse(self.paths["before"].exists())

    def test_listing_is_capped(self):
        before = "\n\n".join(f"Room {n} isn't included in the fee." for n in range(1, 31)) + "\n"
        self.art.write_text(before, encoding="utf-8")
        cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.art.write_text(before.replace("isn't", "is"), encoding="utf-8")
        r = cli("meaning-diff", "email.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([x for x in r.stdout.splitlines() if x.startswith("M")]), 10)
        self.assertIn("… 20 more in .plainspoken/reports/", r.stdout)

    def test_exit_0_when_nothing_listed(self):
        cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.art.write_text((FIX / "issue-join.md").read_text(encoding="utf-8"), encoding="utf-8")
        r = cli("meaning-diff", "email.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["meaning-diff: nothing listed", meaning.FOOTER])

    def test_a_new_start_clears_the_old_result(self):
        cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.art.write_text(self.rw, encoding="utf-8")
        cli("meaning-diff", "email.md", cwd=self.cwd)
        self.assertTrue(self.paths["meaning"].exists())
        cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.assertFalse(self.paths["meaning"].exists())


class Saved(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.reports = self.cwd / ".plainspoken" / "reports"
        self.art = self.cwd / "email.md"
        self.src = (FIX / "issue-src.md").read_text(encoding="utf-8")
        self.art.write_text(self.src, encoding="utf-8")

    def test_states(self):
        self.assertEqual(meaning.saved(self.art, self.cwd, self.reports), ("no-baseline", []))
        meaning.start(self.art, self.cwd, self.reports)
        self.assertEqual(meaning.saved(self.art, self.cwd, self.reports), ("missing", []))
        self.art.write_text((FIX / "issue-rw.md").read_text(encoding="utf-8"), encoding="utf-8")
        meaning.record(self.art, self.cwd, self.reports, self.src)
        state, changes = meaning.saved(self.art, self.cwd, self.reports)
        self.assertEqual((state, len(changes)), ("current", 3))
        self.art.write_text("Edited after the diff ran.\n", encoding="utf-8")
        self.assertEqual(meaning.saved(self.art, self.cwd, self.reports), ("stale", []))

    def test_summarise(self):
        changes = meaning.diff(self.src, (FIX / "issue-rw.md").read_text(encoding="utf-8"))
        text = meaning.summarise(changes, shown=2, path="r/x.meaning.json")
        self.assertIn('M2 cut: dropped "separate", "isn\'t"; was: "Your ad spend is separate', text)
        self.assertIn("… 1 more in r/x.meaning.json", text)
        self.assertEqual(text.splitlines()[-1], meaning.FOOTER)
        self.assertEqual(meaning.summarise([]).splitlines(), ["meaning-diff: nothing listed", meaning.FOOTER])


if __name__ == "__main__":
    unittest.main()
