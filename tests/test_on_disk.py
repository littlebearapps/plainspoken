"""What a default check leaves on disk: the README's "What stays on disk" list, kept in step with the files the
engine and the edit hooks really write (#111).

Covered: `check` twice on a changed draft, the lint-watch and integrity hooks (with and without
CLAUDE_PLUGIN_DATA), and `[kaizen] capture = false`. Not covered: the Stop (kaizen nudge) and SubagentStop (kaizen
backstop) hooks, the files those and a capture error write (the README's "Sometimes" line), `--no-record` (see
tests/test_capture.py), and calling the hooks through hooks.json: they're run directly here."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_cli import REPO, cli

# One source of truth for the README section "What stays on disk" (README.md, the section after Host setup). Change
# both together. `<key>` is the report key (`paths <article>`), `<YYYY-MM>` the month of the ledger events.
ON_DISK = {
    "reports": {  # under .plainspoken/reports/, written by `check`
        "<key>.lint.json",            # each finding's verbatim excerpt
        "<key>.checked.md",           # a full copy of the draft as checked
        "<key>.prev.lint.json",       # from the second check of a changed draft on
        "<key>.prev.checked.md",
    },
    "ledger": {"<YYYY-MM>.jsonl"},  # under .plainspoken/ledger/: hashes and ruleset words, no text with excerpts off
    "hook_state": {  # in $CLAUDE_PLUGIN_DATA, else .plainspoken/: written by the edit hooks, keyed by session + path
        "lint-watch-state.json",
        "integrity-state.json",
    },
}
# The README's "Sometimes" line: written only by the Stop and SubagentStop hooks, a capture error, or capture off.
SOMETIMES = ("friction.jsonl", "kaizen-backstop-state.json", "kaizen-nudge-state.json", "capture-off.txt")

DRAFT = ("# A note on the hall\n\nWe delve into the plan for the hall. The committee met on Tuesday and agreed to "
         "paint the back room before winter.\n")
EDITED = DRAFT.replace("We delve into the plan for the hall.", "We looked at the plan for the hall.")
MONTH = re.compile(r"\d{4}-\d{2}\.jsonl")


def files_under(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def run_hook(name: str, project: Path, art: Path, data: Path | None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    env.update({"CLAUDE_PROJECT_DIR": str(project), "CLAUDE_PLUGIN_OPTION_PROFILE": "default"})
    if data is not None:
        env["CLAUDE_PLUGIN_DATA"] = str(data)
    event = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s1", "cwd": str(project),
             "tool_input": {"file_path": str(art)}}
    return subprocess.run([sys.executable, str(REPO / "hooks" / name)], input=json.dumps(event),
                          capture_output=True, text=True, env=env, cwd=project)


class WhatStaysOnDisk(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()  # the project root
        self.art = self.root / "post.md"

    def check_twice(self) -> str:
        """`check` on the draft, an edit, `check` again; returns the report key."""
        self.art.write_text(DRAFT, encoding="utf-8")
        first = cli("check", "post.md", "--profile", "default", cwd=self.root)
        self.assertEqual(first.returncode, 1, first.stderr)  # the delve BLOCK
        self.art.write_text(EDITED, encoding="utf-8")
        second = cli("check", "post.md", "--profile", "default", cwd=self.root)
        self.assertIn(second.returncode, (0, 1), second.stderr)
        paths = cli("paths", "post.md", cwd=self.root)
        self.assertEqual(paths.returncode, 0, paths.stderr)
        return json.loads(paths.stdout)["key"]

    def written(self, key: str, data: Path | None) -> dict[str, set[str]]:
        found = files_under(self.root) - {"post.md", ".plainspoken/config.toml"}
        out = {"reports": set(), "ledger": set(), "hook_state": set(), "other": set()}
        for rel in found:
            if rel.startswith(".plainspoken/reports/"):
                out["reports"].add(rel.split("/", 2)[2].replace(key, "<key>"))
            elif rel.startswith(".plainspoken/ledger/"):
                name = rel.split("/", 2)[2]
                out["ledger"].add("<YYYY-MM>.jsonl" if MONTH.fullmatch(name) else name)
            elif data is None and rel.startswith(".plainspoken/") and rel.count("/") == 1:
                out["hook_state"].add(rel.split("/", 1)[1])
            else:
                out["other"].add(rel)
        if data is not None:
            out["hook_state"] |= files_under(data)
        return out

    def assert_documented(self, data: Path | None):
        key = self.check_twice()
        for hook in ("lint_watch.py", "integrity.py"):
            r = run_hook(hook, self.root, self.art, data)
            self.assertEqual(r.returncode, 0, r.stderr)
        got = self.written(key, data)
        self.assertEqual(got.pop("other"), set(), "a file the README's list doesn't name")
        self.assertEqual(got, ON_DISK)
        return key

    def test_with_plugin_data_folder(self):
        data = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, data, ignore_errors=True)
        key = self.assert_documented(data)
        reports = self.root / ".plainspoken" / "reports"
        self.assertEqual((reports / f"{key}.checked.md").read_text(encoding="utf-8"), EDITED)
        self.assertEqual((reports / f"{key}.prev.checked.md").read_text(encoding="utf-8"), DRAFT)
        excerpts = [f["excerpt"] for f in json.loads((reports / f"{key}.prev.lint.json").read_text())["findings"]]
        self.assertTrue(any("delve" in e.lower() for e in excerpts), excerpts)
        ledger = "".join(p.read_text(encoding="utf-8") for p in (self.root / ".plainspoken" / "ledger").iterdir())
        self.assertIn('"term":"delve"', ledger)  # a ruleset word, not the draft's
        for words in ("the plan for the hall", "back room"):  # excerpts are off by default: no draft text
            self.assertNotIn(words, ledger)

    def test_without_plugin_data_state_goes_in_plainspoken(self):
        self.assert_documented(None)

    def test_capture_off_deletes_the_snapshots_and_keeps_the_lint(self):
        key = self.check_twice()
        (self.root / ".plainspoken" / "config.toml").write_text("[kaizen]\ncapture = false\n", encoding="utf-8")
        r = cli("check", "post.md", "--profile", "default", cwd=self.root)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        got = self.written(key, None)
        self.assertEqual(got["reports"], {"<key>.lint.json"})
        self.assertEqual(got["other"], {".plainspoken/kaizen/capture-off.txt"})
        self.assertEqual(got["hook_state"], set())

    def test_readme_names_every_file(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        section = readme.split("### What stays on disk\n", 1)[1].split("\n## ", 1)[0]
        for names in (*ON_DISK.values(), SOMETIMES):
            for name in names:
                with self.subTest(name=name):
                    self.assertIn(name.replace("<YYYY-MM>", "YYYY-MM"), section)


if __name__ == "__main__":
    unittest.main()
