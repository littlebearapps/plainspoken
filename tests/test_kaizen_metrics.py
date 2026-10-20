"""Per-rule kaizen metrics, the `kaizen report` table and the anonymised `--share` export."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from plainspoken import kaizen, ledger
from plainspoken.registry import load_config

REPO = Path(__file__).resolve().parents[1]
CFG = load_config()
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
PROFILE = "secret-voice"
D1, D2, D3 = ledger.label_id("doc-1"), ledger.label_id("doc-2"), ledger.label_id("doc-3")
SHA_A, SHA_B = "a" * 64, "b" * 64


def ev(event, actor, outcome, rule, severity="WARN", doc=D1, span="x", sha=SHA_A, ts="2026-10-10T09:00:00+00:00",
       **kw):
    return ledger.make_event(event=event, actor=actor, outcome=outcome, ruleset_version=CFG.version, profile=PROFILE,
                             rule=rule, severity=severity, doc_id=doc, doc_sha=sha,
                             span_hash=None if span is None else ledger.span_hash(str(rule), span), ts=ts, **kw)


def fired(rule, span, doc=D1, severity="WARN", **kw):
    return ev("lint", "lint", "fired", rule, severity, doc, span, **kw)


STAR = "*"


def sample() -> list[dict]:
    """A hand-built ledger. 4b: span `a` fires three times (same id) and again on a new draft (new doc_sha, new id),
    so it counts once."""
    out = []
    a = fired("4b", "also", facets={"term": "also"}, ts="2026-10-01T09:00:00+00:00")
    out += [a, a, a]
    out.append(fired("4b", "also", sha=SHA_B, facets={"term": "also"}, ts="2026-10-02T09:00:00+00:00"))
    out.append(fired("4b", "then", doc=D2, facets={"term": "then", "section": "faq"}, ts="2026-10-05T09:00:00+00:00"))
    out.append(fired("4b", "shadowish", doc=D2, severity="INFO", ts="2026-10-06T09:00:00+00:00"))  # not a fire
    out.append(ev("fix", "lint", "fixed", "4b", span="also", sha=SHA_B, facets={"term": "also"}))
    out.append(ev("justify", "human", "justified:voice", "4b", doc=D2, span=STAR))
    out.append(ev("jr", "jr", "jr_accept", "4b", doc=D2, span=STAR, facets={"kind": "voice"}))
    out.append(ev("publish", "publish", "survived_publish", "4b", doc=D2, span="then",
                  facets={"term": "then", "section": "faq"}))
    out.append(ev("publish", "publish", "survived_publish", "4b", doc=D2, span=STAR, facets={"kind": "voice"}))
    # rule 2 (lint+judge BLOCK): 4 fires over 2 docs, 2 dismissed, 1 upheld; judge agreement 1 of 2.
    for i, doc in enumerate((D1, D1, D2, D2)):
        out.append(fired("2", f"ban{i}", doc=doc, severity="BLOCK", ts=f"2026-10-0{i + 1}T10:00:00+00:00"))
    out.append(ev("override", "human", "dismissed", "2", "BLOCK", span="ban0", facets={"kind": "false_positive"},
                  reason="fine"))
    out.append(ev("override", "human", "dismissed", "2", "BLOCK", span="ban1", facets={"kind": "quote"},
                  reason="quoted"))
    out.append(ev("override", "human", "upheld", "2", "BLOCK", doc=D2, span="ban2", reason="right"))
    out.append(ev("judge", "judge:J1", "fired", "2", "BLOCK", doc=D3, span="q1", facets={"agree": True},
                  ts="2026-10-12T08:00:00+00:00"))
    out.append(ev("judge", "judge:J1", "passed", "2", "BLOCK", doc=D3, span=STAR, facets={"agree": False}))
    # rule 15: 2 fires; one JR-accepted false-positive justification whose kind comes only from the justify event.
    out.append(fired("15", "x15a", doc=D1))
    out.append(fired("15", "x15b", doc=D2))
    out.append(ev("justify", "human", "justified:false_positive", "15", doc=D2, span=STAR))
    out.append(ev("jr", "jr", "jr_accept", "15", doc=D2, span=STAR))
    out.append(ev("jr", "jr", "jr_reject", "15", doc=D1, span=STAR, facets={"kind": "voice"}))
    # rule 7: upheld outweighs dismissed, so effective_fp floors at 0.
    out.append(fired("7", "run1"))
    out.append(ev("override", "human", "upheld", "7", span="run1", reason="yes"))
    out.append(ev("override", "human", "upheld", "7", doc=D2, span="run2", reason="yes"))
    out.append(ev("override", "human", "dismissed", "7", doc=D3, span="run3", facets={"kind": "voice"}, reason="no"))
    # rule 21 (judged): missed twice, never fired.
    out.append(ev("diff", "human", "missed", "21", None, doc=D1, span="hunk one"))
    out.append(ev("diff", "human", "missed", "21", None, doc=D2, span="hunk two"))
    # pattern-only missed tells: rule "?" + facet pattern.
    out.append(ev("diff", "human", "missed", "?", None, doc=D1, span="h1", facets={"pattern": "hedge-stack"}))
    out.append(ev("diff", "human", "missed", "?", None, doc=D2, span="h2", facets={"pattern": "hedge-stack"}))
    out.append(ev("diff", "human", "missed", "?", None, doc=D2, span="h3", facets={"pattern": "listicle"}))
    out.append(ledger.make_event(event="decision", actor="human", outcome="approved", ruleset_version=CFG.version,
                                 profile=PROFILE, proposal="KZ-1", ts="2026-10-11T00:00:00+00:00"))
    return out


class Metrics(unittest.TestCase):
    def setUp(self):
        self.m = kaizen.rule_metrics(sample(), CFG, NOW)

    def test_counts_distinct_spans_not_lines_or_ids(self):
        r = self.m["4b"]
        self.assertEqual(r["fires"], 2)  # `also` (4 lines, 2 ids) + `then`; the INFO fire doesn't count
        self.assertEqual(r["docs"], 2)
        self.assertEqual((r["fixed"], r["justified"], r["jr_accept"], r["jr_reject"]), (1, 1, 1, 0))
        self.assertEqual((r["dismissed"], r["upheld"], r["missed"], r["survived"]), (0, 0, 0, 2))
        self.assertEqual(r["kept_docs"], 1)  # doc 2 once, though it has a jr_accept and two survived spans
        self.assertEqual(r["fix_rate"], 0.5)
        self.assertEqual(r["justify_rate"], 0.5)
        self.assertEqual(r["jr_accept_rate"], 1.0)
        self.assertEqual(r["dismiss_rate"], 0.0)
        self.assertEqual(r["effective_fp"], 0.0)
        self.assertIsNone(r["agreement"])
        self.assertEqual(r["last_fired"], "2026-10-06T09:00:00+00:00")  # the INFO fire still shows life

    def test_facets_among_fired_and_kept_spans(self):
        f = self.m["4b"]["facets"]
        self.assertEqual(f["fired"]["term"], {"also": 1, "then": 1})
        self.assertEqual(f["fired"]["section"], {"faq": 1})
        self.assertEqual(f["kept"]["term"], {"then": 1})
        self.assertEqual(f["kept"]["kind"], {"voice": 1})
        self.assertEqual(self.m["2"]["facets"]["dismissed"]["kind"], {"false_positive": 1, "quote": 1})

    def test_effective_fp_subtracts_upheld(self):
        r = self.m["2"]
        self.assertEqual((r["fires"], r["docs"], r["dismissed"], r["upheld"]), (5, 3, 2, 1))  # 4 lint + 1 judge
        self.assertAlmostEqual(r["effective_fp"], (2 - 1) / 5)
        self.assertAlmostEqual(r["dismiss_rate"], 2 / 5)
        self.assertEqual(self.m["7"]["effective_fp"], 0.0)  # 1 dismissed − 2 upheld floors at 0

    def test_effective_fp_counts_jr_accepted_false_positives_joined_from_justify(self):
        r = self.m["15"]
        self.assertEqual((r["fires"], r["justified"], r["jr_accept"], r["jr_reject"]), (2, 1, 1, 1))
        self.assertEqual(r["effective_fp"], 0.5)
        self.assertEqual(r["jr_accept_rate"], 0.5)
        self.assertEqual(r["kept_docs"], 1)

    def test_rates_never_pass_100_percent(self):  # a --since window can hold fixes of older fires
        events = [fired("4b", "a", ts="2026-10-10T09:00:00+00:00")]
        events += [ev("fix", "lint", "fixed", "4b", span=x) for x in ("a", "b", "c")]
        events += [ev("override", "human", "dismissed", "4b", span=x, facets={"kind": "false_positive"},
                      reason="fine") for x in ("b", "c")]
        r = kaizen.rule_metrics(events, CFG, NOW)["4b"]
        self.assertEqual((r["fires"], r["fixed"]), (1, 3))
        for key in ("fix_rate", "dismiss_rate", "effective_fp"):
            self.assertLessEqual(r[key], 1.0, key)
        widths = {len(line) for line in kaizen.report_lines({"4b": r}, 0, {})[:2]}
        self.assertEqual(len(widths), 1, widths)  # the row stays as wide as the header

    def test_fp_kind_is_the_latest_justification(self):  # not any version's false_positive
        def rows(first, second):
            return [fired("15", "x"),
                    ev("justify", "human", f"justified:{first}", "15", span=STAR, ts="2026-10-10T09:00:00+00:00"),
                    ev("justify", "human", f"justified:{second}", "15", span=STAR, sha=SHA_B,
                       ts="2026-10-11T09:00:00+00:00"),
                    ev("jr", "jr", "jr_accept", "15", span=STAR, sha=SHA_B, facets={"kind": second},
                       ts="2026-10-11T09:00:00+00:00")]
        self.assertEqual(kaizen.rule_metrics(rows("false_positive", "voice"), CFG, NOW)["15"]["effective_fp"], 0.0)
        self.assertEqual(kaizen.rule_metrics(rows("voice", "false_positive"), CFG, NOW)["15"]["effective_fp"], 1.0)

    def test_agreement_tie_break_ignores_file_order(self):
        a = ev("judge", "judge:J1", "fired", "2", "BLOCK", span="q", facets={"agree": True})
        b = ev("judge", "judge:J1", "passed", "2", "BLOCK", span="q", facets={"agree": False})
        one = kaizen.rule_metrics([fired("2", "q", severity="BLOCK"), a, b], CFG, NOW)["2"]["agreement"]
        two = kaizen.rule_metrics([fired("2", "q", severity="BLOCK"), b, a], CFG, NOW)["2"]["agreement"]
        self.assertEqual(one, two)

    def test_agreement_on_lint_judge_rules(self):
        self.assertEqual(self.m["2"]["agreement"], 0.5)

    def test_zero_fires_gives_none_rates(self):
        r = self.m["21"]
        self.assertEqual((r["fires"], r["missed"], r["missed_docs"]), (0, 2, 2))
        for key in ("fix_rate", "justify_rate", "jr_accept_rate", "dismiss_rate", "effective_fp", "agreement"):
            self.assertIsNone(r[key], key)
        self.assertIsNone(r["last_fired"])
        self.assertIsNone(r["days_since_fired"])
        quiet = self.m["22"]  # a ruleset rule with no events at all is still listed (dormancy needs it)
        self.assertEqual(quiet["fires"], 0)
        self.assertIsNone(quiet["fix_rate"])

    def test_days_since_fired(self):
        self.assertEqual(self.m["4b"]["days_since_fired"], 8)

    def test_pattern_missed_never_a_rule_row(self):
        self.assertNotIn("?", self.m)
        self.assertEqual(kaizen.pattern_metrics(sample()),
                         {"hedge-stack": {"missed": 2, "docs": 2}, "listicle": {"missed": 1, "docs": 1}})

    def test_empty(self):
        m = kaizen.rule_metrics([], CFG, NOW)
        self.assertEqual(set(m), set(CFG.rules))
        self.assertFalse(any(kaizen.has_events(r) for r in m.values()))


class Report(unittest.TestCase):
    def test_table_rows_for_rules_with_events_only(self):
        evs = sample()
        lines = kaizen.report_lines(kaizen.rule_metrics(evs, CFG, NOW), 0, kaizen.friction_summary([], evs),
                                    kaizen.pattern_metrics(evs))
        text = "\n".join(lines)
        rows = [ln.split()[0] for ln in lines if ln[:1].strip() and ln.split()[0] in CFG.rules]
        self.assertEqual(rows, ["2", "4b", "7", "15", "21"])  # ruleset order
        self.assertNotIn("\n?", text)
        self.assertIn("hedge-stack", text)
        self.assertNotIn("unreadable", text)
        self.assertNotIn("score", text.lower())  # no composite score
        widths = {len(ln) for ln in lines if ln.split() and ln.split()[0] in ("rule", "2", "4b", "7", "15", "21")}
        self.assertEqual(len(widths), 1, lines)  # fixed width

    def test_pattern_review_proposal_is_not_a_rule_row(self):  # its events belong to the missed patterns
        evs = sample() + [
            ledger.make_event(event="calibrate", actor="engine", outcome="proposed", ruleset_version=CFG.version,
                              profile=PROFILE, rule="pattern:hedge-stack", proposal="KZ-20261010-abcdef",
                              ts="2026-10-10T09:00:00+00:00"),
            ledger.make_event(event="decision", actor="human", outcome="rejected", ruleset_version=CFG.version,
                              profile=PROFILE, rule="pattern:hedge-stack", proposal="KZ-20261010-abcdef",
                              facets={"by": "Robin"}, ts="2026-10-11T09:00:00+00:00")]
        metrics = kaizen.rule_metrics(evs, CFG, NOW)
        self.assertFalse(any(rid.startswith("pattern:") for rid in metrics))
        lines = kaizen.report_lines(metrics, 0, kaizen.friction_summary([], evs), kaizen.pattern_metrics(evs))
        self.assertFalse(any(ln.split()[:1] == ["pattern:hedge-stack"] for ln in lines), lines)
        self.assertIn("  hedge-stack: 2 spans in 2 docs", lines)

    def test_bad_lines_and_friction(self):
        evs = sample()
        rows = [{"v": 1, "ts": "2026-10-10T00:00:00+00:00", "kind": "agent_handback",
                 "source": "plainspoken:tells-judge", "detail": ""}] * 3
        rows += [{"v": 1, "ts": "2026-10-10T00:00:00+00:00", "kind": "merge_incomplete", "source": "merge",
                  "detail": "missing verdicts: 9"}]
        fr = kaizen.friction_summary(rows, evs)
        self.assertEqual(fr["kinds"], {"agent_handback": 3, "merge_incomplete": 1})
        self.assertEqual((fr["judge_returned"], fr["judge_recorded"]), (3, 3))  # J1 on D3 + JR on D2 and D1
        text = "\n".join(kaizen.report_lines(kaizen.rule_metrics(evs, CFG, NOW), 2, fr, {}))
        self.assertIn("2 unreadable ledger lines", text)
        self.assertIn("judge replies returned (backstop) 3 vs recorded 3", text)
        self.assertIn("merge_incomplete", text)

    def test_empty_ledger(self):
        lines = kaizen.report_lines(kaizen.rule_metrics([], CFG, NOW), 0, kaizen.friction_summary([], []), {})
        self.assertIn("no kaizen events yet", "\n".join(lines))


def _walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, None
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)
    else:
        yield None, obj


FORBIDDEN_KEYS = {"profile", "doc_id", "span_hash", "facets", "reason", "excerpt"}


class Share(unittest.TestCase):
    def test_counts_only(self):
        evs = sample()
        out = kaizen.share(kaizen.rule_metrics(evs, CFG, NOW), CFG, "9.9.9", since="2026-10-01T00:00:00+00:00")
        self.assertEqual(out["plainspoken"], "9.9.9")
        self.assertEqual(out["ruleset_version"], CFG.version)
        self.assertEqual(out["window"], {"since": "2026-10-01T00:00:00+00:00", "until": None})
        self.assertEqual(set(out["rules"]), {"2", "4b", "7", "15", "21"})
        self.assertEqual(set(out["rules"]["4b"]), {"fires", "docs", "fixed", "justified", "jr_accept", "jr_reject",
                                                    "dismissed", "upheld", "missed", "survived"})
        self.assertEqual(out["rules"]["4b"]["fires"], 2)
        keys = {k for k, _ in _walk(out) if k is not None}
        self.assertFalse(keys & FORBIDDEN_KEYS)
        values = [v for _, v in _walk(out) if isinstance(v, str)]
        self.assertFalse([v for v in values if "/" in v])
        dumped = json.dumps(out)
        for word in (PROFILE, "also", "then", "hedge-stack", "false_positive", D1, ledger.span_hash("4b", "also")):
            self.assertNotIn(word, dumped)

    def test_only_ruleset_rule_ids(self):  # a hand-made line could carry any string as its rule
        evs = sample() + [fired("secret-client-name", "x")]
        m = kaizen.rule_metrics(evs, CFG, NOW)
        self.assertEqual(m["secret-client-name"]["fires"], 1)  # the local report still sees it
        self.assertNotIn("secret-client-name", json.dumps(kaizen.share(m, CFG, "1.0.0")))


class When(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(kaizen.parse_when("2026-10-01"), "2026-10-01T00:00:00+00:00")
        self.assertEqual(kaizen.parse_when("2026-10-01T10:30:00+10:00"), "2026-10-01T00:30:00+00:00")
        self.assertEqual(kaizen.parse_when("2026-10-01T10:30"), "2026-10-01T10:30:00+00:00")  # naive = UTC
        with self.assertRaises(ValueError):
            kaizen.parse_when("last tuesday")


def cli(*args, cwd: Path, env: dict | None = None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    e["PYTHONPATH"] = str(REPO / "lib")
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=cwd, capture_output=True, text=True,
                          env=e)


class Cli(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()
        self.dir = self.root / ".plainspoken" / "ledger"
        self.settings = {"ledger_dir": self.dir, "root": self.root, "excerpts": False}

    def write(self, events):
        for e in events:
            ledger.append(e, self.settings)

    def test_empty_ledger_exits_0(self):
        r = cli("kaizen", "report", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no kaizen events yet", r.stdout)

    def test_bad_lines_counted_and_exit_0(self):
        self.write(sample())
        month = self.dir / "2026-10.jsonl"
        good = month.read_text(encoding="utf-8").splitlines()[0]
        with month.open("a", encoding="utf-8") as fh:
            fh.write('{"v": 2, "id": "0000000000000000"}\n')  # a future schema
            fh.write(good[:40])  # a truncated last line, no newline
        r = cli("kaizen", "report", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2 unreadable ledger lines", r.stdout)
        self.assertIn("4b", r.stdout)

    def test_only_bad_lines(self):
        self.dir.mkdir(parents=True)
        (self.dir / "2026-10.jsonl").write_text("not json\n", encoding="utf-8")
        r = cli("kaizen", "report", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no kaizen events yet", r.stdout)
        self.assertIn("1 unreadable ledger line", r.stdout)

    def test_since_filters_by_ts(self):
        self.write([fired("4b", "old", ts="2026-09-20T09:00:00+00:00"),
                    fired("2b", "new", ts="2026-10-02T09:00:00+00:00")])
        r = cli("kaizen", "report", "--since", "2026-10-01", "--json", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["rules"]["2b"]["fires"], 1)
        self.assertEqual(data["rules"]["4b"]["fires"], 0)
        self.assertEqual(data["window"]["since"], "2026-10-01T00:00:00+00:00")
        r = cli("kaizen", "report", "--until", "2026-10-01", "--json", cwd=self.root)
        data = json.loads(r.stdout)
        self.assertEqual((data["rules"]["4b"]["fires"], data["rules"]["2b"]["fires"]), (1, 0))

    def test_bad_since_is_usage(self):
        r = cli("kaizen", "report", "--since", "soon", cwd=self.root)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--since", r.stderr)

    def test_share_is_anonymised(self):
        self.write(sample())
        r = cli("kaizen", "report", "--share", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        version = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        self.assertEqual(out["plainspoken"], version)
        keys = {k for k, _ in _walk(out) if k is not None}
        self.assertFalse(keys & FORBIDDEN_KEYS)
        self.assertFalse([v for _, v in _walk(out) if isinstance(v, str) and "/" in v])
        self.assertNotIn(PROFILE, r.stdout)
        self.assertNotIn(str(self.root), r.stdout)

    def test_share_drops_non_ruleset_rules(self):
        self.write(sample() + [fired("secret-client-name", "x")])
        r = cli("kaizen", "report", "--share", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("secret-client-name", r.stdout)
        self.assertIn('"4b"', r.stdout)

    def test_bad_friction_line_counts_as_unreadable(self):
        self.write(sample())
        ledger.friction("agent_handback", "plainspoken:tells-judge", "", {**self.settings, "capture": True})
        with (self.dir / "friction.jsonl").open("a", encoding="utf-8") as fh:
            fh.write("{broken\n")
        r = cli("kaizen", "report", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 unreadable ledger line (skipped)", r.stdout)
        self.assertIn("friction: agent_handback 1", r.stdout)
        self.assertEqual(json.loads(cli("kaizen", "report", "--json", cwd=self.root).stdout)["bad_lines"], 1)

    def test_symlinked_ledger_folder_reads_nothing(self):
        real = self.root / "elsewhere"
        self.write([])
        ledger.append(fired("4b", "x"), {**self.settings, "ledger_dir": real})
        ledger.friction("skill", "s", "d", {**self.settings, "ledger_dir": real, "capture": True})
        (self.root / ".plainspoken").mkdir()
        self.dir.symlink_to(real)
        r = cli("kaizen", "report", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no kaizen events yet", r.stdout)
        self.assertIn("friction: none", r.stdout)

    def test_broken_ruleset_is_one_line_exit_2(self):
        bad = self.root / "rules.toml"
        bad.write_text("version = [unterminated\n", encoding="utf-8")
        for extra in ((), ("--share",), ("--json",)):
            r = cli("kaizen", "report", *extra, cwd=self.root, env={"PLAINSPOKEN_RULES": str(bad)})
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
            self.assertTrue(r.stderr.startswith("plainspoken: kaizen report: "), r.stderr)
            self.assertEqual(r.stdout, "")

    def test_table(self):
        self.write(sample())
        r = cli("kaizen", "report", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("missed patterns", r.stdout)
        self.assertNotIn(PROFILE, r.stdout)


if __name__ == "__main__":
    unittest.main()
