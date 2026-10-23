"""Lint verdict diff: `scripts/dev/verdict_diff.py`.

The diff and the markdown take injected lint results, so most tests run no git and no lint. One end-to-end test lints
a two-text corpus with two temp copies of the engine (no git, no network)."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.dev import verdict_diff as vd

REPO = Path(__file__).resolve().parents[1]


def res(*findings, ruleset="4.3.0"):
    return {"findings": [list(f) for f in findings], "ruleset": ruleset}


class StatusAndCounts(unittest.TestCase):
    def test_status_order(self):
        self.assertEqual(vd.status(res(("2", "BLOCK"), ("7", "WARN"))), "BLOCK")
        self.assertEqual(vd.status(res(("7", "WARN"), ("6", "CANDIDATE"))), "WARN")
        self.assertEqual(vd.status(res(("6", "CANDIDATE"), ("28", "INFO"))), "CLEAN")
        self.assertEqual(vd.status(res()), "CLEAN")
        self.assertEqual(vd.status({"error": "boom"}), "ERROR")

    def test_counts_by_rule_and_severity(self):
        c = vd.counts(res(("6", "CANDIDATE"), ("6", "CANDIDATE"), ("7", "WARN")))
        self.assertEqual(c[("6", "CANDIDATE")], 2)
        self.assertEqual(c[("7", "WARN")], 1)
        self.assertEqual(vd.counts({"error": "boom"}), {})


class Diff(unittest.TestCase):
    def test_no_change(self):
        old = {"a": res(("7", "WARN")), "b": res()}
        rep = vd.diff(old, json.loads(json.dumps(old)))
        self.assertEqual(rep["changed"], 0)
        self.assertEqual(rep["texts"], 2)
        self.assertEqual(rep["status_old"], {"WARN": 1, "CLEAN": 1})
        self.assertEqual(rep["rules"], [])
        self.assertEqual(rep["changed_texts"], [])

    def test_status_move_and_counts(self):
        old = {"a": res(("7", "WARN")), "b": res(("6", "CANDIDATE")), "c": res()}
        new = {"a": res(("7", "WARN"), ("2", "BLOCK")), "b": res(("6", "CANDIDATE"), ("6", "CANDIDATE")), "c": res()}
        rep = vd.diff(old, new)
        self.assertEqual(rep["changed"], 2)
        self.assertEqual(rep["transitions"], {"WARN → BLOCK": 1})
        a, b = rep["changed_texts"]
        self.assertEqual((a["id"], a["old"], a["new"], a["changes"]), ("a", "WARN", "BLOCK", {"2 BLOCK": [0, 1]}))
        self.assertEqual((b["id"], b["old"], b["new"], b["changes"]), ("b", "CLEAN", "CLEAN", {"6 CANDIDATE": [1, 2]}))
        self.assertEqual(rep["rules"], [
            {"rule": "2", "severity": "BLOCK", "old": 0, "new": 1, "texts": 1},
            {"rule": "6", "severity": "CANDIDATE", "old": 1, "new": 2, "texts": 1},
        ])

    def test_rule_order_is_numeric_then_letters(self):
        old = {"a": res()}
        new = {"a": res(("12f", "WARN"), ("2b", "WARN"), ("HM", "WARN"), ("2", "WARN"))}
        self.assertEqual([r["rule"] for r in vd.diff(old, new)["rules"]], ["2", "2b", "12f", "HM"])

    def test_errors_and_missing_texts(self):
        rep = vd.diff({"a": {"error": "old engine failed"}, "b": res()}, {"a": res(("7", "WARN"))})
        rows = {t["id"]: t for t in rep["changed_texts"]}
        self.assertEqual((rows["a"]["old"], rows["a"]["new"]), ("ERROR", "WARN"))
        self.assertEqual(rows["a"]["old_error"], "old engine failed")
        self.assertEqual((rows["b"]["old"], rows["b"]["new"], rows["b"]["new_error"]), ("CLEAN", "ERROR", "not linted"))


def report(old, new):
    rep = vd.diff(old, new)
    rep["corpus"] = {"golden": 2, "prose": 1}
    rep["old"] = {"label": "base", "ruleset": "4.3.0"}
    rep["new"] = {"label": "head", "ruleset": "4.4.0"}
    return rep


class Markdown(unittest.TestCase):
    def test_unchanged(self):
        md = vd.markdown(report({"a": res(("7", "WARN"))}, {"a": res(("7", "WARN"))}))
        self.assertIn("### Lint verdict diff: `base` → `head`", md)
        self.assertIn("Ruleset 4.3.0 → 4.4.0", md)
        self.assertIn("| WARN | 1 | 1 |", md)
        self.assertIn("No status or finding count changed.", md)

    def test_changed_rows_and_cap(self):
        old = {f"t{i}": res() for i in range(5)}
        new = {f"t{i}": res(("2", "BLOCK")) for i in range(5)}
        md = vd.markdown(report(old, new), max_rows=2)
        self.assertIn("**5 of 5 texts changed.** Status moves: CLEAN → BLOCK: 5.", md)
        self.assertIn("| 2 | BLOCK | 0 | 5 | 5 |", md)
        self.assertIn("| `t0` | CLEAN → BLOCK | r2 BLOCK 0→1 |", md)
        self.assertNotIn("`t2`", md)
        self.assertIn("3 more changed texts", md)

    def test_error_text_cannot_break_the_table(self):
        md = vd.markdown(report({"a": {"error": "bad | pipe"}}, {"a": res()}))
        self.assertIn("old: bad / pipe", md)


class Corpus(unittest.TestCase):
    def test_reads_golden_cases_then_prose_fixtures(self):
        with tempfile.TemporaryDirectory() as t:
            tree = Path(t)
            (tree / "evals" / "golden").mkdir(parents=True)
            (tree / "evals" / "golden" / "J1.toml").write_text(
                'schema = 1\ngroup = "J1"\n[[case]]\nid = "J1-x-001"\ncontent_type = "social"\ntext = "One."\n'
                '[[case]]\nid = "J1-x-002"\ntext = "Two."\n', encoding="utf-8")
            (tree / "evals" / "rewrite" / "r1").mkdir(parents=True)
            (tree / "evals" / "rewrite" / "r1" / "reference.md").write_text("Short reply.\n", encoding="utf-8")
            (tree / "tests" / "fixtures" / "voice").mkdir(parents=True)
            (tree / "tests" / "fixtures" / "voice" / "long.md").write_text("word " * 300, encoding="utf-8")
            items = vd.corpus(tree)
        self.assertEqual([(i["id"], i["content_type"]) for i in items], [
            ("golden/J1-x-001", "social"), ("golden/J1-x-002", "article"),
            ("evals/rewrite/r1/reference.md", "social"), ("tests/fixtures/voice/long.md", "article")])

    def test_empty_tree_is_an_error(self):
        with tempfile.TemporaryDirectory() as t, self.assertRaises(vd.DiffError):
            vd.corpus(Path(t))

    def test_repo_corpus_covers_the_golden_set(self):
        items = vd.corpus(REPO)
        golden = [i for i in items if i["id"].startswith("golden/")]
        self.assertGreaterEqual(len(golden), 250)
        self.assertEqual(len({i["id"] for i in items}), len(items))

    def test_folder_without_engine_is_refused(self):
        with tempfile.TemporaryDirectory() as t, self.assertRaises(vd.DiffError):
            vd.materialise(t, Path(t))


class EndToEnd(unittest.TestCase):
    """Two temp copies of the engine, one with an extra banned word in its default profile."""

    def test_cli_on_two_copies(self):
        with tempfile.TemporaryDirectory() as t:
            old, new = Path(t) / "old", Path(t) / "new"
            for tree in (old, new):
                for part in ("lib", "data"):
                    shutil.copytree(REPO / part, tree / part, ignore=shutil.ignore_patterns("__pycache__"))
            prof = new / "data" / "profiles" / "default.toml"
            prof.write_text(prof.read_text(encoding="utf-8").replace("extra_bans = []", 'extra_bans = ["kettle"]'),
                            encoding="utf-8")
            (new / "evals" / "golden").mkdir(parents=True)
            (new / "evals" / "golden" / "J1.toml").write_text(
                'schema = 1\ngroup = "J1"\n[[case]]\nid = "J1-x-001"\ncontent_type = "article"\n'
                'text = """\nI put the kettle on before the meeting and it went fine.\n"""\n', encoding="utf-8")
            (new / "tests" / "fixtures" / "voice").mkdir(parents=True)
            (new / "tests" / "fixtures" / "voice" / "a.md").write_text("I walked home in the rain.\n",
                                                                         encoding="utf-8")
            before = sorted(p.relative_to(t) for p in Path(t).rglob("*"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = vd.main([str(old), str(new), "--json", "--fail-on-change"])
            after = sorted(p.relative_to(t) for p in Path(t).rglob("*") if "__pycache__" not in p.parts)
            before = [p for p in before if "__pycache__" not in p.parts]
        rep = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(after, before, "the diff wrote into a tree")
        self.assertEqual((rep["texts"], rep["corpus"]), (2, {"golden": 1, "prose": 1}))
        self.assertEqual(rep["changed"], 1)
        row = rep["changed_texts"][0]
        self.assertEqual((row["id"], row["new"]), ("golden/J1-x-001", "BLOCK"))
        self.assertTrue(any(k.endswith("BLOCK") for k in row["changes"]))


if __name__ == "__main__":
    unittest.main()
