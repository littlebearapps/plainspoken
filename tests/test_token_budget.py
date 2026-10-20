import contextlib
import io
import unittest
from pathlib import Path

from scripts.dev import token_budget as tb

DETAILS = """plainspoken 0.1.0
Projected token cost
  Always-on:   ~840 tok   added to every session
"""


class ParseTests(unittest.TestCase):
    def test_plain_number(self):
        self.assertEqual(tb.always_on_tokens(DETAILS), 840)

    def test_k_suffix(self):
        self.assertEqual(tb.always_on_tokens("  Always-on:   ~1.2k tok   added"), 1200)

    def test_thousands_separator(self):  # Claude Code prints ~1,025 once the raw total passes 1,000 (Phase 5)
        self.assertEqual(tb.always_on_tokens("  Always-on:   ~1,025 tok   added to every session"), 1025)
        self.assertEqual(tb.component_costs("Per-component (rounded)\n  check  ~1,200  ~1.7k\n"), {"check": 1200})

    def test_missing_line_raises(self):
        with self.assertRaises(ValueError):
            tb.always_on_tokens("no cost line here")


class BudgetTests(unittest.TestCase):
    def test_within_budget(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tb.verdict(always_on=300, hook_tokens=150, budget=500), 0)

    def test_hook_tokens_count_towards_budget(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tb.verdict(always_on=400, hook_tokens=150, budget=500), 1)


DETAILS2 = """Projected token cost
  Always-on:   ~500 tok   added to every session

Per-component (rounded)
  component    always-on  on-invoke
  voice              ~60       < 20
  humanize          ~130      ~2.5k
  check             ~150      ~1.6k
  tells-judge       ~100       ~840
"""


class ManualOnly(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for name, manual in (("voice", True), ("check", False)):
            d = self.root / "skills" / name
            d.mkdir(parents=True)
            extra = "disable-model-invocation: true\n" if manual else ""
            (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n{extra}---\n", encoding="utf-8")

    def test_component_costs(self):
        self.assertEqual(tb.component_costs(DETAILS2), {"voice": 60, "humanize": 130, "check": 150, "tells-judge": 100})

    def test_manual_only(self):
        self.assertEqual(tb.manual_only(self.root), {"voice"})

    def test_counted_leaves_out_manual_only_skills(self):
        self.assertEqual(tb.counted(DETAILS2, self.root), (440, {"voice": 60}))


class FailsClosed(unittest.TestCase):
    def run_main(self, side_effect):
        from unittest import mock
        err = io.StringIO()
        with mock.patch("subprocess.run", side_effect=side_effect), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            code = tb.main(["."])
        return code, err.getvalue()

    def test_missing_claude_binary(self):
        code, err = self.run_main(FileNotFoundError("claude"))
        self.assertEqual(code, 2)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertTrue(err.startswith("plainspoken: token-budget: "))

    def test_details_command_fails(self):  # the message, not just the exit code
        import subprocess
        code, err = self.run_main(subprocess.CalledProcessError(1, ["claude"]))
        self.assertEqual(code, 2)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertTrue(err.startswith("plainspoken: token-budget: "), err)
        self.assertIn("returned non-zero exit status 1", err)

    def test_details_command_stderr_is_shown(self):  # claude's own reason reaches the log
        import subprocess
        e = subprocess.CalledProcessError(1, ["claude"], output="", stderr="\nError: plugin 'x' not found\nhint\n")
        code, err = self.run_main(e)
        self.assertEqual(code, 2)
        self.assertEqual(err, "plainspoken: token-budget: claude exited 1: Error: plugin 'x' not found\n")

    def test_bad_root(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(tb.main(["/nonexistent/root"]), 2)


class UnparsableTable(unittest.TestCase):  # a table it can't read exits 2, never a silent over-count
    def setUp(self):
        import shutil
        import tempfile
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        d = self.root / "skills" / "voice"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: voice\ndescription: x\ndisable-model-invocation: true\n---\n",
                                    encoding="utf-8")

    def run_main(self, stdout: str):
        import subprocess
        from unittest import mock
        done = subprocess.CompletedProcess(["claude"], 0, stdout=stdout, stderr="")
        err = io.StringIO()
        with mock.patch("subprocess.run", return_value=done), contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            code = tb.main([str(self.root)])
        return code, err.getvalue()

    def test_no_table(self):
        with self.assertRaises(ValueError):
            tb.component_costs(DETAILS)
        code, err = self.run_main(DETAILS)
        self.assertEqual(code, 2)
        self.assertIn("Per-component", err)

    def test_table_with_no_rows(self):
        broken = DETAILS + "\nPer-component (rounded)\n  component    always-on  on-invoke\n  voice  sixty  lots\n"
        with self.assertRaises(ValueError):
            tb.component_costs(broken)
        self.assertEqual(self.run_main(broken)[0], 2)

    def test_manual_only_skill_missing_from_the_table(self):
        code, err = self.run_main(DETAILS2.replace("  voice              ~60       < 20\n", ""))
        self.assertEqual(code, 2)
        self.assertIn("voice", err)

    def test_parsable_table_still_counts(self):
        self.assertEqual(self.run_main(DETAILS2), (0, ""))


if __name__ == "__main__":
    unittest.main()
