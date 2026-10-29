"""Calibrate turns ledger evidence into at most 3 proposals (triggers → candidates → proposals with a
diff and a corpus effect). It never edits the ruleset, the rubrics or a profile."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from plainspoken import calibrate, calibrate_knobs, config, kaizen, ledger, proposals, rulesedit
from plainspoken.profile import default as default_profile
from plainspoken.registry import load_config

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "data" / "rules.toml"
CFG = load_config()
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
RECENT = NOW - timedelta(days=30)   # a ledger too young for the dormant trigger
OLD = NOW - timedelta(days=100)     # old enough
SHA = "a" * 64
DOCS = [ledger.label_id(f"doc-{i}") for i in range(30)]
TOTAL_ONLY = 'density_total_only = [\n  "then",\n  "so",\n  "now",\n]'


def ts(when: datetime) -> str:
    return when.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def ev(event, actor, outcome, rule, severity="WARN", doc=0, span="x", when=None, profile="default", **kw):
    return ledger.make_event(event=event, actor=actor, outcome=outcome, ruleset_version=CFG.version, profile=profile,
                             rule=rule, severity=severity, doc_id=None if doc is None else DOCS[doc], doc_sha=SHA,
                             span_hash=None if span is None else ledger.span_hash(str(rule), span),
                             ts=ts(when or NOW - timedelta(days=2)), **kw)


def fired(rule, span, doc=0, severity="WARN", **kw):
    return ev("lint", "lint", "fired", rule, severity, doc, span, **kw)


def fp_events(rule="2b", fires=25, dismissed=4) -> list[dict]:
    out = [fired(rule, f"s{i}", doc=i % 10) for i in range(fires)]
    out += [ev("override", "human", "dismissed", rule, "WARN", i % 10, f"s{i}", facets={"kind": "false_positive"},
               reason="fine here") for i in range(dismissed)]
    return out


def kept_4b_events() -> list[dict]:
    out = []
    for doc, term in ((1, "then"), (2, "then"), (3, "so")):
        out.append(fired("4b", term, doc=doc, facets={"term": term}))
        out.append(ev("publish", "publish", "survived_publish", "4b", "WARN", doc, term, facets={"term": term}))
    return out


def stuck_12f_events() -> list[dict]:
    span = "mattr"
    return [fired("12f", span, doc=4, severity="BLOCK", facets={"metric": "mattr"}),
            ev("override", "human", "dismissed", "12f", "BLOCK", 4, span,
               facets={"metric": "mattr", "kind": "unfixable"}, reason="removal-only fixes can't raise MATTR")]


def decision(pid, outcome, when, by="Robin"):
    return ledger.make_event(event="decision", actor="human", outcome=outcome, ruleset_version=CFG.version,
                             profile="default", proposal=pid, facets={"by": by}, reason="a reason", ts=ts(when))


def applied(rule, when):
    return ledger.make_event(event="apply", actor="engine", outcome="applied", ruleset_version=CFG.version,
                             profile="default", rule=rule, proposal="KZ-20260101-abcdef", ts=ts(when))


def ruleset_text(*, mattr_blocking=False, total_only=True) -> str:
    text = RULES.read_text(encoding="utf-8")
    if mattr_blocking:
        text = rulesedit.apply_edits(text, [{"kind": "set_threshold", "table": "default", "key": "mattr_blocking",
                                             "old": False, "new": True}])
    if not total_only:
        if TOTAL_ONLY not in text:  # not `assert`: the fixture must hold under -O too
            raise AssertionError("data/rules.toml no longer has the density_total_only line this fixture edits")
        text = text.replace(TOTAL_ONLY, "density_total_only = []")
    return text


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="plainspoken-cal-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "project"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.settings = {**config.kaizen_settings(self.root, {}), **calibrate.load_settings()}

    def copy(self, **kw) -> Path:
        path = self.tmp / "rules" / "rules.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ruleset_text(**kw), encoding="utf-8")
        return path

    def cands(self, events, cfg=CFG, start=RECENT, now=NOW):
        metrics = kaizen.rule_metrics(events, cfg, now)
        return calibrate.candidates(metrics, events, cfg, self.settings, now, start)

    def write_ledger(self, events):
        for e in events:
            ledger.append(e, self.settings)


class Settings(unittest.TestCase):
    def test_shipped_settings(self):
        s = calibrate.load_settings()
        self.assertEqual(s["triggers"]["fp_min_fires"], 20)
        self.assertEqual(s["triggers"]["max_proposals"], 3)
        self.assertEqual(s["triggers"]["cooldown_days"], 60)
        rules = [k["rule"] for k in s["knobs"]]
        self.assertNotIn("21", rules)  # a judged rule has no threshold
        self.assertIn("23", rules)
        self.assertEqual(rules.index("4b"), 0)  # the narrow term knob comes first

    def write(self, text: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = tmp / "kaizen.toml"
        base = calibrate.DEFAULT.read_text(encoding="utf-8")
        path.write_text(base + text, encoding="utf-8")
        return path

    def test_unknown_rule(self):
        path = self.write('\n[[knobs]]\nrule = "99z"\ndirection = "loosen"\n'
                          'edit = { kind = "set_threshold", key = "filler_warn", step = 1 }\n')
        with self.assertRaisesRegex(ValueError, "unknown rule"):
            calibrate.load_settings(path)

    def test_unknown_threshold(self):
        path = self.write('\n[[knobs]]\nrule = "23"\ndirection = "loosen"\n'
                          'edit = { kind = "set_threshold", key = "no_such_key", step = 1 }\n')
        with self.assertRaisesRegex(ValueError, "unknown threshold"):
            calibrate.load_settings(path)

    def test_unknown_list(self):
        path = self.write('\n[[knobs]]\nrule = "4b"\nfacet = "term"\ndirection = "loosen"\n'
                          'edit = { kind = "list_add", list = "no_such_list" }\n')
        with self.assertRaisesRegex(ValueError, "unknown list"):
            calibrate.load_settings(path)


class Fp(TmpCase):
    def test_fp_loosens_with_the_broad_knob(self):
        cands = self.cands(fp_events())
        self.assertEqual([(c["rule"], c["trigger"], c["action"]) for c in cands], [("2b", "fp", "loosen")])
        p = calibrate.materialise(cands[0], None, CFG, None, [], NOW)
        self.assertEqual(p["edits"], [{"kind": "set_threshold", "table": "default", "key": "claude_warn_total",
                                       "old": 4, "new": 5}])
        self.assertEqual(p["bump"], "minor")
        self.assertRegex(p["id"], r"^KZ-20261014-[0-9a-f]{6}$")
        self.assertEqual(p["targets"], ["ruleset", "profile"])
        self.assertIn("-claude_warn_total = 4", p["diff"])
        self.assertIn("+claude_warn_total = 5", p["diff"])
        self.assertEqual(p["base_sha256"], hashlib.sha256(RULES.read_bytes()).hexdigest())
        self.assertEqual(p["effect"], {"corpus": "not measured (no corpus)", "golden": "not available until Phase 6"})
        self.assertEqual(p["evidence"]["fires"], 25)
        self.assertEqual(p["evidence"]["dismissed"], 4)
        self.assertNotIn("\n", p["summary"])

    def test_nineteen_fires_is_not_enough(self):
        self.assertEqual(self.cands(fp_events(fires=19)), [])

    def test_id_is_stable_for_the_same_edits(self):
        c = self.cands(fp_events())[0]
        a = calibrate.materialise(c, None, CFG, None, [], NOW)
        b = calibrate.materialise(c, None, CFG, None, [], NOW + timedelta(hours=1))
        self.assertEqual(a["id"], b["id"])

    def test_fp_on_a_lint_warn_rule_with_no_knob_shadows_it(self):
        cands = self.cands(fp_events(rule="13"))
        self.assertEqual([(c["rule"], c["action"]) for c in cands], [("13", "shadow")])
        p = calibrate.materialise(cands[0], None, CFG, None, [], NOW)
        self.assertEqual(p["edits"], [{"kind": "rule_field", "rule": "13", "field": "status", "old": None,
                                       "new": "shadow"}])

    def test_fp_on_a_judge_method_block_rule_demotes_its_severity(self):
        path = self.tmp / "judge-block.toml"  # no shipped judge-only rule is BLOCK, so make one
        path.write_text(rulesedit.apply_edits(RULES.read_text(encoding="utf-8"), [
            {"kind": "rule_field", "rule": "9", "field": "severity", "old": "WARN", "new": "BLOCK"}]), encoding="utf-8")
        cfg = load_config(path)
        cands = self.cands(fp_events(rule="9"), cfg=cfg)
        self.assertEqual([(c["rule"], c["action"]) for c in cands], [("9", "demote")])
        p = calibrate.materialise(cands[0], path, cfg, None, [], NOW)
        self.assertEqual(p["edits"], [{"kind": "rule_field", "rule": "9", "field": "severity", "old": "BLOCK",
                                       "new": "WARN"}])

    def test_fp_on_a_lint_judge_block_rule_is_a_review(self):
        for rule in ("2", "5b"):  # their lint checks hard-code BLOCK, so a severity edit would change nothing
            with self.subTest(rule=rule):
                cands = self.cands(fp_events(rule=rule))
                self.assertEqual([(c["rule"], c["action"]) for c in cands], [(rule, "review")])
                p = calibrate.materialise(cands[0], None, CFG, None, [], NOW)
                self.assertEqual(p["edits"], [])
                self.assertIn("lint check sets its severities in code", p["summary"])

    def test_fp_on_a_lint_judge_warn_rule_is_a_review(self):  # shadow is lint-only
        cands = self.cands(fp_events(rule="12"))
        self.assertEqual([(c["rule"], c["action"], c["edits"]) for c in cands], [("12", "review", [])])

    def test_fp_on_a_lint_block_rule_with_no_demote_knob_is_a_review(self):
        cands = self.cands(fp_events(rule="20"))  # a lint severity lives in code
        self.assertEqual([(c["rule"], c["action"]) for c in cands], [("20", "review")])
        p = calibrate.materialise(cands[0], None, CFG, None, [], NOW)
        self.assertEqual(p["edits"], [])
        self.assertEqual(p["targets"], [])
        self.assertIsNone(p["bump"])
        self.assertIn("in code", p["summary"])


class Kept(TmpCase):
    def test_kept_4b_terms_use_the_narrow_knob(self):
        path = self.copy(total_only=False)
        cfg = load_config(path)
        cands = self.cands(kept_4b_events(), cfg=cfg)
        self.assertEqual([(c["rule"], c["trigger"], c["action"]) for c in cands], [("4b", "kept", "loosen")])
        self.assertTrue(cands[0]["narrow"])
        p = calibrate.materialise(cands[0], path, cfg, None, [], NOW)
        self.assertEqual(p["edits"], [{"kind": "list_add", "list": "density_total_only", "values": ["so", "then"]}])
        self.assertEqual(p["targets"], ["ruleset"])

    def test_terms_already_listed_fall_back_to_the_broad_knob(self):
        cands = self.cands(kept_4b_events())  # the shipped list already has then and so
        p = calibrate.materialise(cands[0], None, CFG, None, [], NOW)
        self.assertEqual(p["edits"][0]["key"], "transition_single_max")
        self.assertFalse(cands[0]["narrow"])

    def kept_12d(self, sections):
        out = []
        for doc, section in enumerate(sections, start=1):
            out.append(fired("12d", f"run{doc}", doc=doc, facets={"section": section}))
            out.append(ev("publish", "publish", "survived_publish", "12d", "WARN", doc, f"run{doc}",
                          facets={"section": section}))
        return out

    def test_kept_12d_in_faqs_turns_the_faq_knob(self):
        cands = self.cands(self.kept_12d(["faq", "faq", "other"]))
        self.assertEqual([(c["rule"], c["action"], c["narrow"]) for c in cands], [("12d", "loosen", True)])
        p = calibrate.materialise(cands[0], None, CFG, None, [], NOW)
        self.assertEqual(p["edits"], [{"kind": "set_threshold", "table": "default", "key": "paragraph_uniform_faq_run",
                                       "old": 4, "new": 5}])
        self.assertEqual(p["targets"], ["ruleset", "profile"])

    def test_kept_12d_elsewhere_turns_the_broad_knob(self):
        cands = self.cands(self.kept_12d(["faq", "other", "question"]))
        p = calibrate.materialise(cands[0], None, CFG, None, [], NOW)
        self.assertEqual(p["edits"][0]["key"], "paragraph_uniform_run")
        self.assertFalse(cands[0]["narrow"])

    def test_two_docs_is_not_enough(self):
        self.assertEqual(self.cands(kept_4b_events()[:4], cfg=load_config(self.copy(total_only=False))), [])

    def test_a_block_rule_is_never_loosened_on_kept_evidence(self):
        events = []
        for d in range(5):
            events.append(fired("1", f"dash{d}", doc=d, severity="BLOCK"))
            events.append(ev("publish", "publish", "survived_publish", "1", "BLOCK", d, f"dash{d}"))
        self.assertEqual(self.cands(events), [])


class Stuck(TmpCase):
    def test_unfixable_mattr_block_demotes_through_the_knob_first(self):
        path = self.copy(mattr_blocking=True)
        cfg = load_config(path)
        cands = self.cands(fp_events() + stuck_12f_events(), cfg=cfg)
        self.assertEqual([(c["rule"], c["trigger"], c["action"]) for c in cands],
                         [("12f", "stuck", "demote"), ("2b", "fp", "loosen")])
        p = calibrate.materialise(cands[0], path, cfg, None, [], NOW)
        self.assertEqual(p["edits"], [{"kind": "set_threshold", "table": "default", "key": "mattr_blocking",
                                       "old": True, "new": False}])

    def test_already_demoted_is_a_review(self):
        cands = self.cands(stuck_12f_events())  # shipped: mattr_blocking is already false
        self.assertEqual([(c["rule"], c["action"]) for c in cands], [("12f", "review")])


class Spent(TmpCase):
    """A rule's evidence up to its latest applied proposal is spent; only later events count."""

    def test_stuck_before_an_applied_demote_doesnt_fire_again(self):
        events = stuck_12f_events()  # 2 days ago
        self.assertEqual([(c["rule"], c["trigger"]) for c in self.cands(events)], [("12f", "stuck")])
        events.append(applied("12f", NOW - timedelta(days=1)))
        self.assertEqual(self.cands(events), [])

    def test_new_evidence_after_the_apply_counts(self):
        later = NOW - timedelta(hours=12)
        events = stuck_12f_events() + [applied("12f", NOW - timedelta(days=1)),
                                       fired("12f", "mattr", doc=5, severity="BLOCK", facets={"metric": "mattr"},
                                             when=later),
                                       ev("override", "human", "dismissed", "12f", "BLOCK", 5, "mattr", when=later,
                                          facets={"metric": "mattr", "kind": "unfixable"}, reason="still stuck")]
        cands = self.cands(events)
        self.assertEqual([(c["rule"], c["trigger"]) for c in cands], [("12f", "stuck")])
        self.assertEqual((cands[0]["evidence"]["unfixable_spans"], cands[0]["evidence"]["docs"]), (1, 1))

    def test_kept_evidence_is_spent_by_its_own_rule_only(self):
        events = kept_4b_events() + fp_events() + [applied("4b", NOW - timedelta(days=1))]
        self.assertEqual([c["rule"] for c in self.cands(events)], ["2b"])

    def test_a_profile_apply_spends_only_that_profiles_evidence(self):  # spent evidence is keyed by rule and profile
        a = [e for e in fp_events()]  # profile "default"
        b = [fired("2b", f"t{i}", doc=i % 10, profile="other") for i in range(25)]
        b += [ev("override", "human", "dismissed", "2b", "WARN", i % 10, f"t{i}", profile="other",
                 facets={"kind": "false_positive"}, reason="fine here") for i in range(4)]
        spent_a = ledger.make_event(event="apply", actor="engine", outcome="applied", ruleset_version=CFG.version,
                                    profile="default", rule="2b", proposal="KZ-20260101-abcdef",
                                    facets={"kind": "profile"}, ts=ts(NOW - timedelta(days=1)))
        cands = self.cands(a + b + [spent_a])
        self.assertEqual([c["rule"] for c in cands], ["2b"])  # profile "other"'s evidence still counts
        self.assertEqual(cands[0]["evidence"]["fires"], 25)
        self.assertEqual(self.cands(a + [spent_a]), [])  # and "default"'s is spent
        self.assertEqual(self.cands(a + b + [applied("2b", NOW - timedelta(days=1))]), [])  # a ruleset apply: all

    def test_an_unapplied_proposal_doesnt_reset(self):
        events = stuck_12f_events() + [decision("KZ-20261013-abcdef", "approved", NOW - timedelta(days=1))]
        self.assertEqual([c["rule"] for c in self.cands(events)], ["12f"])

    def test_spent_fires_still_count_against_dormant(self):
        events = [fired("2b", "a", when=NOW - timedelta(days=50)), applied("2b", NOW - timedelta(days=40))]
        self.assertNotIn("2b", {c["rule"] for c in self.cands(events, start=OLD)})  # fired 50 days ago, not silent


class Missed(TmpCase):
    def test_missed_rule_and_pattern_in_two_docs_are_reviews(self):
        events = [ev("diff", "human", "missed", "21", None, 0, "h1"),
                  ev("diff", "human", "missed", "21", None, 1, "h2"),
                  ev("diff", "human", "missed", "?", None, 0, "p1", facets={"pattern": "hedge-stack"}),
                  ev("diff", "human", "missed", "?", None, 1, "p2", facets={"pattern": "hedge-stack"}),
                  ev("diff", "human", "missed", "?", None, 1, "p3", facets={"pattern": "listicle"})]
        cands = self.cands(events)
        self.assertEqual([(c["rule"], c["trigger"], c["action"]) for c in cands],
                         [("21", "missed", "review"), ("pattern:hedge-stack", "missed", "review")])
        p = calibrate.materialise(cands[0], None, CFG, None, [], NOW)
        self.assertEqual(p["edits"], [])
        self.assertEqual(p["evidence"]["missed_docs"], 2)


class Dormant(TmpCase):
    def test_young_ledger_proposes_nothing(self):
        self.assertEqual(self.cands([fired("2b", "a")], start=RECENT), [])

    def test_old_ledger_deprecates_a_silent_rule(self):
        cands = self.cands([fired("2b", "a")], start=OLD)
        by_rule = {c["rule"]: c for c in cands}
        self.assertIn("22", by_rule)
        self.assertNotIn("2b", by_rule)  # it fired
        self.assertNotIn("3", by_rule)   # method n/a never fires
        self.assertNotIn("NR-3", by_rule)  # needs the narrative flag; the default profile hasn't it
        c = by_rule["22"]
        self.assertEqual((c["trigger"], c["action"]), ("dormant", "deprecate"))
        p = calibrate.materialise(c, None, CFG, None, [], NOW)
        self.assertEqual(p["edits"], [{"kind": "rule_field", "rule": "22", "field": "status", "old": None,
                                       "new": "deprecated"}])

    def test_recent_apply_blocks_the_next_step(self):
        cands = self.cands([fired("2b", "a"), applied("22", NOW - timedelta(days=10))], start=OLD)
        self.assertNotIn("22", {c["rule"] for c in cands})
        cands = self.cands([fired("2b", "a"), applied("22", NOW - timedelta(days=40))], start=OLD)
        self.assertIn("22", {c["rule"] for c in cands})

    def test_retirement_steps(self):
        text = rulesedit.apply_edits(RULES.read_text(encoding="utf-8"), [
            {"kind": "rule_field", "rule": "22", "field": "status", "old": None, "new": "deprecated"},
            {"kind": "rule_field", "rule": "23", "field": "status", "old": None, "new": "deprecated"},
            {"kind": "rule_field", "rule": "7d", "field": "status", "old": None, "new": "shadow"},
            {"kind": "rule_field", "rule": "12e", "field": "status", "old": None, "new": "shadow"}])
        path = self.tmp / "steps.toml"
        path.write_text(text, encoding="utf-8")
        cfg = load_config(path)
        by_rule = {c["rule"]: c for c in self.cands([fired("2b", "a")], cfg=cfg, start=OLD)}
        self.assertEqual(by_rule["22"]["action"], "remove")   # lint+judge: no shadow step
        self.assertEqual(by_rule["23"]["action"], "shadow")   # lint
        self.assertEqual(by_rule["32"]["action"], "remove")   # already shadow
        self.assertEqual(by_rule["7d"]["action"], "review")   # an alias target can't be removed
        self.assertEqual(by_rule["12e"]["action"], "review")  # a knob in kaizen.toml names it
        self.assertIn("has a knob in kaizen.toml", by_rule["12e"]["reason"])
        p = calibrate.materialise(by_rule["22"], path, cfg, None, [], NOW)
        self.assertEqual(p["edits"], [{"kind": "rule_remove", "rule": "22", "old": {"severity": "WARN",
                                                                                   "status": "deprecated"}}])
        self.assertEqual(p["bump"], "major")


class PrivateReads(unittest.TestCase):
    def test_no_module_reads_the_private_thresholds(self):  # through Config.thresholds() only
        for path in sorted((REPO / "lib" / "plainspoken").rglob("*.py")):
            if path.name != "registry.py":
                with self.subTest(path=path.name):
                    self.assertNotIn("._thresholds", path.read_text(encoding="utf-8"))

    def test_calibrate_is_split(self):  # settings and knobs live in calibrate_knobs
        self.assertIs(calibrate.load_settings, calibrate_knobs.load_settings)
        for name in ("calibrate.py", "calibrate_knobs.py"):
            n = len((REPO / "lib" / "plainspoken" / name).read_text(encoding="utf-8").splitlines())
            self.assertLess(n, 550, name)


class Describe(unittest.TestCase):
    def test_a_falsy_old_value_reads_as_unset_or_its_toml(self):
        f = calibrate._describe
        self.assertEqual(f({"kind": "rule_field", "field": "status", "old": "", "new": "deprecated"}),
                         "status unset → deprecated")
        self.assertEqual(f({"kind": "rule_field", "field": "status", "old": None, "new": "shadow"}),
                         "status unset → shadow")
        self.assertEqual(f({"kind": "rule_field", "field": "models", "old": [], "new": ["m1"]}), "models unset → m1")
        self.assertEqual(f({"kind": "rule_field", "field": "flag", "old": False, "new": True}), "flag false → true")
        self.assertEqual(f({"kind": "rule_field", "field": "n", "old": 0, "new": 2}), "n 0 → 2")


class Cooldown(TmpCase):
    def rejected_store(self, when):
        c = self.cands(fp_events())[0]
        p = calibrate.materialise(c, None, CFG, None, [], NOW - timedelta(days=80))
        proposals.save(p, self.settings)
        return fp_events() + [decision(p["id"], "rejected", when)]

    def test_rejected_twenty_days_ago_is_skipped(self):
        self.assertEqual(self.cands(self.rejected_store(NOW - timedelta(days=20))), [])

    def test_rejected_seventy_days_ago_comes_back(self):
        self.assertEqual([c["rule"] for c in self.cands(self.rejected_store(NOW - timedelta(days=70)))], ["2b"])

    def test_a_pending_proposal_is_not_proposed_again(self):
        c = self.cands(fp_events())[0]
        proposals.save(calibrate.materialise(c, None, CFG, None, [], NOW - timedelta(days=5)), self.settings)
        self.assertEqual(self.cands(fp_events()), [])


class Run(TmpCase):
    def six(self) -> list[dict]:
        out = stuck_12f_events() + fp_events() + kept_4b_events()
        out += [ev("diff", "human", "missed", "21", None, 0, "h1"), ev("diff", "human", "missed", "21", None, 1, "h2")]
        out += [ev("diff", "human", "missed", "?", None, d, f"p{d}", facets={"pattern": "hedge-stack"})
                for d in (0, 1)]
        for d in range(3):
            out.append(fired("25", f"v{d}", doc=d))
            out.append(ev("publish", "publish", "survived_publish", "25", "WARN", d, f"v{d}"))
        return out

    def test_at_most_three_in_priority_order(self):
        path = self.copy(mattr_blocking=True, total_only=False)
        events = self.six()
        self.write_ledger(events)
        with mock.patch.dict(os.environ, {"PLAINSPOKEN_RULES": str(path)}):
            cfg = load_config()
            all_cands = self.cands(events, cfg=cfg, start=RECENT)
            self.assertEqual(len(all_cands), 6)
            out = calibrate.run(self.root, self.settings, NOW, [])
        self.assertEqual([(p["rule"], p["trigger"]) for p in out], [("12f", "stuck"), ("2b", "fp"), ("21", "missed")])
        stored = sorted(x.stem for x in (self.root / ".plainspoken" / "kaizen" / "proposals").glob("*.json"))
        self.assertEqual(stored, sorted(p["id"] for p in out))
        logged = [e for e in ledger.read(self.settings)[0] if e["event"] == "calibrate"]
        self.assertEqual(sorted(e["proposal"] for e in logged), sorted(p["id"] for p in out))
        self.assertTrue(all(e["outcome"] == "proposed" and e["actor"] == "engine" for e in logged))
        # a second run skips what's already pending and moves down the list
        with mock.patch.dict(os.environ, {"PLAINSPOKEN_RULES": str(path)}):
            again = calibrate.run(self.root, self.settings, NOW, [])
        self.assertEqual([(p["rule"], p["trigger"]) for p in again],
                         [("pattern:hedge-stack", "missed"), ("4b", "kept"), ("25", "kept")])


class Effect(TmpCase):
    SO = ("# Notes\n\nSo, I planted the beans early this year in the back bed. So, the frost came late and hit them "
          "hard overnight. So, I covered the rows with old sheets from the cupboard. So, most of them made it "
          "through to the warmer weeks in the end.\n")
    PLAIN = ("# Notes\n\nI planted the beans early this year in the back bed. The frost came late and hit them hard "
             "overnight. I covered the rows with old sheets from the cupboard. Most of them made it through.\n")

    def test_corpus_effect_names_the_changed_file(self):
        path = self.copy(total_only=False)
        cfg = load_config(path)
        a, b = self.tmp / "a.md", self.tmp / "b.md"
        a.write_text(self.SO, encoding="utf-8")
        b.write_text(self.PLAIN, encoding="utf-8")
        c = self.cands(kept_4b_events(), cfg=cfg)[0]
        before = path.read_bytes()
        p = calibrate.materialise(c, path, cfg, default_profile(), [a, b], NOW)
        self.assertEqual(path.read_bytes(), before)
        corpus = p["effect"]["corpus"]
        self.assertEqual(corpus["files"], 2)
        self.assertEqual(corpus["changed"], ["a"])
        self.assertGreater(corpus["before"].get("4b", 0), corpus["after"].get("4b", 0))
        self.assertEqual(p["effect"]["golden"], "not available until Phase 6")


def cli(*args, cwd: Path, env: dict | None = None):
    # TRELLO_: with real credentials in the shell, the adapter tests would call Trello.
    e = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_", "TRELLO_"))}
    e["PYTHONPATH"] = str(REPO / "lib")
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=cwd, capture_output=True, text=True,
                          env=e)


def shipped_hashes() -> dict[str, str]:
    files = [RULES, REPO / "data" / "profiles" / "default.toml",
             *sorted(p for p in (REPO / "data" / "rubrics").rglob("*") if p.is_file())]
    return {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


class Cli(TmpCase):
    def test_calibrate_never_edits_the_ruleset_rubrics_or_profiles(self):
        events = fp_events() + kept_4b_events() + [fired("2b", "old", when=OLD)]  # an old ledger: dormant fires too
        self.write_ledger(events)
        before = shipped_hashes()
        self.assertTrue(any(k.startswith("data/rubrics/") for k in before))
        r = cli("kaizen", "calibrate", "--now", ts(NOW), cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(shipped_hashes(), before)
        stored = list((self.root / ".plainspoken" / "kaizen" / "proposals").glob("*.json"))
        self.assertEqual(len(stored), 3)
        for p in stored:
            self.assertIn(p.stem, r.stdout)
        self.assertIn("+claude_warn_total = 5", r.stdout)

    def test_damaged_ledger_still_calibrates(self):
        self.write_ledger(fp_events())
        month = next((self.root / ".plainspoken" / "ledger").glob("*.jsonl"))
        with month.open("a", encoding="utf-8") as f:
            f.write('{"v": 2, "truncated\n')
        r = cli("kaizen", "calibrate", "--now", ts(NOW), "--json", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([p["rule"] for p in json.loads(r.stdout)], ["2b"])

    def test_no_proposals(self):
        r = cli("kaizen", "calibrate", "--now", ts(NOW), cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no proposals", r.stdout)

    def test_json_and_review(self):
        self.write_ledger(fp_events())
        r = cli("kaizen", "calibrate", "--now", ts(NOW), "--json", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual([p["rule"] for p in out], ["2b"])
        r = cli("kaizen", "review", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(out[0]["id"], r.stdout)
        self.assertIn("awaiting decision", r.stdout)

    def test_bad_now(self):
        r = cli("kaizen", "calibrate", "--now", "yesterday", cwd=self.root)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)


class RuleAddProposal(unittest.TestCase):
    BLOCK = {"name": "Test rule", "method": "judge", "group": "J2", "severity": "WARN", "era": "2026"}

    def test_a_rule_add_materialises_for_the_ruleset_only(self):
        c = {"rule": "99", "trigger": "owner", "action": "add", "reason": "a test",
             "edits": [{"kind": "rule_add", "rule": "99", "block": self.BLOCK, "lists": {"test_phrases": ["a b"]},
                        "thresholds": {"test_phrases_warn": 2}}]}
        p = calibrate.materialise(c, None, CFG, None, [], NOW)
        self.assertEqual(p["action"], "add")
        self.assertEqual(p["edits"], c["edits"])
        self.assertEqual((p["bump"], p["targets"]), ("minor", ["ruleset"]))
        self.assertIn('+id = "99"', p["diff"])
        self.assertIn("add rule 99 (Test rule) with list test_phrases and threshold test_phrases_warn", p["summary"])

    def test_a_rule_add_for_an_existing_rule_is_a_review(self):
        c = {"rule": "32", "trigger": "owner", "action": "add", "reason": "a test",
             "edits": [{"kind": "rule_add", "rule": "32", "block": self.BLOCK}]}
        p = calibrate.materialise(c, None, CFG, None, [], NOW)
        self.assertEqual((p["action"], p["edits"]), ("review", []))
        self.assertIn("already exists", p["summary"])



class ThresholdAddProposal(unittest.TestCase):
    def test_a_threshold_add_materialises_for_the_ruleset_only(self):
        c = {"rule": "12d", "trigger": "owner", "action": "add", "reason": "a test",
             "edits": [{"kind": "threshold_add", "key": "x_faq_run", "value": 4, "after": "paragraph_uniform_run"}]}
        p = calibrate.materialise(c, None, CFG, None, [], NOW)
        self.assertEqual((p["action"], p["edits"], p["bump"], p["targets"]), ("add", c["edits"], "minor",
                                                                                ["ruleset"]))
        self.assertIn("+x_faq_run = 4", p["diff"])
        self.assertIn("add threshold x_faq_run = 4", p["summary"])

    def test_an_existing_threshold_is_a_review(self):
        c = {"rule": "12d", "trigger": "owner", "action": "add", "reason": "a test",
             "edits": [{"kind": "threshold_add", "key": "paragraph_uniform_run", "value": 4}]}
        p = calibrate.materialise(c, None, CFG, None, [], NOW)
        self.assertEqual((p["action"], p["edits"]), ("review", []))
        self.assertIn("already exists", p["summary"])

if __name__ == "__main__":
    unittest.main()


def proposed(pid, when, event="mine"):
    return ledger.make_event(event=event, actor="engine", outcome="proposed", ruleset_version=CFG.version,
                             profile="default", rule="2b", proposal=pid, ts=ts(when))


class MonthlyCap(TmpCase):
    """`[kaizen] monthly_cap` is shared by calibrate and mine: what either stored this calendar month counts."""

    def test_counts_this_month_only_from_the_ledger_and_the_store(self):
        events = [proposed("KZ-20261002-aaaaaa", NOW.replace(day=2)),
                  proposed("KZ-20261002-aaaaaa", NOW.replace(day=2)),  # the same id twice counts once
                  proposed("KZ-20261003-bbbbbb", NOW.replace(day=3), event="calibrate"),
                  proposed("KZ-20260930-cccccc", NOW.replace(month=9, day=30)),  # last month
                  ev("lint", "lint", "fired", "2b")]
        stored = {"id": "KZ-20261005-dddddd", "created": ts(NOW.replace(day=5))}  # stored, its ledger line lost
        proposals.save(stored, self.settings)
        self.assertEqual(proposals.made_in_month(self.settings, events, NOW), 3)
        self.assertEqual(proposals.made_in_month(self.settings, events, NOW.replace(month=11, day=1)), 0)

    def test_limit(self):
        events = [proposed("KZ-20261002-aaaaaa", NOW.replace(day=2))]
        no_cap = proposals.run_limit(self.settings, events, NOW, 3)
        self.assertEqual((no_cap["limit"], no_cap["cap"], no_cap["used"]), (3, None, None))
        self.assertEqual(proposals.run_limit(self.settings, events, NOW, 3, asked=1)["limit"], 1)
        self.assertEqual(proposals.run_limit(self.settings, events, NOW, 3, asked=9)["limit"], 3)  # only lowers
        capped = {**self.settings, "monthly_cap": 3}
        self.assertEqual(proposals.run_limit(capped, events, NOW, 3)["limit"], 2)
        self.assertEqual(proposals.run_limit(capped, events, NOW, 3, asked=1)["limit"], 1)
        full = proposals.run_limit({**self.settings, "monthly_cap": 1}, events, NOW, 5)
        self.assertEqual((full["limit"], full["cap"], full["used"], full["month"]), (0, 1, 1, "2026-10"))

    def test_run_stores_only_what_the_cap_leaves(self):
        events = stuck_12f_events() + fp_events() + kept_4b_events()
        events.append(proposed("KZ-20261001-aaaaaa", NOW.replace(day=1)))  # mine stored one this month
        self.write_ledger(events)
        settings = {**self.settings, "monthly_cap": 2}
        limits: dict = {}
        out = calibrate.run(self.root, settings, NOW, [], limits=limits)
        self.assertEqual(len(out), 1)
        self.assertEqual((limits["cap"], limits["used"], limits["limit"]), (2, 1, 1))
        again: dict = {}
        self.assertEqual(calibrate.run(self.root, settings, NOW, [], limits=again), [])
        self.assertEqual((again["used"], again["limit"]), (2, 0))

    def test_max_new_lowers_one_run(self):
        self.write_ledger(stuck_12f_events() + fp_events() + kept_4b_events())
        out = calibrate.run(self.root, self.settings, NOW, [], max_new=1)
        self.assertEqual([p["rule"] for p in out], ["12f"])
        self.assertEqual(calibrate.run(self.root, self.settings, NOW, [], max_new=0), [])

    def test_cli(self):
        self.write_ledger(fp_events() + kept_4b_events())
        r = cli("kaizen", "calibrate", "--now", ts(NOW), "--max", "1", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 proposal stored", r.stdout)
        self.assertNotIn("monthly cap", r.stdout)
        (self.root / ".plainspoken" / "config.toml").write_text("[kaizen]\nmonthly_cap = 1\n", encoding="utf-8")
        r = cli("kaizen", "calibrate", "--now", ts(NOW), cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("monthly cap 1: 1 stored in 2026-10 before this run, room for 0", r.stdout)
        self.assertIn("no proposals", r.stdout)
        for bad in ("-1", "two"):
            r = cli("kaizen", "calibrate", "--max", bad, cwd=self.root)
            self.assertEqual(r.returncode, 2)
            self.assertIn("whole number", r.stderr)
