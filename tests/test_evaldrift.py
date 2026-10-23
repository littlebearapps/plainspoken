"""Model drift (plan 8.4): `eval drift` between two judge runs, `eval trigger-record` and `eval trigger-estimate`.
Free and offline: every run folder and result file here is built from fixtures; no model is called."""
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plainspoken import __main__ as cli_main
from plainspoken import evaldrift as ed
from plainspoken import evalhistory as eh
from plainspoken import evalmetrics as em
from plainspoken import evaltriggers as et

REPO = Path(__file__).resolve().parents[1]
TRIGGER = REPO / "tests" / "fixtures" / "evals" / "trigger-result.json"


def run_cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def row(tp: int, fn: int, tn: int, fp: int) -> dict:
    conf = {"tp": tp, "fn": fn, "tn": tn, "fp": fp, "errors": 0, "n": tp + fn + tn + fp}
    return {**conf, "missing": 0, "error_rate": 0.0, **em.rates(conf)}


def split(models: dict, majority: dict | None = None, proxy: bool = False) -> dict:
    return {"cases": 40, "labels": {"fail": 20, "pass": 20}, "provisional": 3 if proxy else 0, "proxy": proxy,
            "models": models, "majority": majority or {}, "kappa": None}


def summary(groups: dict, ids: dict, *, run_id: str, sha: str = "a" * 64, stopped=None) -> dict:
    """A judge-validation summary in the shape `evaljudges.score` writes. `ids`: name → (asked for, answered as)."""
    return {"schema": 1, "models": [{"name": n, "vendor": "v", "transport": "openrouter", "model_requested": a,
                                     "billed": True, "groups": None, "model_reported": r, "providers": {},
                                     "anthropic": False} for n, (a, r) in ids.items()],
            "groups": {g: {"positive": "fail", "negative": "pass", "splits": {"all": s, "human": split({})}}
                       for g, s in groups.items()},
            "rules": {}, "errors": {}, "cost": {"billed_usd": 0.0, "notional_usd": 0.0, "models": {}}, "sampling": {},
            "run": {"id": run_id, "dir": f"/runs/{run_id}", "started": "2026-10-01T00:00:00Z",
                    "scored": "2026-10-01T00:05:00Z", "golden_sha256": sha, "golden_cases": 80,
                    "filters": {"group": None, "status": None}, "stopped": stopped, "max_cost_usd": 5.0}}


def old_summary() -> dict:
    return summary({"J1": split({"glm": row(19, 1, 20, 0), "openai": row(19, 1, 19, 1)},
                                {"non-Anthropic models": row(19, 1, 20, 0)}),
                    "J2": split({"glm": row(20, 0, 20, 0), "openai": row(18, 2, 20, 0)})},
                   {"glm": ("z-ai/glm-5", "z-ai/glm-5"), "openai": ("openai/gpt-6", "openai/gpt-6")},
                   run_id="judges-old")


def new_summary() -> dict:
    # glm J1 TPR 0.95 → 0.40: a drop. openai J1 TPR 0.95 → 0.82-ish: overlapping intervals, no flag.
    # openai's model id changed. J2 is gone, J3 is new.
    return summary({"J1": split({"glm": row(8, 12, 20, 0), "openai": row(16, 4, 20, 0)},
                                {"non-Anthropic models": row(15, 5, 20, 0)}),
                    "J3": split({"glm": row(20, 0, 20, 0), "openai": row(20, 0, 20, 0)})},
                   {"glm": ("z-ai/glm-5", "z-ai/glm-5"), "openai": ("openai/gpt-6.1", "openai/gpt-6.1")},
                   run_id="judges-new")


def write_run(folder: Path, s: dict, model_ids: dict | None = None) -> Path:
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text(json.dumps(s), encoding="utf-8")
    if model_ids is not None:
        (folder / "run.json").write_text(json.dumps({"schema": 1, "model_ids": model_ids}), encoding="utf-8")
    return folder


class Project(unittest.TestCase):
    """A temp project as the working folder, so the history lands in it."""

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

    def runs(self) -> tuple[Path, Path]:
        return (write_run(self.d / "judges-new", new_summary()), write_run(self.d / "judges-old", old_summary()))


class Change(unittest.TestCase):
    def test_intervals(self):
        self.assertEqual(ed.change([0.7, 0.9], [0.2, 0.6]), "drop")
        self.assertEqual(ed.change([0.2, 0.6], [0.7, 0.9]), "rise")
        self.assertEqual(ed.change([0.7, 0.9], [0.6, 0.75]), "overlap")
        self.assertEqual(ed.change(None, [0.6, 0.75]), "n/a")


class Compare(Project):
    def compare(self, new=None, old=None, split_name="all") -> dict:
        n = write_run(self.d / "n", new or new_summary())
        o = write_run(self.d / "o", old or old_summary())
        return ed.compare(ed.load(n), ed.load(o), split_name)

    def test_drop_whose_intervals_dont_overlap_is_flagged(self):
        d = self.compare()
        drops = [f for f in d["flags"] if f["type"] == "drop"]
        self.assertEqual([(f["group"], f["judge"], f["metric"]) for f in drops], [("J1", "glm", "tpr")])
        self.assertIn("0.95", drops[0]["text"])
        self.assertIn("0.40", drops[0]["text"])

    def test_overlapping_fall_is_shown_but_not_flagged(self):
        d = self.compare()
        r = next(r for r in d["rows"] if (r["group"], r["judge"], r["metric"]) == ("J1", "openai", "tpr"))
        self.assertEqual(r["change"], "overlap")
        self.assertAlmostEqual(r["old"]["value"], 0.95)
        self.assertAlmostEqual(r["new"]["value"], 0.80)

    def test_majority_rows_are_compared(self):
        d = self.compare()
        judges = {r["judge"] for r in d["rows"]}
        self.assertIn("majority: non-Anthropic models", judges)

    def test_model_id_change_is_flagged(self):
        d = self.compare()
        changed = [f for f in d["flags"] if f["type"] == "model_changed"]
        self.assertEqual([f["judge"] for f in changed], ["openai"])
        self.assertIn("asked for openai/gpt-6 → openai/gpt-6.1", changed[0]["text"])
        self.assertIn("answered as openai/gpt-6 → openai/gpt-6.1", changed[0]["text"])

    def test_not_reported_is_not_a_change(self):
        new = old_summary()
        new["models"][0]["model_reported"] = ""
        d = self.compare(new=new)
        self.assertEqual([f for f in d["flags"] if f["type"] == "model_changed"], [])

    def test_model_ids_from_run_json_when_the_summary_lacks_them(self):
        s = old_summary()
        for m in s["models"]:
            m["model_requested"] = None
        run = ed.load(write_run(self.d / "r", s, model_ids={"glm": "z-ai/glm-5", "openai": "openai/gpt-6"}))
        self.assertEqual(run["models"]["openai"]["requested"], "openai/gpt-6")

    def test_group_on_one_side_is_flagged(self):
        d = self.compare()
        missing = sorted((f["group"], f["text"]) for f in d["flags"] if f["type"] == "missing_group")
        self.assertEqual([g for g, _ in missing], ["J2", "J3"])
        self.assertIn("only in the old run", dict(missing)["J2"])
        self.assertIn("only in the new run", dict(missing)["J3"])

    def test_judge_on_one_side_is_a_note(self):
        new = new_summary()
        new["groups"]["J1"]["splits"]["all"]["models"]["gemini"] = row(20, 0, 20, 0)
        d = self.compare(new=new)
        self.assertTrue(any("J1 · gemini: only in the new run" in n for n in d["notes"]))
        self.assertFalse(any(f.get("judge") == "gemini" for f in d["flags"]))

    def test_notes_golden_stopped_and_proxy(self):
        new = new_summary()
        new["run"]["golden_sha256"] = "b" * 64
        new["run"]["stopped"] = "budget"
        new["groups"]["J1"]["splits"]["all"]["proxy"] = True
        notes = " | ".join(self.compare(new=new)["notes"])
        self.assertIn("golden set changed", notes)
        self.assertIn("new run stopped early (budget)", notes)
        self.assertIn("J1: provisional labels", notes)

    def test_no_cases_is_na_not_a_drop(self):
        new = new_summary()
        new["groups"]["J1"]["splits"]["all"]["models"]["glm"] = row(0, 0, 20, 0)
        d = self.compare(new=new)
        r = next(r for r in d["rows"] if (r["group"], r["judge"], r["metric"]) == ("J1", "glm", "tpr"))
        self.assertEqual(r["change"], "n/a")

    def test_identical_runs_have_no_flags(self):
        d = self.compare(new=old_summary())
        self.assertEqual(d["flags"], [])
        self.assertTrue(all(r["change"] == "overlap" for r in d["rows"]))

    def test_bad_split_and_unreadable_run(self):
        with self.assertRaises(ed.DriftError):
            self.compare(split_name="nope")
        (self.d / "empty").mkdir()
        with self.assertRaises(ed.DriftError):
            ed.load(self.d / "empty")

    def test_render(self):
        text = ed.render(self.compare())
        self.assertIn("# Judge drift: judges-new against judges-old", text)
        self.assertIn("## Flags (4)", text)
        self.assertIn("| J1 | glm | TPR | 0.95 [", text)
        self.assertIn("| drop |", text)


class DriftCli(Project):
    def test_report_exit_0_and_writes_nothing(self):
        new, old = self.runs()
        before = sorted(p.relative_to(self.d) for p in self.d.rglob("*"))
        code, out, err = run_cli("eval", "drift", "--run", str(new), "--against", str(old))
        self.assertEqual(code, 0, err)
        self.assertIn("## Flags (4)", out)
        self.assertEqual(sorted(p.relative_to(self.d) for p in self.d.rglob("*")), before)

    def test_fail_on_drift(self):
        new, old = self.runs()
        code, _, err = run_cli("eval", "drift", "--run", str(new), "--against", str(old), "--fail-on-drift")
        self.assertEqual(code, 1)
        self.assertIn("4 flags", err)
        code, _, _ = run_cli("eval", "drift", "--run", str(old), "--against", str(old), "--fail-on-drift")
        self.assertEqual(code, 0)

    def test_json(self):
        new, old = self.runs()
        code, out, _ = run_cli("eval", "drift", "--run", str(new), "--against", str(old), "--json")
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["split"], "all")
        self.assertEqual(len(d["flags"]), 4)

    def test_missing_or_unreadable_run_exits_2(self):
        new, _ = self.runs()
        code, _, err = run_cli("eval", "drift", "--run", str(new), "--against", str(self.d / "nope"))
        self.assertEqual(code, 2)
        self.assertIn("no such run folder", err)
        (self.d / "bad").mkdir()
        (self.d / "bad" / "summary.json").write_text("{not json", encoding="utf-8")
        code, _, err = run_cli("eval", "drift", "--run", str(new), "--against", str(self.d / "bad"))
        self.assertEqual(code, 2)
        self.assertIn("no readable judge-validation summary", err)


def trigger_result() -> dict:
    return json.loads(TRIGGER.read_text(encoding="utf-8"))


class Summarise(unittest.TestCase):
    def test_fixture(self):
        t = et.summarise(trigger_result())
        self.assertEqual((t["passed"], t["runs"], t["case_count"], t["runs_per_case"]), (10, 12, 4, 3))
        self.assertEqual(t["cases"]["check--sounds-like-ai"], {"passed": 1, "runs": 3})
        self.assertAlmostEqual(t["cost_per_run"], t["cost_usd"] / 12, places=5)
        self.assertAlmostEqual(t["cost_per_case"], t["cost_usd"] / 4, places=5)
        self.assertEqual(t["claude_version"], "2.1.303")
        self.assertEqual(t["plugin_version"], "0.7.0")
        self.assertIsNone(t["model"])
        lo, hi = t["ci"]
        self.assertLess(lo, 10 / 12)
        self.assertGreater(hi, 10 / 12)

    def test_other_suite_or_not_a_result(self):
        smoke = trigger_result()
        smoke["suite"]["tagFilters"] = ["smoke"]
        with self.assertRaisesRegex(et.TriggerError, "not a trigger-suite run"):
            et.summarise(smoke)
        for bad in ([], {"cases": []}, {"suite": {}, "cases": [{"arms": {}}]},
                    {"suite": {"tagFilters": ["trigger"]}, "cases": [{"name": "x", "arms": {"with": 3}}]}):
            with self.assertRaises(et.TriggerError):
                et.summarise(bad)

    def test_count_cases(self):
        self.assertEqual(et.count_cases(), len(list((REPO / "evals" / "triggers").glob("*/prompt.md"))))
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a", "b"):
                (Path(tmp) / name).mkdir()
                (Path(tmp) / name / "prompt.md").write_text("x", encoding="utf-8")
            (Path(tmp) / "no-prompt").mkdir()
            self.assertEqual(et.count_cases(Path(tmp)), 2)

    def test_estimate(self):
        self.assertAlmostEqual(et.estimate({"cost_per_run": 0.1}, 42, 1), 4.2)
        self.assertAlmostEqual(et.estimate({"cost_per_run": 0.1}, 42, 3), 12.6)
        self.assertIsNone(et.estimate({"cost_per_run": None}, 42, 1))


def entry_from(result: dict, model: str | None = "m-1") -> dict:
    return eh.trigger_entry(et.summarise(result), "/r.json", model=model, ruleset_version="1", plugin_version="0")


class TriggerCompare(unittest.TestCase):
    def test_same_run_no_flags(self):
        e = entry_from(trigger_result())
        flags, lines = et.compare(e, e)
        self.assertEqual(flags, [])
        self.assertIn("(overlap)", lines[0])

    def test_drop_cli_and_model_change_and_case_lines(self):
        old = entry_from(trigger_result())
        worse = trigger_result()
        worse["claudeVersion"] = "2.1.310"
        for c in worse["cases"]:
            for r in c["arms"]["with"]:
                r["passed"] = c["name"] == "adapt--natural"
        new = entry_from(worse, model="m-2")
        flags, lines = et.compare(old, new)
        text = "\n".join(flags)
        self.assertIn("the pass rate dropped", text)
        self.assertIn("CLI version changed: 2.1.303 → 2.1.310", text)
        self.assertIn("model changed: m-1 → m-2", text)
        self.assertTrue(any("humanize--de-ai: 3/3 → 0/3" in line for line in lines))
        self.assertFalse(any("adapt--natural" in line for line in lines))

    def test_case_set_change(self):
        old = entry_from(trigger_result())
        fewer = trigger_result()
        fewer["cases"] = fewer["cases"][:3]
        _, lines = et.compare(old, entry_from(fewer))
        self.assertIn("cases: 0 new, 1 no longer run", lines[-1])


class HistoryKind(Project):
    def test_triggers_entry_is_a_valid_history_line(self):
        e = entry_from(trigger_result())
        eh.append(self.d, e)
        got = eh.read(self.d)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["kind"], "triggers")
        self.assertEqual(got[0]["metric"], eh.TRIGGER_METRIC)
        self.assertEqual(got[0]["cases"]["check--sounds-like-ai"], {"passed": 1, "runs": 3})
        self.assertTrue(eh.trigger_recorded(got, e))
        self.assertIs(eh.last_trigger(got), got[0])

    def test_goodhart_ignores_trigger_lines(self):
        eh.append(self.d, entry_from(trigger_result()))
        code, out, _ = run_cli("eval", "goodhart")
        self.assertEqual(code, 0)
        self.assertIn("not enough history", out)


class TriggerCli(Project):
    def result(self, data: dict | None = None, name: str = "r.json") -> Path:
        p = self.d / name
        p.write_text(json.dumps(data or trigger_result()), encoding="utf-8")
        return p

    def test_record_once_then_already_there(self):
        r = self.result()
        code, out, err = run_cli("eval", "trigger-record", str(r), "--model", "claude-opus-5-5")
        self.assertEqual(code, 0, err)
        self.assertIn("10 of 12 runs passed", out)
        self.assertIn("no earlier trigger run", out)
        lines = eh.read(self.d)
        self.assertEqual([e["model"] for e in lines], ["claude-opus-5-5"])
        self.assertEqual(lines[0]["claude_version"], "2.1.303")
        code, out, _ = run_cli("eval", "trigger-record", str(r), "--model", "claude-opus-5-5")
        self.assertEqual(code, 0)
        self.assertIn("already in the eval history", out)
        self.assertEqual(len(eh.read(self.d)), 1)

    def test_second_run_is_compared_with_the_first(self):
        run_cli("eval", "trigger-record", str(self.result()), "--model", "m-1")
        later = trigger_result()
        later["startedAt"] = "2026-11-04T00:00:00.000Z"
        later["claudeVersion"] = "2.1.320"
        code, out, _ = run_cli("eval", "trigger-record", str(self.result(later, "r2.json")), "--model", "m-1")
        self.assertEqual(code, 0)
        self.assertIn("flag: CLI version changed: 2.1.303 → 2.1.320", out)
        self.assertNotIn("flag: model changed", out)
        self.assertEqual(len(eh.read(self.d)), 2)

    def test_partial_run_not_recorded(self):
        partial = trigger_result()
        partial["partial"] = True
        code, _, err = run_cli("eval", "trigger-record", str(self.result(partial)))
        self.assertEqual(code, 1)
        self.assertIn("partial run", err)
        self.assertFalse(self.history.exists())

    def test_bad_files_exit_2(self):
        smoke = trigger_result()
        smoke["suite"]["tagFilters"] = ["smoke"]
        code, _, err = run_cli("eval", "trigger-record", str(self.result(smoke)))
        self.assertEqual(code, 2)
        self.assertIn("not a trigger-suite run", err)
        code, _, _ = run_cli("eval", "trigger-record", str(self.d / "missing.json"))
        self.assertEqual(code, 2)
        self.assertFalse(self.history.exists())

    def test_estimate_after_record(self):
        code, out, _ = run_cli("eval", "trigger-estimate")
        self.assertEqual(code, 1)
        self.assertIn("no trigger run with a cost recorded", out)
        run_cli("eval", "trigger-record", str(self.result()), "--model", "m-1")
        per = eh.read(self.d)[0]["cost_per_run"]
        code, out, _ = run_cli("eval", "trigger-estimate", "--cases", "42")
        self.assertEqual(code, 0)
        self.assertIn(f"about US${per * 42:.2f} for 42 cases × 1 run", out)
        code, out, _ = run_cli("eval", "trigger-estimate", "--runs", "3")
        self.assertIn(f"for {et.count_cases()} cases × 3 runs", out)
        self.assertEqual(run_cli("eval", "trigger-estimate", "--runs", "0")[0], 2)
        self.assertEqual(run_cli("eval", "trigger-estimate", "--history", str(self.d / "nope.jsonl"))[0], 2)

    def test_estimate_reads_a_given_history_file(self):
        other = self.d / "elsewhere"
        other.mkdir()
        eh.append(other, copy.deepcopy(entry_from(trigger_result())))
        code, out, _ = run_cli("eval", "trigger-estimate", "--cases", "10", "--history", str(eh.path(other)))
        self.assertEqual(code, 0)
        self.assertIn("for 10 cases", out)
        self.assertIn("model m-1", out)


if __name__ == "__main__":
    unittest.main()
