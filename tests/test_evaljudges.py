"""Judge validation runs: golden set × panel → replies → metrics report (Phase 6). Fakes only: no test
touches the network or spawns `claude`."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plainspoken import __main__ as cli_main
from plainspoken import evaljudges, golden
from plainspoken.adapters import llm_panel as lp

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "golden"

OPUS = lp.PanelModel("claude-opus", "Anthropic", "claude-cli", "claude-opus-5-5", 0.0, 0.0)
GROK = lp.PanelModel("grok", "xAI", "openrouter", "x-ai/grok-test", 2.0, 10.0)
KIMI = lp.PanelModel("kimi", "Moonshot", "openrouter", "moonshotai/kimi-test", 1.0, 1.0)
KEY = "sk-or-v1-UNIQUESECRET0123456789"
REPORTED = {"claude-opus": "claude-opus-5-5-20261001", "grok": "x-ai/grok-test-0915", "kimi": "moonshotai/kimi-0901"}

PANEL = """max_out_tokens = 800

[gateway]
transport = "openrouter"
base_url = "https://openrouter.test/api/v1"
key_env = "OPENROUTER_API_KEY"

[[model]]
name = "claude-opus"
vendor = "Anthropic"
transport = "claude-cli"
model = "claude-opus-5-5"
price_in = 0
price_out = 0

[[model]]
name = "grok"
vendor = "xAI"
model = "x-ai/grok-test"
price_in = 2.0
price_out = 10.0
"""


def gcase(cid: str, label: str, status: str = "provisional", rule: str | None = None) -> golden.GoldenCase:
    group = cid.split("-")[0]
    extra = {"kind": "format", "reason": "a heading list", "evidence": ({"line": 1, "quote": "Line"},)} \
        if group == "JR" else {}
    return golden.GoldenCase(id=cid, group=group, rule=rule or cid.split("-")[1], label=label, text="Line one.\n",
                             content_type="article", source=golden.SOURCE_FOR_STATUS[status], status=status,
                             origin="test case", **extra)


def verdict_text(case: golden.GoldenCase, label: str) -> str:
    return json.dumps({"group": case.group, "article_sha256": "x",
                       "verdicts": [{"rule": case.rule, "verdict": label, "severity": "WARN", "evidence": []}]})


def reply(case, model: lp.PanelModel, label: str | None = None, *, text: str | None = None, error: str | None = None,
          cost: float = 0.0) -> lp.Reply:
    body = text if text is not None else (verdict_text(case, label) if label else "")
    return lp.Reply(key=f"{case.id}|{model.name}", name=model.name, model_requested=model.model,
                    model_reported="" if error else REPORTED[model.name], text=body, in_tokens=10, out_tokens=5,
                    cost_usd=cost, billed=model.billed, at="2026-10-16T01:02:03Z", error=error)


def replies_for(cases, model, labels) -> dict:
    return {f"{c.id}|{model.name}": reply(c, model, lab) for c, lab in zip(cases, labels)}


def flip(label: str) -> str:
    return {"fail": "pass", "pass": "fail", "accept": "reject", "reject": "accept"}[label]


class TestJobs(unittest.TestCase):
    def test_jobs_one_per_case_model(self):
        cases = golden.load(FIX)
        with tempfile.TemporaryDirectory() as d:
            work = Path(d) / "work"
            jobs = evaljudges.jobs(cases, [OPUS, GROK], work)
            self.assertEqual(len(jobs), len(cases) * 2)
            self.assertEqual([k for k, _, _ in jobs][:2], [f"{cases[0].id}|claude-opus", f"{cases[0].id}|grok"])
            self.assertEqual(len({k for k, _, _ in jobs}), len(jobs))
            by_key = {k: (m, p) for k, m, p in jobs}
            self.assertIs(by_key["J1-5b-001|grok"][0], GROK)
            self.assertIn("## How every judge works", by_key["J1-5b-001|grok"][1])
            self.assertIn("## JR Justification review", by_key["JR-format-001|claude-opus"][1])
            self.assertEqual(by_key["J1-5b-001|grok"][1], by_key["J1-5b-001|claude-opus"][1])  # same prompt
            for _, _, p in jobs:
                self.assertNotIn('"label"', p)
            self.assertTrue(work.is_dir())  # the lint's temp files live under the given folder


class TestGroupLimits(unittest.TestCase):
    """A panel model may judge only some groups (`groups = [...]` in the panel): it gets no jobs for the others, and
    the score and accept bar treat those groups as not its job, never as errors or misses."""
    J_ONLY = lp.PanelModel("openai", "OpenAI", "openrouter", "openai/gpt-test", 0.1, 0.5, None,
                           ("J1", "J2", "J3", "J4"))

    def test_jobs_skip_groups_the_model_does_not_judge(self):
        cases = golden.load(FIX)
        with tempfile.TemporaryDirectory() as d:
            keys = [k for k, _, _ in evaljudges.jobs(cases, [GROK, self.J_ONLY], Path(d) / "work")]
        jr = [c.id for c in cases if c.group == "JR"]
        self.assertTrue(jr)
        for cid in jr:
            self.assertIn(f"{cid}|grok", keys)
            self.assertNotIn(f"{cid}|openai", keys)
        self.assertEqual(len(keys), 2 * len(cases) - len(jr))

    def test_score_and_accept_leave_unjudged_groups_out(self):
        cases = golden.load(FIX)
        replies = {}
        for c in cases:
            for m in (GROK, self.J_ONLY):
                if m.groups and c.group not in m.groups:
                    continue
                key = evaljudges.job_key(c.id, m.name)
                replies[key] = lp.Reply(key, m.name, m.model, m.model, verdict_text(c, c.label), 10, 10, 0.0, True,
                                        "2026-10-17T00:00:00Z", None)
        s = evaljudges.score(cases, replies, [GROK, self.J_ONLY])
        self.assertNotIn("openai", s["groups"]["JR"]["splits"]["all"]["models"])
        self.assertIn("openai", s["groups"]["J1"]["splits"]["all"]["models"])
        self.assertNotIn("openai", s["errors"])
        rows = {(r["group"], r["model"]): r for r in evaljudges.accept(s)}
        self.assertTrue(rows[("JR", "openai")]["ok"])
        self.assertIn("doesn't judge JR", rows[("JR", "openai")]["why"])
        self.assertTrue(rows[("J1", "openai")]["ok"])
        self.assertIn("doesn't judge JR", evaljudges.render(s))


class TestScore(unittest.TestCase):
    def setUp(self):
        self.human = [gcase("J1-5b-001", "fail", "confirmed"), gcase("J1-5b-002", "fail", "endorsed"),
                      gcase("J1-5b-003", "pass", "confirmed"), gcase("J1-5b-004", "pass", "endorsed")]
        self.prov = [gcase("J1-5b-005", "fail"), gcase("J1-5b-006", "fail")]
        self.cases = self.human + self.prov

    def test_score_split_human_vs_all(self):
        labels = [c.label for c in self.human] + ["pass", "pass"]  # right on the human cases, wrong on the rest
        s = evaljudges.score(self.cases, replies_for(self.cases, GROK, labels), models=[GROK])
        g = s["groups"]["J1"]
        self.assertEqual(g["positive"], "fail")
        alls, human = g["splits"]["all"], g["splits"]["human"]
        self.assertEqual((alls["cases"], alls["provisional"], alls["proxy"]), (6, 2, True))
        self.assertEqual((human["cases"], human["provisional"], human["proxy"]), (4, 0, False))
        row = alls["models"]["grok"]
        self.assertEqual((row["tp"], row["fn"], row["tn"], row["fp"], row["errors"], row["n"]), (2, 2, 2, 0, 0, 6))
        self.assertAlmostEqual(row["tpr"]["value"], 0.5)
        self.assertAlmostEqual(human["models"]["grok"]["tpr"]["value"], 1.0)
        self.assertAlmostEqual(human["models"]["grok"]["tnr"]["value"], 1.0)
        rule = s["rules"]["J1"]["5b"]["all"]["grok"]
        self.assertEqual(rule["n"], 6)
        self.assertEqual(s["models"][0]["model_reported"], REPORTED["grok"])

    def test_score_errors_column(self):
        c1, c2, c3 = self.human[:3]
        rs = {f"{c1.id}|grok": reply(c1, GROK, error="OpenRouter HTTP 503: busy"),
              f"{c2.id}|grok": reply(c2, GROK, text="I think it fails."),
              f"{c3.id}|grok": reply(c3, GROK, "pass")}
        s = evaljudges.score([c1, c2, c3], rs, models=[GROK])
        row = s["groups"]["J1"]["splits"]["all"]["models"]["grok"]
        self.assertEqual((row["errors"], row["n"], row["tn"], row["tp"], row["fn"]), (2, 3, 1, 0, 0))
        self.assertAlmostEqual(row["error_rate"], 2 / 3)
        reasons = s["errors"]["grok"]
        self.assertEqual(reasons.get("not one JSON object"), 1)
        self.assertTrue(any("503" in r for r in reasons))

    def test_score_missing_is_not_an_error(self):
        s = evaljudges.score(self.human, replies_for(self.human[:2], GROK, ["fail", "fail"]), models=[GROK, KIMI])
        grok = s["groups"]["J1"]["splits"]["all"]["models"]["grok"]
        kimi = s["groups"]["J1"]["splits"]["all"]["models"]["kimi"]
        self.assertEqual((grok["n"], grok["missing"], grok["errors"]), (2, 2, 0))
        self.assertEqual((kimi["n"], kimi["missing"]), (0, 4))
        names = {m["name"]: m for m in s["models"]}
        self.assertIsNone(names["kimi"]["model_reported"])

    def test_score_majority_rows(self):
        c = self.human  # truths: fail fail pass pass
        rs = {}
        rs.update(replies_for(c, OPUS, ["fail", "fail", "pass", "pass"]))
        rs.update(replies_for(c, GROK, ["fail", "pass", "pass", "fail"]))
        rs.update(replies_for(c, KIMI, ["pass", "pass", "pass", "pass"]))
        s = evaljudges.score(c, rs, models=[OPUS, GROK, KIMI])
        maj = s["groups"]["J1"]["splits"]["all"]["majority"]
        self.assertEqual(set(maj), {"all models", "non-Anthropic models"})
        every = maj["all models"]  # votes: f/f/p → fail · f/p/p → pass · p/p/p → pass · p/f/p → pass
        self.assertEqual((every["tp"], every["fn"], every["tn"], every["fp"], every["errors"]), (1, 1, 2, 0, 0))
        non = maj["non-Anthropic models"]  # f/p tie · p/p · p/p · f/p tie
        self.assertEqual((non["tp"], non["fn"], non["tn"], non["fp"], non["errors"]), (0, 1, 1, 0, 2))
        kappa = s["groups"]["J1"]["splits"]["all"]["kappa"]
        self.assertEqual((kappa["models"], kappa["cases"]), (3, 4))
        self.assertIsInstance(kappa["value"], float)

    def test_score_majority_needs_two_models(self):
        s = evaljudges.score(self.human, replies_for(self.human, GROK, [c.label for c in self.human]), models=[GROK])
        self.assertEqual(s["groups"]["J1"]["splits"]["all"]["majority"], {})
        self.assertIsNone(s["groups"]["J1"]["splits"]["all"]["kappa"])

    def test_score_jr_positive_is_reject(self):
        cases = [gcase("JR-format-001", "reject", "confirmed", rule="12e"),
                 gcase("JR-format-002", "accept", "confirmed", rule="12e")]
        s = evaljudges.score(cases, replies_for(cases, GROK, ["reject", "reject"]), models=[GROK])
        g = s["groups"]["JR"]
        self.assertEqual(g["positive"], "reject")
        row = g["splits"]["all"]["models"]["grok"]
        self.assertEqual((row["tp"], row["fp"]), (1, 1))

    def test_models_derived_from_replies(self):
        s = evaljudges.score(self.human, replies_for(self.human, GROK, [c.label for c in self.human]))
        self.assertEqual([m["name"] for m in s["models"]], ["grok"])


class TestFollowUpsT4Score(unittest.TestCase):
    """Judges: scoring."""

    def setUp(self):
        self.cases = [gcase("J1-5b-001", "fail"), gcase("J1-5b-002", "fail"), gcase("J1-5b-003", "pass"),
                      gcase("J1-5b-004", "pass")]

    def test_majority_counts_an_all_missing_case_as_missing(self):
        rs = {**replies_for(self.cases[:2], GROK, ["fail", "fail"]),
              **replies_for(self.cases[:2], KIMI, ["fail", "fail"])}
        rs.update(replies_for(self.cases[2:3], GROK, ["pass"]))  # one voter is enough to stay out of "missing"
        s = evaljudges.score(self.cases, rs, models=[GROK, KIMI])
        row = s["groups"]["J1"]["splits"]["all"]["majority"]["all models"]
        self.assertEqual((row["tp"], row["tn"], row["errors"], row["missing"], row["n"]), (2, 1, 0, 1, 3))

    def test_cost_is_set_once_from_the_calls_given(self):
        rs = replies_for(self.cases, GROK, ["fail", "fail", "pass", "pass"])
        rs = {k: lp.Reply(**{**r.__dict__, "cost_usd": 0.01}) for k, r in rs.items()}
        s = evaljudges.score(self.cases, rs, models=[GROK])
        self.assertAlmostEqual(s["cost"]["billed_usd"], 0.04)
        retried = [*rs.values(), lp.Reply(**{**next(iter(rs.values())).__dict__, "cost_usd": 0.5})]
        s = evaljudges.score(self.cases, rs, models=[GROK], calls=retried)
        self.assertAlmostEqual(s["cost"]["billed_usd"], 0.54)
        self.assertEqual(s["cost"]["models"]["grok"]["calls"], 5)


def judge_summary(*, wrong_fails: int = 0, models=(GROK,), provisional: bool = True) -> dict:
    """A scored judge-validation summary for 20 J1 cases (10 confirmed fails, 10 passes), each model wrong on the
    first `wrong_fails` cases; kimi is listed but never ran. Shared with the history tests."""
    cases = [gcase(f"J1-5b-{i:03d}", "fail", "confirmed") for i in range(1, 11)]
    cases += [gcase(f"J1-5b-{i:03d}", "pass", "provisional" if provisional else "endorsed")
              for i in range(11, 21)]
    rs = {}
    for m in models:
        labels = [flip(c.label) if i < wrong_fails else c.label for i, c in enumerate(cases)]
        for c, lab in zip(cases, labels):
            rs[f"{c.id}|{m.name}"] = reply(c, m, lab, cost=0.001 if m.billed else 0.02)
    s = evaljudges.score(cases, rs, models=list(models) + [KIMI])
    s["run"] = {"id": "judges-20261016T010203Z", "started": "2026-10-16T01:02:03Z",
                "scored": "2026-10-16T01:09:00Z", "golden_sha256": "ab" * 32, "golden_cases": 20,
                "filters": {"group": None, "status": None}, "stopped": None}
    return s


class TestRenderAndAccept(unittest.TestCase):
    def _summary(self, **kw) -> dict:
        return judge_summary(**kw)

    def test_providers_reported_per_model(self):
        """The hosts that served each model's answered calls are listed, so a flip can be lined up with a host
        change; a model whose replies name no host shows "not reported"."""
        cases = [gcase(f"J1-5b-{i:03d}", "fail") for i in range(1, 4)]
        rs = {}
        for c, host in zip(cases, ("DeepInfra", "Together", "DeepInfra")):
            r = reply(c, GROK, "fail")
            rs[r.key] = lp.Reply(**{**r.__dict__, "provider": host})
        for c in cases:
            r = reply(c, OPUS, "fail")
            rs[r.key] = r
        s = evaljudges.score(cases, rs, models=[GROK, OPUS])
        names = {m["name"]: m for m in s["models"]}
        self.assertEqual(names["grok"]["providers"], {"DeepInfra": 2, "Together": 1})
        self.assertEqual(names["claude-opus"]["providers"], {})
        s["run"] = {"id": "r", "started": "x", "scored": "y", "golden_sha256": "ab" * 32, "golden_cases": 3,
                    "filters": {"group": None, "status": None}, "stopped": None}
        md = evaljudges.render(s)
        self.assertIn("served by", md)
        self.assertIn("DeepInfra 2, Together 1", md)

    def test_render_has_ci_and_model_ids(self):
        s = self._summary(models=(GROK, OPUS))
        md = evaljudges.render(s)
        self.assertIn(REPORTED["grok"], md)
        self.assertIn(REPORTED["claude-opus"], md)
        self.assertIn("not run", md)  # kimi
        self.assertIn("2026-10-16", md)
        self.assertIn("US$0.02 billed", md)  # 20 grok replies at US$0.001
        self.assertIn("US$0.40 notional", md)  # 20 subscription replies at US$0.02
        self.assertIn("provisional labels: proxy", md)
        self.assertRegex(md, r"1\.00 \[0\.\d\d–1\.00\]")  # a rate with its Wilson interval
        self.assertIn("95%", md)
        self.assertIn("majority: all models", md)
        self.assertNotIn("score:", md.lower())  # no composite score

    def test_sampling_recorded_per_transport(self):
        """The CLI has no temperature flag, so the summary and the report header say how each transport samples and
        that run-to-run variance isn't comparable across them."""
        s = self._summary(models=(GROK, OPUS))
        self.assertEqual(s["sampling"], {"openrouter": lp.SAMPLING["openrouter"],
                                         "claude-cli": lp.SAMPLING["claude-cli"]})
        self.assertIn("temperature 0", s["sampling"]["openrouter"])
        self.assertIn("no temperature flag", s["sampling"]["claude-cli"])
        header = evaljudges.render(s).split("## Models")[0]
        self.assertIn("- Sampling: openrouter at temperature 0 · claude-cli at", header)
        self.assertIn("isn't comparable across transports", header)
        only = judge_summary(models=(OPUS,))
        self.assertEqual(set(only["sampling"]), {"claude-cli", "openrouter"})  # kimi is listed (OpenRouter), not run
        derived = evaljudges.score([], {}, models=None)
        self.assertEqual(derived["sampling"], {})

    def test_render_no_proxy_label_without_provisional(self):
        md = evaljudges.render(self._summary(provisional=False))
        self.assertNotIn("provisional labels: proxy", md)

    def test_accept_bar(self):
        ok = evaljudges.accept(self._summary(), models=["grok"])
        self.assertEqual([(r["group"], r["model"], r["ok"]) for r in ok], [("J1", "grok", True)])
        bad = evaljudges.accept(self._summary(wrong_fails=3), models=["grok"])  # TPR 0.7
        self.assertFalse(bad[0]["ok"])
        self.assertIn("TPR 0.70", bad[0]["why"])
        self.assertTrue(evaljudges.accept(self._summary(wrong_fails=3), models=["grok"], min_rate=0.6)[0]["ok"])
        notrun = evaljudges.accept(self._summary(), models=["kimi"])
        self.assertFalse(notrun[0]["ok"])
        self.assertIn("not run", notrun[0]["why"])


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class FakeCall:
    """Stands in for llm_panel.call: answers every case with its golden label."""

    def __init__(self):
        self.cases = {c.id: c for c in golden.load(FIX)}
        self.keys: list[str] = []

    def __call__(self, model, prompt, panel, *, opener=None, runner=None, env=None, key=""):
        self.keys.append(key)
        case = self.cases[key.split("|")[0]]
        return lp.Reply(key=key, name=model.name, model_requested=model.model,
                        model_reported=REPORTED[model.name], text=verdict_text(case, case.label), in_tokens=100,
                        out_tokens=20, cost_usd=0.002 if model.billed else 0.05, billed=model.billed,
                        at="2026-10-16T01:02:03Z", error=None)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        old = os.getcwd()  # judges and judges-report append to the project's eval history: keep it in the temp folder
        os.chdir(self.d)
        self.addCleanup(os.chdir, old)
        env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""})
        env.start()
        self.addCleanup(env.stop)
        self.panel = self.d / "panel.toml"
        self.panel.write_text(PANEL, encoding="utf-8")

    def judges(self, *extra, out=True):
        args = ["eval", "judges", "--golden", str(FIX), "--panel", str(self.panel)]
        if out:
            args += ["--out", str(self.d / "run")]
        return run_cli(*args, *extra)

    def test_cli_dry_run_prints_estimate_no_calls(self):
        fake = FakeCall()
        with mock.patch.object(lp, "call", fake):
            code, out, err = self.judges("--models", "grok,claude-opus", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.keys, [])
        self.assertIn("grok", out)
        self.assertIn("claude-opus", out)
        self.assertIn("estimate", out.lower())
        self.assertIn("dry run", out.lower())
        self.assertFalse((self.d / "run").exists())  # a dry run writes nothing

    def test_cli_run_writes_files_and_resumes(self):
        fake = FakeCall()
        with mock.patch.object(lp, "call", fake):
            code, out, err = self.judges("--models", "claude-opus")
        run = self.d / "run"
        self.assertIn(code, (0, 1), err)  # the tiny fixture set can't meet the accept bar's TNR on J2
        self.assertEqual(len(fake.keys), 4)
        meta = json.loads((run / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(set(meta) >= {"golden_sha256", "panel", "models", "filters", "started"}, True)
        self.assertEqual(meta["models"], ["claude-opus"])
        summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["groups"]["J1"]["splits"]["all"]["models"]["claude-opus"]["tp"], 1)
        self.assertIn(REPORTED["claude-opus"], (run / "report.md").read_text(encoding="utf-8"))
        self.assertFalse((run / "work").exists())  # the lint's temp files never stay in the run folder
        self.assertEqual(len((run / "replies.jsonl").read_text(encoding="utf-8").splitlines()), 4)
        with mock.patch.object(lp, "call", fake):
            self.judges("--models", "claude-opus")
        self.assertEqual(len(fake.keys), 4)  # resumed: nothing called twice

    def test_cli_errors_counted_then_retried(self):
        fake = FakeCall()
        real = fake.__call__

        def flaky(model, prompt, panel, **kw):
            r = real(model, prompt, panel, **kw)
            if kw.get("key") == "J1-5b-001|claude-opus" and fake.keys.count(kw["key"]) == 1:
                return lp.Reply(**{**r.__dict__, "text": "", "model_reported": "", "error": "claude-cli: timed out"})
            if kw.get("key") == "J1-5b-002|claude-opus":
                return lp.Reply(**{**r.__dict__, "text": "Looks fine to me."})
            return r
        with mock.patch.object(lp, "call", flaky):
            self.judges("--models", "claude-opus")
        run = self.d / "run"
        s1 = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        row = s1["groups"]["J1"]["splits"]["all"]["models"]["claude-opus"]
        self.assertEqual((row["errors"], row["n"]), (2, 2))
        self.assertEqual(s1["errors"]["claude-opus"], {"call failed: claude-cli: timed out": 1,
                                                       "not one JSON object": 1})
        self.assertIn("timed out", (run / "report.md").read_text(encoding="utf-8"))
        with mock.patch.object(lp, "call", flaky):
            self.judges("--models", "claude-opus")
        self.assertEqual(fake.keys.count("J1-5b-001|claude-opus"), 2)  # the errored call is retried once
        self.assertEqual(fake.keys.count("J1-5b-002|claude-opus"), 1)  # an unparseable reply isn't: it's an answer
        s2 = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        row = s2["groups"]["J1"]["splits"]["all"]["models"]["claude-opus"]
        self.assertEqual((row["errors"], row["tp"]), (1, 1))
        self.assertAlmostEqual(s2["cost"]["notional_usd"], 5 * 0.05)  # every call recorded, the retry included
        self.assertEqual(s2["cost"]["billed_usd"], 0.0)

    def test_cli_filters(self):
        fake = FakeCall()
        with mock.patch.object(lp, "call", fake):
            code, _, err = self.judges("--models", "claude-opus", "--group", "J1", "--status", "endorsed")
        self.assertIn(code, (0, 1), err)
        self.assertEqual(fake.keys, ["J1-5b-002|claude-opus"])
        code, _, err = self.judges("--models", "claude-opus", "--group", "J9")
        self.assertEqual(code, 2)
        self.assertIn("J9", err)

    def test_cli_billed_needs_yes(self):
        fake = FakeCall()
        with mock.patch.object(lp, "call", fake), mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY}):
            code, out, err = self.judges("--models", "grok")
        self.assertEqual(code, 1)
        self.assertIn("--yes", err)
        self.assertEqual(fake.keys, [])
        self.assertFalse((self.d / "run").exists())  # a refused run writes nothing, not even the lint's work files
        code, out, err = self.judges("--models", "grok", out=False)  # the default run folder isn't made either
        self.assertEqual(code, 1)
        self.assertFalse((self.d / ".plainspoken").exists())
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        with mock.patch.object(lp, "call", fake), mock.patch.dict(os.environ, env, clear=True):
            code, out, err = self.judges("--models", "grok", "--yes")
        self.assertEqual(code, 2)
        self.assertIn("OPENROUTER_API_KEY", err)
        self.assertEqual(fake.keys, [])
        with mock.patch.object(lp, "call", fake), mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY}):
            code, out, err = self.judges("--models", "grok", "--yes", "--max-cost-usd", "1")
        self.assertIn(code, (0, 1), err)
        self.assertEqual(len(fake.keys), 4)
        for f in (self.d / "run").iterdir():
            if f.is_file():
                self.assertNotIn(KEY, f.read_text(encoding="utf-8"), f.name)

    def test_cli_stopped_run_writes_no_history(self):
        fake = FakeCall()
        with mock.patch.object(lp, "call", fake), mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY}):
            code, out, err = self.judges("--models", "grok", "--yes", "--max-cost-usd", "0")
        self.assertEqual(code, 1)
        self.assertIn("stopped early", err)
        self.assertTrue((self.d / "run" / "summary.json").is_file())
        self.assertFalse((self.d / ".plainspoken" / "evals" / "history.jsonl").exists())
        self.assertNotIn("history", err)

    def test_cli_refuses_a_changed_golden_set(self):
        fake = FakeCall()
        with mock.patch.object(lp, "call", fake):
            self.judges("--models", "claude-opus")
        meta_path = self.d / "run" / "run.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["golden_sha256"] = "0" * 64
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        with mock.patch.object(lp, "call", fake):
            code, _, err = self.judges("--models", "claude-opus")
        self.assertEqual(code, 2)
        self.assertIn("golden set", err)

    def test_cli_default_out_under_project(self):
        project = self.d / "project"
        (project / ".git").mkdir(parents=True)
        fake = FakeCall()
        old = os.getcwd()
        try:
            os.chdir(project)
            with mock.patch.object(lp, "call", fake), mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""}):
                code, out, err = self.judges("--models", "claude-opus", out=False)
        finally:
            os.chdir(old)
        self.assertIn(code, (0, 1), err)
        runs = list((project / ".plainspoken" / "evals").glob("judges-*"))
        self.assertEqual(len(runs), 1)
        self.assertRegex(runs[0].name, r"^judges-\d{8}T\d{6}Z$")
        self.assertTrue((runs[0] / "summary.json").is_file())
        history = [json.loads(x) for x in (project / ".plainspoken" / "evals" / "history.jsonl")
                   .read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(h["kind"], h["model"], h["run"]) for h in history],
                         [("judges", "claude-opus", str(runs[0].resolve()))])  # one line per model

    def history(self) -> list[dict]:
        path = self.d / ".plainspoken" / "evals" / "history.jsonl"
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def test_report_after_judges_adds_no_duplicate_history(self):
        (self.d / ".git").mkdir()
        fake = FakeCall()
        with mock.patch.object(lp, "call", fake):
            self.judges("--models", "claude-opus")
        self.assertEqual(len(self.history()), 1)
        run_cli("eval", "judges-report", "--run", str(self.d / "run"))
        run_cli("eval", "judges-report", "--run", str(self.d / "run"))
        self.assertEqual(len(self.history()), 1)
        run_cli("eval", "judges-report", "--run", str(self.d / "run"), "--min", "0.6")  # a new bar is a new line
        self.assertEqual([h["min_rate"] for h in self.history()], [0.8, 0.6])

    def test_out_naming_a_file_is_a_clear_error(self):
        target = self.d / "taken.txt"
        target.write_text("not a run\n", encoding="utf-8")
        code, _, err = run_cli("eval", "judges", "--golden", str(FIX), "--panel", str(self.panel), "--out",
                               str(target), "--models", "claude-opus")
        self.assertEqual(code, 2)
        self.assertIn(f"plainspoken: eval judges: {target}: not a folder", err)
        self.assertNotIn("internal", err.lower())
        self.assertEqual(target.read_text(encoding="utf-8"), "not a run\n")

    def test_judges_and_panel_estimates_print_one_table(self):  # one table, not two copies
        from plainspoken import evalcli
        prompts = ["a" * 4000, "b" * 400]
        files = []
        for i, text in enumerate(prompts):
            f = self.d / f"p{i}.txt"
            f.write_text(text, encoding="utf-8")
            files.append(str(f))
        code, est_out, err = run_cli("eval", "panel", "estimate", "--panel", str(self.panel), "--models",
                                     "grok,claude-opus", *files)
        self.assertEqual(code, 0, err)
        panel = lp.load_panel(self.panel)
        models = [panel.get("grok"), panel.get("claude-opus")]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            evalcli._print_estimate([(f"k{i}|{m.name}", m, p) for i, p in enumerate(prompts) for m in models],
                                    models, panel)
        self.assertEqual(est_out, out.getvalue())

    def _run_dir(self, name: str, wrong_fails: int) -> Path:
        s = TestRenderAndAccept._summary(TestRenderAndAccept(), wrong_fails=wrong_fails)
        run = self.d / name
        run.mkdir()
        (run / "summary.json").write_text(json.dumps(s), encoding="utf-8")
        (run / "run.json").write_text(json.dumps({"models": ["grok"]}), encoding="utf-8")
        return run

    def test_cli_report_exit_codes(self):
        good = self._run_dir("good", 0)
        code, out, err = run_cli("eval", "judges-report", "--run", str(good))
        self.assertEqual(code, 0, err)
        self.assertIn("J1", out)
        bad = self._run_dir("bad", 3)
        code, out, err = run_cli("eval", "judges-report", "--run", str(bad))
        self.assertEqual(code, 1)
        self.assertIn("J1", err)
        self.assertIn("grok", err)
        self.assertIn("TPR 0.70", out + err)
        code, _, err = run_cli("eval", "judges-report", "--run", str(bad), "--min", "0.6")
        self.assertEqual(code, 0, err)
        code, _, err = run_cli("eval", "judges-report", "--run", str(self.d / "missing"))
        self.assertEqual(code, 2)
        self.assertIn("plainspoken: eval judges-report:", err)

    def test_judge_validate_script(self):
        good = self._run_dir("good", 0)
        done = subprocess.run([sys.executable, str(REPO / "scripts" / "dev" / "judge_validate.py"), "--run",
                               str(good)], capture_output=True, text=True, timeout=60, cwd=self.d)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("J1", done.stdout)


if __name__ == "__main__":
    unittest.main()
