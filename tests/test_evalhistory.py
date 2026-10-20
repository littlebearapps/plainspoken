"""The eval history file and the anti-Goodhart report (`eval goodhart`, `eval lint-rate`), plus the
history lines `eval judges`, `eval judges-report` and `eval blind score` append."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plainspoken import __main__ as cli_main
from plainspoken import evalhistory as eh

REPO = Path(__file__).resolve().parents[1]


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def entry(kind: str, metric: str, value, *, lo=None, hi=None, n=10, run="r", **extra) -> dict:
    return {"date": "2026-10-16T00:00:00Z", "kind": kind, "ruleset_version": "1.0.0", "plugin_version": "0.3.0",
            "metric": metric, "value": value, "ci_low": lo, "ci_high": hi, "n": n, "run": run, **extra}


def blind(value, lo, hi, drafts, run, tier="tier-2 proxy") -> dict:
    return entry("blind", eh.BLIND_METRIC, value, lo=lo, hi=hi, n=24, run=run, tier=tier, judge="panel majority",
                 drafts=drafts)


def lint(value, drafts) -> dict:
    return entry("lint", eh.LINT_METRIC, value, n=10, run=drafts)


class Project(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name).resolve()
        (self.d / ".git").mkdir()
        old = os.getcwd()
        os.chdir(self.d)
        self.addCleanup(os.chdir, old)
        env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""})
        env.start()
        self.addCleanup(env.stop)

    @property
    def history(self) -> Path:
        return self.d / ".plainspoken" / "evals" / "history.jsonl"


class AppendRead(Project):
    def test_append_read_roundtrip(self):
        a = lint(0.5, "/x/drafts")
        b = blind(0.4, 0.3, 0.5, "/x/drafts", "/x/blind")
        eh.append(self.d, a)
        eh.append(self.d, b)
        self.assertTrue(self.history.is_file())
        self.assertEqual(eh.read(self.d), [a, b])
        self.assertEqual(len(self.history.read_text(encoding="utf-8").splitlines()), 2)

    def test_torn_line_skipped(self):
        a = lint(0.5, "/x/drafts")
        eh.append(self.d, a)
        with self.history.open("a", encoding="utf-8") as f:
            f.write('{"date": "2026-10-16", "kind": "li')  # a torn last line
        self.assertEqual(eh.read(self.d), [a])
        with self.history.open("a", encoding="utf-8") as f:
            f.write("\n[1, 2]\nnot json\n")
        b = lint(0.7, "/x/drafts2")
        eh.append(self.d, b)
        self.assertEqual(eh.read(self.d), [a, b])

    def test_read_missing_is_empty(self):
        self.assertEqual(eh.read(self.d), [])

    def test_append_refuses_a_bad_entry(self):
        bad = lint(0.5, "/x")
        del bad["metric"]
        with self.assertRaises(ValueError):
            eh.append(self.d, bad)
        with self.assertRaises(ValueError):
            eh.append(self.d, {**lint(0.5, "/x"), "kind": "vibes"})
        self.assertFalse(self.history.exists())

    def test_append_refuses_a_symlinked_folder(self):
        elsewhere = self.d / "elsewhere"
        elsewhere.mkdir()
        (self.d / ".plainspoken").mkdir()
        (self.d / ".plainspoken" / "evals").symlink_to(elsewhere)
        with self.assertRaises(OSError):
            eh.append(self.d, lint(0.5, "/x"))
        self.assertEqual(list(elsewhere.iterdir()), [])


def ci(v):
    return {"value": v, "k": 0, "n": 10, "ci": [max(0.0, v - 0.2), min(1.0, v + 0.2)]}


def judge_row(name, model, value, tier="tier-2 proxy", kind="model"):
    return {"name": name, "tier": tier, "kind": kind, "model_requested": model, "plainspoken_judged_human": ci(value)}


class BlindEntries(unittest.TestCase):
    def entries(self, summary):
        return eh.blind_entries(summary, "/run", "/drafts", ruleset_version="1", plugin_version="0")

    def test_tier2_uses_the_non_anthropic_majority(self):
        s = {"pairs": 5, "judges": [judge_row("opus", "claude-opus-5-5", 0.1), judge_row("grok", "x-ai/grok", 0.4),
                                    judge_row("kimi", "moonshotai/kimi", 0.5)],
             "majority": [{"name": "panel majority", "tier": "tier-2 proxy", "kind": "majority",
                           "judges": ["opus", "grok", "kimi"], "plainspoken_judged_human": ci(0.2)},
                          {"name": "non-Anthropic majority", "tier": "tier-2 proxy", "kind": "majority",
                           "judges": ["grok", "kimi"], "plainspoken_judged_human": ci(0.45)}]}
        (e,) = self.entries(s)
        self.assertEqual((e["judge"], e["value"]), ("non-Anthropic majority", 0.45))

    def test_tier2_one_non_anthropic_judge_is_used_alone(self):
        s = {"pairs": 5, "judges": [judge_row("opus", "claude-opus-5-5", 0.1), judge_row("grok", "x-ai/grok", 0.4)],
             "majority": [{"name": "panel majority", "tier": "tier-2 proxy", "kind": "majority",
                           "judges": ["opus", "grok"], "plainspoken_judged_human": ci(0.2)}]}
        (e,) = self.entries(s)
        self.assertEqual((e["judge"], e["value"]), ("grok", 0.4))

    def test_tier2_all_anthropic_writes_nothing(self):
        s = {"pairs": 5, "judges": [judge_row("opus", "claude-opus-5-5", 0.1),
                                    judge_row("sonnet", "anthropic/claude-sonnet", 0.3)],
             "majority": [{"name": "panel majority", "tier": "tier-2 proxy", "kind": "majority",
                           "judges": ["opus", "sonnet"], "plainspoken_judged_human": ci(0.2)}]}
        self.assertEqual(self.entries(s), [])

    def test_no_valid_judgement_writes_nothing(self):
        row = judge_row("ann", None, 0.5, tier="tier-1", kind="rater")
        row["plainspoken_judged_human"] = {"value": None, "k": 0, "n": 0, "ci": [0.0, 1.0]}
        self.assertEqual(self.entries({"pairs": 5, "judges": [row], "majority": []}), [])

    def test_tier1_unchanged(self):
        s = {"pairs": 5, "judges": [judge_row("ann", None, 0.5, tier="tier-1", kind="rater")], "majority": []}
        (e,) = self.entries(s)
        self.assertEqual((e["tier"], e["judge"]), ("tier-1", "ann"))


class Goodhart(unittest.TestCase):
    def test_goodhart_flags_rise_with_flat_reader(self):
        entries = [lint(0.50, "/d1"), blind(0.40, 0.25, 0.55, "/d1", "/b1"),
                   lint(0.80, "/d2"), blind(0.42, 0.27, 0.58, "/d2", "/b2")]
        flags = eh.goodhart(entries)
        self.assertEqual(len(flags), 1)
        text = flags[0]
        self.assertIn("0.50", text)
        self.assertIn("0.80", text)
        self.assertIn("/b1", text)
        self.assertIn("/b2", text)
        self.assertIn("investigate", text.lower())
        self.assertIn("held-out", text.lower())

    def test_goodhart_quiet_when_reader_improves(self):
        entries = [lint(0.50, "/d1"), blind(0.20, 0.10, 0.30, "/d1", "/b1"),
                   lint(0.80, "/d2"), blind(0.55, 0.45, 0.65, "/d2", "/b2")]
        self.assertEqual(eh.goodhart(entries), [])

    def test_goodhart_flags_rise_while_readers_get_worse(self):
        entries = [lint(0.50, "/d1"), blind(0.45, 0.35, 0.55, "/d1", "/b1"),
                   lint(0.80, "/d2"), blind(0.15, 0.05, 0.25, "/d2", "/b2")]
        flags = eh.goodhart(entries)
        self.assertEqual(len(flags), 1)
        self.assertIn("worse", flags[0])

    def test_goodhart_null_value_is_a_note_not_a_flag(self):
        entries = [lint(0.50, "/d1"), blind(0.40, 0.25, 0.55, "/d1", "/b1"),
                   lint(0.80, "/d2"), blind(None, 0.0, 1.0, "/d2", "/b2")]
        flags, notes = eh.report(entries)
        self.assertEqual(flags, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("no value", notes[0])

    def test_goodhart_quiet_when_lint_rise_is_small(self):
        entries = [lint(0.50, "/d1"), blind(0.40, 0.25, 0.55, "/d1", "/b1"),
                   lint(0.55, "/d2"), blind(0.42, 0.27, 0.58, "/d2", "/b2")]
        self.assertEqual(eh.goodhart(entries), [])
        self.assertEqual(len(eh.goodhart(entries, lint_jump=0.05)), 1)

    def test_goodhart_pairs_the_lint_entry_by_drafts(self):
        # a lint run on other drafts in between never counts; a pair with no lint entry is a note, not a flag
        entries = [lint(0.50, "/d1"), blind(0.40, 0.25, 0.55, "/d1", "/b1"), lint(0.95, "/other"),
                   blind(0.42, 0.27, 0.58, "/d2", "/b2")]
        flags, notes = eh.report(entries)
        self.assertEqual(flags, [])
        self.assertTrue(any("/d2" in n for n in notes), notes)

    def test_goodhart_reused_folder_pairs_by_file_order(self):
        # one drafts folder linted before each blind run: each run takes the lint measured at or before it
        entries = [lint(0.50, "/drafts"), blind(0.40, 0.25, 0.55, "/drafts", "/b1"),
                   lint(0.80, "/drafts"), blind(0.42, 0.27, 0.58, "/drafts", "/b2")]
        flags, notes = eh.report(entries)
        self.assertEqual(len(flags), 1, notes)
        self.assertIn("0.50 → 0.80", flags[0])
        self.assertEqual(notes, [])

    def test_goodhart_later_relint_never_replaces_the_before_side(self):
        entries = [lint(0.50, "/d1"), blind(0.40, 0.25, 0.55, "/d1", "/b1"),
                   lint(0.80, "/d2"), blind(0.42, 0.27, 0.58, "/d2", "/b2"), lint(0.95, "/d1")]
        flags = eh.goodhart(entries)
        self.assertEqual(len(flags), 1)
        self.assertIn("0.50 → 0.80", flags[0])

    def test_goodhart_lint_after_the_blind_run_is_the_fallback(self):
        # linted after its blind run, before the next one: still that run's measurement
        entries = [blind(0.40, 0.25, 0.55, "/d1", "/b1"), lint(0.50, "/d1"),
                   lint(0.80, "/d2"), blind(0.42, 0.27, 0.58, "/d2", "/b2")]
        self.assertEqual(len(eh.goodhart(entries)), 1)

    def test_goodhart_same_lint_measurement_is_a_note(self):
        entries = [lint(0.50, "/drafts"), blind(0.40, 0.25, 0.55, "/drafts", "/b1"),
                   blind(0.42, 0.27, 0.58, "/drafts", "/b2")]
        flags, notes = eh.report(entries)
        self.assertEqual(flags, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("same lint measurement", notes[0])

    def test_goodhart_compares_within_a_tier(self):
        entries = [lint(0.50, "/d1"), blind(0.40, 0.25, 0.55, "/d1", "/b1"),
                   lint(0.80, "/d2"), blind(0.42, 0.27, 0.58, "/d2", "/b2", tier="tier-1")]
        self.assertEqual(eh.goodhart(entries), [])
        self.assertFalse(eh.enough(entries))


class GoodhartCli(Project):
    def test_goodhart_needs_two_blind_runs(self):
        code, out, err = run_cli("eval", "goodhart")
        self.assertEqual(code, 0, err)
        self.assertIn("not enough history", out)
        eh.append(self.d, lint(0.5, "/d1"))
        eh.append(self.d, blind(0.4, 0.3, 0.5, "/d1", "/b1"))
        code, out, err = run_cli("eval", "goodhart")
        self.assertEqual(code, 0, err)
        self.assertIn("not enough history", out)

    def test_goodhart_cli_flags_exit_1(self):
        path = self.d / "h.jsonl"
        rows = [lint(0.50, "/d1"), blind(0.40, 0.25, 0.55, "/d1", "/b1"),
                lint(0.80, "/d2"), blind(0.42, 0.27, 0.58, "/d2", "/b2")]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        code, out, err = run_cli("eval", "goodhart", "--history", str(path))
        self.assertEqual(code, 1)
        self.assertIn("investigate", out.lower())
        self.assertIn("plainspoken: eval goodhart:", err)
        rows[3] = blind(0.70, 0.60, 0.80, "/d2", "/b2")
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        code, out, err = run_cli("eval", "goodhart", "--history", str(path))
        self.assertEqual(code, 0, err)
        self.assertIn("no flag", out.lower())
        rows[2] = blind(0.45, 0.30, 0.60, "/d1", "/b3")  # /b3 → /b2 can't be compared (no lint on /d2 now)
        rows.append(lint(0.60, "/other"))
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        code, out, err = run_cli("eval", "goodhart", "--history", str(path))
        self.assertEqual(code, 0, err)
        self.assertNotIn("never rose", out)
        self.assertIn("not compared", out)
        self.assertNotIn("0 pairs", out)  # neither pair could be compared, so say that
        self.assertIn("none of the 2 pairs of blind runs could be compared", out)
        code, out, err = run_cli("eval", "goodhart", "--history", str(self.d / "missing.jsonl"))
        self.assertEqual(code, 2)
        self.assertIn("plainspoken: eval goodhart:", err)


class LintRate(Project):
    def test_lint_rate_appends_a_lint_entry(self):
        drafts = self.d / "drafts"
        drafts.mkdir()
        (drafts / "clean.md").write_text("I wrote this on a Tuesday. It was cold, and the kettle took ages.\n",
                                         encoding="utf-8")
        (drafts / "tells.md").write_text("Let's delve into the rich tapestry of this pivotal, robust landscape.\n",
                                         encoding="utf-8")
        code, out, err = run_cli("eval", "lint-rate", "--drafts", str(drafts))
        self.assertEqual(code, 0, err)
        self.assertIn("1 of 2", out)
        self.assertIn("tells.md", out)
        rows = eh.read(self.d)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["kind"], "lint")
        self.assertEqual(row["metric"], eh.LINT_METRIC)
        self.assertEqual(row["value"], 0.5)
        self.assertEqual(row["n"], 2)
        self.assertEqual(row["run"], str(drafts.resolve()))
        self.assertLessEqual(row["ci_low"], 0.5)
        self.assertGreaterEqual(row["ci_high"], 0.5)
        self.assertLessEqual(set(eh.KEYS), set(row))

    def test_lint_rate_recurses_into_model_folders(self):
        drafts = self.d / "drafts"
        for sub, name, text in (("model-a", "clean.md", "I wrote this on a Tuesday. It was cold, and the kettle took "
                                 "ages.\n"),
                                ("model-b", "tells.md", "Let's delve into the rich tapestry of this pivotal, robust "
                                 "landscape.\n")):
            (drafts / sub).mkdir(parents=True)
            (drafts / sub / name).write_text(text, encoding="utf-8")
        code, out, err = run_cli("eval", "lint-rate", "--drafts", str(drafts))
        self.assertEqual(code, 0, err)
        self.assertIn("1 of 2", out)
        self.assertIn("model-b/tells.md", out)

    def test_lint_rate_bad_input_exit_2(self):
        code, _, err = run_cli("eval", "lint-rate", "--drafts", str(self.d / "nope"))
        self.assertEqual(code, 2)
        self.assertIn("plainspoken: eval lint-rate:", err)
        (self.d / "empty").mkdir()
        code, _, err = run_cli("eval", "lint-rate", "--drafts", str(self.d / "empty"))
        self.assertEqual(code, 2)
        self.assertFalse(self.history.exists())

    def test_history_failure_never_changes_the_result(self):
        drafts = self.d / "drafts"
        drafts.mkdir()
        (drafts / "clean.md").write_text("I wrote this on a Tuesday. It was cold, and the kettle took ages.\n",
                                         encoding="utf-8")
        code, out, _ = run_cli("eval", "lint-rate", "--drafts", str(drafts))
        with mock.patch.object(eh, "append", side_effect=OSError("disk full")):
            code2, out2, err2 = run_cli("eval", "lint-rate", "--drafts", str(drafts))
        self.assertEqual((code2, out2), (code, out))
        self.assertEqual(err2.strip().splitlines(), ["plainspoken: eval history skipped: OSError: disk full"])


class StoppedRunNoHistory(Project):
    def test_judges_report_on_a_stopped_run_appends_nothing(self):
        from tests import test_evaljudges as tj

        run = self.d / "run"
        run.mkdir()
        summary = tj.judge_summary(wrong_fails=0)
        summary["run"] = {"id": "run", "stopped": "budget: US$5.00 reached"}
        (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (run / "run.json").write_text(json.dumps({"models": ["grok"]}), encoding="utf-8")
        code, out, err = run_cli("eval", "judges-report", "--run", str(run))
        self.assertEqual(code, 0, err)
        self.assertIn("stopped early", err)
        self.assertEqual(eh.read(self.d), [])


class SummaryWritesHistory(Project):
    def test_summary_writes_history(self):
        from tests import test_blind as tb
        from tests import test_evaljudges as tj

        # judges-report: one line per model, the share of groups meeting the bar
        run = self.d / "run"
        run.mkdir()
        summary = tj.judge_summary(wrong_fails=0)
        (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (run / "run.json").write_text(json.dumps({"models": ["grok"]}), encoding="utf-8")
        code, _, err = run_cli("eval", "judges-report", "--run", str(run))
        self.assertEqual(code, 0, err)
        rows = eh.read(self.d)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "judges")
        self.assertEqual(rows[0]["metric"], eh.JUDGES_METRIC)
        self.assertEqual(rows[0]["model"], "grok")
        self.assertEqual(rows[0]["value"], 1.0)
        self.assertEqual(rows[0]["run"], str(run.resolve()))
        self.assertIsNone(rows[0]["ci_low"])

        # blind score: one line for the panel's tier, with the generated drafts' folder
        src = self.d / "src"
        src.mkdir()
        gen = self.d / "gen"
        gen.mkdir()
        spec = []
        for i in range(2):
            (src / f"h{i}.md").write_text(tb.prose(i, 12), encoding="utf-8")
            (gen / f"g{i}.md").write_text(tb.prose(i + 10, 12), encoding="utf-8")
            spec.append({"id": f"case-{i}", "human": str(src / f"h{i}.md"), "generated": str(gen / f"g{i}.md"),
                         "model": "m"})
        (self.d / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        out = self.d / "blind"
        code, _, err = run_cli("eval", "blind", "build", "--spec", str(self.d / "spec.json"), "--out", str(out),
                               "--words", "60", "--seed", "3")
        self.assertEqual(code, 0, err)
        key = json.loads((out / "key.json").read_text(encoding="utf-8"))
        answers = self.d / "answers.csv"
        answers.write_text("rater,pair,human,better\n" + "".join(f"ann,{p},{k['human']},a\n" for p, k in key.items()),
                           encoding="utf-8")
        code, _, err = run_cli("eval", "blind", "score", "--out", str(out), "--answers", str(answers))
        self.assertEqual(code, 0, err)
        rows = eh.read(self.d)
        self.assertEqual(len(rows), 2)
        b = rows[1]
        self.assertEqual(b["kind"], "blind")
        self.assertEqual(b["metric"], eh.BLIND_METRIC)
        self.assertEqual(b["tier"], "tier-1")
        self.assertEqual(b["value"], 0.0)  # the rater found the person every time
        self.assertEqual(b["n"], 2)
        self.assertEqual(b["drafts"], str(gen.resolve()))
        self.assertEqual(b["run"], str(out.resolve()))
        self.assertIsNotNone(b["ci_high"])
        for r in rows:
            self.assertEqual(r["plugin_version"], json.loads((REPO / ".claude-plugin" / "plugin.json")
                                                             .read_text(encoding="utf-8"))["version"])
            self.assertIsInstance(r["ruleset_version"], str)

    def test_relative_spec_records_the_real_drafts_folder(self):
        """A relative --spec with relative paths in it: the history's drafts folder is where the generated texts
        are, wherever the score is run from."""
        from tests import test_blind as tb

        (self.d / "specs").mkdir()
        gen = self.d / "gen"
        gen.mkdir()
        spec = []
        for i in range(2):
            (self.d / "specs" / f"h{i}.md").write_text(tb.prose(i, 12), encoding="utf-8")
            (gen / f"g{i}.md").write_text(tb.prose(i + 10, 12), encoding="utf-8")
            spec.append({"id": f"case-{i}", "human": f"h{i}.md", "generated": f"../gen/g{i}.md", "model": "m"})
        (self.d / "specs" / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        code, _, err = run_cli("eval", "blind", "build", "--spec", "specs/spec.json", "--out", "blind", "--words",
                               "60", "--seed", "3")
        self.assertEqual(code, 0, err)
        key = json.loads((self.d / "blind" / "key.json").read_text(encoding="utf-8"))
        answers = self.d / "answers.csv"
        answers.write_text("rater,pair,human,better\n" + "".join(f"ann,{p},{k['human']},a\n" for p, k in key.items()),
                           encoding="utf-8")
        (self.d / "elsewhere").mkdir()
        os.chdir(self.d / "elsewhere")  # the same project, another folder
        code, _, err = run_cli("eval", "blind", "score", "--out", str(self.d / "blind"), "--answers", str(answers))
        self.assertEqual(code, 0, err)
        (b,) = eh.read(self.d)
        self.assertEqual(b["drafts"], str(gen.resolve()))


if __name__ == "__main__":
    unittest.main()
