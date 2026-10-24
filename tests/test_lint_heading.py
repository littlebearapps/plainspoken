"""#109: a bare lint's heading names the content type and the BLOCK/WARN counts, never says CLEAN above listed
WARNs, and says the judges didn't run."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from plainspoken.report import lint_status, summarise

REPO = Path(__file__).resolve().parents[1]
WARNS = ("This is genuinely useful. It is particularly good. It is arguably fine. It is essentially done. "
         "It is broadly right.\n")


def _lint(findings, content_type="social"):
    return {"article": "/tmp/x/post.md", "profile": "default", "content_type": content_type, "findings": findings,
            "lint_rules": ["1", "2"], "metrics": {"words": 3}}


def _f(sev, rule="2", line=1):
    return {"rule": rule, "severity": sev, "line": line, "message": f"a {sev} finding"}


def _stdin(text):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "PLAINSPOKEN_"))}
    return subprocess.run([sys.executable, str(REPO / "lib" / "run.py"), "check", "-", "--plugin-profile", "default"],
                          input=text, capture_output=True, text=True, cwd=REPO, env=env)


class LintHeading(unittest.TestCase):
    def test_warn_only_is_not_clean_and_counts_the_warns(self):
        head = summarise(_lint([_f("WARN"), _f("WARN", "7")])).splitlines()[0]
        self.assertNotIn("CLEAN", head)
        self.assertIn("no BLOCK, 2 WARN", head)
        self.assertIn("social", head)
        self.assertTrue(head.endswith("lint only, judges not run"), head)

    def test_block_and_warn_counts(self):
        head = summarise(_lint([_f("BLOCK"), _f("WARN"), _f("WARN", "7")], "article")).splitlines()[0]
        self.assertIn("1 BLOCK, 2 WARN", head)
        self.assertIn("article", head)
        self.assertIn("lint only, judges not run", head)

    def test_nothing_listed_reads_as_no_findings(self):
        head = summarise(_lint([])).splitlines()[0]
        self.assertIn("no findings · lint only, judges not run", head)
        self.assertNotIn("CLEAN", head)

    def test_zero_counts_read_as_no(self):
        head = summarise(_lint([_f("CANDIDATE", "6")])).splitlines()[0]
        self.assertIn("· no BLOCK, no WARN, 1 CANDIDATE ·", head)
        head = summarise(_lint([_f("BLOCK")] * 3)).splitlines()[0]
        self.assertIn("· 3 BLOCK, no WARN ·", head)

    def test_stable_prefix_keeps_the_profile_third(self):  # blogs' anti-ai-check reads the profile from field 3
        head = summarise(_lint([_f("WARN")])).splitlines()[0]
        self.assertTrue(head.startswith("anti-AI lint · post.md · default · "), head)

    def test_lint_status_is_unchanged(self):
        self.assertEqual(lint_status(_lint([_f("WARN")])), "CLEAN")
        self.assertEqual(lint_status(_lint([_f("BLOCK")])), "BLOCK")

    def test_stdin_short_post_says_social_and_lint_only(self):
        r = _stdin("Short synthetic post.\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        head = r.stdout.splitlines()[0]
        self.assertIn("anti-AI lint", head)
        self.assertIn("social", head)
        self.assertIn("lint only, judges not run", head)

    def test_stdin_with_warns_and_no_block_never_prints_clean(self):
        r = _stdin(WARNS)
        self.assertEqual(r.returncode, 0, r.stderr)
        head, *rest = r.stdout.splitlines()
        warns = [line for line in rest if line.startswith("  WARN")]
        self.assertTrue(warns, r.stdout)
        self.assertIn(f"no BLOCK, {len(warns)} WARN", head)
        self.assertNotIn("CLEAN", r.stdout)


if __name__ == "__main__":
    unittest.main()
