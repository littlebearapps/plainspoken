"""Human overrides (dismiss, uphold), the edit diff against the check snapshot, missed tells and
survived-publish capture, through `overrides` and the `kaizen` CLI group."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from plainspoken import capture, kaizen, ledger, overrides, report, sentdiff
from plainspoken.profile import default as default_profile
from plainspoken.registry import load_config
from tests.test_anti_ai_report import _judges
from tests.test_capture import ARTICLE, _six_word_runs

REPO = Path(__file__).resolve().parents[1]
CFG = load_config()

# Two WARN spans and no BLOCK: 4b's per-word "also" WARN (line 10) and 7d's no-long-sentence WARN under "How do I
# start?" (line 12).
TWO_WARNS = ARTICLE.replace(
    " I won't delve into the soil chemistry here because my neighbour knows far more about it than me.", "")
# One "Also," opener gone: the 4b WARN goes, the 7d WARN stays.
TWO_WARNS_EDITED = TWO_WARNS.replace("Also, I checked the drainage", "I checked the drainage")
# Two hard-ban (rule 2) BLOCKs on different lines.
TWO_BANS = ARTICLE.replace("Pick a sunny bed.", "Pick a sunny bed with a stunning view.")

DELETED = "Also, I moved the tap timer so the hose reached the far corner."
REWRITTEN = "Do beans need staking?"


def cli(*args, cwd: Path, env: dict | None = None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    e["PYTHONPATH"] = str(REPO / "lib")
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=cwd, capture_output=True, text=True,
                          env=e)


class Base(unittest.TestCase):
    TEXT = ARTICLE

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()
        self.art = self.root / "post.md"
        self.art.write_text(self.TEXT, encoding="utf-8")
        self.ledger_dir = self.root / ".plainspoken" / "ledger"
        self.dir = self.root / ".plainspoken" / "reports"
        self.key = report.report_key(self.art, self.root)

    def run_cli(self, *args, env=None):
        return cli(*args, cwd=self.root, env=env)

    def check(self, env=None):
        r = self.run_cli("check", "post.md", "--profile", "default", env=env)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return r

    def kaizen(self, *args, env=None):
        return self.run_cli("kaizen", *args, env=env)

    def events(self, *outcomes):
        evs = ledger.read({"ledger_dir": self.ledger_dir, "root": self.root})[0]
        return [e for e in evs if not outcomes or e["outcome"] in outcomes]

    def fired(self, rule):
        return [e for e in self.events("fired") if e["rule"] == rule and e["actor"] == "lint"]


class Dismiss(Base):
    def test_no_prior_check_refuses_and_logs_nothing(self):
        r = self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "false_positive", "--reason", "fine here")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("run check first", r.stderr)
        self.assertFalse(self.ledger_dir.exists())

    def test_stale_check_refuses(self):
        self.check()
        self.art.write_text(ARTICLE + "\nOne more line.\n", encoding="utf-8")
        n = len(self.events())
        r = self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "false_positive", "--reason", "fine here")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no current check", r.stderr)
        self.assertEqual(len(self.events()), n)

    def test_dismiss_finds_the_files_own_profile(self):  # [engine] profiles
        voices = self.root / ".plainspoken" / "voices"
        voices.mkdir(parents=True)
        (voices / "garden.toml").write_text('[profile]\nname = "garden-voice"\n', encoding="utf-8")
        (self.root / ".plainspoken" / "config.toml").write_text(
            '[engine]\nprofile = "default"\nprofiles = [{ glob = "post.md", profile = "voices/garden.toml" }]\n',
            encoding="utf-8")
        r = self.run_cli("check", "post.md")
        self.assertIn("garden-voice", r.stdout)
        r = self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "false_positive", "--reason", "fine here")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("dismissed")
        self.assertEqual(e["profile"], "garden-voice")
        self.assertIn("section", e["facets"])  # the profile was found, so the text was parsed

    def test_dismiss_4b_logs_one_dismissed_with_kind_and_reason(self):
        self.check()
        r = self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "false_positive",
                        "--reason", "these are a list of chores, not transitions")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("dismissed", r.stdout)
        (e,) = self.events("dismissed")
        self.assertEqual((e["event"], e["actor"], e["rule"], e["severity"]), ("override", "human", "4b", "WARN"))
        self.assertEqual(e["facets"]["kind"], "false_positive")
        self.assertEqual(e["facets"]["term"], "also")
        self.assertEqual(e["reason"], "these are a list of chores, not transitions")
        self.assertEqual(e["doc_id"], ledger.doc_id(self.art, self.root))
        self.assertEqual(e["doc_sha"], report.sha256(self.art))
        self.assertNotIn("excerpt", e)

    def test_dismissed_span_joins_the_fired_span(self):
        self.check()
        self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "voice", "--reason", "my voice")
        (fired,) = self.fired("4b")
        (dismissed,) = self.events("dismissed")
        self.assertEqual(dismissed["span_hash"], fired["span_hash"])

    def test_section_level_7d_span_joins_the_fired_span(self):
        self.check()
        (fired,) = self.fired("7d")
        self.kaizen("dismiss", "post.md", "--rule", "7d", "--kind", "format", "--reason", "an FAQ-style list")
        (dismissed,) = self.events("dismissed")
        self.assertEqual(dismissed["span_hash"], fired["span_hash"])
        self.assertEqual(dismissed["facets"]["section"], "question")

    def test_no_finding_for_the_rule_refuses(self):
        self.check()
        r = self.kaizen("dismiss", "post.md", "--rule", "26", "--kind", "other", "--reason", "nothing to see")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("rule 26 has no finding in the current check", r.stderr)
        self.assertEqual(self.events("dismissed"), [])

    def test_unknown_kind_is_usage(self):
        self.check()
        r = self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "bogus", "--reason", "x y z")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.events("dismissed"), [])

    def test_unknown_rule_and_empty_reason_are_usage(self):
        self.check()
        r = self.kaizen("dismiss", "post.md", "--rule", "ZZ-9", "--kind", "other", "--reason", "x y z")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "other", "--reason", "   ")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.events("dismissed"), [])

    def test_uphold_logs_upheld(self):
        self.check()
        r = self.kaizen("uphold", "post.md", "--rule", "4b", "--reason", "the openers really do drag")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("upheld")
        self.assertEqual((e["event"], e["actor"], e["rule"]), ("override", "human", "4b"))
        self.assertNotIn("kind", e["facets"])
        self.assertEqual(e["reason"], "the openers really do drag")
        (fired,) = self.fired("4b")
        self.assertEqual(e["span_hash"], fired["span_hash"])

    def test_uphold_takes_no_kind(self):
        with self.assertRaises(overrides.UsageError):
            overrides.override(self.art, self.root, "4b", "upheld", "voice", "a reason")

    def test_capture_off_refuses(self):
        self.check()
        (self.root / ".plainspoken" / "config.toml").write_text("[kaizen]\ncapture = false\n", encoding="utf-8")
        n = len(self.events())
        r = self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "other", "--reason", "fine here")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("capture is off", r.stderr)
        self.assertEqual(len(self.events()), n)


class DismissFromSnapshot(Base):
    """The check's fix pass can remove a finding before the person disagrees with it. `--from-snapshot`
    dismisses against the lint saved with the check snapshot (`<key>.checked.md`), not the edited file."""
    TEXT = TWO_WARNS

    def test_a_finding_the_fix_pass_removed(self):
        self.check()
        (fired,) = self.fired("4b")
        snap = self.dir / f"{self.key}.checked.md"
        snap_sha = report.sha256(snap)
        self.art.write_text(TWO_WARNS_EDITED, encoding="utf-8")  # the fix pass removed the 4b "also" opener
        args = ("dismiss", "post.md", "--rule", "4b", "--kind", "false_positive", "--reason", "a list of chores")
        r = self.kaizen(*args)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no current check", r.stderr)
        self.assertIn("--from-snapshot", r.stderr)
        r = self.kaizen(*args, "--from-snapshot")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("dismissed")
        self.assertEqual(e["span_hash"], fired["span_hash"])  # it joins the fire the check recorded
        self.assertEqual((e["doc_sha"], e["doc_id"]), (snap_sha, fired["doc_id"]))
        self.assertEqual(e["facets"], {"term": "also", "section": fired["facets"]["section"],
                                       "kind": "false_positive"})

    def test_the_check_skills_own_sequence(self):  # check → fix pass → re-check → dismiss (12a G1)
        self.check()
        (fired,) = self.fired("4b")
        first_sha = report.sha256(self.art)
        self.art.write_text(TWO_WARNS_EDITED, encoding="utf-8")  # the fix pass removed the 4b "also" opener
        self.check()  # check skill step 6 → step 1: the snapshot and the lint are now the fixed text's
        prev = self.dir / f"{self.key}.prev.checked.md"
        self.assertEqual(report.sha256(prev), first_sha)
        self.assertEqual(json.loads((self.dir / f"{self.key}.prev.lint.json").read_text(encoding="utf-8"))
                         ["article_sha256"], first_sha)
        args = ("dismiss", "post.md", "--rule", "4b", "--kind", "false_positive", "--reason", "a list of chores")
        r = self.kaizen(*args)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("--from-snapshot", r.stderr)
        r = self.kaizen(*args, "--from-snapshot")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("dismissed")
        self.assertEqual((e["span_hash"], e["doc_sha"]), (fired["span_hash"], first_sha))

    def test_a_finding_in_neither_check_is_refused(self):
        self.check()
        self.art.write_text(TWO_WARNS_EDITED, encoding="utf-8")
        self.check()
        r = self.kaizen("dismiss", "post.md", "--rule", "2", "--kind", "voice", "--reason", "mine", "--from-snapshot")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no finding in the last check or the one before it", r.stderr)
        self.assertEqual(self.events("dismissed"), [])

    def test_one_previous_pair_per_key(self):
        self.check()
        self.art.write_text(TWO_WARNS_EDITED, encoding="utf-8")
        self.check()
        second = report.sha256(self.art)
        self.check()  # the same text again: the previous pair stays the first check's
        self.assertNotEqual(report.sha256(self.dir / f"{self.key}.prev.checked.md"), second)
        self.art.write_text(TWO_WARNS_EDITED + "\nOne more line.\n", encoding="utf-8")
        self.check()  # a new version rotates: the previous pair is now the second check's
        self.assertEqual(report.sha256(self.dir / f"{self.key}.prev.checked.md"), second)
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.prev.*")),
                         sorted([f"{self.key}.prev.checked.md", f"{self.key}.prev.lint.json"]))

    def test_a_snapshot_the_lint_doesnt_match_refuses(self):
        self.check()
        (self.dir / f"{self.key}.checked.md").write_text("Some other text.\n", encoding="utf-8")
        r = self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "voice", "--reason", "mine",
                        "--from-snapshot")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("doesn't match its check snapshot", r.stderr)
        self.assertEqual(self.events("dismissed"), [])

    def test_no_snapshot_refuses(self):
        r = self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "voice", "--reason", "mine",
                        "--from-snapshot")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no check snapshot", r.stderr)


class DismissLine(Base):
    TEXT = TWO_BANS

    def test_line_narrows_to_one_finding(self):
        self.check()
        bans = self.fired("2")
        self.assertEqual(len(bans), 2)
        lint = json.loads((self.dir / f"{self.key}.lint.json").read_text(encoding="utf-8"))
        lines = sorted(f["line"] for f in lint["findings"] if f["rule"] == "2")
        r = self.kaizen("dismiss", "post.md", "--rule", "2", "--kind", "quote", "--reason", "a quoted phrase",
                        "--line", str(lines[1]))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("dismissed")
        want = next(f for f in lint["findings"] if f["rule"] == "2" and f["line"] == lines[1])
        self.assertEqual(e["span_hash"], capture.span(want, capture.facets(want, None, CFG)))
        self.assertEqual(e["severity"], "BLOCK")

    def test_without_line_every_finding(self):
        self.check()
        r = self.kaizen("dismiss", "post.md", "--rule", "2", "--kind", "voice", "--reason", "both are mine")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual({e["span_hash"] for e in self.events("dismissed")},
                         {e["span_hash"] for e in self.fired("2")})

    def test_line_with_no_finding_refuses(self):
        self.check()
        r = self.kaizen("dismiss", "post.md", "--rule", "2", "--kind", "voice", "--reason", "x y z", "--line", "1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.events("dismissed"), [])


QUOTE = "I dug in two bags of compost and a handful of blood and bone"


class DismissJudged(Base):
    def test_judge_evidence_span_joins_the_judge_fire(self):
        self.check()
        lint = json.loads((self.dir / f"{self.key}.lint.json").read_text(encoding="utf-8"))
        _judges(self.dir, self.key, lint["article_sha256"], CFG, default_profile(), fails=("5b",))
        p = self.dir / f"{self.key}.J1.judge.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        for v in data["verdicts"]:
            if v["rule"] == "5b":
                v["evidence"] = [{"line": 10, "quote": QUOTE, "reason": "frames the paragraph"}]
        p.write_text(json.dumps(data), encoding="utf-8")
        self.run_cli("merge", "post.md", "--profile", "default")
        (fired,) = [e for e in self.events("fired") if e["rule"] == "5b"]
        r = self.kaizen("dismiss", "post.md", "--rule", "5b", "--kind", "false_positive", "--reason", "not meta")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("dismissed")
        self.assertEqual((e["span_hash"], e["severity"]), (fired["span_hash"], fired["severity"]))
        self.assertEqual(e["facets"]["section"], "other")
        self.assertNotIn("excerpt", e)
        for line in (self.ledger_dir / f"{e['ts'][:7]}.jsonl").read_text(encoding="utf-8").splitlines():
            self.assertNotIn("compost", line)

    def judge_with_two_quotes(self):
        """Check, then J1 fails 5b with two evidence quotes (lines 3 and 7), then merge."""
        self.check()
        lint = json.loads((self.dir / f"{self.key}.lint.json").read_text(encoding="utf-8"))
        _judges(self.dir, self.key, lint["article_sha256"], CFG, default_profile(), fails=("5b",))
        p = self.dir / f"{self.key}.J1.judge.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        for v in data["verdicts"]:
            if v["rule"] == "5b":
                v["evidence"] = [{"line": 3, "quote": "What I learnt growing broad beans", "reason": "frames it"},
                                 {"line": 7, "quote": QUOTE, "reason": "frames the paragraph"}]
        p.write_text(json.dumps(data), encoding="utf-8")
        self.run_cli("merge", "post.md", "--profile", "default")
        (fired,) = [e for e in self.events("fired") if e["rule"] == "5b"]
        self.assertEqual(fired["span_hash"], ledger.span_hash("5b", "What I learnt growing broad beans"))
        return fired

    def test_two_quotes_give_one_override_on_the_fired_span(self):
        fired = self.judge_with_two_quotes()
        r = self.kaizen("dismiss", "post.md", "--rule", "5b", "--kind", "false_positive", "--reason", "not meta")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("dismissed")
        self.assertEqual(e["span_hash"], fired["span_hash"])

    def test_line_of_the_second_quote_selects_the_same_single_span(self):
        fired = self.judge_with_two_quotes()
        r = self.kaizen("dismiss", "post.md", "--rule", "5b", "--kind", "voice", "--reason", "mine", "--line", "7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("dismissed")
        self.assertEqual(e["span_hash"], fired["span_hash"])

    def test_line_matching_no_quote_refuses(self):
        self.judge_with_two_quotes()
        r = self.kaizen("dismiss", "post.md", "--rule", "5b", "--kind", "voice", "--reason", "mine", "--line", "99")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no finding on line 99", r.stderr)
        self.assertEqual(self.events("dismissed"), [])

    def test_judged_rule_without_a_report_refuses(self):
        self.check()
        r = self.kaizen("dismiss", "post.md", "--rule", "5b", "--kind", "other", "--reason", "x y z")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)


class Diff(Base):
    def edit(self):
        text = ARTICLE.replace(DELETED + " ", "").replace(REWRITTEN, "Will the beans want stakes?")
        self.art.write_text(text, encoding="utf-8")

    def test_no_snapshot_refuses(self):
        r = self.kaizen("diff", "post.md")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no check snapshot", r.stderr)
        with self.assertRaisesRegex(ValueError, "run check first"):
            overrides.hunks(self.art, self.root)

    def test_capture_off_check_leaves_no_snapshot_and_diff_says_why(self):
        (self.root / ".plainspoken").mkdir()
        (self.root / ".plainspoken" / "config.toml").write_text("[kaizen]\ncapture = false\n", encoding="utf-8")
        self.check()
        self.assertFalse((self.dir / f"{self.key}.checked.md").exists())
        self.assertFalse((self.root / ".plainspoken" / "kaizen").exists())  # never captured: no capture-off stamp
        self.edit()
        for cmd in ("diff", "published"):
            r = self.kaizen(cmd, "post.md")
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("no check snapshot", r.stderr)
            self.assertIn("only when kaizen capture is on", r.stderr)
        self.assertFalse(self.ledger_dir.exists())

    def config(self, text):
        (self.root / ".plainspoken").mkdir(exist_ok=True)
        (self.root / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def stale_after_capture_off(self, off: str):  # a snapshot left from before capture was turned off
        self.check()
        snap = self.dir / f"{self.key}.checked.md"
        other = self.dir / "other-0123456789abcdef.checked.md"  # another article's snapshot in the same folder
        other.write_text("Old text.\n", encoding="utf-8")
        self.assertTrue(snap.exists())
        self.config(off)
        self.edit()
        for cmd in ("diff", "published"):
            r = self.kaizen(cmd, "post.md")
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("ignored", r.stderr)
            self.assertIn("capture is off", r.stderr)
        prev_snap, prev_lint = (self.dir / f"{self.key}.prev.checked.md"), (self.dir / f"{self.key}.prev.lint.json")
        prev_snap.write_text("Older text.\n", encoding="utf-8")
        prev_lint.write_text("{}\n", encoding="utf-8")
        self.check()  # the next check with capture off deletes the snapshots and the previous pairs
        self.assertFalse(snap.exists())
        self.assertFalse(other.exists())
        self.assertFalse(prev_snap.exists())
        self.assertFalse(prev_lint.exists())
        self.assertTrue((self.root / ".plainspoken" / "kaizen" / "capture-off.txt").is_file())
        self.config("")  # capture back on: nothing stale to diff against
        r = self.kaizen("diff", "post.md")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no check snapshot", r.stderr)
        self.check()
        self.assertEqual(self.kaizen("diff", "post.md").returncode, 0)

    def test_stale_snapshot_after_capture_false(self):
        self.stale_after_capture_off("[kaizen]\ncapture = false\n")

    def test_stale_snapshot_after_check_leaves_capture_sources(self):
        self.stale_after_capture_off('[kaizen]\ncapture_sources = ["merge", "judge", "lint-watch"]\n')

    def test_a_snapshot_older_than_the_capture_off_time_is_ignored(self):
        other = self.root / "elsewhere"
        r = self.run_cli("check", "post.md", "--profile", "default", "--reports", "elsewhere")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        self.config("[kaizen]\ncapture = false\n")
        self.check()  # capture off: stamps the time (the other reports folder isn't touched)
        self.config("")
        self.edit()
        r = self.kaizen("diff", "post.md", "--reports", "elsewhere")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("older than the last time kaizen capture was off", r.stderr)
        self.assertIn("ignored", r.stderr)
        r = self.run_cli("check", "post.md", "--profile", "default", "--reports", "elsewhere")
        r = self.kaizen("diff", "post.md", "--reports", "elsewhere")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(other.is_dir())

    def test_no_changes(self):
        self.check()
        r = self.kaizen("diff", "post.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("(no changes since the last check)", r.stdout)
        self.assertEqual(overrides.hunks(self.art, self.root), [])

    def test_delete_and_rewrite_give_two_hunks(self):
        self.check()
        self.edit()
        hunks = overrides.hunks(self.art, self.root)
        self.assertEqual([h["n"] for h in hunks], [1, 2])
        self.assertEqual((hunks[0]["old"], hunks[0]["new"]), (DELETED, ""))
        self.assertEqual(hunks[0]["old_lines"], [10, 10])
        self.assertEqual((hunks[1]["old"], hunks[1]["new"]), (REWRITTEN, "Will the beans want stakes?"))
        self.assertEqual(hunks[1]["old_lines"], [18, 18])
        r = self.kaizen("diff", "post.md", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), hunks)
        r = self.kaizen("diff", "post.md")
        self.assertIn(DELETED, r.stdout)
        self.assertTrue(re.search(r"^\[2\] ", r.stdout, re.M), r.stdout)

    def test_fenced_code_lines_are_units_of_their_own(self):  # not prose to join and split
        old = "# T\n\nSome prose.\n\n```\nx = 1. y = 2.\nz = 3.\n```\n"
        new = old.replace("z = 3.", "z = 4.")
        (h,) = overrides._hunks(old, new)
        self.assertEqual((h["old"], h["new"], h["old_lines"]), ("z = 3.", "z = 4.", [7, 7]))
        self.assertIn(("x = 1. y = 2.", 6, 6), overrides._units(old))  # one line, one unit, never split

    def test_a_sentence_the_splitter_reshaped_covers_the_rest_of_its_paragraph(self):
        text = "Alpha one.\nBeta two.\nGamma three.\n"
        real = sentdiff.split_sentences
        sentdiff.split_sentences = lambda t: ["Alpha one.", "Gamma."]  # not a substring of the paragraph
        self.addCleanup(setattr, sentdiff, "split_sentences", real)
        units = overrides._units(text)
        self.assertEqual(units[0], ("Alpha one.", 1, 1))
        sentence, first, last = units[1]
        self.assertLessEqual(first, 3)
        self.assertEqual(last, 3)  # never placed short of the line it really sits on

    def test_wrapped_paragraph_is_one_sentence(self):
        text = "# T\n\nThe first sentence runs on\nacross two lines. A second one.\n"
        self.art.write_text(text, encoding="utf-8")
        self.check()
        self.art.write_text(text.replace("A second one.", "A second, changed one."), encoding="utf-8")
        (h,) = overrides.hunks(self.art, self.root)
        self.assertEqual((h["old"], h["old_lines"]), ("A second one.", [4, 4]))
        self.art.write_text(text.replace("runs on\nacross", "runs\nacross"), encoding="utf-8")
        (h,) = overrides.hunks(self.art, self.root)
        self.assertEqual((h["old"], h["old_lines"]), ("The first sentence runs on across two lines.", [3, 4]))

    def test_missed_with_pattern(self):
        self.check()
        self.edit()
        r = self.kaizen("missed", "post.md", "--hunk", "2", "--pattern", "salience-flag",
                        "--reason", "a question heading that adds nothing")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("missed")
        self.assertEqual((e["event"], e["actor"], e["severity"], e["rule"]), ("diff", "human", None, "?"))
        self.assertEqual(e["facets"]["pattern"], "salience-flag")
        self.assertEqual(e["span_hash"], ledger.span_hash("salience-flag", REWRITTEN))
        self.assertEqual(e["reason"], "a question heading that adds nothing")
        self.assertEqual(e["doc_sha"], report.sha256(self.dir / f"{self.key}.checked.md"))
        self.assertNotIn("excerpt", e)

    def test_missed_with_rule(self):
        self.check()
        self.edit()
        r = self.kaizen("missed", "post.md", "--hunk", "1", "--rule", "4b")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("missed")
        self.assertEqual(e["rule"], "4b")
        self.assertEqual(e["span_hash"], ledger.span_hash("4b", DELETED))
        self.assertNotIn("pattern", e["facets"])
        self.assertNotIn("reason", e)

    def test_missed_excerpt_only_with_excerpts_on(self):
        self.check()
        self.edit()
        self.kaizen("missed", "post.md", "--hunk", "1", "--rule", "4b",
                    env={"CLAUDE_PLUGIN_OPTION_LEDGER_EXCERPTS": "true"})
        (e,) = self.events("missed")
        self.assertEqual(e["excerpt"], DELETED)

    def test_missed_on_an_insertion_refuses(self):
        self.check()
        self.art.write_text(ARTICLE + "\nA brand new closing line about the beans.\n", encoding="utf-8")
        (h,) = overrides.hunks(self.art, self.root)
        self.assertEqual((h["old"], h["new"]), ("", "A brand new closing line about the beans."))
        r = self.kaizen("missed", "post.md", "--hunk", "1", "--rule", "4b")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("only adds text", r.stderr)

    def test_privacy_no_article_text_with_excerpts_off(self):
        self.check()
        self.kaizen("dismiss", "post.md", "--rule", "4b", "--kind", "voice", "--reason", "my voice")
        self.edit()
        self.kaizen("missed", "post.md", "--hunk", "1", "--rule", "4b")
        self.kaizen("published", "post.md")
        self.assertTrue(self.events("dismissed") and self.events("missed") and self.events("survived_publish"))
        lines = [ledger.normalise(x) for p in sorted(self.ledger_dir.iterdir())
                 for x in p.read_text(encoding="utf-8").splitlines()]
        runs = _six_word_runs(ARTICLE)
        self.assertEqual([r for r in runs if any(r in x for x in lines)], [])

    def test_missed_bad_hunk_refuses(self):
        self.check()
        self.edit()
        r = self.kaizen("missed", "post.md", "--hunk", "9", "--pattern", "salience-flag")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.events("missed"), [])

    def test_missed_needs_exactly_one_of_rule_and_pattern(self):
        self.check()
        self.edit()
        both = self.kaizen("missed", "post.md", "--hunk", "1", "--rule", "4b", "--pattern", "salience-flag")
        neither = self.kaizen("missed", "post.md", "--hunk", "1")
        bad = self.kaizen("missed", "post.md", "--hunk", "1", "--pattern", "Not A Pattern")
        unknown = self.kaizen("missed", "post.md", "--hunk", "1", "--rule", "ZZ-9")
        self.assertEqual([x.returncode for x in (both, neither, bad, unknown)], [2, 2, 2, 2])
        self.assertEqual(self.events("missed"), [])
        with self.assertRaises(overrides.UsageError):
            overrides.missed(self.art, self.root, 1)


class Published(Base):  # the article is edited after a PASS
    TEXT = TWO_WARNS

    def test_removed_span_does_not_survive_and_shows_in_diff(self):
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(sorted(e["rule"] for e in self.events("fired")), ["4b", "7d"])
        self.art.write_text(TWO_WARNS_EDITED, encoding="utf-8")
        r = self.kaizen("published", "post.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = self.events("survived_publish")
        (fired_7d,) = self.fired("7d")
        self.assertEqual((e["event"], e["actor"], e["rule"], e["severity"]), ("publish", "publish", "7d", "WARN"))
        self.assertEqual(e["span_hash"], fired_7d["span_hash"])
        self.assertEqual(e["doc_sha"], report.sha256(self.art))
        self.assertIn("7d", r.stdout)
        d = self.kaizen("diff", "post.md")
        self.assertIn("Also, I checked the drainage after a heavy shower.", d.stdout)

    def test_unchanged_file_keeps_both_and_repeat_is_the_same_ids(self):
        self.check()
        self.kaizen("published", "post.md")
        first = self.events("survived_publish")
        self.assertEqual(sorted(e["rule"] for e in first), ["4b", "7d"])
        self.kaizen("published", "post.md")
        self.assertEqual({e["id"] for e in self.events("survived_publish")}, {e["id"] for e in first})

    def test_justified_rule_survives(self):
        self.check()
        sha = report.sha256(self.art)
        (self.dir / f"{self.key}.report.json").write_text(json.dumps({
            "article": str(self.art), "article_sha256": sha, "profile": "default",
            "profile_sha256": default_profile().sha256, "ruleset_version": CFG.version, "status": "PASS",
            "justified": [{"rule": "7d", "kind": "voice", "reason": "my own diary reads like this",
                           "review": "accept"}], "rules": {}}), encoding="utf-8")
        self.kaizen("published", "post.md")
        just = [e for e in self.events("survived_publish") if e["span_hash"] == ledger.span_hash("7d", "*")]
        self.assertEqual(len(just), 1)
        self.assertEqual(just[0]["facets"], {"kind": "voice"})
        self.assertNotIn("reason", just[0])

    QUOTE = "Pick a sunny bed. Water it well."

    def judge_report(self, quote, sha, rule="18"):
        (self.dir / f"{self.key}.report.json").write_text(json.dumps({
            "article": str(self.art), "article_sha256": sha, "profile": "default",
            "profile_sha256": default_profile().sha256, "ruleset_version": CFG.version, "status": "PASS",
            "justified": [], "rules": {rule: {"source": "judge:J1", "verdict": "fail", "judge_verdict": "fail",
                                              "severity": "WARN", "evidence": [{"quote": quote, "line": 14}]}}}),
            encoding="utf-8")

    def test_judge_only_warn_kept_when_its_span_is_still_there(self):  # a judge-only WARN can count as kept
        self.check()
        self.judge_report(self.QUOTE, report.sha256(self.art))  # judged the checked text
        self.art.write_text(TWO_WARNS_EDITED, encoding="utf-8")  # an edit elsewhere; the judged span stays
        r = self.kaizen("published", "post.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        (e,) = [e for e in self.events("survived_publish") if e["rule"] == "18"]
        self.assertEqual((e["event"], e["actor"], e["severity"]), ("publish", "publish", "WARN"))
        self.assertEqual(e["span_hash"], ledger.span_hash("18", self.QUOTE))  # the judge fire's span (merge_events)
        self.assertEqual(e["facets"], {"section": "question"})
        m = kaizen.rule_metrics(self.events(), CFG, datetime.now(timezone.utc))["18"]
        self.assertEqual((m["survived"], m["kept_docs"]), (1, 1))

    def test_judge_only_warn_whose_span_went_is_not_kept(self):
        self.check()
        self.judge_report(self.QUOTE, report.sha256(self.art))
        self.art.write_text(TWO_WARNS.replace("Water it well. ", ""), encoding="utf-8")
        self.kaizen("published", "post.md")
        self.assertEqual([e for e in self.events("survived_publish") if e["rule"] == "18"], [])

    def test_a_report_of_another_version_or_a_pass_counts_nothing(self):
        self.check()
        self.judge_report(self.QUOTE, "b" * 64)  # neither the checked nor the published text
        self.kaizen("published", "post.md")
        self.judge_report(self.QUOTE, report.sha256(self.art), rule="4b")  # not a judge-only rule
        self.kaizen("published", "post.md")
        self.assertEqual([e for e in self.events("survived_publish") if e["rule"] in ("18", "4b")
                          and e["span_hash"] == ledger.span_hash(e["rule"], self.QUOTE)], [])

    def test_no_snapshot_refuses(self):
        r = self.kaizen("published", "post.md")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no check snapshot", r.stderr)
        self.assertFalse(self.ledger_dir.exists())

    def test_wrong_profile_refuses(self):
        self.check()
        other = REPO / "tests" / "fixtures" / "profiles" / "product_like.toml"
        r = self.kaizen("published", "post.md", "--profile", str(other))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.events("survived_publish"), [])


if __name__ == "__main__":
    unittest.main()
