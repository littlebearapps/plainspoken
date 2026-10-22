"""Capture — lint findings become ledger events (facets, span hashes, the check-to-check fix diff),
from `check` and the lint-watch hook, without ever breaking the command."""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken import capture, config, judges, justify, ledger, report
from plainspoken.doc import parse
from plainspoken.profile import default as default_profile
from plainspoken.registry import load_config
from tests._profiles import CONSULTING
from tests.test_anti_ai_report import _judges

REPO = Path(__file__).resolve().parents[1]
CFG = load_config()

ARTICLE = """---
title: Planting a winter garden
description: What I learnt growing broad beans through a cold Melbourne winter.
---

I planted broad beans in late April because the soil was still warm enough for them to settle before the frosts arrived properly in June.

## Getting the bed ready

I dug in two bags of compost and a handful of blood and bone, then left the bed to sit for a week while the worms did their quiet work underneath. Also, I checked the drainage after a heavy shower. Also, I moved the tap timer so the hose reached the far corner. Also, I pulled out the old tomato stakes that had been leaning there since February. Also, I sharpened the spade, which was long overdue and made the whole job easier. I won't delve into the soil chemistry here because my neighbour knows far more about it than me.

## How do I start?

Pick a sunny bed. Water it well. Sow the seeds. Wait a while. Then check again.

## FAQ

Do beans need staking? Yes, once they pass knee height a few stakes and some twine stop the wind from flattening them in a storm, which happens more often than you'd think in an exposed backyard.
"""
# The same article with one "Also," opener removed: 4b's per-word WARN on "also" goes, nothing else changes.
EDITED = ARTICLE.replace("Also, I checked the drainage", "I checked the drainage")


SHED = """# Shed notes

I rebuilt the garden shed over three weekends last spring because the old one had started leaning towards the fence after a wet winter.

## What I did

I pulled the old cladding off first and stacked it by the gate for the tip run, which took most of the first Saturday morning. Also, I bought new stumps from the hardware shop down the road. Also, I borrowed my brother's spirit level for the whole job. Also, I cut the bearers on the back lawn where the ground was flat. Also, I painted the cut ends before they went in. Plus, the weather held for both of the first two weekends. Plus, my neighbour lent me his drop saw for the trickier angled cuts. Still, the roof took far longer than I had planned for. Still, I'm glad I didn't rush the flashing around the window. Plus, I'll build a small potting bench along the sunny side wall. Still, the whole thing cost less than a new flat-pack shed would have, even counting the paint.
"""
# One "Also," opener gone (same sentence length): the 4b total BLOCK still fires with a new tally, and the per-word
# WARN on "also" goes.
SHED_EDITED = SHED.replace("Also, I painted the cut ends", "I carefully painted the cut ends")


def cli(*args, cwd: Path, env: dict | None = None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    e["PYTHONPATH"] = str(REPO / "lib")
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=cwd, capture_output=True, text=True,
                          env=e)


def _finding(rule, line, excerpt, message, severity="WARN"):
    return {"rule": rule, "severity": severity, "line": line, "excerpt": excerpt, "message": message,
            "source": "lint"}


class Facets(unittest.TestCase):
    def doc(self, text, profile=None):
        return parse(text, path="post.md", profile=profile or default_profile())

    def test_4b_per_word_warn_on_then_gives_term(self):
        # "then" is a density_total_only word, so today's ruleset never WARNs it per word; an older ruleset (or a
        # history backfill) did, and the facet must still name the ruleset word.
        doc = self.doc(ARTICLE)
        f = _finding("4b", 10, "then", "“then” opens 4 sentences (max 3)")
        self.assertEqual(capture.facets(f, doc, CFG)["term"], "then")

    def test_term_from_a_real_4b_warn(self):
        lint = report.run_lint(self._write(ARTICLE), default_profile(), cfg=CFG)
        warn = next(f for f in lint["findings"] if f["rule"] == "4b")
        self.assertEqual(capture.facets(warn, self.doc(ARTICLE), CFG)["term"], "also")

    def test_term_from_the_quoted_word_in_the_message(self):
        f = _finding("2", 10, "I won't delve into the soil chemistry here.", "Hard-ban word: “delve”", "BLOCK")
        self.assertEqual(capture.facets(f, self.doc(ARTICLE), CFG)["term"], "delve")

    def test_term_is_never_article_text(self):
        f = _finding("2", 10, "Broad beans settle.", "Something odd: “broad beans”", "BLOCK")
        self.assertNotIn("term", capture.facets(f, self.doc(ARTICLE), CFG))

    def test_7d_no_long_under_faq(self):
        doc = self.doc(ARTICLE)
        line = next(ln for ln, _, t in doc.headings if t == "FAQ")
        f = _finding("7d", line, "FAQ", "No sentence over 25 words in this section — join two short sentences that share a thought")
        facets = capture.facets(f, doc, CFG)
        self.assertEqual((facets["section"], facets["form"]), ("faq", "no-long"))

    def test_7d_under_a_question_heading(self):
        lint = report.run_lint(self._write(ARTICLE), default_profile(), cfg=CFG)
        f = next(f for f in lint["findings"] if f["rule"] == "7d")
        facets = capture.facets(f, self.doc(ARTICLE), CFG)
        self.assertEqual((facets["section"], facets["form"]), ("question", "no-long"))

    def test_7d_short_run_and_intro(self):
        doc = self.doc(ARTICLE)
        f = _finding("7d", 6, "I planted broad beans.", "5 consecutive sentences under 12 words")
        facets = capture.facets(f, doc, CFG)
        self.assertEqual((facets["section"], facets["form"]), ("intro", "short-run"))
        intro = capture.facets(_finding("NR-2", 6, "(intro)", "No sentence over 25 words"), doc, CFG)
        self.assertEqual(intro["form"], "no-long")
        other = capture.facets(_finding("2", 10, "x", "y", "BLOCK"), doc, CFG)
        self.assertEqual(other["section"], "other")
        self.assertNotIn("form", other)

    def test_faq_frontmatter_lines_are_faq(self):
        text = ("---\ntitle: T\nfaqs:\n  - question: \"Why?\"\n    answer: \"Because. It is. So.\"\n---\n\n"
                "Body text here.\n")
        doc = self.doc(text, CONSULTING)
        self.assertEqual(capture.facets(_finding("7d", 5, "Because.", "run"), doc, CFG)["section"], "faq")
        self.assertEqual(capture.facets(_finding("2", 2, "T", "x"), doc, CFG)["section"], "intro")

    def test_line_0_has_no_section(self):
        f = _finding("HM", 0, "no human markers", "No contractions")
        self.assertNotIn("section", capture.facets(f, self.doc(ARTICLE), CFG))

    def test_metrics(self):
        doc = self.doc(ARTICLE)
        for excerpt, message, want in (("mattr 0.61", "MATTR-50 0.61 < 0.7 — vary", "mattr"),
                                       ("burstiness 0.2", "Burstiness 0.2 < 0.3", "burstiness"),
                                       ("ttr 0.3", "Raw TTR 0.3", "ttr"),
                                       ("{'words': 400}", "2 slop metrics tripped: opening repetition 0.27 > 0.25; MATTR 0.4 < 0.46", "slop")):
            self.assertEqual(capture.facets(_finding("12f", 0, excerpt, message), doc, CFG)["metric"], want)
        self.assertNotIn("metric", capture.facets(_finding("4b", 3, "mattr 0.5", "x"), doc, CFG))

    def test_mattr_span_hash_is_the_same_across_articles(self):
        other = "A completely different article.\n\nWith different words entirely, about bicycles.\n"
        spans = []
        for text in (ARTICLE, other):
            lint = {"article": "post.md", "profile": "default", "ruleset_version": CFG.version,
                    "article_sha256": hashlib.sha256(text.encode()).hexdigest(), "content_type": "article",
                    "findings": [_finding("12f", 0, f"mattr 0.{len(text) % 90 + 10}", "MATTR-50 low")]}
            (ev,) = capture.lint_events(lint, self.doc(text), CFG, Path.cwd())
            spans.append((ev["span_hash"], ev["doc_sha"]))
        self.assertEqual(spans[0][0], spans[1][0])
        self.assertEqual(spans[0][0], ledger.span_hash("12f", "mattr"))
        self.assertNotEqual(spans[0][1], spans[1][1])

    def _write(self, text):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = d / "post.md"
        p.write_text(text, encoding="utf-8")
        return p


class Aggregates(unittest.TestCase):
    """A finding whose excerpt is a tally or summary hashes a stable span, so a changed tally that still
    fires is the same span."""

    # (rule, severity, line, (excerpt, message) one, (excerpt, message) two): two tallies of the same finding.
    CASES = (
        ("1", "BLOCK", 4, ("lines [4, 9]", "5 em dashes (limit 3)"), ("lines [4, 9, 12]", "6 em dashes (limit 3)")),
        ("NR-1", "BLOCK", 4, ("lines [4]", "6 em dashes (limit 5)"), ("lines [7]", "7 em dashes (limit 5)")),
        ("4b", "BLOCK", 7, ("{'also': 4, 'plus': 3}", "10 sentence-opening transitions (max 8)."),
         ("{'also': 3, 'plus': 3}", "9 sentence-opening transitions (max 8).")),
        ("2b", "WARN", 0, ("genuinely ×2, arguably ×2", "Claude WARN words: 4 (limit 3) — …"),
         ("genuinely ×3, arguably ×2", "Claude WARN words: 5 (limit 3) — …")),
        ("4a2", "BLOCK", 0, ("however ×6", "Conversational transitions: 6 (limit 5) — however ×6"),
         ("however ×7", "Conversational transitions: 7 (limit 5) — however ×7")),
        ("4a2", "WARN", 0, ("notably ×3", "Conversational transitions: 3 (limit 2) — notably ×3"),
         ("notably ×4", "Conversational transitions: 4 (limit 2) — notably ×4")),
        ("23", "WARN", 0, ("in order to ×3", "Filler phrases: 3 (limit 2)"), ("in order to ×4", "Filler phrases: 4")),
        ("25", "WARN", 0, ("various ×3", "Vague quantifiers: 3 (limit 2)"), ("numerous ×3", "Vague quantifiers: 3")),
        ("24", "WARN", 0, ("12 bold spans / 400 words", "Mechanical mid-prose bold (3.0 per 100 words)"),
         ("14 bold spans / 410 words", "Mechanical mid-prose bold (3.4 per 100 words)")),
        ("12f", "WARN", 0, ("{'words': 400, 'mattr': 0.6}", "2 slop metrics tripped: opening repetition 0.27 > 0.25; …"),
         ("{'words': 420, 'mattr': 0.62}", "3 slop metrics tripped: paragraph SD 22 < 25; …")),
        ("15", "WARN", 0, ("3 expanded vs 5 contracted", "Contraction avoidance"), ("4 expanded vs 5 contracted", "x")),
        ("HM", "WARN", 0, ("no human markers", "No contractions"), ("no human markers ", "No contractions, …")),
        ("NR-5", "WARN", 0, ("shortest 22w, longest 70w", "A narrative piece needs…"),
         ("shortest 25w, longest 75w", "A narrative piece needs…")),
        ("NR-6", "WARN", 0, ("no opinion marker", "A narrative piece needs the opinion-delivery pattern"),
         ("no opinion marker", "A narrative piece needs the opinion-delivery pattern at least once")),
    )

    def test_every_aggregate_entry_is_covered(self):
        self.assertEqual({(r, s) for r, s, *_ in self.CASES}, set(capture.AGGREGATE))

    def test_changed_tally_is_the_same_span(self):
        for rule, sev, line, (e1, m1), (e2, m2) in self.CASES:
            with self.subTest(rule=rule, severity=sev):
                a, b = _finding(rule, line, e1, m1, sev), _finding(rule, line + (rule in ("1", "4b")), e2, m2, sev)
                self.assertEqual(capture.span(a), capture.span(b))
                self.assertEqual(capture.span(a), ledger.span_hash(rule, f"{sev}:{'slop' if rule == '12f' else 'doc'}"))
                self.assertIsNotNone(capture.aggregate_key(a))

    def test_text_findings_of_the_same_rules_still_hash_their_excerpt(self):
        curly = (_finding("24", 3, "He said “yes”.", "Curly quotes on 1 line(s)"),
                 _finding("24", 3, "She said “no”.", "Curly quotes on 1 line(s)"))
        however = (_finding("4a2", 5, "However, it rained.", "“However,” opens 3 sentences (max 2)"),
                   _finding("4a2", 5, "However, it snowed.", "“However,” opens 4 sentences (max 2)"))
        per_word = (_finding("4b", 7, "also", "“also” opens 4 sentences"), _finding("4b", 7, "plus", "“plus” opens 4"))
        for a, b in (curly, however, per_word):
            with self.subTest(rule=a["rule"]):
                self.assertIsNone(capture.aggregate_key(a))
                self.assertNotEqual(capture.span(a), capture.span(b))
        mattr = _finding("12f", 0, "mattr 0.61", "MATTR-50 0.61 < 0.7", "WARN")
        self.assertIsNone(capture.aggregate_key(mattr))
        self.assertEqual(capture.span(mattr), ledger.span_hash("12f", "mattr"))

    def test_escalated_tally_is_not_fixed(self):
        lint = {"article": "post.md", "profile": "default", "profile_sha256": "p", "ruleset_version": CFG.version,
                "content_type": "article", "article_sha256": "a" * 64,
                "findings": [_finding("4a2", 0, "notably ×3", "Conversational transitions: 3", "WARN")]}
        cur = {**lint, "article_sha256": "b" * 64,
               "findings": [_finding("4a2", 0, "notably ×6", "Conversational transitions: 6", "BLOCK")]}
        self.assertEqual(capture.fixed_events(lint, cur, None, CFG, Path.cwd()), [])

    def test_total_block_still_firing_is_not_fixed(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        art = root / "shed.md"
        art.write_text(SHED, encoding="utf-8")
        prev = report.run_lint(art, default_profile(), cfg=CFG)
        art.write_text(SHED_EDITED, encoding="utf-8")
        cur = report.run_lint(art, default_profile(), cfg=CFG)
        blocks = [[f["excerpt"] for f in lint["findings"] if (f["rule"], f["severity"]) == ("4b", "BLOCK")]
                  for lint in (prev, cur)]
        self.assertEqual(len(blocks[0]), 1)
        self.assertEqual(len(blocks[1]), 1)
        self.assertNotEqual(blocks[0], blocks[1])  # the tally changed, the BLOCK still fires
        fixed = capture.fixed_events(prev, cur, parse(SHED, path=str(art)), CFG, root)
        self.assertEqual([(e["rule"], e["severity"], e["span_hash"]) for e in fixed],
                         [("4b", "WARN", ledger.span_hash("4b", "also"))])
        doc = parse(SHED, path=str(art))
        fired = {(e["rule"], e["severity"]): e["span_hash"] for e in capture.lint_events(prev, doc, CFG, root)}
        again = {(e["rule"], e["severity"]): e["span_hash"]
                 for e in capture.lint_events(cur, parse(SHED_EDITED, path=str(art)), CFG, root)}
        self.assertEqual(fired[("4b", "BLOCK")], again[("4b", "BLOCK")])
        self.assertEqual(fired[("4b", "BLOCK")], ledger.span_hash("4b", "BLOCK:doc"))


class Events(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.art = self.root / "post.md"
        self.art.write_text(ARTICLE, encoding="utf-8")
        self.lint = report.run_lint(self.art, default_profile(), cfg=CFG)
        self.doc = parse(ARTICLE, path=str(self.art))

    def test_one_fired_per_block_or_warn(self):
        events = capture.lint_events(self.lint, self.doc, CFG, self.root)
        want = [f for f in self.lint["findings"] if f["severity"] in ("BLOCK", "WARN")]
        self.assertEqual(len(events), len(want))
        self.assertTrue(all(e["outcome"] == "fired" and e["event"] == "lint" and e["actor"] == "lint"
                            for e in events))
        self.assertEqual({e["rule"] for e in events}, {"2", "4b", "7d"})
        e = events[0]
        self.assertEqual((e["doc_sha"], e["ruleset_version"], e["profile"]),
                         (self.lint["article_sha256"], self.lint["ruleset_version"], "default"))
        self.assertEqual(e["doc_id"], ledger.doc_id(self.art, self.root))
        self.assertTrue(all(ledger.validate(x) == [] for x in events))

    def test_candidates_and_info_are_skipped_shadow_is_info(self):
        lint = {**self.lint, "findings": [
            _finding("6", 10, "x", "Three-item list", "CANDIDATE"), _finding("12f", 0, "ttr 0.3", "Raw TTR", "INFO"),
            _finding("28", 10, "Also, I", "[shadow] Something", "INFO")]}
        (e,) = capture.lint_events(lint, self.doc, CFG, self.root)
        self.assertEqual((e["rule"], e["severity"], e["outcome"]), ("28", "INFO", "fired"))

    def test_doc_id_override(self):
        events = capture.lint_events(self.lint, self.doc, CFG, self.root, doc_id=ledger.label_id("article-3"))
        self.assertEqual({e["doc_id"] for e in events}, {ledger.label_id("article-3")})

    def test_excerpt_is_carried_only_for_append_to_drop(self):
        events = capture.lint_events(self.lint, self.doc, CFG, self.root)
        self.assertTrue(any(e.get("excerpt", "").startswith("I won't delve") for e in events))

    def test_facet_work_is_done_once_per_call(self):  # cache per call, not per finding
        class Counting:
            def __init__(self, cfg):
                self._cfg, self.reads = cfg, 0

            def __getattr__(self, name):
                return getattr(self._cfg, name)

            @property
            def lists(self):
                self.reads += 1
                return self._cfg.lists

        cfg = Counting(CFG)
        events = capture.lint_events(self.lint, self.doc, cfg, self.root)
        self.assertGreater(len(events), 1)
        self.assertEqual(cfg.reads, 1)
        self.assertEqual(events, capture.lint_events(self.lint, self.doc, CFG, self.root))

    def test_fixed_events(self):
        prev = self.lint
        self.art.write_text(EDITED, encoding="utf-8")
        cur = report.run_lint(self.art, default_profile(), cfg=CFG)
        (e,) = capture.fixed_events(prev, cur, self.doc, CFG, self.root)
        self.assertEqual((e["rule"], e["outcome"], e["event"], e["severity"]), ("4b", "fixed", "fix", "WARN"))
        self.assertEqual(e["span_hash"], ledger.span_hash("4b", "also"))
        self.assertEqual((e["doc_sha"], e["facets"]["term"], e["facets"]["section"]),
                         (cur["article_sha256"], "also", "other"))

    def test_no_fixed_events_when_not_comparable(self):
        self.assertEqual(capture.fixed_events(None, self.lint, None, CFG, self.root), [])
        self.assertEqual(capture.fixed_events(self.lint, self.lint, None, CFG, self.root), [])  # same sha
        cur = {**self.lint, "article_sha256": "b" * 64, "findings": []}
        self.assertEqual(len(capture.fixed_events(self.lint, cur, None, CFG, self.root)), 3)
        for key, value in (("ruleset_version", "0.0.1"), ("profile_sha256", "c" * 64), ("profile", "other"),
                           ("article", "elsewhere/other.md")):
            self.assertEqual(capture.fixed_events({**self.lint, key: value}, cur, None, CFG, self.root), [], key)
        damaged = {**self.lint, "findings": [{"rule": 5}, "x", _finding("2", "ten", "x", "y", "BLOCK")]}
        self.assertEqual(capture.fixed_events(damaged, cur, None, CFG, self.root), [])
        self.assertEqual(capture.fixed_events({"findings": 3}, cur, None, CFG, self.root), [])

    def test_record_never_raises(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            capture.record([{"not": "an event"}], self.root, "check")  # bad event: friction, no raise
        rows = (self.root / ".plainspoken" / "ledger" / "friction.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(r)["kind"] for r in rows], ["capture_error"])

        def boom():
            raise RuntimeError("builder broke\nsecond line")
        with contextlib.redirect_stderr(err):
            capture.record(boom, self.root, "check")
            capture.record([], Path("/nonexistent/\0bad"), "check")  # settings can't be built: no friction
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(all(x.startswith("plainspoken: kaizen capture skipped: ") for x in lines))
        self.assertEqual(lines[1], "plainspoken: kaizen capture skipped: RuntimeError: builder broke")

    def test_record_capture_off_does_not_build(self):
        (self.root / ".plainspoken").mkdir(exist_ok=True)
        (self.root / ".plainspoken" / "config.toml").write_text("[kaizen]\ncapture = false\n", encoding="utf-8")

        built = []
        capture.record(lambda: built.append(1) or [], self.root, "check")
        self.assertEqual(built, [])
        self.assertFalse((self.root / ".plainspoken" / "ledger").exists())


class CheckCli(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()  # the project root
        self.art = self.root / "post.md"
        self.art.write_text(ARTICLE, encoding="utf-8")
        self.ledger_dir = self.root / ".plainspoken" / "ledger"

    def check(self, *extra, env=None):
        return cli("check", "post.md", "--profile", "default", *extra, cwd=self.root, env=env)

    def events(self):
        return ledger.read({"ledger_dir": self.ledger_dir, "root": self.root})[0]

    def lines(self):
        out = []
        if self.ledger_dir.is_dir():
            for p in sorted(self.ledger_dir.iterdir()):
                out += p.read_text(encoding="utf-8").splitlines()
        return out

    def test_repeat_check_appends_same_ids(self):
        first = self.check()
        self.assertEqual(first.returncode, 1, first.stderr)  # the delve BLOCK
        n = len(ledger.distinct(self.events()))
        self.assertEqual(n, 3)
        self.check()
        events = self.events()
        self.assertEqual(len(events), 6)
        self.assertEqual(len(ledger.distinct(events)), n)

    def test_edit_gives_one_fixed_event(self):
        self.check()
        self.art.write_text(EDITED, encoding="utf-8")
        self.check()
        fixed = [e for e in self.events() if e["outcome"] == "fixed"]
        self.assertEqual(len(fixed), 1)
        self.assertEqual((fixed[0]["rule"], fixed[0]["span_hash"]), ("4b", ledger.span_hash("4b", "also")))

    def test_no_save_writes_no_fixed_and_no_snapshot(self):
        self.check("--no-save")
        self.art.write_text(EDITED, encoding="utf-8")
        r = self.check("--no-save")
        self.assertEqual(r.returncode, 1, r.stderr)
        events = self.events()
        self.assertTrue(events)
        self.assertFalse(any(e["outcome"] == "fixed" for e in events))
        self.assertFalse((self.root / ".plainspoken" / "reports").exists())

    def test_out_elsewhere_writes_no_snapshot_and_no_fixed(self):
        self.check()
        self.art.write_text(EDITED, encoding="utf-8")
        r = self.check("--out", "elsewhere/lint.json")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue((self.root / "elsewhere" / "lint.json").exists())
        self.assertFalse(any(e["outcome"] == "fixed" for e in self.events()))
        paths = json.loads(cli("paths", "post.md", cwd=self.root).stdout)
        self.assertEqual(Path(paths["checked"]).read_bytes(), ARTICLE.encode("utf-8"))  # the keyed snapshot stays

    def tree(self, folder: Path) -> dict:
        return {p.relative_to(folder): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}

    def test_no_record_prints_the_lint_and_writes_nothing(self):  # #1
        r = self.check("--no-record", "--json")
        self.assertEqual(r.returncode, 1, r.stderr)  # same exit as a recorded check: the delve BLOCK
        self.assertTrue(json.loads(r.stdout)["findings"])
        self.assertEqual(r.stderr, "")
        self.assertFalse((self.root / ".plainspoken").exists())  # no ledger, no friction, no reports, no snapshot

    def test_no_record_leaves_ledger_lint_and_snapshots_alone(self):
        self.check()
        self.art.write_text(EDITED, encoding="utf-8")
        self.check()  # now there's a previous pair as well as the current lint and snapshot
        reports = self.root / ".plainspoken" / "reports"
        ledger_before, reports_before = self.lines(), self.tree(reports)
        self.art.write_text(ARTICLE, encoding="utf-8")
        r = self.check("--no-record")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(self.lines(), ledger_before)
        self.assertEqual(self.tree(reports), reports_before)

    def test_no_record_keeps_snapshots_when_capture_is_off(self):
        self.check()
        reports = self.root / ".plainspoken" / "reports"
        before = self.tree(reports)
        (self.root / ".plainspoken" / "config.toml").write_text("[kaizen]\ncapture = false\n", encoding="utf-8")
        self.check("--no-record")
        self.assertEqual(self.tree(reports), before)  # a plain check here would delete the snapshot

    def test_no_record_out_elsewhere_writes_only_that_file(self):
        r = self.check("--no-record", "--out", "elsewhere/lint.json")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue((self.root / "elsewhere" / "lint.json").exists())
        self.assertFalse((self.root / ".plainspoken").exists())

    def test_no_record_refuses_out_at_the_report_key(self):
        self.check()
        reports = self.root / ".plainspoken" / "reports"
        ledger_before, reports_before = self.lines(), self.tree(reports)
        lint = json.loads(cli("paths", "post.md", cwd=self.root).stdout)["lint"]
        r = self.check("--no-record", "--out", lint)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--no-record", r.stderr)
        self.assertEqual((self.lines(), self.tree(reports)), (ledger_before, reports_before))

    def test_missing_previous_snapshot_still_gives_fixed_without_section(self):
        self.check()
        paths = json.loads(cli("paths", "post.md", cwd=self.root).stdout)
        Path(paths["checked"]).unlink()
        self.art.write_text(EDITED, encoding="utf-8")
        self.check()
        (fixed,) = [e for e in self.events() if e["outcome"] == "fixed"]
        self.assertEqual(fixed["rule"], "4b")
        self.assertNotIn("section", fixed["facets"])  # no old text to place it in
        self.assertFalse(capture.previous_pair(Path(paths["checked"]))[0].exists())

    def test_mismatched_previous_snapshot_gives_no_section_and_no_previous_pair(self):
        self.check()
        paths = json.loads(cli("paths", "post.md", cwd=self.root).stdout)
        Path(paths["checked"]).write_text("# Not the checked text\n", encoding="utf-8")
        self.art.write_text(EDITED, encoding="utf-8")
        self.check()
        (fixed,) = [e for e in self.events() if e["outcome"] == "fixed"]
        self.assertNotIn("section", fixed["facets"])
        prev_snap, prev_lint = capture.previous_pair(Path(paths["checked"]))
        self.assertFalse(prev_snap.exists() or prev_lint.exists())
        self.assertEqual(Path(paths["checked"]).read_bytes(), EDITED.encode("utf-8"))

    def test_article_changed_during_the_check_removes_the_old_snapshot(self):  # sha-mismatch path
        self.check()
        paths = json.loads(cli("paths", "post.md", cwd=self.root).stdout)
        snap = Path(paths["checked"])
        self.assertTrue(snap.exists())
        lint = report.run_lint(self.art, default_profile(), cfg=CFG)
        self.art.write_text(EDITED, encoding="utf-8")  # changed after the lint was made
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            capture.for_check(lint, self.art, default_profile(), CFG, self.root, previous=lint, snapshot=snap,
                              reports=snap.parent)
        self.assertIn("the article changed while it was being checked", err.getvalue())
        self.assertFalse(snap.exists())  # never a snapshot beside a lint it doesn't match

    def test_snapshot_written_and_listed_in_paths(self):
        self.check()
        paths = json.loads(cli("paths", "post.md", cwd=self.root).stdout)
        snap = Path(paths["checked"])
        self.assertTrue(snap.name.endswith(".checked.md"))
        self.assertEqual(snap.read_bytes(), self.art.read_bytes())
        self.art.write_text(EDITED, encoding="utf-8")
        self.check()
        self.assertEqual(snap.read_bytes(), EDITED.encode("utf-8"))

    def test_capture_off_writes_nothing_and_changes_nothing(self):
        on = self.check()
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        (other / ".git").mkdir()
        (other / ".plainspoken").mkdir()
        (other / ".plainspoken" / "config.toml").write_text("[kaizen]\ncapture = false\n", encoding="utf-8")
        (other / "post.md").write_text(ARTICLE, encoding="utf-8")
        off = cli("check", "post.md", "--profile", "default", cwd=other)
        self.assertEqual((off.returncode, off.stdout, off.stderr), (on.returncode, on.stdout, ""))
        self.assertFalse((other / ".plainspoken" / "ledger").exists())
        # the snapshot is kaizen's, so capture off writes none (the saved lint is check's own)
        paths = json.loads(cli("paths", "post.md", cwd=other).stdout)
        self.assertTrue(Path(paths["lint"]).exists())
        self.assertFalse(Path(paths["checked"]).exists())
        self.assertEqual(sorted(x.name for x in Path(paths["lint"]).parent.iterdir()), [Path(paths["lint"]).name])

    def test_symlinked_ledger_folder(self):
        normal = self.check("--no-save")
        shutil.rmtree(self.ledger_dir)
        real = self.root / "elsewhere"
        real.mkdir()
        self.ledger_dir.symlink_to(real, target_is_directory=True)
        r = self.check()
        self.assertEqual((r.returncode, r.stdout), (normal.returncode, normal.stdout))
        skipped = [x for x in r.stderr.splitlines() if "kaizen capture skipped" in x]
        self.assertEqual(len(skipped), 1, r.stderr)
        self.assertTrue(skipped[0].startswith("plainspoken: kaizen capture skipped: LedgerError: "))
        self.assertEqual(list(real.iterdir()), [])  # nothing written through the symlink, friction included

    def test_symlinked_month_file_logs_capture_error(self):
        normal = self.check("--no-save")
        for p in self.ledger_dir.iterdir():
            p.unlink()
            p.symlink_to(self.root / "target.jsonl")
        r = self.check()
        self.assertEqual((r.returncode, r.stdout), (normal.returncode, normal.stdout))
        self.assertEqual(r.stderr.count("kaizen capture skipped"), 1, r.stderr)
        rows = [json.loads(x) for x in (self.ledger_dir / "friction.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(x["kind"], x["source"]) for x in rows], [("capture_error", "check")])
        self.assertFalse((self.root / "target.jsonl").exists())

    def test_bad_kaizen_settings_skip_capture_quietly(self):
        (self.root / ".plainspoken").mkdir()
        (self.root / ".plainspoken" / "config.toml").write_text('[kaizen]\nadapter = "github"\n', encoding="utf-8")
        r = self.check()
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("anti-AI lint", r.stdout)
        self.assertEqual(r.stderr.count("plainspoken: kaizen capture skipped: ConfigError: "), 1, r.stderr)
        self.assertFalse(self.ledger_dir.exists())
        paths = json.loads(cli("paths", "post.md", cwd=self.root).stdout)
        self.assertFalse(Path(paths["checked"]).exists())  # no snapshot when the settings can't be built

    def test_privacy_no_article_text_with_excerpts_off(self):
        self.check()
        self.art.write_text(EDITED, encoding="utf-8")
        self.check()
        lines = [ledger.normalise(x) for x in self.lines()]
        self.assertTrue(lines)
        runs = _six_word_runs(ARTICLE) | _six_word_runs(EDITED)
        leaked = [r for r in runs if any(r in x for x in lines)]
        self.assertEqual(leaked, [])

    def test_privacy_test_has_teeth_with_excerpts_on(self):
        self.check(env={"CLAUDE_PLUGIN_OPTION_LEDGER_EXCERPTS": "true"})
        lines = [ledger.normalise(x) for x in self.lines()]
        self.assertTrue(any(r in x for r in _six_word_runs(ARTICLE) for x in lines))


def _six_word_runs(text: str) -> set[str]:
    words = re.findall(r"[a-z']+", ledger.normalise(text))
    return {" ".join(words[i:i + 6]) for i in range(len(words) - 5)}


class LintWatchHook(unittest.TestCase):
    HOOK = REPO / "hooks" / "lint_watch.py"

    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.art = self.project / "post.md"
        self.art.write_text(ARTICLE, encoding="utf-8")
        self.ledger_dir = self.project / ".plainspoken" / "ledger"

    def run_hook(self, payload):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env.update({"CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_PLUGIN_DATA": str(self.project / ".data"),
                    "CLAUDE_PLUGIN_OPTION_PROFILE": "default"})
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(self.HOOK)], input=stdin, capture_output=True, text=True,
                              env=env, cwd=self.project)

    def test_write_event_appends_fired(self):
        r = self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s1",
                           "cwd": str(self.project), "tool_input": {"file_path": str(self.art)}})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hookSpecificOutput", r.stdout)
        events = ledger.read({"ledger_dir": self.ledger_dir, "root": self.project})[0]
        self.assertEqual({e["rule"] for e in events}, {"2", "4b", "7d"})
        self.assertTrue(all((e["event"], e["actor"], e["outcome"]) == ("lint", "lint", "fired") for e in events))
        self.assertEqual({e["doc_id"] for e in events}, {ledger.doc_id(self.art, self.project)})

    def test_capture_root_is_the_one_check_finds(self):  # resolve via config.project_root
        top = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, top, ignore_errors=True)
        (top / ".git").mkdir()
        sub = top / "sub"
        sub.mkdir()
        art = sub / "post.md"
        art.write_text(ARTICLE, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env.update({"CLAUDE_PROJECT_DIR": str(sub), "CLAUDE_PLUGIN_DATA": str(top / ".data"),
                    "CLAUDE_PLUGIN_OPTION_PROFILE": "default"})
        r = subprocess.run([sys.executable, str(self.HOOK)], capture_output=True, text=True, env=env, cwd=sub,
                           input=json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Write",
                                             "session_id": "s1", "cwd": str(sub),
                                             "tool_input": {"file_path": str(art)}}))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((sub / ".plainspoken" / "ledger").exists())
        hook_ids = {e["doc_id"] for e in ledger.read({"ledger_dir": top / ".plainspoken" / "ledger",
                                                      "root": top})[0]}
        cli("check", "post.md", "--profile", "default", cwd=sub)  # check from the same folder, as Bash runs it
        events = ledger.read({"ledger_dir": top / ".plainspoken" / "ledger", "root": top})[0]
        self.assertEqual(hook_ids, {ledger.doc_id(art, top)})
        self.assertEqual({e["doc_id"] for e in events}, hook_ids)

    def test_a_cwd_in_a_sibling_repo_records_under_the_edited_files_project(self):
        (self.project / ".git").mkdir()
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        (other / ".git").mkdir()
        r = self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s1",
                           "cwd": str(other), "tool_input": {"file_path": str(self.art)}})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((other / ".plainspoken").exists())  # never a folder in another repository
        events = ledger.read({"ledger_dir": self.ledger_dir, "root": self.project})[0]
        self.assertEqual({e["doc_id"] for e in events}, {ledger.doc_id(self.art, self.project)})

    def test_bad_stdin_appends_nothing(self):
        r = self.run_hook("{not json")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))
        self.assertFalse(self.ledger_dir.exists())


class CaptureSources(unittest.TestCase):  # [kaizen] capture_sources
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()
        self.art = self.root / "post.md"
        self.art.write_text(ARTICLE, encoding="utf-8")
        self.ledger_dir = self.root / ".plainspoken" / "ledger"
        (self.root / ".plainspoken").mkdir()

    def sources(self, *names):
        body = ", ".join(f'"{n}"' for n in names)
        (self.root / ".plainspoken" / "config.toml").write_text(f"[kaizen]\ncapture_sources = [{body}]\n",
                                                               encoding="utf-8")

    def events(self):
        return ledger.read({"ledger_dir": self.ledger_dir, "root": self.root})[0]

    def friction(self):
        path = self.ledger_dir / "friction.jsonl"
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def hook(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env.update({"CLAUDE_PROJECT_DIR": str(self.root), "CLAUDE_PLUGIN_DATA": str(self.root / ".data"),
                    "CLAUDE_PLUGIN_OPTION_PROFILE": "default"})
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": "s1",
                   "cwd": str(self.root), "tool_input": {"file_path": str(self.art)}}
        return subprocess.run([sys.executable, str(REPO / "hooks" / "lint_watch.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, cwd=self.root)

    def test_capture_sources_drops_lint_watch(self):
        self.sources("check", "merge", "judge")
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("BLOCK", r.stdout)  # the hook still lints; it just doesn't record
        self.assertEqual(self.events(), [])
        r = cli("check", "post.md", "--profile", "default", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stderr)
        events = self.events()
        self.assertTrue(events)
        self.assertTrue(all(e["outcome"] == "fired" and e["event"] == "lint" for e in events))
        r = cli("merge", "post.md", "--profile", "default", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stderr)  # INCOMPLETE: no judge verdicts
        self.assertEqual([row["kind"] for row in self.friction()], ["merge_incomplete"])

    def test_dropped_check_writes_no_events_and_no_snapshot(self):
        self.sources("lint-watch")
        r = cli("check", "post.md", "--profile", "default", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(self.events(), [])
        paths = json.loads(cli("paths", "post.md", cwd=self.root).stdout)
        self.assertFalse(Path(paths["checked"]).exists())
        self.hook()
        self.assertTrue(self.events())

    def test_dropped_judge_and_merge_log_no_friction(self):
        self.sources("check")
        capture.for_rejected_reply("stale", self.root)
        capture.record((), self.root, "merge", frictions=[("merge_incomplete", "x")])
        self.assertEqual(self.friction(), [])
        self.sources("judge")
        capture.for_rejected_reply("stale", self.root)
        self.assertEqual([(r["kind"], r["source"]) for r in self.friction()],
                         [("judge_reply_rejected", "judge-record")])

    def test_dropped_judge_skips_the_backstop(self):
        self.sources("check")
        self.ledger_dir.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env.update({"CLAUDE_PROJECT_DIR": str(self.root), "CLAUDE_PLUGIN_DATA": str(self.root / ".data")})
        payload = {"hook_event_name": "SubagentStop", "session_id": "s1", "cwd": str(self.root),
                   "agent_type": "plainspoken:tells-judge", "agent_id": "a1"}
        r = subprocess.run([sys.executable, str(REPO / "hooks" / "kaizen_backstop.py")], input=json.dumps(payload),
                           capture_output=True, text=True, env=env, cwd=self.root)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(self.friction(), [])


class Settings(unittest.TestCase):
    def test_kaizen_settings_still_resolve(self):  # guards the fixture assumption the CLI tests rely on
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        s = config.kaizen_settings(root, {})
        self.assertEqual(s["ledger_dir"], root.resolve() / ".plainspoken" / "ledger")


# --- merge, JR and judge-record ---------------------------------------------------------------------------------

QUOTE = "I dug in two bags of compost and a handful of blood and bone"  # article text a judge quotes (never logged)
JUSTIFY_REASON = "the quiet garden-bed rhythm is how my own seed diary reads"  # a person's justification (never logged)


class MergeCli(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()
        self.art = self.root / "post.md"
        self.art.write_text(ARTICLE, encoding="utf-8")
        self.ledger_dir = self.root / ".plainspoken" / "ledger"
        self.dir = self.root / ".plainspoken" / "reports"
        self.key = report.report_key(self.art, self.root)

    def run_cli(self, *args, env=None, root=None):
        return cli(*args, cwd=root or self.root, env=env)

    def check(self, env=None, root=None):
        r = self.run_cli("check", "post.md", "--profile", "default", env=env, root=root)
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return r

    def merge(self, env=None, root=None):
        return self.run_cli("merge", "post.md", "--profile", "default", env=env, root=root)

    def judges(self, root=None):
        """Every judge passes, apart from J1 failing 5b with evidence quoting QUOTE (line 10)."""
        root = root or self.root
        d, key = root / ".plainspoken" / "reports", report.report_key(root / "post.md", root)
        lint = json.loads((d / f"{key}.lint.json").read_text(encoding="utf-8"))
        prof = default_profile()
        self.assertEqual(lint["profile_sha256"], prof.sha256)  # the CLI's `default` is the profile the helper uses
        _judges(d, key, lint["article_sha256"], CFG, prof, fails=("5b",))
        p = d / f"{key}.J1.judge.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        for v in data["verdicts"]:
            if v["rule"] == "5b":
                v["evidence"] = [{"line": 10, "quote": QUOTE, "reason": "frames what the paragraph is about to do"}]
        p.write_text(json.dumps(data), encoding="utf-8")
        return lint

    def justify_7d(self, verdict="accept"):
        sha = hashlib.sha256(self.art.read_bytes()).hexdigest()
        jp = self.dir / f"{self.key}.justify.json"
        jp.write_text(json.dumps({"article_sha256": sha, "items": [
            {"rule": "7d", "kind": "voice", "reason": JUSTIFY_REASON}]}), encoding="utf-8")
        prof = default_profile()
        (self.dir / f"{self.key}.JR.judge.json").write_text(json.dumps({
            "group": "JR", "article_sha256": sha, "justify_sha256": hashlib.sha256(jp.read_bytes()).hexdigest(),
            "profile_sha256": prof.sha256, "ruleset_version": CFG.version,
            "verdicts": [{"rule": "7d", "verdict": verdict, "reason": "the reason holds for the FAQ answer"}]}),
            encoding="utf-8")

    def events(self, *kinds):
        evs = ledger.read({"ledger_dir": self.ledger_dir, "root": self.root})[0]
        return [e for e in evs if not kinds or e["event"] in kinds]

    def friction(self, root=None):
        p = (root or self.root) / ".plainspoken" / "ledger" / "friction.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def lines(self):
        out = []
        for p in sorted(self.ledger_dir.iterdir()):
            out += p.read_text(encoding="utf-8").splitlines()
        return out

    def test_judge_fired_and_passed(self):
        self.check()
        self.judges()
        r = self.merge()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # FAIL: the lint's delve BLOCK
        self.assertTrue(r.stdout.startswith("FAIL · "), r.stdout)
        judged = {e["rule"]: e for e in self.events("judge")}
        fired = [e for e in judged.values() if e["outcome"] == "fired"]
        self.assertEqual([(e["rule"], e["actor"], e["severity"]) for e in fired], [("5b", "judge:J1", "BLOCK")])
        self.assertEqual(fired[0]["span_hash"], ledger.span_hash("5b", QUOTE))
        self.assertEqual(fired[0]["facets"], {"agree": False, "section": "other"})  # lint had no 5b finding
        self.assertEqual((judged["26"]["outcome"], judged["26"]["actor"]), ("passed", "judge:J1"))
        self.assertEqual(judged["26"]["span_hash"], ledger.span_hash("26", "*"))
        self.assertIs(judged["26"]["facets"]["agree"], True)  # no lint finding, judge passes
        self.assertIs(judged["6"]["facets"]["agree"], False)  # a lint CANDIDATE the judge passes
        self.assertEqual(judged["6"]["outcome"], "passed")
        # The lint's delve BLOCK forces rule 2's merged verdict to fail; the judge itself passed it.
        self.assertEqual((judged["2"]["outcome"], judged["2"]["actor"]), ("passed", "judge:J3"))
        self.assertIs(judged["2"]["facets"]["agree"], False)
        self.assertNotIn("agree", judged["9"]["facets"])  # a judge-only rule has no lint side
        self.assertEqual({e["doc_id"] for e in judged.values()}, {ledger.doc_id(self.art, self.root)})
        self.assertEqual({e["doc_sha"] for e in judged.values()}, {hashlib.sha256(self.art.read_bytes()).hexdigest()})
        self.assertEqual(self.friction(), [])

    def test_justified_and_jr_accept(self):
        self.check()
        self.judges()
        self.justify_7d("accept")
        r = self.merge()
        self.assertNotIn("7d", r.stdout.split("unresolved", 1)[1], r.stdout)
        (j,) = self.events("justify")
        (jr,) = self.events("jr")
        self.assertEqual((j["outcome"], j["actor"], j["rule"], j["severity"]), ("justified:voice", "human", "7d", "WARN"))
        self.assertEqual((jr["outcome"], jr["actor"], jr["rule"], jr["severity"]), ("jr_accept", "jr", "7d", "WARN"))
        self.assertEqual(j["span_hash"], ledger.span_hash("7d", "*"))
        self.assertEqual(jr["span_hash"], j["span_hash"])
        for e in (j, jr):
            self.assertNotIn("reason", e)
            self.assertNotIn("excerpt", e)

    def test_jr_reject(self):
        self.check()
        self.judges()
        self.justify_7d("reject")
        self.merge()
        self.assertEqual([e["outcome"] for e in self.events("justify", "jr")], ["justified:voice", "jr_reject"])

    def test_merge_twice_adds_no_new_ids(self):
        self.check()
        self.judges()
        self.justify_7d()
        self.merge()
        first = {e["id"] for e in self.events()}
        n = len(self.events())
        self.merge()
        self.assertGreater(len(self.events()), n)
        self.assertEqual({e["id"] for e in self.events()}, first)

    def test_incomplete_merge_logs_friction_and_changes_nothing(self):
        self.check()
        on = self.merge()
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        (other / ".git").mkdir()
        (other / ".plainspoken").mkdir()
        (other / ".plainspoken" / "config.toml").write_text("[kaizen]\ncapture = false\n", encoding="utf-8")
        (other / "post.md").write_text(ARTICLE, encoding="utf-8")
        self.check(root=other)
        off = self.merge(root=other)
        self.assertEqual((on.returncode, on.stdout, on.stderr), (off.returncode, off.stdout, ""))
        self.assertTrue(on.stdout.startswith("INCOMPLETE"), on.stdout)
        (row,) = self.friction()
        self.assertEqual((row["kind"], row["source"]), ("merge_incomplete", "merge"))
        self.assertTrue(row["detail"].startswith("J1: judge file missing"), row)
        self.assertLessEqual(len(row["detail"]), 200)
        self.assertEqual(self.events("judge", "justify", "jr"), [])
        self.assertFalse((other / ".plainspoken" / "ledger").exists())

    def test_privacy_no_judge_quote_or_reason_with_excerpts_on(self):
        env = {"CLAUDE_PLUGIN_OPTION_LEDGER_EXCERPTS": "true"}
        self.check(env=env)
        self.judges()
        self.justify_7d()
        self.merge(env=env)
        self.assertTrue(self.events("judge") and self.events("jr"))
        lines = [ledger.normalise(x) for x in self.lines()]
        for text in (QUOTE, JUSTIFY_REASON, "frames what the paragraph", "the reason holds"):
            self.assertFalse(any(ledger.normalise(text) in x for x in lines), text)
        self.assertTrue(any("excerpt" in e for e in self.events("lint")))  # excerpts really are on
        self.assertFalse(any("excerpt" in e or "reason" in e for e in self.events("judge", "justify", "jr")))

    def test_capture_error_at_merge_keeps_output(self):
        self.check()
        self.judges()
        normal = self.merge()
        for p in self.ledger_dir.glob("*.jsonl"):
            if p.name != "friction.jsonl":
                p.unlink()
                p.symlink_to(self.root / "target.jsonl")
        r = self.merge()
        self.assertEqual((r.returncode, r.stdout), (normal.returncode, normal.stdout))
        self.assertEqual(r.stderr.count("plainspoken: kaizen capture skipped: LedgerError: "), 1, r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)

    def reply(self, data) -> Path:
        p = self.root / "reply.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_stale_judge_reply_logs_friction(self):
        self.check()
        p = self.reply({"group": "J1", "article_sha256": "0" * 64, "verdicts": []})
        r = self.run_cli("judge-record", "post.md", "--group", "J1", "--from", str(p))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr, "plainspoken: judge reply not recorded: stale: the reply judged a different "
                                   "version of the article\n")
        (row,) = self.friction()
        self.assertEqual((row["kind"], row["source"], row["detail"]),
                         ("judge_reply_rejected", "judge-record",
                          "stale: the reply judged a different version of the article"))

    def test_rejected_reply_detail_carries_no_reply_text(self):
        self.check()
        p = self.reply({"group": QUOTE, "verdicts": []})
        r = self.run_cli("judge-record", "post.md", "--group", "J2", "--from", str(p))
        self.assertEqual(r.returncode, 1)
        self.assertIn(QUOTE, r.stderr)  # stderr is unchanged; only the ledger is scrubbed
        (row,) = self.friction()
        self.assertEqual(row["detail"], "reply is for group ?, expected J2")

    def test_capture_failure_at_judge_record_keeps_the_output(self):
        self.check()
        p = self.reply({"group": "J1", "article_sha256": "0" * 64, "verdicts": []})
        normal = self.run_cli("judge-record", "post.md", "--group", "J1", "--from", str(p))
        (self.root / ".plainspoken" / "config.toml").write_text('[kaizen]\nadapter = "github"\n', encoding="utf-8")
        p = self.reply({"group": "J1", "article_sha256": "0" * 64, "verdicts": []})
        r = self.run_cli("judge-record", "post.md", "--group", "J1", "--from", str(p))
        self.assertEqual((r.returncode, r.stdout), (normal.returncode, normal.stdout))
        lines = r.stderr.splitlines()
        self.assertEqual(lines[0], normal.stderr.strip())
        self.assertEqual(len(lines), 2, r.stderr)
        self.assertTrue(lines[1].startswith("plainspoken: kaizen capture skipped: ConfigError: "), r.stderr)
        self.assertEqual(len(self.friction()), 1)  # only the first, captured reply
        (self.root / ".plainspoken" / "config.toml").unlink()
        shutil.rmtree(self.ledger_dir)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.ledger_dir.symlink_to(elsewhere, target_is_directory=True)
        p = self.reply({"group": "J1", "article_sha256": "0" * 64, "verdicts": []})
        r = self.run_cli("judge-record", "post.md", "--group", "J1", "--from", str(p))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (normal.returncode, normal.stdout, normal.stderr))
        self.assertEqual(list(elsewhere.iterdir()), [])  # friction never writes through the link

    def test_merge_friction_detail_carries_no_justify_text(self):  # the scrubber at the CLI level
        self.check()
        self.judges()
        sha = hashlib.sha256(self.art.read_bytes()).hexdigest()
        (self.dir / f"{self.key}.justify.json").write_text(json.dumps({"article_sha256": sha, "items": [
            {"rule": JUSTIFY_REASON, "kind": "nope", "reason": JUSTIFY_REASON}]}), encoding="utf-8")
        r = self.merge()
        self.assertTrue(r.stdout.startswith("INCOMPLETE"), r.stdout)
        (row,) = self.friction()
        self.assertEqual(row["kind"], "merge_incomplete")
        self.assertNotIn("seed diary", row["detail"])
        self.assertIn("justify: rule ?", row["detail"])

    def test_recorded_reply_logs_no_friction(self):
        self.check()
        sha = hashlib.sha256(self.art.read_bytes()).hexdigest()
        p = self.reply({"group": "J1", "article_sha256": sha, "verdicts": []})
        r = self.run_cli("judge-record", "post.md", "--group", "J1", "--from", str(p))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.friction(), [])


class MergeEvents(unittest.TestCase):
    def merged(self, **rules):
        return {"article": "post.md", "profile": "default", "ruleset_version": CFG.version,
                "article_sha256": "a" * 64, "profile_sha256": "b" * 64, "justified": [], "rules": rules}

    def test_doc_id_override_and_lint_only_entries_skipped(self):
        m = self.merged(**{"4b": {"source": "lint", "verdict": "fail", "severity": "WARN", "findings": []},
                           "18": {"source": "judge:J1", "verdict": "pass", "severity": "WARN", "evidence": [],
                                  "findings": []}})
        (e,) = capture.merge_events(m, None, CFG, Path("."), doc_id=ledger.label_id("article-2"))
        self.assertEqual((e["rule"], e["outcome"], e["doc_id"]), ("18", "passed", ledger.label_id("article-2")))

    def test_agree_comes_from_the_entry_findings(self):  # no second read of the lint on disk
        cand = _finding("6", 10, "x", "Three-item list", "CANDIDATE")
        m = self.merged(**{"6": {"source": "judge:J2", "verdict": "pass", "severity": "BLOCK", "evidence": [],
                                 "findings": [cand]}})
        (e,) = capture.merge_events(m, None, CFG, Path("."))
        self.assertIs(e["facets"]["agree"], False)  # the lint flagged it, the judge passed it
        m["rules"]["6"]["findings"] = []
        (e,) = capture.merge_events(m, None, CFG, Path("."))
        self.assertIs(e["facets"]["agree"], True)

    def test_a_judge_pass_keeps_the_rules_own_severity(self):  # not the lint BLOCK that overrode it
        m = self.merged(**{"7b": {"source": "judge:J2", "verdict": "fail", "judge_verdict": "pass",
                                  "severity": "BLOCK", "evidence": [], "findings": []}})
        (e,) = capture.merge_events(m, None, CFG, Path("."))
        self.assertEqual((e["outcome"], e["severity"]), ("passed", CFG.rules["7b"].severity))
        m["rules"]["7b"]["judge_verdict"] = "fail"  # the judge's own fail on a lint-BLOCKed rule stays BLOCK
        (e,) = capture.merge_events(m, None, CFG, Path("."))
        self.assertEqual((e["outcome"], e["severity"]), ("fired", "BLOCK"))

    def test_damaged_entries_are_skipped(self):
        m = self.merged(**{"5b": {"source": "judge:J9", "verdict": "fail"}, "26": "x",
                           "11": {"source": "judge:J1", "verdict": "maybe"},
                           "18": {"source": "judge:J1", "verdict": "fail", "severity": "WARN",
                                  "evidence": ["not a dict", {"quote": 3}]}})
        m["justified"] = [{"rule": "7d", "kind": "nonsense", "review": "accept"}, "x"]
        (e,) = capture.merge_events(m, None, CFG, Path("."))
        self.assertEqual((e["rule"], e["span_hash"]), ("18", ledger.span_hash("18", "*")))


class FrictionDetail(unittest.TestCase):
    def test_problem_details_drop_free_text(self):
        secret = "my neighbour knows far more about it"
        cases = {
            f"justify: item without a rule: {{'kind': 'voice', 'reason': '{secret}'}}": "justify: item without a rule",
            f"J2: bad verdict entry for rule {secret}": "J2: bad verdict entry for rule ?",
            "J2: bad verdict entry for rule 7b": "J2: bad verdict entry for rule 7b",
            f"JR: bad verdict entry for rule {secret}": "JR: bad verdict entry for rule ?",
            f"JR: no verdict for rule {secret}": "JR: no verdict for rule ?",
            f"justify: rule {secret} is justified twice": "justify: rule ? is justified twice",
            f"justify: rule {secret}: kind must be one of voice, quote": "justify: rule ?: kind must be one of voice, quote",
            f"justify: rule {secret}: reason must be one line": "justify: rule ?: reason must be one line",
            f"lint report made under ruleset '{secret}', current is '3.0.0' (the ruleset changed) — rerun `check`":
                "lint report made under ruleset ?, current is '3.0.0' (the ruleset changed) — rerun `check`",
            f"reply is for group '{secret}', expected J1": "reply is for group ?, expected J1",
            "reply is for group 'J2', expected J1": "reply is for group 'J2', expected J1",
            f"no current lint for {secret}.md: run `check` first": "no current lint for the article: run `check` first",
            "J1: judge file missing or not valid JSON": "J1: judge file missing or not valid JSON",
        }
        cases.update({  # a slot keeps only a rule id, a group or a version, never a short word
            "J2: bad verdict entry for rule delve": "J2: bad verdict entry for rule ?",
            "justify: rule compost is justified twice": "justify: rule ? is justified twice",
            "reply is for group 'beans', expected J1": "reply is for group ?, expected J1",
            "J2: bad verdict entry for rule NR-2": "J2: bad verdict entry for rule NR-2",
            "JR: no verdict for rule 4a2": "JR: no verdict for rule 4a2",
            "reply is for group 'JR', expected J1": "reply is for group 'JR', expected J1"})
        for raw, want in cases.items():
            self.assertEqual(capture.engine_detail(raw), want, raw)
        self.assertEqual(capture.engine_detail("first line\nsecond"), "first line")

    def test_slots_match_the_messages_the_engine_really_makes(self):  # pinned to the producers
        secret = "my neighbour knows far more about it"
        made = justify.validate_justify({"article_sha256": "a" * 64, "items": [
            {"kind": "voice", "reason": secret}, {"rule": secret, "kind": "nope", "reason": "x"},
            {"rule": secret, "kind": "voice", "reason": f"{secret}\nsecond line"}]})
        made += justify.validate_review({"verdicts": [{"rule": secret, "verdict": "maybe"}]}, {secret, "7d"})
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        art = root / f"{secret}.md"
        art.write_text(ARTICLE, encoding="utf-8")
        for group, reply in (("J1", {"group": secret, "verdicts": []}), ("J1", {"group": "J1", "verdicts": []})):
            try:
                judges.record_reply(art, group, json.dumps(reply), root / "reports", root)
            except ValueError as e:
                made.append(str(e))
        self.assertGreaterEqual(len(made), 8, made)
        self.assertGreaterEqual(sum(secret in raw for raw in made), 7, made)
        for raw in made:
            self.assertNotIn("neighbour", capture.engine_detail(raw), raw)  # every producer's slot is scrubbed


        self.assertEqual(len(capture.engine_detail("x" * 500)), 200)


if __name__ == "__main__":
    unittest.main()
