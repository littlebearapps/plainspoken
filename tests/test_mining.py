"""`kaizen mine` compares model drafts written from the fixed briefs with a human corpus and queues at
most 5 model-tagged candidates. It never edits the ruleset and never calls a model."""
import hashlib
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
from types import SimpleNamespace
from unittest import mock

from plainspoken import adapters, calibrate, config, ledger, mining, proposals
from plainspoken.adapters import file as file_adapter
from plainspoken.profile import default as default_profile
from plainspoken.registry import load_config
from scripts.dev import leak_guard

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "data" / "rules.toml"
FIX = REPO / "tests" / "fixtures" / "kaizen" / "mining"
BRIEFS = REPO / "evals" / "briefs"
CFG = load_config()
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def shipped_hashes() -> dict[str, str]:
    files = [RULES, REPO / "data" / "profiles" / "default.toml", REPO / "data" / "kaizen.toml",
             *sorted(p for p in (REPO / "data" / "rubrics").rglob("*") if p.is_file())]
    return {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


# The fixtures hold 2 or 3 drafts per model, below the real bar (`mining.MIN_MODEL_DRAFTS`, 10), so the tests lower
# it; `Bar` checks the real one.
_CLI = ("import sys; from plainspoken import mining; mining.MIN_MODEL_DRAFTS = int(sys.argv[1]); "
        "from plainspoken.__main__ import main; sys.exit(main(sys.argv[2:]))")


def cli(*args, cwd: Path, bar: int = 1):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    e["PYTHONPATH"] = str(REPO / "lib")
    return subprocess.run([sys.executable, "-c", _CLI, str(bar), *args], cwd=cwd, capture_output=True, text=True,
                          env=e)


class PhraseRates(unittest.TestCase):
    STOP = frozenset(CFG.lists["repeat_stopwords"])

    def test_rate_per_thousand_words_and_docs(self):
        texts = ["Red kite over the hill. A red kite again.", "No birds here at all today, sadly."]
        rates = mining.phrase_rates(texts, 2, 2, stopwords=self.STOP)
        rate, docs = rates["red kite"]
        words = 9 + 7
        self.assertAlmostEqual(rate, 2 * 1000 / words, places=6)
        self.assertEqual(docs, 1)

    def test_ngrams_stay_inside_sentences(self):
        rates = mining.phrase_rates(["Green door. Blue gate!\nOld fence? New wall"], 2, 3, stopwords=self.STOP)
        self.assertIn("green door", rates)
        self.assertIn("new wall", rates)
        for phrase in ("door blue", "gate old", "fence new"):
            self.assertNotIn(phrase, rates)

    def test_stopword_only_and_brief_words_are_skipped(self):
        rates = mining.phrase_rates(["It is what it is, with the tide coming in."], 2, 3, stopwords=self.STOP,
                                    brief_words=frozenset({"tide"}))
        self.assertNotIn("it is", rates)
        self.assertNotIn("the tide", rates)
        self.assertNotIn("tide coming", rates)
        self.assertIn("coming in", rates)

    def test_frontmatter_code_and_curly_apostrophes(self):
        text = "---\ntitle: Moss garden\n---\n\nThe moss’s colour.\n\n```\nsecret phrase here\n```\n"
        rates = mining.phrase_rates([text], 2, 2, stopwords=self.STOP)
        self.assertIn("moss's colour", rates)
        self.assertNotIn("secret phrase", rates)
        self.assertNotIn("moss garden", rates)


class Case(unittest.TestCase):
    BAR = 1

    def setUp(self):
        bar = mock.patch.object(mining, "MIN_MODEL_DRAFTS", self.BAR)
        bar.start()
        self.addCleanup(bar.stop)
        self.tmp = Path(tempfile.mkdtemp(prefix="plainspoken-mine-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "project"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.settings = {**config.kaizen_settings(self.root, {}), **calibrate.load_settings(),
                         "mining": mining.load_settings()}
        self.corpus = sorted((FIX / "corpus").glob("*.md"))

    def mine(self, drafts=FIX / "drafts", briefs=FIX / "briefs", corpus=None, **kw):
        return mining.mine(drafts, self.corpus if corpus is None else corpus, briefs, CFG, default_profile(),
                           self.settings, now=NOW, **kw)

    def stored(self) -> list[Path]:
        return sorted((self.root / ".plainspoken" / "kaizen" / "proposals").glob("*.json"))


class Mine(Case):
    def test_proposes_the_new_phrase_tagged_with_the_model(self):
        out = self.mine()
        self.assertEqual(out["models"], {"m1": {"drafts": 3, "words": out["models"]["m1"]["words"]}})
        phrases = [c for c in out["candidates"] if c["action"] == "add-term"]
        self.assertEqual([c["evidence"]["phrase"] for c in phrases], ["worth noting that"])
        p = phrases[0]
        self.assertEqual(p["model"], "m1")
        self.assertEqual(p["trigger"], "mined")
        self.assertEqual(p["rule"], "32")
        self.assertEqual(p["edits"][0], {"kind": "list_add", "list": "newer_model_words",
                                         "values": ["worth noting that"]})
        models = list(CFG.rules["32"].models)
        self.assertEqual(p["edits"][1], {"kind": "rule_field", "rule": "32", "field": "models", "old": models,
                                         "new": models + ["m1"]})
        self.assertRegex(p["diff"], r'(?m)^\+newer_model_words = \[.*"worth noting that"\]$')
        self.assertRegex(p["diff"], r'(?m)^\+models = \[.*"m1"\]$')
        self.assertEqual(p["base_sha256"], hashlib.sha256(RULES.read_bytes()).hexdigest())
        self.assertGreater(p["evidence"]["ratio"], 4)
        self.assertEqual(p["evidence"]["share"], 1.0)
        # "quietly" is already listed, so neither it nor a phrase around it is proposed
        self.assertFalse(any("quietly" in x["phrase"] for x in out["phrases"]))

    def test_a_phrase_in_one_of_three_drafts_is_no_candidate(self):
        out = self.mine()  # "copper tin" is in a.md's prose once (and in its code block, which doesn't count)
        self.assertFalse(any("copper" in x["phrase"] for x in out["phrases"]))

    def test_a_phrase_with_a_brief_word_is_no_candidate(self):
        out = self.mine()  # "whole spices keep" is in all three drafts, and the brief says "whole spices"
        self.assertFalse(any("spices" in x["phrase"] for x in out["phrases"]))
        other = self.mine(briefs=FIX / "briefs-other", dry_run=True)
        self.assertIn("whole spices keep", [x["phrase"] for x in other["phrases"]])

    def test_a_shadow_rule_firing_in_every_draft_is_a_promote(self):
        out = self.mine()
        promote = [c for c in out["candidates"] if c["action"] == "promote"]
        self.assertEqual([c["rule"] for c in promote], ["32"])
        self.assertEqual(promote[0]["edits"], [{"kind": "rule_field", "rule": "32", "field": "status",
                                                "old": "shadow", "new": None}])
        self.assertEqual(promote[0]["model"], "m1")
        self.assertIn('-status = "shadow"', promote[0]["diff"])
        moves = {m["rule"]: m for m in out["moves"]}
        self.assertEqual(moves["32"]["action"], "promote")
        self.assertEqual(moves["32"]["corpus_rate"], 0)
        # an active rule meeting the test (rule 4a fires on "it's worth noting that") is evidence only
        self.assertEqual(moves["4a"]["action"], "evidence")
        self.assertFalse(any(c["rule"] == "4a" for c in out["candidates"]))

    def test_ranked_by_ratio_times_share(self):
        out = self.mine()
        scores = [c["evidence"]["ratio"] * c["evidence"]["share"] for c in out["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_rank_order_is_ratio_times_share_not_either_alone(self):  # a ranking the sort must get right
        drafts = self.tmp / "ranked" / "m1"
        drafts.mkdir(parents=True)
        for n in range(4):  # cobalt harbour: 2 a draft in all 4; amber falcon: 1 in all 4; brisk meadow: 2 in 2 of 4
            body = "Amber falcon. Cobalt harbour. Cobalt harbour." + (" Brisk meadow. Brisk meadow." if n < 2 else "")
            (drafts / f"d{n}.md").write_text(f"# Notes\n\n{body}\n", encoding="utf-8")
        out = self.mine(drafts=drafts.parent, dry_run=True)
        terms = [c["evidence"]["phrase"] for c in out["candidates"] if c["action"] == "add-term"]
        self.assertEqual(terms, ["cobalt harbour", "amber falcon", "brisk meadow"])
        ev = {c["evidence"]["phrase"]: c["evidence"] for c in out["candidates"] if c["action"] == "add-term"}
        self.assertEqual(ev["amber falcon"]["ratio"], ev["brisk meadow"]["ratio"])  # same ratio: share decides
        self.assertGreater(ev["amber falcon"]["share"], ev["brisk meadow"]["share"])

    def test_a_promote_names_every_model_that_passed(self):  # not just the top-ranked one
        drafts = self.tmp / "two"
        for model in ("m1", "m2"):
            shutil.copytree(FIX / "drafts" / "m1", drafts / model)
        out = self.mine(drafts=drafts, dry_run=True)
        (promote,) = [c for c in out["candidates"] if c["action"] == "promote"]
        self.assertEqual(promote["evidence"]["models"], ["m1", "m2"])
        self.assertIn("m1", promote["summary"])
        self.assertIn("m2", promote["summary"])

    def test_a_known_proposal_isnt_measured_again(self):  # the id is checked before the corpus effect
        first = self.mine()
        for c in first["candidates"]:
            ledger.append(ledger.make_event(event="apply", actor="engine", outcome="applied", ruleset_version="1.0.0",
                                            profile="default", rule=c["rule"], proposal=c["id"], ts=NOW),
                          self.settings)
        with mock.patch.object(calibrate, "_effect", side_effect=AssertionError("measured again")) as effect:
            again = self.mine()
        self.assertEqual(again["candidates"], [])
        effect.assert_not_called()

    def test_never_more_than_five(self):
        drafts = self.tmp / "drafts"
        words = ["amber falcon", "brisk meadow", "cobalt harbour", "dusty lantern", "ember orchard",
                 "frosty pebble", "gentle quarry"]
        for model in ("m1", "m2"):
            (drafts / model).mkdir(parents=True)
            for n in range(2):
                (drafts / model / f"d{n}.md").write_text(
                    "# Notes\n\n" + " ".join(f"{w.capitalize()} {model} {n}." for w in words) + "\n", encoding="utf-8")
        out = self.mine(drafts=drafts)
        self.assertGreater(len(out["phrases"]), 5)
        self.assertEqual(len(out["candidates"]), 5)
        self.assertEqual(len(self.stored()), 5)

    def test_stores_logs_and_is_not_emitted(self):
        out = self.mine()
        ids = sorted(c["id"] for c in out["candidates"])
        self.assertEqual([p.stem for p in self.stored()], ids)
        events = ledger.read(self.settings)[0]
        self.assertEqual(sorted(e["proposal"] for e in events), ids)
        for e in events:
            self.assertEqual((e["event"], e["actor"], e["outcome"]), ("mine", "engine", "proposed"))
            self.assertEqual(e["facets"], {"model": "m1"})
        for c in out["candidates"]:
            stored = proposals.load(c["id"], self.settings)
            self.assertEqual(stored["trigger"], "mined")
            self.assertEqual(stored["model"], "m1")
            self.assertEqual(stored["adapter"], "file")  # the local queue: never github or trello
            self.assertTrue((self.root / stored["ref"]).is_file())
        self.assertEqual(adapters.unsent(self.settings), [])

    def test_a_second_run_skips_open_proposals(self):
        first = self.mine()
        self.assertTrue(first["candidates"])
        again = self.mine()
        self.assertEqual(again["candidates"], [])
        self.assertEqual(len(self.stored()), len(first["candidates"]))

    def test_dry_run_stores_and_logs_nothing(self):
        out = self.mine(dry_run=True)
        self.assertTrue(out["candidates"])
        self.assertFalse((self.root / ".plainspoken").exists())

    def test_never_edits_the_ruleset(self):
        before = shipped_hashes()
        self.mine()
        self.assertEqual(shipped_hashes(), before)

    def test_bad_input(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(mining.MiningError, "no drafts"):
            self.mine(drafts=empty)
        with self.assertRaisesRegex(mining.MiningError, "human corpus"):
            self.mine(corpus=[])
        bad = self.tmp / "bad"
        (bad / "not a model").mkdir(parents=True)
        (bad / "not a model" / "a.md").write_text("Some text here.\n", encoding="utf-8")
        with self.assertRaisesRegex(mining.MiningError, "'not a model'"):
            self.mine(drafts=bad)


class Bar(Case):
    """The mining bar is at least 10 drafts per model (6 briefs gave 6, too few for the share test to mean
    much)."""
    BAR = mining.MIN_MODEL_DRAFTS

    def test_the_bar_is_ten_drafts_per_model(self):
        self.assertEqual(mining.MIN_MODEL_DRAFTS, 10)

    def test_a_model_below_the_bar_is_skipped(self):
        texts = [f"# Note {n}\n\nIt's worth noting that the kettle hums. Item {n} is fine.\n" for n in range(10)]
        drafts = write_drafts(self.tmp / "drafts", "m2", texts)
        write_drafts(drafts, "m1", texts[:9])
        out = self.mine(drafts=drafts, dry_run=True)
        self.assertEqual(out["models"]["m1"]["skipped"], "fewer than 10 drafts")
        self.assertNotIn("skipped", out["models"]["m2"])
        self.assertTrue(out["candidates"])
        self.assertEqual({c["model"] for c in out["candidates"]}, {"m2"})
        self.assertEqual({x["model"] for x in out["phrases"] + out["moves"]}, {"m2"})

    def test_every_model_below_the_bar_is_bad_input(self):
        with self.assertRaisesRegex(mining.MiningError, "at least 10 drafts"):
            self.mine()  # the fixture's 3 drafts

    def test_the_cli_says_so(self):
        shutil.copytree(FIX / "corpus", self.root / "corpus")
        shutil.copytree(FIX / "drafts", self.root / "drafts")
        r = cli("kaizen", "mine", "--drafts", "drafts", "--corpus", "corpus/*.md", "--briefs", str(FIX / "briefs"),
                cwd=self.root, bar=mining.MIN_MODEL_DRAFTS)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("at least 10 drafts", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


class ModelIds(unittest.TestCase):
    """Ruling B1: '.' and '-' are the same in a model id, so a mined `claude-opus-5-5` matches rule 32's
    `claude-opus-5.5`, and the ruleset's spelling is the one kept."""
    M = {"target_rule": "32", "target_list": "newer_model_words"}

    def candidate(self, model, have):
        cfg = SimpleNamespace(rules={"32": SimpleNamespace(models=tuple(have))})  # all _phrase_candidate reads
        x = {"phrase": "worth noting that", "model": model, "ratio": 5.0, "drafts": 3, "of": 3, "share": 1.0}
        return mining._phrase_candidate(x, cfg, self.M)

    def model_edits(self, c):
        return [e for e in c["edits"] if e.get("field") == "models"]

    def test_an_equivalent_spelling_adds_no_model(self):
        self.assertEqual(self.model_edits(self.candidate("claude-opus-5-5", ["claude-opus-5.5"])), [])
        self.assertEqual(self.model_edits(self.candidate("claude-sonnet-5.5", ["claude-sonnet-5-5", "gpt-6"])), [])

    def test_a_new_model_is_added_once_as_mined(self):
        (edit,) = self.model_edits(self.candidate("claude-sonnet-5-5", ["claude-opus-5.5"]))
        self.assertEqual(edit["new"], ["claude-opus-5.5", "claude-sonnet-5-5"])

    def test_the_shipped_rule_32_spelling(self):  # the session id form against the ruleset's dotted form
        self.assertIn("claude-opus-5.5", CFG.rules["32"].models)
        self.assertEqual(self.model_edits(self.candidate("claude-opus-5-5", CFG.rules["32"].models)), [])


class Settings(unittest.TestCase):
    def test_shipped_values(self):
        self.assertEqual(mining.load_settings(), {
            "ngram_min": 2, "ngram_max": 4, "min_draft_share": 0.5, "min_drafts": 2, "ratio": 4.0,
            "smoothing_per_1k": 0.1, "max_candidates": 5, "target_list": "newer_model_words", "target_rule": "32",
            "not_tell_lists": NOT_BANS})

    def test_bad_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = calibrate.DEFAULT.read_text(encoding="utf-8")
            for old, new in (("target_rule = \"32\"", "target_rule = \"999\""), ("ngram_max = 4", "ngram_max = 1"),
                             ("smoothing_per_1k = 0.1", "smoothing_per_1k = 0")):
                path = Path(tmp) / "kaizen.toml"
                path.write_text(text.replace(old, new), encoding="utf-8")
                with self.assertRaises(ValueError, msg=new):
                    mining.load_settings(path)


class Cli(Case):
    def setUp(self):
        super().setUp()
        shutil.copytree(FIX / "corpus", self.root / "corpus")
        shutil.copytree(FIX / "drafts", self.root / "drafts")

    def test_mine_prints_candidates_and_keeps_the_ruleset(self):
        before = shipped_hashes()
        r = cli("kaizen", "mine", "--drafts", "drafts", "--corpus", "corpus/*.md", "--briefs", str(FIX / "briefs"),
                cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(shipped_hashes(), before)
        self.assertIn("m1: 3 drafts", r.stdout)
        self.assertIn('"worth noting that"', r.stdout)
        for p in self.stored():
            self.assertIn(p.stem, r.stdout)

    def test_json_and_dry_run(self):
        r = cli("kaizen", "mine", "--drafts", "drafts", "--corpus", "corpus/*.md", "--briefs", str(FIX / "briefs"),
                "--json", "--dry-run", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(set(out) >= {"models", "phrases", "moves", "candidates"}, True)
        self.assertTrue(out["candidates"])
        self.assertFalse((self.root / ".plainspoken").exists())

    def test_human_corpus_setting(self):
        (self.root / ".plainspoken").mkdir()
        (self.root / ".plainspoken" / "config.toml").write_text('[kaizen]\nhuman_corpus = ["corpus/*.md"]\n',
                                                                encoding="utf-8")
        r = cli("kaizen", "mine", "--drafts", "drafts", "--briefs", str(FIX / "briefs"), "--dry-run", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"worth noting that"', r.stdout)

    def test_bad_input_exits_2(self):
        (self.root / "empty").mkdir()
        for args, needle in ((("--drafts", "empty", "--corpus", "corpus/*.md"), "no drafts"),
                             (("--drafts", "drafts"), "human corpus"),
                             (("--drafts", "drafts", "--corpus", "nothing/*.md"), "human corpus"),
                             (("--drafts", "missing", "--corpus", "corpus/*.md"), "missing")):
            r = cli("kaizen", "mine", *args, cwd=self.root)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn(needle, r.stderr)
            self.assertNotIn("Traceback", r.stderr)
        (self.root / "drafts" / "bad name").mkdir()
        (self.root / "drafts" / "bad name" / "a.md").write_text("Text.\n", encoding="utf-8")
        r = cli("kaizen", "mine", "--drafts", "drafts", "--corpus", "corpus/*.md", cwd=self.root)
        self.assertEqual(r.returncode, 2)
        self.assertIn("'bad name'", r.stderr)

    def test_paths_are_relative_to_the_project_root(self):
        shutil.copytree(FIX / "briefs", self.root / "briefs")
        sub = self.root / "notes" / "deep"
        sub.mkdir(parents=True)
        r = cli("kaizen", "mine", "--drafts", "drafts", "--corpus", "corpus/*.md", "--briefs", "briefs", "--dry-run",
                cwd=sub)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"worth noting that"', r.stdout)

    def test_no_candidates(self):  # drafts that read like the corpus: nothing stands out
        drafts = self.root / "plain" / "m2"
        drafts.mkdir(parents=True)
        for f in ("h1.md", "h2.md"):
            shutil.copy(self.root / "corpus" / f, drafts / f)
        r = cli("kaizen", "mine", "--drafts", "plain", "--corpus", "corpus/*.md", "--briefs", str(FIX / "briefs"),
                cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no candidates", r.stdout)


def rules_copy(tmp: Path, drop: str | None = None) -> Path:
    path = tmp / "rules" / "rules.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = RULES.read_text(encoding="utf-8")
    if drop is not None:
        assert f'"{drop}", ' in text
        text = text.replace(f'"{drop}", ', "")
    path.write_text(text, encoding="utf-8")
    return path


def write_drafts(root: Path, model: str, texts: list[str]) -> Path:
    for n, text in enumerate(texts):
        (root / model).mkdir(parents=True, exist_ok=True)
        (root / model / f"d{n}.md").write_text(text, encoding="utf-8")
    return root


def decision_event(pid: str, outcome: str, when: datetime, by: str = "Robin") -> dict:
    return ledger.make_event(event="decision", actor="human", outcome=outcome, ruleset_version=CFG.version,
                             profile="default", proposal=pid, facets={"by": by}, reason="a reason",
                             ts=when.replace(microsecond=0).isoformat())


class LocalQueue(Case):
    """Mined proposals go to the file adapter whatever [kaizen] adapter says, and can be decided and
    applied through it."""

    def setUp(self):
        super().setUp()
        (self.root / ".plainspoken").mkdir()
        (self.root / ".plainspoken" / "config.toml").write_text(
            '[kaizen]\nadapter = "github"\napprovers = ["Robin"]\n\n[kaizen.github]\nrepo = "someone/somewhere"\n',
            encoding="utf-8")
        self.settings = {**config.kaizen_settings(self.root, {}), **calibrate.load_settings(),
                         "mining": mining.load_settings()}
        self.assertEqual(self.settings["adapter"], "github")

    def test_mine_decide_apply_through_the_file_adapter(self):
        out = self.mine()
        p = next(c for c in out["candidates"] if c["action"] == "add-term")
        stored = proposals.load(p["id"], self.settings)
        self.assertEqual(stored["adapter"], "file")
        md = self.root / stored["ref"]
        self.assertTrue(md.is_file())
        self.assertEqual(adapters.unsent(self.settings), [])
        with md.open("a", encoding="utf-8") as f:
            f.write("APPROVE: Robin: real tell\n")

        def runner(*a, **kw):
            raise AssertionError("the github runner must never be called for a mined proposal")

        lines, errors = adapters.record_decisions(self.settings, NOW, runner=runner)
        self.assertEqual(errors, [])
        self.assertIn(f"{p['id']} approved by Robin: real tell", lines)
        self.assertFalse(any("not yet sent" in x for x in lines))
        events = ledger.read(self.settings)[0]
        self.assertEqual(proposals.status(p["id"], events), "approved")
        copy = rules_copy(self.tmp)
        r = cli("kaizen", "apply", p["id"], "--dry-run", "--rules", str(copy), cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run, nothing written", r.stdout)
        self.assertIn("worth noting that", r.stdout)

    def test_a_failed_file_emit_is_sent_again_by_the_next_mine(self):
        folder = self.root / ".plainspoken" / "kaizen" / "proposals"
        folder.mkdir(parents=True)
        with mock.patch.object(file_adapter.FileAdapter, "emit_proposal",
                               side_effect=adapters.AdapterError("disk full")):
            out = self.mine()
        self.assertTrue(all(not proposals.load(c["id"], self.settings).get("ref") for c in out["candidates"]))
        lines, _ = adapters.record_decisions(self.settings, NOW)
        self.assertFalse(any("not yet sent" in x for x in lines))
        self.assertTrue(any("kaizen mine" in x for x in lines))
        self.mine()
        for c in out["candidates"]:
            stored = proposals.load(c["id"], self.settings)
            self.assertEqual(stored["adapter"], "file")
            self.assertTrue(stored.get("ref"))  # the retry really stored the ref
            self.assertTrue((self.root / stored["ref"]).is_file())
            self.assertNotIn("emit_error", stored)

    def test_sent_but_not_saved_is_reported(self):  # not kept only in memory
        boot = ("import sys; sys.path.insert(0, %r); from plainspoken import adapters, mining\n"
                "mining.MIN_MODEL_DRAFTS = 1\n"
                "def send(p, settings, adapter): raise adapters.NotSaved('file x.md', OSError('disk full'))\n"
                "adapters.send = send\n"
                "from plainspoken.__main__ import main; sys.exit(main(sys.argv[1:]))") % str(REPO / "lib")
        corpus = self.root / "corpus"
        shutil.copytree(FIX / "corpus", corpus)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        r = subprocess.run([sys.executable, "-c", boot, "kaizen", "mine", "--drafts", str(FIX / "drafts"),
                            "--corpus", "corpus/*.md", "--briefs", str(FIX / "briefs")], cwd=self.root,
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("sent to file x.md, but the proposal file couldn't be updated (disk full)", r.stderr)
        self.assertIn("the next kaizen mine writes it again", r.stderr)


class TopicWords(Case):
    """Only a brief's Topic: paragraph supplies topic words."""

    def test_topic_paragraph_only(self):
        words = mining.brief_words(BRIEFS, CFG.lists["repeat_stopwords"])
        self.assertIn("coffee", words)
        self.assertIn("receipts", words)
        for generic in ("keep", "make", "time", "thing", "audience", "format", "length"):
            self.assertNotIn(generic, words)

    def test_earns_its_keep_surfaces_and_the_topic_stays_blocked(self):
        copy = rules_copy(self.tmp, drop="earns its keep")
        cfg = load_config(copy)
        drafts = write_drafts(self.tmp / "drafts", "m1", [
            "# One\n\nThe old kettle earns its keep. My coffee machine hums every morning.\n",
            "# Two\n\nA cheap grinder earns its keep. The coffee machine sat unused for weeks.\n",
            "# Three\n\nThat battered tray earns its keep. Our coffee machine needs a descale soon.\n"])
        out = mining.mine(drafts, self.corpus, None, cfg, default_profile(), self.settings, now=NOW, dry_run=True,
                          rules_path=copy)
        found = [x["phrase"] for x in out["phrases"]]
        self.assertIn("earns its keep", found)
        self.assertFalse(any("coffee" in x or "machine" in x for x in found), found)

    def test_a_brief_without_a_topic_paragraph(self):
        briefs = self.tmp / "briefs"
        briefs.mkdir()
        (briefs / "x.md").write_text("# Brief\n\nAudience: anyone. Format: a note. Length: short.\n", encoding="utf-8")
        with self.assertRaisesRegex(mining.MiningError, "Topic:"):
            self.mine(briefs=briefs)


class Cooldown(Case):
    """An add-term is identified by (list, phrase, model), so a rule-32 models change made by another
    apply doesn't bring back a rejected phrase."""

    def test_rejected_phrase_stays_rejected_after_another_apply(self):
        copy = rules_copy(self.tmp)
        drafts = write_drafts(self.tmp / "drafts", "m1", [
            "# One\n\nAmber falcon. Brisk meadow. Nothing else to say here.\n",
            "# Two\n\nAmber falcon. Brisk meadow. Another line of filler.\n"])
        first = mining.mine(drafts, self.corpus, FIX / "briefs", load_config(copy), default_profile(), self.settings,
                            now=NOW, rules_path=copy)
        by_phrase = {c["evidence"]["phrase"]: c for c in first["candidates"] if c["action"] == "add-term"}
        self.assertEqual(sorted(by_phrase), ["amber falcon", "brisk meadow"])
        a, b = by_phrase["amber falcon"], by_phrase["brisk meadow"]
        ledger.append(decision_event(b["id"], "approved", NOW), self.settings)
        proposals.apply(b["id"], self.root, self.settings, rules_path=copy, now=NOW)
        self.assertIn("m1", load_config(copy).rules["32"].models)
        ledger.append(decision_event(a["id"], "rejected", NOW), self.settings)
        again = mining.mine(drafts, self.corpus, FIX / "briefs", load_config(copy), default_profile(), self.settings,
                            now=NOW, rules_path=copy)
        # "brisk meadow" is now listed (rule 32 fires on it, so a promote may come up); "amber falcon" stays rejected
        self.assertEqual([c for c in again["candidates"] if c["action"] == "add-term"], [])
        self.assertIn("amber falcon", [x["phrase"] for x in again["phrases"]])  # still found, just not re-proposed


# Lists that hold plain function words or human markers, not tells: a brief may use their words. Pinned here on
# purpose: the engine reads them from data/kaizen.toml [mining] not_tell_lists, and this copy makes a change
# there a deliberate one.
NOT_BANS = frozenset({"repeat_stopwords", "title_case_function_words", "ing_stop", "ban_exempt_terms",
                      "density_extra_openers", "density_total_only", "expanded_forms", "opinion_markers"})


class NotTellLists(unittest.TestCase):
    def test_read_from_the_data_and_checked_against_the_ruleset(self):  # not hard-coded in the engine
        self.assertEqual(mining.load_settings(cfg=CFG)["not_tell_lists"], NOT_BANS)
        self.assertFalse(hasattr(mining, "NOT_TELL_LISTS"))
        text = calibrate.DEFAULT.read_text(encoding="utf-8").replace('"opinion_markers"', '"no_such_list"')
        bad = Path(tempfile.mkdtemp()) / "kaizen.toml"
        self.addCleanup(shutil.rmtree, bad.parent, ignore_errors=True)
        bad.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not_tell_lists: unknown list 'no_such_list'"):
            mining.load_settings(bad, cfg=CFG)


class Briefs(unittest.TestCase):
    TOPICS = ("receipts", "declin", "to-do", "linkedin", "coffee machine", "domain name")

    def setUp(self):
        self.files = sorted(BRIEFS.glob("*.md"))

    def test_six_briefs_one_per_topic(self):
        self.assertEqual(len(self.files), 6)
        texts = [f.read_text(encoding="utf-8").lower() for f in self.files]
        for topic in self.TOPICS:
            self.assertEqual(sum(topic in t for t in texts), 1, topic)

    def test_length_and_audience_format_length(self):
        for f in self.files:
            text = f.read_text(encoding="utf-8")
            n = len(re.findall(r"[A-Za-z0-9'’-]+", text))
            self.assertTrue(60 <= n <= 120, f"{f.name}: {n} words")
            for word in ("audience", "format", "length"):
                self.assertRegex(text.lower(), rf"\b{word}\b", f"{f.name}: {word}")

    def test_each_has_a_topic_paragraph(self):
        for f in self.files:
            self.assertRegex(f.read_text(encoding="utf-8"), r"(?m)^Topic: \S", f.name)

    def test_no_ban_list_word(self):
        for f in self.files:
            text = f.read_text(encoding="utf-8").replace("’", "'")
            for name, entries in CFG.lists.items():
                if name in NOT_BANS:
                    continue
                for entry in entries:
                    pattern = entry if mining.is_pattern(entry) else rf"(?<![\w'-]){re.escape(entry)}(?![\w'-])"
                    self.assertIsNone(re.search(pattern, text, re.I | re.M), f"{f.name}: {name} {entry!r}")

    def test_no_tell_avoidance_instruction(self):
        for f in self.files:
            text = f.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\b(ai|tells?|avoid|robotic|human-sounding|sounds? human|natural)\b",
                                        text, re.I), f.name)

    def test_leak_guard_clean(self):
        terms = leak_guard.load_terms(str(REPO))
        with tempfile.TemporaryDirectory() as tmp:
            for f in self.files:
                shutil.copy(f, Path(tmp) / f.name)
            hits, _ = leak_guard.scan(tmp, terms)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
