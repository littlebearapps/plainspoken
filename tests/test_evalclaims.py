"""Claims-checker validation: the CL golden cases → one Claude model → per-claim verdicts → accuracy (#59). Fakes
only: no test touches the network or spawns `claude`."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plainspoken import __main__ as cli_main
from plainspoken import evalclaims, golden
from plainspoken.adapters import llm_panel as lp

OPUS = evalclaims.make_model("claude-opus-5-5", 4.0, 20.0)
CASES = [c for c in golden.load(golden.DEFAULT_DIR) if c.group == golden.CLAIMS]
BY_ID = {c.id: c for c in CASES}


def reply_text(case: golden.GoldenCase, verdicts: dict[str, str] | None = None, *, warn: tuple = (),
               extra: bool = False, hashes: dict | None = None) -> str:
    """A checker reply for `case`: one blocking finding per claim given `fail` (default: each claim's `expect`), one
    warning per claim id in `warn`. Evidence is the claim's own text, which the article holds word for word."""
    verdicts = verdicts if verdicts is not None else {c["claim_id"]: c["expect"] for c in case.claims}
    claims = {c["claim_id"]: c for c in case.claims}
    findings = [{"claim_id": cid, "location": "body", "class": "unsupported_claim", "severity": "blocking",
                 "evidence": claims[cid]["text"], "why": "No support.", "suggested_fix": None}
                for cid, v in verdicts.items() if v == "fail"]
    findings += [{"claim_id": cid, "location": "body", "class": "unlabelled_judgement", "severity": "warning",
                  "evidence": claims[cid]["text"], "why": "Label it.", "suggested_fix": None} for cid in warn]
    if extra:
        findings.append({"claim_id": None, "location": "body", "class": "unledgered_claim", "severity": "blocking",
                         "evidence": case.text.split()[1] + " " + " ".join(case.text.split()[2:5]), "why": "x",
                         "suggested_fix": None})
    inp = evalclaims.input_block(case)
    body = {"article": "article.md", **{k: inp[k] for k in ("article_sha256", "ledger_sha256", "matrix_sha256")},
            "result": "BLOCKED" if any(f["severity"] == "blocking" for f in findings) else "PASS",
            "findings": findings}
    body.update(hashes or {})
    return json.dumps(body)


def reply(case, text: str | None = None, *, error: str | None = None, cost: float = 0.04) -> lp.Reply:
    return lp.Reply(key=evalclaims.job_key(case.id, OPUS.name), name=OPUS.name, model_requested=OPUS.model,
                    model_reported="" if error else "claude-opus-5-5", text="" if error else (text or reply_text(case)),
                    in_tokens=6000, out_tokens=700, cost_usd=cost, billed=False, at="2026-10-22T01:02:03Z",
                    error=error)


class Prompt(unittest.TestCase):
    def test_prompt_is_self_contained_and_holds_no_label(self):
        for case in CASES:
            with self.subTest(case=case.id):
                p = evalclaims.prompt_for(case)
                self.assertIn("You are the claims checker.", p)
                self.assertIn("# Claims checker rubric", p)  # the whole rubric the agent reads
                self.assertIn(case.text.strip(), p)
                inp = evalclaims.input_block(case)
                self.assertIn(inp["article_sha256"], p)
                self.assertIn(inp["ledger_sha256"], p)
                self.assertEqual(inp["article_sha256"], golden.text_sha256(case.text))
                self.assertEqual(inp["ledger_sha256"], golden.text_sha256(evalclaims.ledger_text(case)))
                for secret in (case.id, case.origin, '"expect"', *(c["why"] for c in case.claims)):
                    self.assertNotIn(secret, p)
                self.assertNotIn('"why"', p.split("## Ledger", 1)[1])  # the rubric's output schema has a why

    def test_prompt_refuses_a_judge_case(self):
        j = golden.GoldenCase(id="J1-5b-001", group="J1", rule="5b", label="fail", text="x", content_type="article",
                              source="constructed", status="provisional", origin="o")
        with self.assertRaises(ValueError):
            evalclaims.prompt_for(j)

    def test_claude_only(self):
        for ok in ("claude-opus-5-5", "claude-haiku-5-5", "opus", "sonnet", "haiku"):
            self.assertTrue(evalclaims.claude_model(ok), ok)
        for bad in ("gpt-6-luna", "anthropic/claude-opus-5-5", "x-ai/grok-4.7", "", "claude opus"):
            self.assertFalse(evalclaims.claude_model(bad), bad)
        self.assertEqual(evalclaims.list_price("opus"), (4.0, 20.0))
        self.assertIsNone(evalclaims.list_price("claude-fable-5-1"))

    def test_estimate_is_list_price_plus_overhead(self):
        p = "x" * 4000  # 1,000 tokens
        want = ((1000 + evalclaims.CLI_OVERHEAD_TOKENS) * 4.0 + evalclaims.EST_OUT_TOKENS * 20.0) / 1e6
        self.assertAlmostEqual(evalclaims.estimate(p, OPUS), want)


class Verdicts(unittest.TestCase):
    case = BY_ID["CL-opinion_label-004"]  # C001 fail, C002 and C003 pass

    def test_blocking_is_fail_and_a_warning_is_pass(self):
        got = evalclaims.verdicts(reply_text(self.case, warn=("C002",)), self.case)
        self.assertEqual(got["verdicts"], {"C001": "fail", "C002": "pass", "C003": "pass"})
        self.assertEqual(got["classes"]["C001"], ["unsupported_claim"])
        self.assertEqual(got["warnings"]["C002"], ["unlabelled_judgement"])
        self.assertEqual(got["reply_result"], "BLOCKED")
        self.assertTrue(got["hashes_ok"])
        self.assertEqual(got["unverified"], 0)

    def test_a_finding_on_no_claim_is_extra_not_a_verdict(self):
        got = evalclaims.verdicts(reply_text(self.case, {"C001": "pass"}, extra=True), self.case)
        self.assertEqual(set(got["verdicts"].values()), {"pass"})
        self.assertEqual(len(got["extra"]), 1)
        self.assertTrue(got["extra"][0].startswith("unledgered_claim:"))

    def test_wrong_hashes_are_noted(self):
        got = evalclaims.verdicts(reply_text(self.case, hashes={"ledger_sha256": "sha256:00"}), self.case)
        self.assertFalse(got["hashes_ok"])

    def test_unscorable_replies_raise(self):
        for text in ("Looks fine to me.", '{"result": "MAYBE", "findings": []}', '{"result": "PASS"}',
                     json.dumps({"result": "BLOCKED", "findings": [{"claim_id": "C001", "severity": "high",
                                                                     "evidence": "x"}]})):
            with self.subTest(text=text), self.assertRaises(ValueError):
                evalclaims.verdicts(text, self.case)


class Score(unittest.TestCase):
    def replies(self, make) -> dict:
        return {evalclaims.job_key(c.id, OPUS.name): make(c) for c in CASES}

    def test_a_perfect_checker(self):
        s = evalclaims.score(CASES, self.replies(reply), OPUS.name)
        c = s["claims"]
        self.assertEqual((c["tpr"]["value"], c["tnr"]["value"], c["accuracy"]["value"]), (1.0, 1.0, 1.0))
        self.assertEqual(c["errors"], 0)
        self.assertEqual(s["cases"]["all_claims_right"], len(CASES))
        self.assertEqual(s["cases"]["result_right"], len(CASES))
        self.assertAlmostEqual(s["notional_usd"], 0.04 * len(CASES))
        self.assertIn("opinion_label", s["rules"])

    def test_blocking_everything_or_nothing_scores_badly(self):
        fails = sum(cl["expect"] == "fail" for c in CASES for cl in c.claims)
        total = sum(len(c.claims) for c in CASES)
        everything = self.replies(lambda c: reply(c, reply_text(c, {x["claim_id"]: "fail" for x in c.claims})))
        s = evalclaims.score(CASES, everything, OPUS.name)["claims"]
        self.assertEqual((s["tpr"]["value"], s["tnr"]["value"]), (1.0, 0.0))
        self.assertAlmostEqual(s["accuracy"]["value"], fails / total)
        self.assertLess(s["accuracy"]["value"], 0.5)
        nothing = self.replies(lambda c: reply(c, reply_text(c, {})))
        s = evalclaims.score(CASES, nothing, OPUS.name)["claims"]
        self.assertEqual((s["tpr"]["value"], s["tnr"]["value"]), (0.0, 1.0))

    def test_errors_and_missing_are_neither_pass_nor_fail(self):
        a, b, c = CASES[0], CASES[1], CASES[2]
        replies = {evalclaims.job_key(a.id, OPUS.name): reply(a, error="claude-cli: timed out"),
                   evalclaims.job_key(b.id, OPUS.name): reply(b, "not json"),
                   evalclaims.job_key(c.id, OPUS.name): reply(c)}
        s = evalclaims.score([a, b, c, CASES[3]], replies, OPUS.name)
        self.assertEqual(s["cases"]["missing"], 1)
        self.assertEqual(s["cases"]["errors"], 2)
        self.assertEqual(s["claims"]["errors"], len(a.claims) + len(b.claims))
        self.assertEqual(s["claims"]["accuracy"]["n"], len(c.claims))
        rows = {r["id"]: r for r in s["rows"]}
        self.assertTrue(rows[a.id]["error"].startswith("call failed"))
        self.assertTrue(rows[b.id]["error"].startswith("unscorable reply"))
        self.assertTrue(rows[CASES[3].id]["missing"])

    def test_render_names_each_miss_with_its_reason(self):
        case = BY_ID["CL-opinion_label-001"]
        wrong = reply(case, reply_text(case, {"C001": "pass", "C002": "fail"}))
        s = evalclaims.score([case], {wrong.key: wrong}, OPUS.name)
        text = evalclaims.render(s)
        self.assertIn("CL-opinion_label-001 (opinion_label, provisional): expected BLOCKED, got BLOCKED", text)
        self.assertIn("MISS  C001 expect fail (got pass: no blocking finding)", text)
        self.assertIn("MISS  C002 expect pass (got fail: unsupported_claim)", text)
        self.assertIn("accuracy 0.00", text)
        self.assertIn(f"- CL-opinion_label-001 C001: expected fail, got pass. {case.claims[0]['why']}", text)


def run_cli(*args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli_main.main(list(args))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class FakeCall:
    """Stands in for llm_panel.call: answers every case with its golden verdicts, at a notional cost."""

    def __init__(self, cost: float = 0.04):
        self.keys: list[str] = []
        self.models: list[str] = []
        self.cost = cost

    def __call__(self, model, prompt, panel, *, opener=None, runner=None, env=None, key=""):
        self.keys.append(key)
        self.models.append(f"{model.transport}:{model.model}")
        return reply(BY_ID[key.split("|")[0]], cost=self.cost)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        old = os.getcwd()
        os.chdir(self.d)
        self.addCleanup(os.chdir, old)
        env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": ""})
        env.start()
        self.addCleanup(env.stop)
        self.out = self.d / "run"

    def claims(self, *extra: str, fake: FakeCall | None = None) -> tuple[int, str, str]:
        with mock.patch.object(lp, "call", fake or FakeCall()):
            return run_cli("eval", "claims", "--out", str(self.out), *extra)

    def test_dry_run_prints_the_plan_and_sends_nothing(self):
        fake = FakeCall()
        code, out, err = self.claims("--dry-run", fake=fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.keys, [])
        self.assertFalse(self.out.exists())
        self.assertIn(f"{len(CASES)} CL cases", out)
        self.assertIn("CL-opinion_label-001: 2 claims", out)
        self.assertIn("total notional estimate: US$", out)
        self.assertIn("dry run: nothing sent, nothing written", out)

    def test_other_vendors_are_refused(self):
        for model in ("gpt-6-luna", "x-ai/grok-4.7", "anthropic/claude-opus-5-5"):
            with self.subTest(model=model):
                code, _, err = self.claims("--model", model, "--dry-run")
                self.assertEqual(code, 2)
                self.assertIn("Claude only", err)

    def test_an_unpriced_model_needs_prices(self):
        code, _, err = self.claims("--model", "claude-fable-5-1", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("--price-in", err)
        code, out, err = self.claims("--model", "claude-fable-5-1", "--price-in", "10", "--price-out", "50",
                                     "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("US$10/US$50", out)

    def test_run_writes_files_reports_accuracy_and_resumes(self):
        fake = FakeCall()
        code, out, err = self.claims(fake=fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.keys), len(CASES))
        self.assertEqual(set(fake.models), {"claude-cli:claude-opus-5-5"})  # Claude only, on the CLI
        for name in ("run.json", "replies.jsonl", "summary.json", "report.md"):
            self.assertTrue((self.out / name).is_file(), name)
        summary = json.loads((self.out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["claims"]["accuracy"]["value"], 1.0)
        self.assertIn("ok    C001 expect fail", out)
        self.assertIn("- Claims: accuracy 1.00", out)
        code, _, err = self.claims(fake=fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.keys), len(CASES))  # resumed: nothing called twice

    def test_budget_stops_before_the_cap_and_resumes(self):
        fake = FakeCall(cost=0.05)
        code, _, err = self.claims("--max-cost-usd", "0.15", "--concurrency", "1", fake=fake)
        self.assertEqual(code, 1)
        self.assertIn("budget reached", err)
        spent = sum(r.cost_usd for r in lp.reply_lines(self.out / lp.REPLIES))
        self.assertLessEqual(spent, 0.15 + 1e-9)
        self.assertLess(len(fake.keys), len(CASES))
        report = (self.out / "report.md").read_text(encoding="utf-8")
        self.assertIn("Stopped early", report)
        self.assertIn("not run", report)
        code, _, err = self.claims("--max-cost-usd", "5", fake=fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(fake.keys), sorted(evalclaims.job_key(c.id, OPUS.name) for c in CASES))

    def test_zero_budget_sends_nothing(self):
        fake = FakeCall()
        code, _, err = self.claims("--max-cost-usd", "0", fake=fake)
        self.assertEqual(code, 1)
        self.assertEqual(fake.keys, [])
        self.assertIn("budget reached", err)

    def test_failed_calls_exit_1_and_are_retried(self):
        fake = FakeCall()
        real = fake.__call__
        first = evalclaims.job_key(CASES[0].id, OPUS.name)

        def flaky(model, prompt, panel, **kw):
            r = real(model, prompt, panel, **kw)
            if kw.get("key") == first and fake.keys.count(first) == 1:
                return reply(CASES[0], error="claude-cli: timed out")
            return r
        with mock.patch.object(lp, "call", flaky):
            code, _, err = run_cli("eval", "claims", "--out", str(self.out))
        self.assertEqual(code, 1)
        self.assertIn("re-run", err)
        with mock.patch.object(lp, "call", flaky):
            code, _, err = run_cli("eval", "claims", "--out", str(self.out))
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.keys.count(first), 2)
        self.assertEqual(len(fake.keys), len(CASES) + 1)

    def test_a_different_model_or_case_set_needs_a_new_out(self):
        self.claims("--status", "provisional")
        code, _, err = self.claims("--model", "claude-sonnet-5-5")
        self.assertEqual(code, 2)
        self.assertIn("new --out", err)

    def test_judges_never_get_claims_cases(self):
        self.assertNotIn(golden.CLAIMS, golden.JUDGE_GROUPS)
        code, _, err = run_cli("eval", "judges", "--models", "claude-opus", "--group", "CL", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("--group", err)
        judged = [c for c in golden.load(golden.DEFAULT_DIR) if c.group in golden.JUDGE_GROUPS]
        code, out, err = run_cli("eval", "judges", "--models", "claude-opus", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn(f"{len(judged)} golden cases × 1 model", out)


if __name__ == "__main__":
    unittest.main()
