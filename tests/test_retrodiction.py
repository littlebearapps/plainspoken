"""Retrodiction. Backfilled from a host engine's real history, would `calibrate` have
proposed the rule changes the host's owner actually made?

The fixture (`tests/fixtures/kaizen/retro/ledger.jsonl`, provenance in its README) is the host's rules-v3 lint of 18
articles, 14 of them published, plus the one override recorded before the decisions: the 12f MATTR BLOCK on an
unpublished article dismissed as `unfixable` ("removal-only fixes can't raise MATTR"). The owner's v4 decisions
(2026-09-27) were:
1. the per-word transition-density WARNs for "then", "so" and "now" became total-only (`density_total_only`);
2. the MATTR floor went from BLOCK to WARN (`mattr_blocking = false`);
3. FAQ sections got a relaxed staccato check (`staccato_faq_short_run`).

The simulation starts from a v3 copy of today's ruleset (those three values put back) and runs the real
`calibrate.run` against it once a cycle (cycle n at 2026-10-01 + 28·(n−1) days). A proposal that matches a v4
decision is approved and applied to the copy with the real `proposals.apply`; every other proposal is rejected,
because the owner didn't make that change. Nothing here tunes the engine to the history: what calibrate proposes is
recorded as it is.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from plainspoken import calibrate, config, ledger, proposals, rulesedit
from plainspoken.registry import load_config
from scripts.dev import backfill_history
from tests.test_calibrate import shipped_hashes

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "data" / "rules.toml"
FIXTURE = REPO / "tests" / "fixtures" / "kaizen" / "retro" / "ledger.jsonl"
TOTAL_ONLY = 'density_total_only = [\n  "then",\n  "so",\n  "now",\n]'
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
CYCLES = 3
V4_TERMS = {"then", "so", "now"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- the backfill script -----------------------------------------------------------------------------------------

TEXT = """---
title: A test
---
Intro line here. Then more.

## Why it matters?

Some prose that runs on.

## FAQ

### Is this a question?

Short. Answer. Here.
"""


def finding(rule, severity, line, excerpt, message="m"):
    return {"rule": rule, "severity": severity, "line": line, "excerpt": excerpt, "message": message}


THEN = finding("4b", "WARN", 4, "then", "“then” opens 4 sentences (max 3)")
MATTR = finding("12f", "BLOCK", 0, "mattr 0.400", "MATTR-500 0.400 < 0.46 — vary the vocabulary")
LINT_0 = [THEN, finding("7d", "WARN", 12, "Is this a question?", "No sentence over 25 words in this section"),
          finding("12d", "WARN", 8, "Some prose that runs on.", "4+ consecutive paragraphs of near-identical length"),
          MATTR, finding("6", "CANDIDATE", 14, "Short. Answer. Here.", "Three-item list — judge J2 decides")]
LINT_1 = [THEN, MATTR]


class BackfillBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="plainspoken-backfill-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        sha_text = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
        for n, findings in enumerate((LINT_0, LINT_1)):
            (self.tmp / f"host-{n}.md").write_text(TEXT, encoding="utf-8")
            (self.tmp / f"host-{n}.json").write_text(json.dumps(
                {"article": f"docs/host-{n}.md", "article_sha256": sha_text, "findings": findings}), encoding="utf-8")
        self.manifest = {
            "ruleset_version": "3", "profile": "host",
            "ts": {"lint": "2026-09-27T00:00:00+00:00", "publish": "2026-09-27T01:00:00+00:00",
                   "override": "2026-09-27T02:00:00+00:00"},
            "articles": [{"lint": "host-0.json", "text": "host-0.md", "published": True},
                         {"lint": "host-1.json", "text": "host-1.md", "published": False}],
            "overrides": [{"article": 1, "rule": "12f", "metric": "mattr", "outcome": "dismissed",
                           "kind": "unfixable", "reason": "removal-only fixes can't raise MATTR"}]}
        self.out = self.tmp / "out" / "ledger.jsonl"
        self.out.parent.mkdir()

    def run_script(self, manifest=None) -> tuple[int, str, str]:
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(manifest or self.manifest), encoding="utf-8")
        return self.run_on(path)

    def run_on(self, path: Path) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = backfill_history.main(["--manifest", str(path), "--out", str(self.out)])
        return code, out.getvalue(), err.getvalue()

    def events(self) -> list[dict]:
        return [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]


class Backfill(BackfillBase):
    def test_expected_events(self):
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        before = sorted(p.relative_to(self.tmp) for p in self.tmp.rglob("*"))
        code, out, _ = self.run_on(path)
        self.assertEqual(code, 0)
        self.assertIn("2 articles (1 published): 6 fired, 3 survived_publish, 0 judge, 0 justify, 1 override; "
                      "10 events", out)
        after = sorted(p.relative_to(self.tmp) for p in self.tmp.rglob("*"))
        self.assertEqual(set(after) - set(before), {Path("out/ledger.jsonl")})  # writes nothing but --out
        doc0, doc1 = ledger.label_id("article-0"), ledger.label_id("article-1")
        got = [(e["doc_id"], e["event"], e["actor"], e["outcome"], e["rule"], e["severity"], e["facets"], e["ts"])
               for e in self.events()]
        lint_ts, pub_ts, ov_ts = (self.manifest["ts"][k] for k in ("lint", "publish", "override"))
        self.assertEqual(got, [
            (doc0, "backfill", "lint", "fired", "4b", "WARN", {"term": "then", "section": "intro"}, lint_ts),
            (doc0, "backfill", "lint", "fired", "7d", "WARN", {"section": "faq", "form": "no-long"}, lint_ts),
            (doc0, "backfill", "lint", "fired", "12d", "WARN", {"section": "question"}, lint_ts),
            (doc0, "backfill", "lint", "fired", "12f", "BLOCK", {"metric": "mattr"}, lint_ts),
            (doc0, "backfill", "publish", "survived_publish", "4b", "WARN", {"term": "then", "section": "intro"},
             pub_ts),
            (doc0, "backfill", "publish", "survived_publish", "7d", "WARN", {"section": "faq", "form": "no-long"},
             pub_ts),
            (doc0, "backfill", "publish", "survived_publish", "12d", "WARN", {"section": "question"}, pub_ts),
            (doc1, "backfill", "lint", "fired", "4b", "WARN", {"term": "then", "section": "intro"}, lint_ts),
            (doc1, "backfill", "lint", "fired", "12f", "BLOCK", {"metric": "mattr"}, lint_ts),
            (doc1, "override", "human", "dismissed", "12f", "BLOCK", {"metric": "mattr", "kind": "unfixable"}, ov_ts),
        ])
        events = self.events()
        for e in events:
            self.assertEqual(ledger.validate(e), [])
            self.assertEqual((e["ruleset_version"], e["profile"]), ("3", "host"))
            self.assertNotIn("excerpt", e)
        fired_mattr = next(e for e in events if e["doc_id"] == doc1 and e["rule"] == "12f" and e["outcome"] == "fired")
        override = events[-1]
        self.assertEqual(override["span_hash"], fired_mattr["span_hash"])  # the dismissal is on the fired span
        self.assertEqual(override["reason"], "removal-only fixes can't raise MATTR")
        self.assertTrue(all("reason" not in e for e in events[:-1]))  # the schema allows no reason on backfill

    def test_no_text_or_path_in_the_output(self):
        self.assertEqual(self.run_script()[0], 0)
        raw = self.out.read_text(encoding="utf-8")
        for text in ("Intro line", "Some prose", "Is this a question", "host-0", "docs/", "mattr 0.400"):
            self.assertNotIn(text, raw)

    def test_single_ts_for_every_family(self):
        self.manifest["ts"] = "2026-09-27T00:00:00+00:00"
        self.assertEqual(self.run_script()[0], 0)
        self.assertEqual({e["ts"] for e in self.events()}, {"2026-09-27T00:00:00+00:00"})

    def test_no_private_capture_helpers(self):  # backfill (and overrides) use capture's public names
        for path in (REPO / "scripts" / "dev" / "backfill_history.py", REPO / "lib" / "plainspoken" / "overrides.py"):
            with self.subTest(path=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"capture\._[a-z]")

    def test_counts_are_of_the_events_written(self):  # counted after distinct, not before
        self.manifest["overrides"] = self.manifest["overrides"] * 2  # the same override twice: one event
        code, out, _ = self.run_script()
        self.assertEqual(code, 0)
        self.assertEqual(sum(1 for e in self.events() if e["event"] == "override"), 1)
        self.assertIn("1 override; 10 events", out)

    def test_a_ts_that_isnt_the_ledgers_form_names_its_family(self):  # _ts is checked
        for ts in ("2026-09-27", {"lint": "2026-09-27T00:00:00Z", "publish": "x", "override": "y"}):
            with self.subTest(ts=ts):
                code, _, err = self.run_script({**self.manifest, "ts": ts})
                self.assertEqual(code, 2)
                self.assertIn("ts: ", err)
                self.assertIn("lint", err)
                self.assertIn("YYYY-MM-DDTHH:MM:SS+00:00", err)

    def test_blank_doc_sha_drops_the_text_hash(self):  # optional, for a fixture that keeps none
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            code = backfill_history.main(["--manifest", str(path), "--out", str(self.out), "--blank-doc-sha"])
        self.assertEqual(code, 0)
        events = self.events()
        self.assertEqual({e["doc_sha"] for e in events}, {None})
        self.assertTrue(all(ledger.validate(e) == [] for e in events))
        self.assertEqual(len(events), 10)

    def test_bad_input_exits_2_and_writes_nothing(self):
        bad = [{**self.manifest, "overrides": [{**self.manifest["overrides"][0], "rule": "1"}]},  # matches nothing
               {**self.manifest, "overrides": [{**self.manifest["overrides"][0], "article": 5}]},
               {**self.manifest, "articles": [{"lint": "missing.json", "text": "host-0.md", "published": True}]},
               {**self.manifest, "articles": [{"lint": "host-0.json", "text": "host-0.md"}]},
               {**self.manifest, "ts": {"lint": "2026-09-27T00:00:00+00:00"}},
               {k: v for k, v in self.manifest.items() if k != "profile"}]
        for m in bad:
            with self.subTest(m=m):
                code, out, err = self.run_script(m)
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith("backfill_history: "))
                self.assertFalse(self.out.exists())


class BackfillProfiles(BackfillBase):
    """Per-domain profiles without doc-id collisions (`--profile-map glob=profile`)."""
    CONSULTING = REPO / "tests" / "fixtures" / "profiles" / "consulting_like.toml"

    def run_map(self, *pairs) -> tuple[int, str, str]:
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        args = ["--manifest", str(path), "--out", str(self.out)]
        for pair in pairs:
            args += ["--profile-map", pair]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = backfill_history.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_doc_ids_are_prefixed_by_the_mapped_profile(self):
        code, _, err = self.run_map("host-0.md=default", f"host-1*={self.CONSULTING}")
        self.assertEqual(code, 0, err)
        consulting_name = "consulting_like"
        by_doc = {}
        for e in self.events():
            by_doc.setdefault(e["doc_id"], set()).add(e["profile"])
        self.assertEqual(by_doc, {ledger.label_id("default:article-0"): {"default"},
                                  ledger.label_id(f"{consulting_name}:article-1"): {consulting_name}})

    def test_two_domains_never_share_a_doc_id(self):
        self.assertEqual(self.run_map("*=default")[0], 0)
        first = {e["doc_id"] for e in self.events()}
        self.assertEqual(self.run_map(f"*={self.CONSULTING}")[0], 0)
        self.assertEqual(first & {e["doc_id"] for e in self.events()}, set())

    def test_an_article_no_glob_matches_keeps_the_manifest_profile(self):
        self.assertEqual(self.run_map("host-0.md=default")[0], 0)
        doc1 = [e for e in self.events() if e["doc_id"] == ledger.label_id("host:article-1")]
        self.assertTrue(doc1)
        self.assertEqual({e["profile"] for e in doc1}, {"host"})

    def test_host_frontmatter_faqs_are_faq_under_the_mapped_profile(self):
        text = "---\ntitle: A test\nfaqs:\n  - q: Is it?\n    a: Yes.\n---\nIntro line here.\n"
        (self.tmp / "host-0.md").write_text(text, encoding="utf-8")
        sha_text = hashlib.sha256(text.encode("utf-8")).hexdigest()
        (self.tmp / "host-0.json").write_text(json.dumps({"article": "docs/host-0.md", "article_sha256": sha_text,
                                                          "findings": [finding("7d", "WARN", 4, "Is it?")]}),
                                              encoding="utf-8")
        self.manifest["articles"] = self.manifest["articles"][:1]
        self.manifest["overrides"] = []
        self.assertEqual(self.run_map(f"*={self.CONSULTING}")[0], 0)
        (e, kept) = [x for x in self.events() if x["rule"] == "7d"]
        self.assertEqual(e["facets"]["section"], "faq")  # the profile's faq_frontmatter_key
        self.assertEqual(self.run_map("*=default")[0], 0)
        self.assertEqual([x["facets"]["section"] for x in self.events() if x["rule"] == "7d"][0], "intro")

    def test_bad_map_exits_2(self):
        for pair in ("no-equals-sign", "=default", "*=no-such-profile"):
            with self.subTest(pair=pair):
                code, _, err = self.run_map(pair)
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith("backfill_history: "), err)
                self.assertFalse(self.out.exists())


class BackfillVerdicts(BackfillBase):
    """The host's judge (J1–J4), justify and JR files become the events `merge` would have recorded."""
    QUOTE = "Some prose that runs on."

    def setUp(self):
        super().setUp()
        sha_text = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
        self.write("host-0.J1.judge.json", {"group": "J1", "article_sha256": sha_text, "verdicts": [
            {"rule": "18", "verdict": "fail", "severity": "WARN", "evidence": [{"quote": self.QUOTE, "line": 8}]},
            {"rule": "26", "verdict": "pass", "severity": "WARN", "evidence": []}]})
        self.write("host-0.J2.judge.json", {"group": "J2", "article_sha256": sha_text, "verdicts": [
            {"rule": "6", "verdict": "fail", "severity": "BLOCK",
             "evidence": [{"quote": "Short. Answer. Here.", "line": 14}]}]})
        justify = self.write("host-0.justify.json", {"article_sha256": sha_text, "items": [
            {"rule": "12d", "kind": "format", "reason": "the FAQ answers are capsules of a fixed size"}]})
        self.write("host-0.JR.judge.json", {"group": "JR", "article_sha256": sha_text,
                                            "justify_sha256": hashlib.sha256(justify).hexdigest(), "verdicts": [
            {"rule": "12d", "verdict": "accept", "reason": "they are capsules"}]})
        self.manifest["articles"][0].update({"judges": ["host-0.J1.judge.json", "host-0.J2.judge.json"],
                                             "justify": "host-0.justify.json", "jr": "host-0.JR.judge.json"})

    def write(self, name, obj) -> bytes:
        data = json.dumps(obj).encode("utf-8")
        (self.tmp / name).write_bytes(data)
        return data

    def test_verdicts_become_backfill_events(self):
        code, out, err = self.run_script()
        self.assertEqual(code, 0, err)
        self.assertIn("3 judge, 2 justify", out)
        doc0 = ledger.label_id("article-0")
        got = sorted((e["actor"], e["outcome"], e["rule"], e["severity"], json.dumps(e["facets"], sort_keys=True))
                     for e in self.events() if e["actor"] in ("judge:J1", "judge:J2", "human", "jr")
                     and e["doc_id"] == doc0)
        self.assertEqual(got, sorted([
            ("judge:J1", "fired", "18", "WARN", '{"section": "question"}'),
            ("judge:J1", "passed", "26", "WARN", '{"agree": true}'),  # 26 is lint+judge; no lint finding
            ("judge:J2", "fired", "6", "BLOCK", '{"agree": true, "section": "faq"}'),
            ("human", "justified:format", "12d", "WARN", "{}"),
            ("jr", "jr_accept", "12d", "WARN", '{"kind": "format"}')]))
        for e in self.events():
            self.assertEqual(ledger.validate(e), [])
            if e["actor"] != "human" or e["event"] != "override":
                self.assertEqual(e["event"], "backfill")
            self.assertNotIn("reason", e) if e["event"] == "backfill" else None
        fire = next(e for e in self.events() if e["rule"] == "18")
        self.assertEqual(fire["span_hash"], ledger.span_hash("18", self.QUOTE))
        raw = self.out.read_text(encoding="utf-8")
        for text in ("capsules", self.QUOTE, "Short. Answer"):
            self.assertNotIn(text, raw)  # no reason or evidence is stored

    def test_metrics_read_the_backfilled_verdicts(self):
        self.assertEqual(self.run_script()[0], 0)
        from plainspoken import kaizen
        m = kaizen.rule_metrics(self.events(), load_config(), START)
        self.assertEqual((m["12d"]["jr_accept"], m["12d"]["justified"], m["12d"]["kept_docs"]), (1, 1, 1))
        self.assertEqual(m["6"]["agreement"], 1.0)  # a backfilled judge verdict counts for agreement
        self.assertEqual(m["18"]["fires"], 1)

    def test_a_verdict_file_for_another_version_exits_2(self):
        self.write("host-0.J1.judge.json", {"group": "J1", "article_sha256": "c" * 64, "verdicts": []})
        code, _, err = self.run_script()
        self.assertEqual(code, 2)
        self.assertIn("another version", err)
        self.assertFalse(self.out.exists())

    def test_a_jr_file_for_another_justify_file_exits_2(self):
        sha_text = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
        self.write("host-0.JR.judge.json", {"group": "JR", "article_sha256": sha_text, "justify_sha256": "d" * 64,
                                            "verdicts": [{"rule": "12d", "verdict": "accept", "reason": "x"}]})
        code, _, err = self.run_script()
        self.assertEqual(code, 2)
        self.assertIn("justify", err)

    def test_bad_group_or_verdict_exits_2(self):
        sha_text = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
        for body in ({"group": "J9", "article_sha256": sha_text, "verdicts": []},
                     {"group": "J1", "article_sha256": sha_text, "verdicts": [{"rule": "18", "verdict": "maybe"}]}):
            with self.subTest(body=body):
                self.write("host-0.J1.judge.json", body)
                self.assertEqual(self.run_script()[0], 2)


# --- the retrodiction ----------------------------------------------------------------------------------------------

def v3_text() -> str:
    """Today's ruleset with the three v4 decisions undone (rulesedit can't empty a list, so that one is a text
    replacement, as in the proposal tests)."""
    text = rulesedit.apply_edits(RULES.read_text(encoding="utf-8"), [
        {"kind": "set_threshold", "table": "default", "key": "mattr_blocking", "old": False, "new": True},
        {"kind": "set_threshold", "table": "default", "key": "staccato_faq_short_run", "old": 7, "new": 5}])
    assert TOTAL_ONLY in text, "data/rules.toml's density_total_only list changed shape"
    return text.replace(TOTAL_ONLY, "density_total_only = []")


def is_v4(p: dict) -> bool:
    """The proposal makes one of the owner's v4 decisions (and nothing else)."""
    edits = p["edits"]
    if len(edits) != 1:
        return False
    e = edits[0]
    if p["rule"] == "12f" and p["action"] == "demote":
        return e.get("key") == "mattr_blocking" and e.get("new") is False
    if p["rule"] == "4b":
        return e["kind"] == "list_add" and e["list"] == "density_total_only" and set(e["values"]) <= V4_TERMS
    if p["rule"] == "7d" and p["action"] == "loosen":
        return e.get("key") == "staccato_faq_short_run"
    return False


class Retrodiction(unittest.TestCase):
    """One simulation for the whole class; each test reads what it recorded."""

    @classmethod
    def setUpClass(cls):
        cls.shipped = {**shipped_hashes(), "data/kaizen.toml": sha(calibrate.DEFAULT)}
        cls.tmp = Path(tempfile.mkdtemp(prefix="plainspoken-retro-test-"))
        try:
            cls._simulate()
        except BaseException:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _simulate(cls):
        root = cls.tmp / "project"
        root.mkdir()
        (root / ".git").mkdir()
        cls.copy = cls.tmp / "rules" / "rules.toml"
        cls.copy.parent.mkdir()
        cls.copy.write_text(v3_text(), encoding="utf-8")
        cls.v3 = load_config(cls.copy)
        with mock.patch.dict(os.environ, {"PLAINSPOKEN_RULES": str(cls.copy)}):
            settings = {**config.kaizen_settings(root, {}), **calibrate.load_settings(cfg=cls.v3)}
            for line in FIXTURE.read_text(encoding="utf-8").splitlines():
                ledger.append(json.loads(line), settings)
            cls.cycles: list[dict] = []
            for n in range(1, CYCLES + 1):
                now = START + timedelta(days=28 * (n - 1))
                made = calibrate.run(root, settings, now, corpus=[])
                cycle = {"n": n, "now": now, "proposals": made, "decisions": {}, "applied": [], "refused": {}}
                for p in made:
                    outcome = "approved" if is_v4(p) else "rejected"
                    cycle["decisions"][p["id"]] = outcome
                    ledger.append(ledger.make_event(
                        event="decision", actor="human", outcome=outcome, ruleset_version=p["ruleset_version"],
                        profile="host", proposal=p["id"], facets={"by": "owner"},
                        reason="v4 decision" if outcome == "approved" else "not a v4 decision", ts=now), settings)
                for p in made:  # in calibrate's ranked order, as a person would work down the list
                    if cycle["decisions"][p["id"]] == "approved":
                        try:
                            proposals.apply(p["id"], root, settings, rules_path=cls.copy, now=now)
                            cycle["applied"].append(p["id"])
                        except proposals.Refused as e:
                            cycle["refused"][p["id"]] = str(e)
                cls.cycles.append(cycle)
            cls.final = load_config(cls.copy)

    def all_proposals(self):
        return [(c, p) for c in self.cycles for p in c["proposals"]]

    def test_fixture_matches_the_v3_starting_point(self):
        self.assertTrue(self.v3._thresholds["default"]["mattr_blocking"])
        self.assertEqual(self.v3.lists["density_total_only"], [])
        self.assertEqual(self.v3._thresholds["default"]["staccato_faq_short_run"], 5)

    def test_a_cycle_1_demotes_the_mattr_floor(self):
        first = self.cycles[0]["proposals"]
        mattr = [p for p in first if p["rule"] == "12f"]
        self.assertEqual(len(mattr), 1)
        p = mattr[0]
        self.assertEqual((p["trigger"], p["action"]), ("stuck", "demote"))
        self.assertEqual(p["edits"], [{"kind": "set_threshold", "table": "default", "key": "mattr_blocking",
                                       "old": True, "new": False}])
        self.assertIn(p["id"], self.cycles[0]["applied"])
        self.assertFalse(self.final._thresholds["default"]["mattr_blocking"])

    def test_b_4b_is_proposed_in_cycle_2(self):
        """The kept trigger finds the decision: per-word "then" WARNs kept to publication in 2 published articles
        and "so" in 2 (3 distinct articles), so the narrow term knob proposes exactly the two words that fired. Since
        12d got its FAQ knob, cycle 1's third slot (`max_proposals = 3`) goes to 12d's narrow FAQ candidate, which has
        more evidence documents, so 4b comes one cycle later."""
        self.assertFalse(any(p["rule"] == "4b" for p in self.cycles[0]["proposals"]))
        p = next(p for p in self.cycles[1]["proposals"] if p["rule"] == "4b")
        self.assertEqual((p["trigger"], p["action"]), ("kept", "loosen"))
        self.assertEqual(p["edits"], [{"kind": "list_add", "list": "density_total_only", "values": ["so", "then"]}])

    def test_b_density_total_only_gains_then_and_so(self):
        """Both v4 approvals apply: the 12f demote in cycle 1 and the 4b list_add in cycle 2. Nothing is refused."""
        second = self.cycles[1]
        p = next(p for p in second["proposals"] if p["rule"] == "4b")
        self.assertIn(p["id"], second["applied"])
        self.assertEqual([c["refused"] for c in self.cycles], [{}] * CYCLES)
        self.assertEqual(self.final.lists["density_total_only"], ["so", "then"])  # "now" never fired

    def test_applied_evidence_is_spent(self):
        """Once the 12f demote and the 4b list_add are applied, their v3 evidence no longer counts, so
        neither rule is proposed again (before spending, cycle 2 re-raised the spent 12f dismissal as a review)."""
        self.assertNotIn("12f", [p["rule"] for c in self.cycles[1:] for p in c["proposals"]])
        self.assertNotIn("4b", [p["rule"] for c in self.cycles[2:] for p in c["proposals"]])

    def test_12d_kept_in_faqs_turns_the_faq_knob(self):
        """Observed, not tuned: 5 of the 9 kept 12d spans sit in FAQ sections, so the narrow FAQ knob fits.
        The owner made no 12d change in v4, so it's rejected, and the broad 12d knob never comes up."""
        observed = [(c["n"], p["trigger"], p["action"], p["edits"]) for c, p in self.all_proposals()
                    if p["rule"] == "12d"]
        self.assertEqual(observed, [(1, "kept", "loosen", [{"kind": "set_threshold", "table": "default",
                                                           "key": "paragraph_uniform_faq_run", "old": 4, "new": 5}])])

    def test_later_cycles_as_observed(self):
        """Observed, not tuned: cycle 2 brings the two kept candidates `max_proposals = 3` cut from cycle 1 (4b, a v4
        decision, and 7's broad knob, rejected); cycle 3 has nothing left outside its cooldown."""
        observed = [[(p["rule"], p["trigger"], p["action"], p["edits"]) for p in c["proposals"]] for c in self.cycles]
        self.assertEqual(observed[1], [
            ("4b", "kept", "loosen", [{"kind": "list_add", "list": "density_total_only", "values": ["so", "then"]}]),
            ("7", "kept", "loosen", [{"kind": "set_threshold", "table": "default", "key": "uniform_sentence_run",
                                      "old": 5, "new": 6}])])
        self.assertEqual(observed[2], [])

    def test_c_the_7d_outcome_is_what_the_data_supports(self):
        """Observed, not tuned. The host's 7d WARNs fire in 16 of the 18 articles, mostly the "no sentence over 25
        words" form, and only one span (in one published article) sits under a heading plainspoken's parser reads as
        an FAQ (the host's v3 engine didn't check frontmatter FAQs, so there was no FAQ evidence from them). So the
        FAQ knob's "at least half the spans" test fails and the `form = no-long` knob wins: cycle 1 proposes lowering
        `staccato_long_sentence` 25 → 22, which the owner didn't do (rejected), and the 60-day cooldown keeps 7d quiet
        through cycle 3. Calibrate never proposes the FAQ-specific relaxation the owner made."""
        observed = [(c["n"], p["trigger"], p["action"], p["edits"]) for c, p in self.all_proposals()
                    if p["rule"] == "7d"]
        self.assertEqual(observed, [(1, "kept", "loosen", [{"kind": "set_threshold", "table": "default",
                                                           "key": "staccato_long_sentence", "old": 25, "new": 22}])])
        self.assertFalse(any(e.get("key") == "staccato_faq_short_run" for _, p in self.all_proposals()
                             for e in p["edits"]))
        self.assertEqual(self.final._thresholds["default"]["staccato_faq_short_run"], 5)

    def test_no_rejected_proposal_returns_within_its_cooldown(self):
        cooldown = timedelta(days=calibrate.load_settings(cfg=self.v3)["triggers"]["cooldown_days"])
        rejected = [(c["now"], p["rule"], p["action"]) for c, p in self.all_proposals()
                    if c["decisions"][p["id"]] == "rejected"]
        self.assertTrue(rejected)
        for c, p in self.all_proposals():
            for when, rule, action in rejected:
                if (p["rule"], p["action"]) == (rule, action) and when < c["now"]:
                    self.assertGreaterEqual(c["now"] - when, cooldown, f"{rule} {action} came back in cycle {c['n']}")

    def test_at_most_max_proposals_per_cycle(self):
        for c in self.cycles:
            self.assertLessEqual(len(c["proposals"]), 3)

    def test_the_real_ruleset_is_untouched(self):
        # the ruleset, rubrics, default profile and kaizen.toml all stay as shipped
        self.assertEqual({**shipped_hashes(), "data/kaizen.toml": sha(calibrate.DEFAULT)}, self.shipped)
        self.assertEqual(load_config(RULES).lists["density_total_only"], ["then", "so", "now"])


class Fixture(unittest.TestCase):
    def test_fixture_holds_hashes_and_ruleset_words_only(self):
        cfg = load_config()
        words = {w.lower() for items in cfg.lists.values() for w in items}
        events = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(events)
        docs = {ledger.label_id(f"article-{n}") for n in range(18)}
        for e in events:
            self.assertEqual(ledger.validate(e), [])
            self.assertNotIn("excerpt", e)
            self.assertIn(e["doc_id"], docs)
            self.assertEqual((e["ruleset_version"], e["profile"]), ("3", "host"))
            if "term" in e["facets"]:
                self.assertIn(e["facets"]["term"], words)
        self.assertEqual([e["reason"] for e in events if "reason" in e], ["removal-only fixes can't raise MATTR"])
        published = {e["doc_id"] for e in events if e["outcome"] == "survived_publish"}
        self.assertEqual(len(published), 14)  # every published article kept a WARN span (README: 14)
        self.assertFalse(any(e["outcome"] == "survived_publish" and e["severity"] != "WARN" for e in events))


if __name__ == "__main__":
    unittest.main()
