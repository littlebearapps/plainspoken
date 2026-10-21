"""The `claims` CLI group, driven through lib/run.py: hash, validate, candidates, gaps, pin, recheck, scaffold, status,
plus the claim paths `paths` prints. Exit codes: 0 ok · 1 findings / INCOMPLETE / BLOCKED · 2 bad input."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from plainspoken import checker, claims_tools, pinning, schema

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / "lib" / "run.py"
FIX = REPO / "tests" / "fixtures" / "claims"
ID = re.compile(r"^[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*$")
PASSAGE = "after-hours bookings made up 41% of all bookings"
SRC = ".plainspoken/sources/example-source.md"


def run(*args, cwd):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_", "CLAUDE_PROJECT_DIR"))}
    env.pop("PYTHONPATH", None)
    return subprocess.run([sys.executable, str(RUN), "claims", *args], cwd=cwd, capture_output=True, text=True,
                          env=env)


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class Project(unittest.TestCase):
    """A temp project (.git marks the root) holding the invented fixture article, its ledger and a saved source."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()
        shutil.copy(FIX / "article.md", self.root / "article.md")
        (self.root / ".plainspoken" / "sources").mkdir(parents=True)
        shutil.copy(FIX / "sources" / "example-source.md", self.root / SRC)
        self.ledger_dir = self.root / ".plainspoken" / "claims"
        self.ledger_dir.mkdir(parents=True)
        self.ledger = self.ledger_dir / "article.claims.toml"
        shutil.copy(FIX / "article.claims.toml", self.ledger)
        self.art = self.root / "article.md"

    def paths(self, article="article.md"):
        r = subprocess.run([sys.executable, str(RUN), "paths", article], cwd=self.root, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def ledger_for(self, article: str) -> Path:
        """The article's ledger path as `paths` prints it: path-keyed when no older stem-only ledger is its own."""
        return Path(self.paths(article)["ledger"])

    def assert_bad_input(self, r, name):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        lines = r.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, r.stderr)
        self.assertIn(name, lines[0])
        self.assertNotIn("Traceback", r.stderr)


class Hash(Project):
    def test_prints_sha256_of_the_bytes(self):
        r = run("hash", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), sha(self.art))

    def test_stamp_adds_a_ready_to_paste_checked_at(self):  # the clock comes from the CLI, not a shell
        r = run("hash", "article.md", "--stamp", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        first, second = r.stdout.splitlines()
        self.assertEqual(first, sha(self.art))
        self.assertRegex(second, r'^checked_at = "\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}"$')
        self.assertIsInstance(tomllib.loads(second)["checked_at"], str)
        self.assert_bad_input(run("hash", "nope.md", "--stamp", cwd=self.root), "nope.md")

    def test_missing_file(self):
        self.assert_bad_input(run("hash", "nope.md", cwd=self.root), "nope.md")


class Validate(Project):
    def test_valid_fresh_ledger_exits_0(self):
        r = run("validate", str(self.ledger), cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_findings_one_per_line_and_exit_1(self):
        self.art.write_text(self.art.read_text(encoding="utf-8") + "\nA new line.\n", encoding="utf-8")
        r = run("validate", str(self.ledger), cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"(?m)^error -: stale verification")

    def test_warning_alone_exits_0(self):
        text = self.ledger.read_text(encoding="utf-8").replace('coverage_status = "complete"',
                                                               'coverage_status = "partial"')
        self.ledger.write_text(text, encoding="utf-8")
        r = run("validate", str(self.ledger), cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"(?m)^warning -: coverage_status=partial")

    def test_root_option(self):
        elsewhere = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        r = run("validate", str(self.ledger), "--root", str(self.root), cwd=elsewhere)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_missing_file_one_line_naming_it(self):
        self.assert_bad_input(run("validate", "missing.claims.toml", cwd=self.root), "missing.claims.toml")

    def test_non_utf8_and_malformed(self):
        bad = self.root / "bad.claims.toml"
        bad.write_bytes(b"\xff\xfe not utf-8")
        self.assert_bad_input(run("validate", "bad.claims.toml", cwd=self.root), "bad.claims.toml")
        bad.write_text("schema_version = = 1\n", encoding="utf-8")
        self.assert_bad_input(run("validate", "bad.claims.toml", cwd=self.root), "bad.claims.toml")


class Candidates(Project):
    def test_lines_and_json(self):
        r = run("candidates", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"(?m)^\d+ body statistic 38%: In 2025, 38%")
        rj = run("candidates", "article.md", "--json", cwd=self.root)
        items = json.loads(rj.stdout)
        self.assertEqual(len(items), len(r.stdout.strip().splitlines()))
        self.assertEqual(set(items[0]), {"surface", "kind", "text", "value", "line"})

    def test_bad_input(self):
        self.assert_bad_input(run("candidates", "nope.md", cwd=self.root), "nope.md")
        (self.root / "latin1.md").write_bytes("caf\xe9 costs $5".encode("latin-1"))
        self.assert_bad_input(run("candidates", "latin1.md", cwd=self.root), "latin1.md")

    def test_malformed_config_is_bad_input(self):
        (self.root / ".plainspoken" / "config.toml").write_text("[claims]\nplatforms_extra = 5\n", encoding="utf-8")
        self.assert_bad_input(run("candidates", "article.md", cwd=self.root), "config.toml")


class Gaps(Project):
    def test_no_gaps_exits_0(self):
        r = run("gaps", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_gap_exits_1_and_names_the_value(self):
        self.art.write_text(self.art.read_text(encoding="utf-8") + "\nA call-out costs A$300 on weekends.\n",
                            encoding="utf-8")
        r = run("gaps", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("currency A$300", r.stdout)
        rj = run("gaps", "article.md", "--json", cwd=self.root)
        self.assertEqual([g["value"] for g in json.loads(rj.stdout)], ["A$300"])

    def test_missing_ledger_is_bad_input(self):
        self.assert_bad_input(run("gaps", "article.md", "--ledger", "none.claims.toml", cwd=self.root),
                              "none.claims.toml")


class Pin(Project):
    def test_fragment_is_ready_to_paste_toml(self):
        r = run("pin", "--source", SRC, "--passage", PASSAGE,
                "--retrieved-at", "2026-10-14T09:00:00+11:00", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("[claims.binding]\n"), r.stdout)
        binding = tomllib.loads(r.stdout)["claims"]["binding"]
        self.assertEqual(binding["passage"], PASSAGE)
        self.assertEqual(binding["passage_sha256"], pinning.sha256_str(PASSAGE))
        self.assertEqual(binding["source_snapshot"], SRC)
        self.assertEqual(binding["retrieved_at"], "2026-10-14T09:00:00+11:00")
        self.assertIn("same_subject", r.stdout)  # reminder of the judgements the schema requires

    def test_snapshot_path_option_and_default_retrieved_at(self):
        saved = self.root / ".plainspoken" / "sources" / "saved" / "page.txt"
        saved.parent.mkdir()
        shutil.copy(self.root / SRC, saved)
        r = run("pin", "--source", SRC, "--passage", PASSAGE,
                "--snapshot-path", ".plainspoken/sources/saved/page.txt", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        binding = tomllib.loads(r.stdout)["claims"]["binding"]
        self.assertEqual(binding["source_snapshot"], ".plainspoken/sources/saved/page.txt")
        self.assertRegex(binding["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")

    def test_additional_fragment_has_no_snapshot(self):
        r = run("pin", "--source", SRC, "--passage", PASSAGE, "--additional",
                "--source-url", "https://example.org/survey", "--locator", "table 2", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("[[claims.binding.additional_passages]]\n"), r.stdout)
        item = tomllib.loads(r.stdout)["claims"]["binding"]["additional_passages"][0]
        self.assertNotIn("source_snapshot", item)
        self.assertEqual(item["source_url"], "https://example.org/survey")
        self.assertEqual(item["locator"], "table 2")
        sub = schema.load("claim-ledger")["$defs"]["claim"]["properties"]["binding"]["properties"]
        self.assertEqual(schema.validate([item], sub["additional_passages"]), [])

    def test_paraphrase_is_refused(self):
        r = run("pin", "--source", SRC, "--passage",
                "after-hours bookings were about 41 per cent of the total", cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("not locatable", r.stderr)
        self.assertEqual(r.stdout, "")

    # the source must be saved under sources_dir, and the article is never its own source.
    def assert_refused(self, r, *fragments):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertIn("pin refused", r.stderr)
        for fragment in fragments:
            self.assertIn(fragment, r.stderr)

    def test_source_that_is_the_article_is_refused(self):
        self.assert_refused(run("pin", "--source", "article.md", "--passage", "41%", cwd=self.root),
                            "article.md", ".plainspoken/sources")
        inside = self.root / ".plainspoken" / "sources" / "draft.md"  # an article kept in sources_dir
        shutil.copy(self.art, inside)
        self.assert_refused(run("pin", "--source", str(inside), "--passage", "41%", "--article", str(inside),
                                cwd=self.root), "article")

    def test_source_outside_sources_dir_is_refused(self):
        (self.root / "notes").mkdir()
        shutil.copy(self.root / SRC, self.root / "notes" / "src.md")
        self.assert_refused(run("pin", "--source", "notes/src.md", "--passage", PASSAGE, cwd=self.root),
                            "notes/src.md", ".plainspoken/sources")
        self.assert_refused(run("pin", "--source", "notes/src.md", "--passage", PASSAGE, "--additional",
                                cwd=self.root), "notes/src.md")
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        shutil.copy(self.root / SRC, outside / "src.md")
        self.assert_refused(run("pin", "--source", str(outside / "src.md"), "--passage", PASSAGE, cwd=self.root),
                            "src.md")
        (self.root / ".plainspoken" / "sources" / "link.md").symlink_to(self.root / "notes" / "src.md")
        self.assert_refused(run("pin", "--source", ".plainspoken/sources/link.md", "--passage", PASSAGE,
                                cwd=self.root), "notes/src.md")

    def test_snapshot_path_outside_sources_dir_or_the_article_is_refused(self):
        for bad in ("saved/page.txt", "article.md"):
            with self.subTest(bad=bad):
                self.assert_refused(run("pin", "--source", SRC, "--passage", PASSAGE, "--snapshot-path", bad,
                                        cwd=self.root), bad)
        self.assert_refused(run("pin", "--source", SRC, "--passage", PASSAGE, "--snapshot-path", SRC,
                                "--article", SRC, cwd=self.root), "article")

    def test_snapshot_path_is_checked_at_pin_time(self):  # never a pin the first recheck fails
        self.assert_refused(run("pin", "--source", SRC, "--passage", PASSAGE, "--snapshot-path",
                                ".plainspoken/sources/none.txt", cwd=self.root), "none.txt", "not found")
        other = self.root / ".plainspoken" / "sources" / "other.txt"
        other.write_text("A different page that never says it.\n", encoding="utf-8")
        self.assert_refused(run("pin", "--source", SRC, "--passage", PASSAGE, "--snapshot-path",
                                ".plainspoken/sources/other.txt", cwd=self.root), "other.txt", "--source")
        (self.root / ".plainspoken" / "sources" / "folder").mkdir()
        self.assert_refused(run("pin", "--source", SRC, "--passage", PASSAGE, "--snapshot-path",
                                ".plainspoken/sources/folder", cwd=self.root), "folder")
        # the same text, typographic quotes and spacing aside, is the same source
        same = self.root / ".plainspoken" / "sources" / "same.txt"
        same.write_text("  " + (self.root / SRC).read_text(encoding="utf-8").replace("'", "’") + "\n\n",
                        encoding="utf-8")
        r = run("pin", "--source", SRC, "--passage", PASSAGE, "--snapshot-path", ".plainspoken/sources/same.txt",
                cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(tomllib.loads(r.stdout)["claims"]["binding"]["source_snapshot"],
                         ".plainspoken/sources/same.txt")

    def test_custom_sources_dir_sets_the_default_snapshot_path(self):
        (self.root / "research").mkdir()
        shutil.copy(self.root / SRC, self.root / "research" / "s.md")
        (self.root / ".plainspoken" / "config.toml").write_text('[claims]\nsources_dir = "research"\n',
                                                                encoding="utf-8")
        r = run("pin", "--source", "research/s.md", "--passage", PASSAGE, cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(tomllib.loads(r.stdout)["claims"]["binding"]["source_snapshot"], "research/s.md")
        self.assert_refused(run("pin", "--source", SRC, "--passage", PASSAGE, cwd=self.root), "research")

    def test_unresolvable_article_path_is_bad_input(self):  # a symlink loop
        (self.root / "loop.md").symlink_to(self.root / "loop.md")
        r = run("pin", "--source", SRC, "--passage", PASSAGE, "--article", "loop.md", cwd=self.root)
        self.assert_bad_input(r, "loop.md")
        self.assertNotIn("internal error", r.stderr)

    def test_missing_or_non_file_article_is_bad_input(self):
        for bad in ("nope.md", ".plainspoken"):
            with self.subTest(bad=bad):
                r = run("pin", "--source", SRC, "--passage", PASSAGE, "--article", bad, cwd=self.root)
                self.assert_bad_input(r, bad)
                self.assertNotIn("internal error", r.stderr)

    def test_misconfigured_sources_dir_is_bad_input(self):
        (self.root / ".plainspoken" / "config.toml").write_text("[claims]\nsources_dir = '/abs'\n", encoding="utf-8")
        self.assert_bad_input(run("pin", "--source", SRC, "--passage", PASSAGE, cwd=self.root), "config.toml")

    def test_bad_input(self):
        self.assert_bad_input(run("pin", "--source", ".plainspoken/sources/none.md", "--passage", PASSAGE,
                                  cwd=self.root), "none.md")
        r = run("pin", "--source", SRC, "--passage", PASSAGE, "--locator", "x",
                cwd=self.root)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--additional", r.stderr)
        r = run("pin", "--source", SRC, "--passage", PASSAGE, "--additional",
                "--source-url", "http://example.org", cwd=self.root)
        self.assertEqual(r.returncode, 2)
        self.assertIn("https://", r.stderr)


class Recheck(Project):
    def _ledger(self, **binding_extra):
        fields = pinning.binding_fields((self.root / SRC).read_text(encoding="utf-8"),
                                        PASSAGE, retrieved_at="2026-10-14", source_snapshot=SRC)
        fields.update(binding_extra)
        data = {"claims": [{"claim_id": "SHOP-C002", "binding": fields}, {"claim_id": "SHOP-C003"}]}
        path = self.root / "pinned.claims.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_ok_with_detail(self):
        self._ledger()
        r = run("recheck", "pinned.claims.json", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip().splitlines(), ["SHOP-C002 ok: passage: passage found and both hashes match"])

    def test_drift_not_checked_stays_visible(self):
        path = self._ledger()
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["claims"][0]["binding"]["source_text_sha256"]
        path.write_text(json.dumps(data), encoding="utf-8")
        r = run("recheck", "pinned.claims.json", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok: passage: passage found; no source_text_sha256 recorded, so source drift isn't checked",
                      r.stdout)

    def test_changed_source_exits_1(self):
        self._ledger()
        src = self.root / SRC
        src.write_text(src.read_text(encoding="utf-8").replace("41%", "44%"), encoding="utf-8")
        r = run("recheck", "pinned.claims.json", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("SHOP-C002 passage_missing:", r.stdout)

    def test_bad_input(self):
        self.assert_bad_input(run("recheck", "none.claims.json", cwd=self.root), "none.claims.json")


class Scaffold(Project):
    def setUp(self):
        super().setUp()
        self.ledger.unlink()
        (self.root / "posts").mkdir()
        self.post = self.root / "posts" / "acme_plumbing--2026.md"
        self.post.write_text(
            '---\ntitle: "Acme Plumbing cut call-out waits by 40%"\n---\n\n'
            "> **TL;DR:** Most jobs cost under $450.\n\n"
            "## Why 2x faster\n\n"
            'The owner said "we answer every call before 9am" and Google ranks the page higher than before.\n'
            "Path C:\\temp and a \"quote with \\\\ backslash inside it\" too.\n",
            encoding="utf-8")

    def candidates(self, article):
        r = run("candidates", article, "--json", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_scaffold_then_validate_blocks_every_candidate(self):
        r = run("scaffold", "posts/acme_plumbing--2026.md", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.ledger_for("posts/acme_plumbing--2026.md")
        self.assertRegex(out.name, r"^acme_plumbing--2026-[0-9a-f]{8}\.claims\.toml$")  # path-keyed
        self.assertIn(str(out), r.stdout)
        cands = self.candidates("posts/acme_plumbing--2026.md")
        self.assertGreaterEqual(len(cands), 5)
        v = run("validate", str(out), cwd=self.root)
        self.assertEqual(v.returncode, 1, v.stdout + v.stderr)
        lines = v.stdout.strip().splitlines()
        self.assertEqual(len([ln for ln in lines if ln.startswith("blocking ")]), len(cands))
        self.assertEqual([ln for ln in lines if not ln.startswith("blocking ")],
                         ["warning -: coverage_status=unstarted: report as incomplete, not passing"])

        ledger = tomllib.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(schema.validate(ledger, schema.load("claim-ledger")), [])
        self.assertEqual(ledger["source_file"], "posts/acme_plumbing--2026.md")
        self.assertEqual(ledger["source_content_hash"], sha(self.post))
        self.assertEqual(ledger["checked_by"], "plainspoken claims scaffold")
        self.assertEqual(ledger["coverage_status"], "unstarted")
        self.assertIsInstance(ledger["checked_at"], str)
        self.assertRegex(ledger["checked_at"], r"[+-]\d{2}:\d{2}$")
        ids = [c["claim_id"] for c in ledger["claims"]]
        self.assertEqual(ids[:2], ["ACME-PLUMBING-2026-C001", "ACME-PLUMBING-2026-C002"])
        self.assertTrue(all(ID.match(i) for i in ids))
        self.assertEqual(len(set(ids)), len(ids))
        for c in ledger["claims"]:
            self.assertEqual(c["status"], "blocking")
            self.assertEqual(c["resolution"], "unreviewed candidate from claims scaffold")
        title = [c for c in ledger["claims"] if c["locations"][0]["kind"] == "frontmatter"]
        self.assertEqual(title[0]["locations"][0], {"kind": "frontmatter", "field": "title"})
        # anchors name the section, not a line (the line stays in the notes)
        anchors = {c["notes"].split(" (")[0]: c["locations"][0].get("anchor") for c in ledger["claims"]}
        self.assertEqual(anchors["currency candidate '$450'"], "before the first heading")
        self.assertEqual(anchors["multiplier candidate '2x'"], "Why 2x faster")
        self.assertEqual(anchors["quote candidate 'we answer every call before 9am'"], "Why 2x faster")
        self.assertTrue(all("line " in c["notes"] for c in ledger["claims"]))
        self.assertEqual(title[0]["prominence"], "high")
        types = {c["claim_type"] for c in ledger["claims"]}
        self.assertTrue({"statistic", "price", "quotation", "platform_behaviour"} <= types, types)
        # the scaffold holds every candidate, so nothing is a gap
        self.assertEqual(run("gaps", "posts/acme_plumbing--2026.md", cwd=self.root).returncode, 0)

    def test_scaffold_twice_refuses(self):
        self.assertEqual(run("scaffold", "posts/acme_plumbing--2026.md", cwd=self.root).returncode, 0)
        out = self.ledger_for("posts/acme_plumbing--2026.md")
        before = out.read_bytes()
        r = run("scaffold", "posts/acme_plumbing--2026.md", cwd=self.root)
        self.assert_bad_input(r, out.name)
        self.assertEqual(out.read_bytes(), before)

    def test_existing_json_ledger_is_named_not_a_suffix_error(self):
        toml_ledger = self.ledger_for("posts/acme_plumbing--2026.md")
        json_ledger = toml_ledger.with_suffix(".json")
        json_ledger.write_text("{}", encoding="utf-8")
        r = run("scaffold", "posts/acme_plumbing--2026.md", cwd=self.root)
        self.assert_bad_input(r, f"a ledger already exists: {json_ledger}")
        self.assertNotIn("TOML", r.stderr)
        self.assertEqual(json_ledger.read_text(encoding="utf-8"), "{}")
        self.assertFalse(toml_ledger.exists())

    def test_out_and_id_prefix(self):
        r = run("scaffold", "posts/acme_plumbing--2026.md", "--out", "mine.claims.toml", "--id-prefix", "AP7",
                cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        ledger = tomllib.loads((self.root / "mine.claims.toml").read_text(encoding="utf-8"))
        self.assertEqual(ledger["claims"][0]["claim_id"], "AP7-C001")

    def test_bad_prefix_and_bad_out(self):
        r = run("scaffold", "posts/acme_plumbing--2026.md", "--id-prefix", "bad prefix!", cwd=self.root)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--id-prefix", r.stderr)
        r = run("scaffold", "posts/acme_plumbing--2026.md", "--out", "mine.claims.json", cwd=self.root)
        self.assertEqual(r.returncode, 2)
        self.assertIn(".toml", r.stderr)

    def test_article_outside_the_project_is_refused(self):
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        (other / "x.md").write_text("It costs $5.\n", encoding="utf-8")
        r = run("scaffold", str(other / "x.md"), cwd=self.root)
        self.assert_bad_input(r, "x.md")

    def test_no_candidates_gives_an_empty_valid_ledger(self):
        (self.root / "plain.md").write_text("Nothing to check here.\n", encoding="utf-8")
        self.assertEqual(run("scaffold", "plain.md", cwd=self.root).returncode, 0)
        ledger = tomllib.loads(self.ledger_for("plain.md").read_text(encoding="utf-8"))
        self.assertEqual(ledger["claims"], [])
        self.assertEqual(schema.validate(ledger, schema.load("claim-ledger")), [])

    def test_bad_input(self):
        self.assert_bad_input(run("scaffold", "posts/none.md", cwd=self.root), "none.md")


def write_check(path: Path, art: Path, ledger: Path, result="PASS", **overrides) -> Path:
    """A checker record for `art` and `ledger` as `claims record` writes it, current unless `overrides` say not."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"result": result, "article_sha256": sha(art), "ledger_sha256": sha(ledger),
           "rubric_sha256": sha(checker.RUBRIC), "matrix_sha256": "none"}
    path.write_text(json.dumps({**rec, **overrides}), encoding="utf-8")
    return path


class Status(Project):
    def check_file(self, result="PASS", article_sha=None, ledger_sha=None, raw=None):
        path = Path(self.paths()["claims-check"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
            return path
        overrides = {k: v for k, v in (("article_sha256", article_sha), ("ledger_sha256", ledger_sha)) if v}
        return write_check(path, self.art, self.ledger, result, **overrides)

    def test_no_checker_is_incomplete_and_writes_the_report(self):
        r = run("status", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "claims: INCOMPLETE")
        self.assertIn("checker not run", r.stdout)
        rep = json.loads(Path(self.paths()["claims"]).read_text(encoding="utf-8"))
        self.assertEqual(rep["status"], "INCOMPLETE")
        self.assertEqual(rep["gaps"], [])
        self.assertEqual(rep["article_sha256"], sha(self.art))
        self.assertEqual(rep["ledger_sha256"], sha(self.ledger))
        self.assertIsNone(rep["check"])

    def test_stale_ledger_is_incomplete(self):
        self.check_file()
        self.art.write_text(self.art.read_text(encoding="utf-8").replace("similar shops", "similar workshops"),
                            encoding="utf-8")
        r = run("status", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "claims: INCOMPLETE")
        self.assertIn("stale verification", r.stdout)
        self.assertIn("checker result stale", r.stdout)

    def test_current_pass_check_gives_pass(self):
        self.check_file()
        r = run("status", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip().splitlines(), ["claims: PASS", "  checker: PASS (0 warnings)"])
        rj = run("status", "article.md", "--json", cwd=self.root)
        payload = json.loads(rj.stdout)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["check"], {"result": "PASS", "current": True, "warnings": 0})

    def test_current_blocked_check_gives_blocked(self):
        self.check_file("BLOCKED")
        r = run("status", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.splitlines()[0], "claims: BLOCKED")

    def test_check_bound_to_an_old_ledger_is_stale(self):
        self.check_file(ledger_sha="sha256:" + "0" * 64)
        r = run("status", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("checker result stale", r.stdout)
        self.assertNotIn("checker not run", r.stdout)

    def test_malformed_check_is_incomplete(self):
        for raw in ("{not json", "[1, 2]", json.dumps({"result": "PASS"})):
            with self.subTest(raw=raw):
                self.check_file(raw=raw)
                r = run("status", "article.md", "--json", cwd=self.root)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                payload = json.loads(r.stdout)
                self.assertEqual(payload["status"], "INCOMPLETE")
                self.assertEqual(payload["check"], {"result": "INCOMPLETE", "current": False})
                self.assertTrue(any("unreadable" in x for x in payload["reasons"]), payload["reasons"])

    def test_relative_path_from_a_subfolder_matches_the_ledger(self):
        self.check_file()
        (self.root / "sub").mkdir()
        r = run("status", "../article.md", cwd=self.root / "sub")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_ledger_for_another_article_is_incomplete(self):
        (self.root / "other.md").write_text(self.art.read_text(encoding="utf-8"), encoding="utf-8")
        r = run("status", "other.md", "--ledger", ".plainspoken/claims/article.claims.toml", cwd=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not this article", r.stdout)

    def test_missing_ledger_is_incomplete_not_a_crash(self):
        self.ledger.unlink()
        r = run("status", "article.md", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("ledger unreadable", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_missing_article_is_bad_input(self):
        self.assert_bad_input(run("status", "nope.md", cwd=self.root), "nope.md")

    def test_malformed_config_is_bad_input(self):
        (self.root / ".plainspoken" / "config.toml").write_text("[claims]\nledger_dir = '/abs'\n", encoding="utf-8")
        self.assert_bad_input(run("status", "article.md", cwd=self.root), "config.toml")


class EndToEndFixture(unittest.TestCase):
    """The ledger and article the Phase 4 E2E run ended with (`fixtures/claims/e2e/final/`, see
    docs/acceptance/p4-claims.md), laid out as that run's project: with a current PASS checker record, status is
    PASS, so the pin and derivation rules hold for a real model-built ledger."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()
        e2e = FIX / "e2e"
        for src, dest in ((e2e / "final" / "tool-library-first-year.md", "posts"),
                          (e2e / "final" / "tool-library-first-year.claims.toml", ".plainspoken/claims"),
                          (e2e / "sources" / "northbank-annual-report-2026.txt", ".plainspoken/sources"),
                          (e2e / "sources" / "examplelend-help-reminders.txt", ".plainspoken/sources")):
            (self.root / dest).mkdir(parents=True, exist_ok=True)
            shutil.copy(src, self.root / dest / src.name)

    def test_reaches_pass(self):
        art = self.root / "posts" / "tool-library-first-year.md"
        ledger = self.root / ".plainspoken" / "claims" / "tool-library-first-year.claims.toml"
        self.assertEqual(run("recheck", str(ledger), cwd=self.root).returncode, 0)
        paths = json.loads(subprocess.run([sys.executable, str(RUN), "paths", "posts/tool-library-first-year.md"],
                                          cwd=self.root, capture_output=True, text=True).stdout)
        write_check(Path(paths["claims-check"]), art, ledger)
        r = run("status", "posts/tool-library-first-year.md", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip().splitlines(), ["claims: PASS", "  checker: PASS (0 warnings)"])

    def test_draft_status_passes_only_with_both_passes(self):  # issue #24: `status` quotes both engines
        from plainspoken.registry import load_config
        from tests._profiles import PRODUCT
        from tests.test_anti_ai_report import PRODUCT_ARGS, _judges
        art = self.root / "posts" / "tool-library-first-year.md"
        ledger = self.root / ".plainspoken" / "claims" / "tool-library-first-year.claims.toml"
        paths = json.loads(subprocess.run([sys.executable, str(RUN), "paths", "posts/tool-library-first-year.md"],
                                          cwd=self.root, capture_output=True, text=True).stdout)
        write_check(Path(paths["claims-check"]), art, ledger)
        engine = [sys.executable, str(RUN)]
        draft = ["posts/tool-library-first-year.md", *PRODUCT_ARGS]
        subprocess.run([*engine, "check", *draft], cwd=self.root, capture_output=True)
        digest, cfg, reports = sha(art).removeprefix("sha256:"), load_config(), Path(paths["report"]).parent
        _judges(reports, paths["key"], digest, cfg, PRODUCT)

        def status() -> tuple[subprocess.CompletedProcess, subprocess.CompletedProcess]:
            merged = subprocess.run([*engine, "merge", *draft], cwd=self.root, capture_output=True, text=True)
            r = subprocess.run([*engine, "status", *draft], cwd=self.root, capture_output=True, text=True)
            self.assertEqual(r.stdout.splitlines()[:3], ["check: " + merged.stdout.splitlines()[0], "claims: PASS",
                                                         "  checker: PASS (0 warnings)"])
            return merged, r

        merged, r = status()  # the lint's WARNs (7d today) are unresolved: a claims PASS alone isn't enough
        kept = json.loads(Path(paths["report"]).read_text())["unresolved"]
        self.assertEqual((r.returncode, merged.stdout.split()[0], bool(kept)), (1, "UNRESOLVED", True), r.stdout)
        jp = reports / f"{paths['key']}.justify.json"
        jp.write_text(json.dumps({"article_sha256": digest, "items": [
            {"rule": rid, "kind": "voice", "reason": "the short lines are the annual report's own figures"}
            for rid in kept]}))
        (reports / f"{paths['key']}.JR.judge.json").write_text(json.dumps({
            "group": "JR", "article_sha256": digest, "justify_sha256": hashlib.sha256(jp.read_bytes()).hexdigest(),
            "judged_at": "2026-10-21T00:00:00Z", "profile_sha256": PRODUCT.sha256, "ruleset_version": cfg.version,
            "verdicts": [{"rule": rid, "verdict": "accept", "reason": "checked against the evidence"} for rid in kept]}))
        merged, r = status()
        self.assertEqual((merged.returncode, r.returncode), (0, 0), r.stdout + r.stderr)


class ScaffoldAnchors(unittest.TestCase):  # section anchors, not line numbers
    def test_sections_skip_frontmatter_and_code(self):
        text = ("---\ntitle: x\n# integrity: allow\n---\n\nIntro 5%.\n\n## Costs ##\n\n```sh\n# not a heading\n"
                "~~~\n# still code\n```\n\n### What you pay {#pay}\n\nIt's $90.\n")
        sections = claims_tools._sections(text)
        self.assertEqual(sections, [(8, "Costs"), (16, "What you pay")])
        self.assertEqual(claims_tools._anchor(sections, 6), claims_tools.BEFORE_HEADINGS)
        self.assertEqual(claims_tools._anchor(sections, 8), "Costs")
        self.assertEqual(claims_tools._anchor(sections, 13), "Costs")
        self.assertEqual(claims_tools._anchor(sections, 18), "What you pay")


class Template(unittest.TestCase):
    def test_template_ledger_is_valid(self):
        data = tomllib.loads((REPO / "templates" / "claim-ledger.toml").read_text(encoding="utf-8"))
        self.assertEqual(schema.validate(data, schema.load("claim-ledger")), [])
        self.assertEqual({c["status"] for c in data["claims"]},
                         {"verified", "first_hand", "opinion_or_inference", "removed"})


class Paths(Project):
    def test_paths_prints_claim_files_and_the_ledger(self):
        out = self.paths()
        self.assertTrue(out["claims"].endswith(f"{out['key']}.claims.json"))
        self.assertTrue(out["claims-check"].endswith(f"{out['key']}.claims-check.json"))
        self.assertEqual(Path(out["ledger"]), self.ledger.resolve())
        self.assertEqual(Path(out["sources"]), (self.root / ".plainspoken" / "sources").resolve())

    def test_new_ledger_is_named_with_the_report_key(self):
        self.ledger.unlink()
        out = self.paths()
        self.assertEqual(Path(out["ledger"]), self.ledger_dir.resolve() / f"{out['key']}.claims.toml")

    def test_two_index_md_never_share_a_ledger(self):
        for folder in ("a", "b"):
            (self.root / folder).mkdir()
            shutil.copy(self.art, self.root / folder / "index.md")
        la, lb = self.ledger_for("a/index.md"), self.ledger_for("b/index.md")
        self.assertNotEqual(la, lb)
        self.assertEqual(run("scaffold", "a/index.md", cwd=self.root).returncode, 0)
        self.assertTrue(la.exists())
        self.assertEqual(self.ledger_for("b/index.md"), lb)
        r = run("gaps", "b/index.md", cwd=self.root)  # b has no ledger; a's is never read for it
        self.assert_bad_input(r, lb.name)
        self.assertEqual(run("scaffold", "b/index.md", cwd=self.root).returncode, 0)
        self.assertTrue(lb.exists())
        ledgers = [tomllib.loads(p.read_text(encoding="utf-8"))["source_file"] for p in (la, lb)]
        self.assertEqual(ledgers, ["a/index.md", "b/index.md"])

    def test_paths_prints_a_custom_sources_dir(self):
        (self.root / ".plainspoken" / "config.toml").write_text('[claims]\nsources_dir = "research/saved"\n',
                                                                encoding="utf-8")
        self.assertEqual(Path(self.paths()["sources"]), self.root.resolve() / "research" / "saved")

    def test_malformed_claims_config_keeps_paths_working(self):
        (self.root / ".plainspoken" / "config.toml").write_text("[claims]\nledger_dir = '/abs'\n", encoding="utf-8")
        out = self.paths()
        self.assertRegex(out["ledger"], r"^\(unresolved: .*ledger_dir.*\)$")
        self.assertRegex(out["sources"], r"^\(unresolved: .*\)$")
        self.assertNotIn("\n", out["ledger"])
        self.assertTrue(out["lint"].endswith(f"{out['key']}.lint.json"))


if __name__ == "__main__":
    unittest.main()
