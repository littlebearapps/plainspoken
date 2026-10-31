"""`plainspoken meaning-diff` (#147): the saved baseline, the saved result bound to both texts, and its lines."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken import meaning, owner_asks, report

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "meaning"


def cli(*args, cwd: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_"))}
    env["PYTHONPATH"] = str(REPO / "lib")
    return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=cwd, capture_output=True, text=True,
                          env=env)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Command(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.src = (FIX / "issue-src.md").read_text(encoding="utf-8")
        self.rw = (FIX / "issue-rw.md").read_text(encoding="utf-8")
        self.art = self.cwd / "email.md"
        self.art.write_text(self.src, encoding="utf-8")
        self.paths = report.report_paths(self.art, self.cwd / ".plainspoken" / "reports", self.cwd)

    def test_start_then_compare(self):
        r = cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "meaning-diff: baseline saved for email.md")
        self.assertEqual(self.paths["before"].read_text(encoding="utf-8"), self.src)
        self.art.write_text(self.rw, encoding="utf-8")
        r = cli("meaning-diff", "email.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual([x.split(" ", 1)[0] for x in lines if x.startswith("M")], ["M1", "M2", "M3"])
        self.assertIn('M3 line 3: dropped "won\'t", "without"', r.stdout)
        self.assertEqual(lines[-1], meaning.FOOTER)
        rec = json.loads(self.paths["meaning"].read_text(encoding="utf-8"))
        self.assertEqual((rec["before_sha256"], rec["after_sha256"]), (sha(self.src), sha(self.rw)))
        self.assertEqual(rec["lexicon_sha256"], meaning.lexicon_sha256())
        self.assertEqual(rec["article"], "email.md")
        self.assertEqual(len(rec["changes"]), 3)

    def test_json(self):
        cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.art.write_text(self.rw, encoding="utf-8")
        r = cli("meaning-diff", "email.md", "--json", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c["id"] for c in json.loads(r.stdout)["changes"]], ["M1", "M2", "M3"])

    def test_before_flag(self):
        old = self.cwd / "old.md"
        old.write_text(self.src, encoding="utf-8")
        self.art.write_text(self.rw, encoding="utf-8")
        r = cli("meaning-diff", "email.md", "--before", "old.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('dropped "won\'t", "without"', r.stdout)
        self.assertFalse(self.paths["meaning"].exists())  # two files given: nothing saved for status

    def test_no_baseline_is_exit_2(self):
        r = cli("meaning-diff", "email.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no baseline for email.md: run meaning-diff email.md --start before the first edit", r.stderr)

    def test_missing_file_is_exit_2(self):
        r = cli("meaning-diff", "nope.md", "--start", cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("nope.md", r.stderr)

    def test_not_utf8_is_exit_2(self):
        self.art.write_bytes(b"caf\xe9 is free\n")
        r = cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("UnicodeDecodeError", r.stderr)
        self.assertFalse(self.paths["before"].exists())

    def test_listing_is_capped(self):
        before = "\n\n".join(f"Room {n} isn't included in the fee." for n in range(1, 31)) + "\n"
        self.art.write_text(before, encoding="utf-8")
        cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.art.write_text(before.replace("isn't", "is"), encoding="utf-8")
        r = cli("meaning-diff", "email.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([x for x in r.stdout.splitlines() if x.startswith("M")]), 10)
        self.assertIn("… 20 more in .plainspoken/reports/", r.stdout)

    def test_exit_0_when_nothing_listed(self):
        cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.art.write_text((FIX / "issue-join.md").read_text(encoding="utf-8"), encoding="utf-8")
        r = cli("meaning-diff", "email.md", cwd=self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["meaning-diff: nothing listed", meaning.FOOTER])

    def test_a_new_start_clears_the_old_result(self):
        cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.art.write_text(self.rw, encoding="utf-8")
        cli("meaning-diff", "email.md", cwd=self.cwd)
        self.assertTrue(self.paths["meaning"].exists())
        cli("meaning-diff", "email.md", "--start", cwd=self.cwd)
        self.assertFalse(self.paths["meaning"].exists())


class Saved(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.reports = self.cwd / ".plainspoken" / "reports"
        self.art = self.cwd / "email.md"
        self.src = (FIX / "issue-src.md").read_text(encoding="utf-8")
        self.art.write_text(self.src, encoding="utf-8")

    def test_states(self):
        self.assertEqual(meaning.saved(self.art, self.cwd, self.reports), ("no-baseline", []))
        meaning.start(self.art, self.cwd, self.reports)
        self.assertEqual(meaning.saved(self.art, self.cwd, self.reports), ("missing", []))
        self.art.write_text((FIX / "issue-rw.md").read_text(encoding="utf-8"), encoding="utf-8")
        meaning.record(self.art, self.cwd, self.reports, self.src)
        state, changes = meaning.saved(self.art, self.cwd, self.reports)
        self.assertEqual((state, len(changes)), ("current", 3))
        self.art.write_text("Edited after the diff ran.\n", encoding="utf-8")
        self.assertEqual(meaning.saved(self.art, self.cwd, self.reports), ("stale", []))

    def test_summarise(self):
        changes = meaning.diff(self.src, (FIX / "issue-rw.md").read_text(encoding="utf-8"))
        text = meaning.summarise(changes, shown=2, path="r/x.meaning.json")
        self.assertIn('M2 cut: dropped "separate", "isn\'t"; was: "Your ad spend is separate', text)
        self.assertIn("… 1 more in r/x.meaning.json", text)
        self.assertEqual(text.splitlines()[-1], meaning.FOOTER)
        self.assertEqual(meaning.summarise([]).splitlines(), ["meaning-diff: nothing listed", meaning.FOOTER])


class Status(unittest.TestCase):
    """`status` lists a current meaning-diff result under `needs the owner`, never changing its exit code."""

    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.reports = self.cwd / ".plainspoken" / "reports"
        self.src = (FIX / "issue-src.md").read_text(encoding="utf-8")
        self.art = self.cwd / "email.md"
        self.art.write_text((FIX / "issue-rw.md").read_text(encoding="utf-8"), encoding="utf-8")

    def status(self) -> subprocess.CompletedProcess:
        return cli("status", "email.md", "--profile", "default", cwd=self.cwd)

    def ledger(self, status: str = "blocking") -> None:
        key = report.report_key(self.art, self.cwd)
        path = self.cwd / ".plainspoken" / "claims" / f"{key}.claims.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        claim = {"claim_id": "E-C1", "text": "management is $300 a month", "locations": [{"kind": "body"}],
                 "claim_type": "price", "prominence": "high", "status": status,
                 "resolution": "Not in the brief: ask the owner."}
        path.write_text(json.dumps({"schema_version": 1, "article_id": "E", "source_file": self.art.name,
                                    "coverage_status": "complete", "claims": [claim]}), encoding="utf-8")

    def owner_block(self, out: str) -> list[str]:
        lines = out.splitlines()
        at = next(i for i, x in enumerate(lines) if x.startswith("needs the owner:"))
        block = [lines[at]]
        for x in lines[at + 1:]:
            if not x.startswith("  "):
                break
            block.append(x)
        return block

    def test_meaning_items_join_the_owner_count(self):
        self.ledger()
        changes = meaning.record(self.art, self.cwd, self.reports, self.src)["changes"]
        block = self.owner_block(self.status().stdout)
        self.assertEqual(block[0], f"needs the owner: {1 + len(changes)}")
        self.assertEqual(block[1], "  E-C1: management is $300 a month (blocking)")
        self.assertEqual([x.split(":", 1)[0].strip() for x in block[2:]], ["M1", "M2", "M3"])
        self.assertEqual(block[3], '  M2: cut: Your ad spend is separate and isn\'t included in that fee. '
                                   '(dropped "separate", "isn\'t"; was: Your ad spend is separate and isn\'t '
                                   'included in that fee.)')
        self.assertTrue(block[4].startswith('  M3: I\'ll make the changes as I go. (dropped "won\'t", "without"'))

    def test_no_ledger_still_lists_the_meaning_items(self):
        meaning.record(self.art, self.cwd, self.reports, self.src)
        block = self.owner_block(self.status().stdout)
        self.assertEqual(block[0], "needs the owner: unknown (no readable ledger)")
        self.assertEqual(len(block), 4)

    def test_stale_meaning_lists_nothing(self):
        self.ledger()
        meaning.record(self.art, self.cwd, self.reports, self.src)
        with self.art.open("a", encoding="utf-8") as f:
            f.write("One more line.\n")
        out = self.status().stdout
        self.assertEqual(self.owner_block(out), ["needs the owner: 1", "  E-C1: management is $300 a month (blocking)"])
        self.assertIn("meaning: stale (rerun meaning-diff)", out.splitlines())
        self.assertNotIn("M1", out)

    def test_no_result_prints_no_meaning_line(self):
        self.ledger()
        out = self.status().stdout
        self.assertNotIn("meaning", out)
        meaning.start(self.art, self.cwd, self.reports)
        self.assertNotIn("meaning", self.status().stdout)

    def test_nothing_listed_leaves_the_owner_line_alone(self):
        self.ledger("verified")
        meaning.record(self.art, self.cwd, self.reports, self.art.read_text(encoding="utf-8"))
        self.assertEqual(self.owner_block(self.status().stdout), ["needs the owner: none"])

    def test_parentheses_are_stripped_from_items(self):
        before = "Management is $300 (inc GST) a month.\n"
        self.art.write_text("Management is a monthly fee (inc GST).\n", encoding="utf-8")
        self.ledger("verified")
        meaning.record(self.art, self.cwd, self.reports, before)
        block = self.owner_block(self.status().stdout)
        self.assertEqual(block[0], "needs the owner: 1")
        item = block[1].strip()
        self.assertEqual(item, 'M1: Management is a monthly fee inc GST. (dropped "$300"; was: Management is $300 inc '
                               'GST a month.)')
        cid, words = owner_asks._item(item)
        self.assertEqual(cid, "M1")
        self.assertIn("management", words)

    def test_exit_code_unchanged_by_meaning(self):
        without = self.status()
        meaning.record(self.art, self.cwd, self.reports, self.src)
        self.assertEqual(self.status().returncode, without.returncode)


class StatusPass(unittest.TestCase):
    """A check PASS and a claims PASS still exit 0 with meaning items listed (the claims E2E project)."""

    def test_exit_0_with_meaning_items(self):
        from plainspoken.registry import load_config
        from tests._profiles import PRODUCT
        from tests.test_anti_ai_report import PRODUCT_ARGS, _judges
        from tests.test_cli_claims import FIX as CLAIMS, RUN, sha as claims_sha, write_check
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / ".git").mkdir()
        e2e = CLAIMS / "e2e"
        for src, dest in ((e2e / "final" / "tool-library-first-year.md", "posts"),
                          (e2e / "final" / "tool-library-first-year.claims.toml", ".plainspoken/claims"),
                          (e2e / "sources" / "northbank-annual-report-2026.txt", ".plainspoken/sources"),
                          (e2e / "sources" / "examplelend-help-reminders.txt", ".plainspoken/sources")):
            (root / dest).mkdir(parents=True, exist_ok=True)
            shutil.copy(src, root / dest / src.name)
        art = root / "posts" / "tool-library-first-year.md"
        ledger = root / ".plainspoken" / "claims" / "tool-library-first-year.claims.toml"
        engine = [sys.executable, str(RUN)]
        draft = ["posts/tool-library-first-year.md", *PRODUCT_ARGS]
        paths = json.loads(subprocess.run([*engine, "paths", draft[0]], cwd=root, capture_output=True,
                                          text=True).stdout)
        write_check(Path(paths["claims-check"]), art, ledger)
        subprocess.run([*engine, "check", *draft], cwd=root, capture_output=True)
        digest, cfg, reports = claims_sha(art).removeprefix("sha256:"), load_config(), Path(paths["report"]).parent
        _judges(reports, paths["key"], digest, cfg, PRODUCT)
        subprocess.run([*engine, "merge", *draft], cwd=root, capture_output=True, text=True)
        kept = json.loads(Path(paths["report"]).read_text())["unresolved"]
        jp = reports / f"{paths['key']}.justify.json"
        jp.write_text(json.dumps({"article_sha256": digest, "items": [
            {"rule": rid, "kind": "voice", "reason": "the short lines are the annual report's own figures"}
            for rid in kept]}))
        (reports / f"{paths['key']}.JR.judge.json").write_text(json.dumps({
            "group": "JR", "article_sha256": digest, "justify_sha256": hashlib.sha256(jp.read_bytes()).hexdigest(),
            "judged_at": "2026-10-21T00:00:00Z", "profile_sha256": PRODUCT.sha256, "ruleset_version": cfg.version,
            "verdicts": [{"rule": rid, "verdict": "accept", "reason": "checked against the evidence"} for rid in kept]}))
        merged = subprocess.run([*engine, "merge", *draft], cwd=root, capture_output=True, text=True)
        self.assertEqual(merged.returncode, 0, merged.stdout)
        text = art.read_text(encoding="utf-8")
        meaning.record(art, root, reports, text + "\nThe first visit is free, and it isn't included in the fee.\n")
        r = subprocess.run([*engine, "status", *draft], cwd=root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("  M1: cut: The first visit is free", r.stdout)


if __name__ == "__main__":
    unittest.main()
