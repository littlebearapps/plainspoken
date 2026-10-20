import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lib"))
from plainspoken import config  # noqa: E402

RUN = REPO / "lib" / "run.py"


def clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}


class ProjectRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.deep = self.tmp / "a" / "b"
        self.deep.mkdir(parents=True)

    def test_nearest_config_wins(self):
        (self.tmp / ".plainspoken").mkdir()
        (self.tmp / ".plainspoken" / "config.toml").write_text("", encoding="utf-8")
        self.assertEqual(config.project_root(self.deep, env={}), self.tmp)

    def test_git_folder_when_no_config(self):
        (self.tmp / ".git").mkdir()
        self.assertEqual(config.project_root(self.deep, env={}), self.tmp)

    def test_git_file_counts(self):  # a worktree's .git is a file
        (self.tmp / "a" / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        self.assertEqual(config.project_root(self.deep, env={}), self.tmp / "a")

    def test_nearest_of_either(self):
        (self.tmp / ".plainspoken").mkdir()
        (self.tmp / ".plainspoken" / "config.toml").write_text("", encoding="utf-8")
        (self.tmp / "a" / ".git").mkdir()
        self.assertEqual(config.project_root(self.deep, env={}), self.tmp / "a")

    def test_claude_project_dir_when_it_contains_start(self):
        (self.tmp / "a" / ".git").mkdir()
        self.assertEqual(config.project_root(self.deep, env={"CLAUDE_PROJECT_DIR": str(self.tmp)}), self.tmp)

    def test_claude_project_dir_ignored_when_unrelated(self):
        other = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        (self.tmp / ".git").mkdir()
        self.assertEqual(config.project_root(self.deep, env={"CLAUDE_PROJECT_DIR": str(other)}), self.tmp)

    def test_falls_back_to_start(self):  # a .git or .plainspoken in / or /tmp can't change the answer
        from unittest import mock
        top = self.tmp / "a"  # the temp root: the walk sees nothing above it, whatever this machine has there
        real_exists, real_is_file = Path.exists, Path.is_file

        def inside(p: Path) -> bool:
            return Path(p).is_relative_to(top)

        (self.tmp / ".git").mkdir()  # stands in for a marker above the temp root, like a /tmp/.git
        with mock.patch.object(Path, "exists", lambda p, *a, **k: inside(p) and real_exists(p, *a, **k)), \
                mock.patch.object(Path, "is_file", lambda p, *a, **k: inside(p) and real_is_file(p, *a, **k)):
            self.assertEqual(config.project_root(self.deep, env={}), self.deep)
            (top / ".git").mkdir()  # the same walk still finds a marker inside the temp root
            self.assertEqual(config.project_root(self.deep, env={}), top)


class CliFromSubfolder(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".plainspoken").mkdir()
        (self.root / ".plainspoken" / "config.toml").write_text('[engine]\nprofile = "default"\n', encoding="utf-8")
        (self.root / "docs").mkdir()
        (self.root / "docs" / "post.md").write_text("I fixed the login bug on Friday.\n", encoding="utf-8")

    def run_cli(self, *args, cwd):
        return subprocess.run([sys.executable, str(RUN), *args], capture_output=True, text=True, cwd=cwd,
                              env=clean_env())

    def test_paths_same_from_root_and_subfolder(self):
        a = self.run_cli("paths", "docs/post.md", cwd=self.root)
        b = self.run_cli("paths", "post.md", cwd=self.root / "docs")
        self.assertEqual((a.returncode, b.returncode), (0, 0), a.stderr + b.stderr)
        self.assertEqual(json.loads(a.stdout), json.loads(b.stdout))

    def test_check_from_subfolder_writes_to_the_root_reports(self):
        r = self.run_cli("check", "post.md", cwd=self.root / "docs")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        self.assertTrue(list((self.root / ".plainspoken" / "reports").glob("post-*.lint.json")))
        self.assertFalse((self.root / "docs" / ".plainspoken").exists())

    def test_project_config_found_from_subfolder(self):
        r = self.run_cli("profile", cwd=self.root / "docs")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("plainspoken profile: default", r.stdout)

    def test_merge_from_subfolder_reads_the_root_reports(self):  # merge defaults to Path.cwd()
        self.run_cli("check", "docs/post.md", cwd=self.root)
        a = self.run_cli("merge", "docs/post.md", cwd=self.root)
        b = self.run_cli("merge", "post.md", cwd=self.root / "docs")
        self.assertEqual((a.returncode, b.returncode), (1, 1))  # INCOMPLETE: no judge files yet
        self.assertEqual(a.stdout, b.stdout)

    def test_justify_from_subfolder_uses_the_root_reports(self):
        self.run_cli("check", "docs/post.md", cwd=self.root)
        self.run_cli("merge", "docs/post.md", cwd=self.root)  # writes an INCOMPLETE report
        a = self.run_cli("justify", "docs/post.md", "--template", cwd=self.root)
        b = self.run_cli("justify", "post.md", "--template", cwd=self.root / "docs")
        self.assertEqual((a.returncode, a.stderr), (b.returncode, b.stderr))
        self.assertIn("INCOMPLETE", b.stderr)  # found the root report; a miss says "no current report"
