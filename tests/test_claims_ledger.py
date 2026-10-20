"""claims.py: ledger load (TOML/JSON), validation, ledger path and status. Ported from a blog workspace's ledger
tests (9 cases), plus the TOML, owner-approval, aggregator and status cases."""
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plainspoken import claims, claims_tools, config, pinning, report

FIX = Path(__file__).parent / "fixtures" / "claims"
SOURCE_REL = ".plainspoken/sources/example-survey.txt"
SOURCE_TEXT = "Example survey, 2026. In our panel, 49% of respondents use the tool every week.\n"
SOURCE_PASSAGE = "49% of respondents use the tool every week"


def _valid_ledger(test, article_text="Body with a 49% statistic.\n"):
    """A minimal valid ledger (JSON) and its matching article, in a temp project. Its one verified claim is pinned
    to a saved source, so `status` can reach PASS."""
    tmp = Path(tempfile.mkdtemp())
    test.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    (tmp / "docs").mkdir()
    (tmp / ".plainspoken" / "claims").mkdir(parents=True)
    (tmp / ".plainspoken" / "sources").mkdir(parents=True)
    (tmp / SOURCE_REL).write_text(SOURCE_TEXT, encoding="utf-8")
    pin = pinning.binding_fields(SOURCE_TEXT, SOURCE_PASSAGE, retrieved_at="2026-07-23", source_snapshot=SOURCE_REL)
    art = tmp / "docs" / "007-example.md"
    art.write_text(article_text, encoding="utf-8")
    ledger = {
        "schema_version": 1,
        "article_id": "007",
        "article_slug": "example",
        "source_file": "docs/007-example.md",
        "source_content_hash": "sha256:" + hashlib.sha256(article_text.encode()).hexdigest(),
        "checked_at": "2026-07-23T12:00:00+10:00",
        "checked_by": "test-session",
        "coverage_status": "complete",
        "claims": [
            {
                "claim_id": "EX-007-C001",
                "text": "49% of respondents use the tool",
                "locations": [{"kind": "body", "anchor": "context"}],
                "claim_type": "statistic",
                "prominence": "high",
                "status": "verified",
                "source": {"url": "https://example.org/report", "title": "Example survey",
                           "source_tier": "primary"},
                "binding": {"same_subject": True, "same_geography": True, "same_period": True,
                            "same_denominator": True, "supports_strength": True, **pin},
            }
        ],
    }
    path = tmp / ".plainspoken" / "claims" / "007-example.claims.json"
    _write(path, ledger)
    return tmp, path, ledger


def _write(path, ledger):
    path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def _messages(findings):
    return [(f["severity"], f["claim_id"], f["message"]) for f in findings]


def _severities(findings):
    return [f["severity"] for f in findings]


class ValidLedger(unittest.TestCase):
    def test_valid_ledger_passes(self):
        tmp, path, _ = _valid_ledger(self)
        self.assertEqual(claims.validate_ledger(path, tmp), [])

    def test_toml_fixture_with_unquoted_dates_is_valid(self):
        ledger = claims.load_ledger(FIX / "article.claims.toml")
        self.assertNotIsInstance(ledger["checked_at"], str)  # tomllib gives a datetime: the fixture tests that path
        self.assertEqual(claims.validate_ledger(FIX / "article.claims.toml", FIX), [])

    def test_json_fixture_matches_the_toml_one(self):
        self.assertEqual(claims.validate_ledger(FIX / "article.claims.json", FIX), [])
        self.assertEqual(claims.load_ledger(FIX / "article.claims.json")["claims"][0]["claim_id"], "SHOP-001-C001")

    def test_toml_inline_dates_in_a_temp_project(self):
        tmp, path, ledger = _valid_ledger(self)
        toml = (FIX / "article.claims.toml").read_text(encoding="utf-8")
        toml = toml.replace('source_file = "article.md"', 'source_file = "docs/007-example.md"').replace(
            'source_content_hash = "sha256:ec6329d11fa5acdbd8d5481e7ca9eacc077080c5d892dc89d6aec4b77402e920"',
            f'source_content_hash = "{ledger["source_content_hash"]}"')
        tpath = path.with_name("007-example.claims.toml")
        tpath.write_text(toml, encoding="utf-8")
        self.assertIn("checked_at = 2026-10-14T09:00:00+10:00", toml)
        self.assertIn("refresh_after = 2027-01-01", toml)
        self.assertEqual(claims.validate_ledger(tpath, tmp), [])


class SchemaViolations(unittest.TestCase):
    def test_unknown_terminal_state_fails(self):
        tmp, path, ledger = _valid_ledger(self)
        ledger["claims"][0]["status"] = "unverified_but_reasonable"
        _write(path, ledger)
        findings = claims.validate_ledger(path, tmp)
        self.assertTrue(any("status" in f["message"] for f in findings))
        self.assertTrue(all(f["message"].startswith("schema: ") for f in findings))

    def test_verified_without_source_fails(self):
        tmp, path, ledger = _valid_ledger(self)
        del ledger["claims"][0]["source"]
        _write(path, ledger)
        self.assertEqual(_messages(claims.validate_ledger(path, tmp)),
                         [("error", None, "schema: claims.0: missing required key 'source'")])

    def test_first_hand_requires_scope(self):
        tmp, path, ledger = _valid_ledger(self)
        c = ledger["claims"][0]
        c["status"] = "first_hand"
        del c["source"]
        del c["binding"]
        _write(path, ledger)
        self.assertEqual(_messages(claims.validate_ledger(path, tmp)),
                         [("error", None, "schema: claims.0: missing required key 'first_hand_scope'")])
        c["first_hand_scope"] = {"owner": "the owner", "scope": "own hosting bill, Jan 2026",
                                 "method": "dashboard export"}
        _write(path, ledger)
        self.assertEqual(claims.validate_ledger(path, tmp), [])

    def test_duplicate_claim_ids_fail(self):
        tmp, path, ledger = _valid_ledger(self)
        ledger["claims"].append(copy.deepcopy(ledger["claims"][0]))
        _write(path, ledger)
        findings = claims.validate_ledger(path, tmp)
        dup = [f for f in findings if "duplicate" in f["message"].lower()]
        self.assertEqual(len(dup), 1)
        self.assertEqual((dup[0]["severity"], dup[0]["claim_id"]), ("error", "EX-007-C001"))

    def test_odd_shapes_never_crash(self):
        tmp, path, ledger = _valid_ledger(self)
        for claims_value in ("not a list", [1, "two", None], [{"status": "blocking", "text": 42}]):
            with self.subTest(claims=claims_value):
                ledger["claims"] = claims_value
                _write(path, ledger)
                findings = claims.validate_ledger(path, tmp)
                self.assertIn("error", _severities(findings))


class HashFreshness(unittest.TestCase):
    def test_stale_source_hash_fails(self):
        tmp, path, _ = _valid_ledger(self)
        art = tmp / "docs" / "007-example.md"
        art.write_text(art.read_text() + "\nA later edit changing 49% to 52%.\n", encoding="utf-8")
        findings = claims.validate_ledger(path, tmp)
        stale = [f for f in findings if f["message"].startswith("stale verification")]
        self.assertEqual(_severities(stale), ["error"])

    def test_article_hash_helper(self):
        tmp, _, _ = _valid_ledger(self, "known content\n")
        h = claims.article_hash(tmp / "docs" / "007-example.md")
        self.assertEqual(h, "sha256:" + hashlib.sha256(b"known content\n").hexdigest())

    def test_missing_source_file(self):
        tmp, path, _ = _valid_ledger(self)
        (tmp / "docs" / "007-example.md").unlink()
        findings = claims.validate_ledger(path, tmp)
        self.assertEqual([(f["severity"], f["message"]) for f in findings],
                         [("error", "source_file not found: docs/007-example.md")])

    def test_source_file_outside_the_project_is_never_read(self):
        tmp, path, ledger = _valid_ledger(self)
        ledger["source_file"] = "../outside.md"
        _write(path, ledger)
        findings = claims.validate_ledger(path, tmp)
        self.assertTrue(any(f["message"].startswith("schema: source_file") for f in findings))
        self.assertFalse(any("stale" in f["message"] for f in findings))


class BlockingAndRemoved(unittest.TestCase):
    def test_blocking_claim_is_reported(self):
        tmp, path, ledger = _valid_ledger(self)
        c = ledger["claims"][0]
        c["status"] = "blocking"
        del c["source"]
        del c["binding"]
        c["resolution"] = "Can't resolve the 49% figure; held pending a primary source."
        _write(path, ledger)
        findings = claims.validate_ledger(path, tmp)
        self.assertEqual(_severities(findings), ["blocking"])
        self.assertEqual(findings[0]["claim_id"], "EX-007-C001")

    def test_removed_requires_resolution(self):
        tmp, path, ledger = _valid_ledger(self)
        c = ledger["claims"][0]
        c["status"] = "removed"
        del c["source"]
        del c["binding"]
        _write(path, ledger)
        self.assertEqual(_messages(claims.validate_ledger(path, tmp)),
                         [("error", None, "schema: claims.0: missing required key 'resolution'")])

    def test_partial_coverage_is_a_warning(self):
        tmp, path, ledger = _valid_ledger(self)
        ledger["coverage_status"] = "partial"
        _write(path, ledger)
        findings = claims.validate_ledger(path, tmp)
        self.assertEqual(_severities(findings), ["warning"])
        self.assertIn("report as incomplete, not passing", findings[0]["message"])

    def test_sensitive_first_hand_needs_owner_approval(self):
        tmp, path, ledger = _valid_ledger(self)
        c = ledger["claims"][0]
        c["status"] = "first_hand"
        del c["source"]
        del c["binding"]
        c["first_hand_scope"] = {"owner": "the owner", "scope": "a client's invoice totals", "method": "invoices",
                                 "sensitive": True}
        _write(path, ledger)
        findings = claims.validate_ledger(path, tmp)
        self.assertEqual(_severities(findings), ["blocking"])
        self.assertIn("owner approval required before publication", findings[0]["message"])
        c["first_hand_scope"]["approved_by_owner"] = False
        _write(path, ledger)
        self.assertEqual(_severities(claims.validate_ledger(path, tmp)), ["blocking"])
        c["first_hand_scope"]["approved_by_owner"] = True
        _write(path, ledger)
        self.assertEqual(claims.validate_ledger(path, tmp), [])

    def test_removed_sensitive_claim_skips_owner_approval(self):  # review fix 3: removed never publishes
        tmp, path, ledger = _valid_ledger(self)
        c = ledger["claims"][0]
        c["status"] = "removed"
        del c["source"]
        del c["binding"]
        c["resolution"] = "cut from the article: the owner didn't want the figure published"
        c["first_hand_scope"] = {"owner": "the owner", "scope": "a client's invoice totals", "method": "invoices",
                                 "sensitive": True}
        _write(path, ledger)
        self.assertEqual(claims.validate_ledger(path, tmp), [])

    def test_aggregator_never_supports_a_verified_claim(self):
        tmp, path, ledger = _valid_ledger(self)
        ledger["claims"][0]["source"]["source_tier"] = "aggregator"
        _write(path, ledger)
        findings = claims.validate_ledger(path, tmp)
        self.assertEqual(_severities(findings), ["error"])
        self.assertIn("an aggregator never supports a claim: trace to the origin or cut", findings[0]["message"])


class SignOff(unittest.TestCase):
    def _signed(self, wording):
        tmp, path, ledger = _valid_ledger(self, "Intro.\n\nBody with a 49%\n   statistic from the survey.\n")
        ledger["claims"][0]["human_signoff"] = {
            "signed": "2026-10-01", "signed_by": "the owner", "against_run": "2026-10-01-abc",
            "findings": ["F1"], "wording": wording, "scope_note": "approved the 49% sentence as worded"}
        _write(path, ledger)
        return claims.validate_ledger(path, tmp)

    def test_signed_wording_present_after_whitespace_normalising(self):
        self.assertEqual(self._signed("Body with a 49% statistic from the survey."), [])

    def test_curly_and_straight_quotes_match_both_ways(self):  # pinning.normalise_text
        for article, wording in (("The owner said \u201cit\u2019s about $100\u201d a visit.\n",
                                  'The owner said "it\'s about $100" a visit.'),
                                 ('The owner said "it\'s about $100" a visit.\n',
                                  "The owner said \u201cit\u2019s about $100\u201d a visit.")):
            with self.subTest(article=article):
                tmp, path, ledger = _valid_ledger(self, article)
                ledger["claims"][0]["human_signoff"] = {
                    "signed": "2026-10-01", "signed_by": "the owner", "against_run": "2026-10-01-abc", "findings": ["F1"],
                    "wording": wording, "scope_note": "as worded"}
                _write(path, ledger)
                self.assertEqual(claims.validate_ledger(path, tmp), [])

    def test_case_still_voids_the_signoff(self):  # quotes and whitespace only: a case change is a wording change
        self.assertEqual(_severities(self._signed("body with a 49% statistic from the survey.")), ["error"])

    def test_signed_wording_gone_voids_the_signoff(self):
        findings = self._signed("Body with a 52% statistic from the survey.")
        self.assertEqual(_severities(findings), ["error"])
        self.assertTrue(findings[0]["message"].startswith("voided sign-off: "))


class Loading(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_yaml_ledger_is_refused(self):
        p = self.tmp / "a.claims.yaml"
        p.write_text("schema_version: 1\n", encoding="utf-8")
        with self.assertRaisesRegex(claims.LedgerError, r"use \.claims\.toml or \.claims\.json"):
            claims.load_ledger(p)
        with self.assertRaises(claims.LedgerError):
            claims.validate_ledger(p, self.tmp)

    def test_malformed_toml_names_the_file_and_line(self):
        p = self.tmp / "broken.claims.toml"
        p.write_text('schema_version = 1\narticle_id = "x\n', encoding="utf-8")
        with self.assertRaises(claims.LedgerError) as cm:
            claims.load_ledger(p)
        self.assertIn("broken.claims.toml", str(cm.exception))
        self.assertIn("line 2", str(cm.exception))

    def test_deeply_nested_toml_is_a_ledger_error(self):  # review fix 1: never a bare RecursionError
        p = self.tmp / "deep.claims.toml"
        p.write_text("a = " + "[" * 5000 + "]" * 5000 + "\n", encoding="utf-8")
        with self.assertRaisesRegex(claims.LedgerError, r"deep\.claims\.toml"):
            claims.load_ledger(p)
        with self.assertRaises(claims.LedgerError):
            claims.validate_ledger(p, self.tmp)
        s = claims.status(self.tmp / "a.md", p, self.tmp, gaps=[], check={"result": "PASS", "current": True})
        self.assertEqual(s["status"], "INCOMPLETE")

    def test_malformed_json_names_the_file(self):
        p = self.tmp / "broken.claims.json"
        p.write_text('{"schema_version": 1,', encoding="utf-8")
        with self.assertRaisesRegex(claims.LedgerError, r"broken\.claims\.json.*line 1"):
            claims.load_ledger(p)

    def test_json_must_be_an_object_without_duplicate_keys_or_nan(self):
        for text in ("[1, 2]", '{"a": 1, "a": 2}', '{"a": NaN}'):
            with self.subTest(text=text):
                p = self.tmp / "odd.claims.json"
                p.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(claims.LedgerError, r"odd\.claims\.json"):
                    claims.load_ledger(p)

    def test_missing_and_undecodable_files(self):
        with self.assertRaisesRegex(claims.LedgerError, r"none\.claims\.toml"):
            claims.load_ledger(self.tmp / "none.claims.toml")
        p = self.tmp / "bin.claims.toml"
        p.write_bytes(b"\xff\xfe\x00")
        with self.assertRaisesRegex(claims.LedgerError, r"bin\.claims\.toml"):
            claims.load_ledger(p)


class LedgerPath(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".plainspoken").mkdir()
        self.dir = self.root / ".plainspoken" / "claims"

    def key(self, rel):
        return report.report_key(self.root / rel, self.root)

    def test_default_dir_and_toml_preferred(self):
        art = self.root / "posts" / "hello.md"
        key = self.key("posts/hello.md")
        self.assertRegex(key, r"^hello-[0-9a-f]{8}$")
        self.assertEqual(claims.ledger_path_for(art, self.root), self.dir / f"{key}.claims.toml")
        self.dir.mkdir()
        (self.dir / f"{key}.claims.json").write_text("{}", encoding="utf-8")
        self.assertEqual(claims.ledger_path_for(art, self.root), self.dir / f"{key}.claims.json")
        (self.dir / f"{key}.claims.toml").write_text("", encoding="utf-8")
        self.assertEqual(claims.ledger_path_for(art, self.root), self.dir / f"{key}.claims.toml")

    def test_configured_ledger_dir(self):
        (self.root / ".plainspoken" / "config.toml").write_text('[claims]\nledger_dir = "ledgers"\n',
                                                                 encoding="utf-8")
        self.assertEqual(claims.ledger_path_for(self.root / "a" / "post.mdx", self.root),
                         self.root / "ledgers" / f"{self.key('a/post.mdx')}.claims.toml")

    def test_bad_ledger_dir_raises(self):
        (self.root / ".plainspoken" / "config.toml").write_text('[claims]\nledger_dir = "../x"\n',
                                                                 encoding="utf-8")
        with self.assertRaises(config.ConfigError):
            claims.ledger_path_for(self.root / "post.md", self.root)

    # --- the ledger is keyed on the path, like the reports ---------------------------------
    def two_index_md(self):
        for folder in ("a", "b"):
            (self.root / folder).mkdir()
            (self.root / folder / "index.md").write_text(f"{folder}: 41% of bookings.\n", encoding="utf-8")
        return self.root / "a" / "index.md", self.root / "b" / "index.md"

    def legacy(self, source_file, name="index.claims.toml"):
        self.dir.mkdir(exist_ok=True)
        path = self.dir / name
        if name.endswith(".json"):
            path.write_text(json.dumps({"source_file": source_file}), encoding="utf-8")
        else:
            path.write_text(f'source_file = "{source_file}"\n', encoding="utf-8")
        return path

    def test_two_index_md_get_two_ledgers(self):
        a, b = self.two_index_md()
        la, lb = claims.ledger_path_for(a, self.root), claims.ledger_path_for(b, self.root)
        self.assertNotEqual(la, lb)
        self.assertEqual((la.parent, lb.parent), (self.dir, self.dir))
        self.assertEqual(la.name, f"{self.key('a/index.md')}.claims.toml")
        self.assertEqual(lb.name, f"{self.key('b/index.md')}.claims.toml")
        self.dir.mkdir()
        la.write_text('source_file = "a/index.md"\n', encoding="utf-8")  # a's ledger is never b's
        self.assertEqual(claims.ledger_path_for(b, self.root), lb)
        self.assertFalse(lb.exists())

    def test_old_stem_only_ledger_is_found_when_its_source_file_names_the_article(self):
        a, b = self.two_index_md()
        for name in ("index.claims.toml", "index.claims.json"):
            with self.subTest(name=name):
                old = self.legacy("a/index.md", name)
                self.assertEqual(claims.ledger_path_for(a, self.root), old)
                # b has the same stem, but the old ledger names a: b gets its own (path-keyed) ledger
                self.assertEqual(claims.ledger_path_for(b, self.root),
                                 self.dir / f"{self.key('b/index.md')}.claims.toml")
                old.unlink()

    def test_path_keyed_ledger_wins_over_an_old_one(self):
        a, _ = self.two_index_md()
        self.legacy("a/index.md")
        keyed = self.dir / f"{self.key('a/index.md')}.claims.toml"
        keyed.write_text('source_file = "a/index.md"\n', encoding="utf-8")
        self.assertEqual(claims.ledger_path_for(a, self.root), keyed)

    def test_ambiguous_old_ledger_is_an_error_never_a_silent_pick(self):
        a, b = self.two_index_md()
        cases = {"source_file names no file": 'source_file = "gone/index.md"\n',
                 "no source_file": 'article_id = "X"\n',
                 "not TOML": "source_file = \n"}
        for why, text in cases.items():
            with self.subTest(why=why):
                self.dir.mkdir(exist_ok=True)
                (self.dir / "index.claims.toml").write_text(text, encoding="utf-8")
                for art, rel in ((a, "a/index.md"), (b, "b/index.md")):
                    with self.assertRaises(claims.LedgerError) as cm:
                        claims.ledger_path_for(art, self.root)
                    msg = str(cm.exception)
                    self.assertIn("index.claims.toml", msg)
                    self.assertIn(f"{self.key(rel)}.claims.toml", msg)  # says what to rename it to


CHECK_PASS = {"result": "PASS", "current": True}


class Status(unittest.TestCase):
    def setUp(self):
        self.tmp, self.path, self.ledger = _valid_ledger(self)
        self.art = self.tmp / "docs" / "007-example.md"

    def status(self, gaps=(), check=CHECK_PASS):
        return claims.status(self.art, self.path, self.tmp, gaps=None if gaps is None else list(gaps), check=check)

    def test_pass_needs_everything(self):
        s = self.status()
        self.assertEqual((s["status"], s["reasons"]), ("PASS", []))
        self.assertEqual(s["article_sha256"], claims.article_hash(self.art))
        self.assertEqual(s["ledger_sha256"], claims.article_hash(self.path))
        self.assertEqual(s["counts"], {"verified": 1})

    def test_toml_fixture_reaches_pass(self):
        root = Path(tempfile.mkdtemp())  # laid out as a project: the pinned source lives under sources_dir
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / ".plainspoken" / "sources").mkdir(parents=True)
        shutil.copy(FIX / "article.md", root / "article.md")
        shutil.copy(FIX / "article.claims.toml", root / "article.claims.toml")
        shutil.copy(FIX / "sources" / "example-source.md", root / ".plainspoken" / "sources" / "example-source.md")
        s = claims.status(root / "article.md", root / "article.claims.toml", root, gaps=[], check=CHECK_PASS)
        self.assertEqual((s["status"], s["counts"]), ("PASS", {"first_hand": 1, "verified": 1}))

    def test_stale_is_incomplete(self):
        self.art.write_text("Body with a 52% statistic.\n", encoding="utf-8")
        s = self.status()
        self.assertEqual(s["status"], "INCOMPLETE")
        self.assertTrue(any("stale" in r for r in s["reasons"]))

    def test_partial_coverage_is_incomplete(self):
        self.ledger["coverage_status"] = "partial"
        _write(self.path, self.ledger)
        self.assertEqual(self.status()["status"], "INCOMPLETE")

    def test_gaps_not_computed_or_present(self):
        s = self.status(gaps=None)
        self.assertEqual(s["status"], "INCOMPLETE")
        self.assertIn("gaps not computed", s["reasons"])
        self.assertEqual(self.status(gaps=[{"text": "12%"}])["status"], "INCOMPLETE")

    def test_checker_not_run_or_not_current(self):
        for check in (None, {"result": "PASS", "current": False}, {"result": "PASS"}, "PASS"):
            with self.subTest(check=check):
                s = self.status(check=check)
                self.assertEqual(s["status"], "INCOMPLETE")
                self.assertIn("checker not run", s["reasons"])
        self.assertEqual(self.status(check={"result": "INCOMPLETE", "current": True})["status"], "INCOMPLETE")

    def test_blocking_claim_is_blocked_and_wins(self):
        c = self.ledger["claims"][0]
        c["status"] = "blocking"
        c["resolution"] = "held pending a primary source"
        _write(self.path, self.ledger)
        s = self.status(gaps=None, check=None)
        self.assertEqual(s["status"], "BLOCKED")
        self.assertIn("gaps not computed", s["reasons"])

    def test_checker_blocked_is_blocked_and_wins(self):
        self.ledger["coverage_status"] = "partial"
        _write(self.path, self.ledger)
        self.assertEqual(self.status(check={"result": "BLOCKED", "current": True})["status"], "BLOCKED")
        # a stale checker record never blocks or passes: it counts as not run
        self.assertEqual(self.status(check={"result": "BLOCKED", "current": False})["status"], "INCOMPLETE")

    def test_schema_error_is_incomplete(self):
        self.ledger["claims"][0]["status"] = "unverified_but_reasonable"
        _write(self.path, self.ledger)
        self.assertEqual(self.status()["status"], "INCOMPLETE")

    def test_unreadable_ledger_is_incomplete_not_a_crash(self):
        self.path.write_text("{", encoding="utf-8")
        s = self.status()
        self.assertEqual(s["status"], "INCOMPLETE")
        s = claims.status(self.art, self.tmp / "nope.claims.toml", self.tmp, gaps=[], check=CHECK_PASS)
        self.assertEqual((s["status"], s["ledger_sha256"]), ("INCOMPLETE", None))

    def test_nul_in_source_file_is_incomplete_not_a_crash(self):  # review fix 2: status never raises
        self.ledger["source_file"] = "docs/007-\x00example.md"
        _write(self.path, self.ledger)
        s = self.status()
        self.assertEqual(s["status"], "INCOMPLETE")
        self.assertTrue(any("source_file" in r for r in s["reasons"]))
        findings = claims.validate_ledger(self.path, self.tmp)
        self.assertTrue(any(f["message"].startswith("schema: source_file") or "source_file" in f["message"]
                            for f in findings))

    def test_status_parses_the_ledger_once(self):  # it read the ledger three times
        with mock.patch.object(claims, "load_ledger", wraps=claims.load_ledger) as load:
            s = claims_tools.status_report(self.art, self.path, self.tmp, self.tmp / "none.claims-check.json", None)
        self.assertEqual(load.call_count, 1)
        self.assertEqual(s["status"], "INCOMPLETE")  # no checker record
        self.assertEqual(s["reasons"], ["checker not run"])
        with mock.patch.object(claims, "load_ledger", wraps=claims.load_ledger) as load:
            self.assertEqual(self.status()["status"], "PASS")
        self.assertEqual(load.call_count, 1)

    def test_nul_path_messages_show_the_path_not_a_repr(self):
        with self.assertRaises(claims.LedgerError) as cm:
            claims.load_ledger(self.tmp / "l\x00.claims.toml")
        msg = str(cm.exception)
        self.assertNotIn("PosixPath(", msg)
        self.assertNotIn("\x00", msg)
        self.assertIn("l\\x00.claims.toml: not a usable ledger path", msg)
        self.ledger["source_file"] = "docs/007-\x00example.md"
        _write(self.path, self.ledger)
        nul = [f["message"] for f in claims.validate_ledger(self.path, self.tmp) if "NUL" in f["message"]]
        self.assertEqual(nul, ["source_file contains a NUL character: docs/007-\\x00example.md"])

    def test_nul_in_article_or_ledger_path_is_incomplete(self):  # review fix 2: status never raises
        s = claims.status(self.tmp / "a\x00.md", self.path, self.tmp, gaps=[], check=CHECK_PASS)
        self.assertEqual((s["status"], s["article_sha256"]), ("INCOMPLETE", None))
        s = claims.status(self.art, self.tmp / "l\x00.claims.toml", self.tmp, gaps=[], check=CHECK_PASS)
        self.assertEqual((s["status"], s["ledger_sha256"]), ("INCOMPLETE", None))

    # --- pins and derivations ---------------------------------------------------------------------------------
    def binding(self):
        return self.ledger["claims"][0]["binding"]

    def incomplete_with(self, *fragments):
        _write(self.path, self.ledger)
        s = self.status()
        self.assertEqual(s["status"], "INCOMPLETE", s["reasons"])
        for fragment in fragments:
            self.assertTrue(any(fragment in r for r in s["reasons"]), (fragment, s["reasons"]))
        return s

    def test_verified_claim_without_a_pinned_passage_is_incomplete(self):
        for key in ("passage", "passage_sha256", "source_text_sha256", "retrieved_at", "source_snapshot"):
            self.binding().pop(key)
        self.incomplete_with("EX-007-C001", "no pinned passage")

    def test_a_passage_gone_from_the_saved_source_is_incomplete(self):
        (self.tmp / SOURCE_REL).write_text(SOURCE_TEXT.replace("49%", "94%"), encoding="utf-8")
        self.incomplete_with("EX-007-C001", "passage_missing")

    def test_a_passage_hash_mismatch_is_incomplete(self):
        self.binding()["passage_sha256"] = pinning.sha256_str("something else")
        self.incomplete_with("EX-007-C001", "passage_hash_mismatch")

    def test_a_missing_snapshot_is_incomplete(self):
        (self.tmp / SOURCE_REL).unlink()
        self.incomplete_with("EX-007-C001", "snapshot_missing")

    def test_a_primary_passage_with_no_snapshot_is_incomplete(self):
        self.binding().pop("source_snapshot")
        self.incomplete_with("EX-007-C001", "unchecked", "source_snapshot")

    # the snapshot must live under sources_dir and never be the article (no self-citation).
    def pin_to(self, rel, text):
        """Re-pin the verified claim to `rel`, whose text is `text`, so only the snapshot's location can fail."""
        self.binding().update(pinning.binding_fields(text, "49%", retrieved_at="2026-07-23", source_snapshot=rel))

    def test_a_snapshot_that_is_the_article_is_incomplete(self):
        self.pin_to("docs/007-example.md", self.art.read_text(encoding="utf-8"))
        self.incomplete_with("EX-007-C001", "snapshot_outside_sources", "article")

    def test_a_snapshot_outside_sources_dir_is_incomplete(self):
        (self.tmp / "notes").mkdir()
        (self.tmp / "notes" / "src.md").write_text(SOURCE_TEXT, encoding="utf-8")
        self.pin_to("notes/src.md", SOURCE_TEXT)
        self.incomplete_with("EX-007-C001", "snapshot_outside_sources")

    def test_a_symlink_in_sources_dir_pointing_outside_it_is_incomplete(self):
        link = self.tmp / ".plainspoken" / "sources" / "article-link.md"
        link.symlink_to(self.art)
        self.pin_to(".plainspoken/sources/article-link.md", self.art.read_text(encoding="utf-8"))
        self.incomplete_with("EX-007-C001", "snapshot_outside_sources")

    def test_a_custom_sources_dir_reaches_pass(self):
        saved = self.tmp / "research" / "saved"
        saved.mkdir(parents=True)
        (saved / "survey.txt").write_text(SOURCE_TEXT, encoding="utf-8")
        (self.tmp / ".plainspoken" / "config.toml").write_text('[claims]\nsources_dir = "research/saved"\n',
                                                               encoding="utf-8")
        self.pin_to("research/saved/survey.txt", SOURCE_TEXT)
        _write(self.path, self.ledger)
        s = self.status()
        self.assertEqual((s["status"], s["reasons"]), ("PASS", []))
        self.pin_to(SOURCE_REL, SOURCE_TEXT)  # the default folder isn't a source folder under this config
        self.incomplete_with("EX-007-C001", "snapshot_outside_sources")

    def test_a_misconfigured_sources_dir_raises_config_error(self):
        (self.tmp / ".plainspoken" / "config.toml").write_text('[claims]\nsources_dir = "../up"\n', encoding="utf-8")
        with self.assertRaises(config.ConfigError):
            self.status()

    def test_a_changed_source_is_a_note_and_still_passes(self):
        (self.tmp / SOURCE_REL).write_text(SOURCE_TEXT.replace("2026", "2025"), encoding="utf-8")
        _write(self.path, self.ledger)
        s = self.status()
        self.assertEqual(s["status"], "PASS", s["reasons"])
        self.assertEqual(len(s["reasons"]), 1)
        self.assertIn("source_changed", s["reasons"][0])
        self.assertTrue(s["reasons"][0].startswith("note: "))

    def test_an_additional_passage_on_another_page_is_a_note_and_still_passes(self):
        self.binding()["additional_passages"] = [{"passage": "Panel run in March 2026.",
                                                  "passage_sha256": pinning.sha256_str("Panel run in March 2026."),
                                                  "source_url": "https://example.org/method"}]
        _write(self.path, self.ledger)
        s = self.status()
        self.assertEqual(s["status"], "PASS", s["reasons"])
        self.assertEqual(len(s["reasons"]), 1)
        self.assertTrue(s["reasons"][0].startswith("note: "), s["reasons"])
        self.assertIn("additional passage 1", s["reasons"][0])

    def test_a_removed_claim_is_skipped(self):
        self.ledger["claims"].append({
            "claim_id": "EX-007-C002", "text": "an old sentence", "locations": [{"kind": "body"}],
            "claim_type": "statistic", "prominence": "low", "status": "removed", "resolution": "cut from the draft",
            "binding": {"same_subject": True, "same_geography": True, "same_period": True, "same_denominator": True,
                        "supports_strength": True, "passage": "nowhere in the source",
                        "passage_sha256": pinning.sha256_str("x"), "source_snapshot": "missing.txt"}})
        _write(self.path, self.ledger)
        s = self.status()
        self.assertEqual((s["status"], s["reasons"]), ("PASS", []))

    def derived(self, *inputs, external=None):
        derivation = {"method": "rounded from C001"}
        if inputs or external is None:
            derivation["inputs"] = list(inputs)
        if external is not None:
            derivation["derived_from_external"] = list(external)
        self.ledger["claims"].append({
            "claim_id": "EX-007-C002", "text": "about half use it", "locations": [{"kind": "body"}],
            "claim_type": "statistic", "prominence": "low", "status": "derived", "derivation": derivation})

    # --- derivation evidence that isn't a claim -----------------------------------------------------------------
    def test_external_derivation_evidence_isnt_called_a_dead_claim(self):
        for inputs, external in (((), ["data/bookings-2026.csv", "https://example.org/survey"]),
                                 (("EX-007-C001",), ["notes/method.md"])):
            with self.subTest(inputs=inputs):
                self.derived(*inputs, external=external)
                _write(self.path, self.ledger)
                self.assertEqual(claims.validate_ledger(self.path, self.tmp), [])
                s = self.status()
                self.assertEqual((s["status"], s["reasons"]), ("PASS", []))
                self.ledger["claims"].pop()

    def test_a_derivation_needs_inputs_or_external_evidence(self):
        self.derived(external=[])
        self.ledger["claims"][-1]["derivation"].pop("derived_from_external")
        _write(self.path, self.ledger)
        msgs = [f["message"] for f in claims.validate_ledger(self.path, self.tmp)]
        self.assertEqual(msgs, ["a derivation needs inputs (claim ids) or derived_from_external (files or URLs)"])
        self.assertEqual(self.status()["status"], "INCOMPLETE")

    def test_external_derivation_evidence_is_a_url_or_project_path(self):
        for bad in ("/etc/passwd", "../outside.csv", "C:\\data.csv", "ftp://example.org/x", "", "a\x00b"):
            with self.subTest(bad=bad):
                self.derived(external=[bad])
                _write(self.path, self.ledger)
                findings = claims.validate_ledger(self.path, self.tmp)
                self.assertTrue(findings, bad)
                self.assertTrue(all(f["severity"] == "error" for f in findings), findings)
                self.ledger["claims"].pop()

    def test_a_dead_input_names_the_external_field(self):
        self.derived("data/bookings.csv")
        s = self.incomplete_with("data/bookings.csv")
        self.assertTrue(any("derived_from_external" in r for r in s["reasons"]), s["reasons"])

    def test_a_derived_claim_with_live_inputs_passes(self):
        self.derived("EX-007-C001")
        _write(self.path, self.ledger)
        self.assertEqual(self.status()["status"], "PASS")

    def test_a_derived_claim_whose_input_is_absent_or_removed_is_incomplete(self):
        self.derived("EX-007-C001", "EX-007-C009")
        self.incomplete_with("EX-007-C002", "EX-007-C009")
        self.ledger["claims"].pop()
        self.derived("EX-007-C003")
        self.ledger["claims"].append({
            "claim_id": "EX-007-C003", "text": "cut", "locations": [{"kind": "body"}], "claim_type": "statistic",
            "prominence": "low", "status": "removed", "resolution": "cut from the draft"})
        self.incomplete_with("EX-007-C002", "EX-007-C003")

    def test_ledger_for_another_article_is_incomplete(self):
        other = self.tmp / "docs" / "copy.md"
        other.write_bytes(self.art.read_bytes())  # same bytes, different file
        s = claims.status(other, self.path, self.tmp, gaps=[], check=CHECK_PASS)
        self.assertEqual(s["status"], "INCOMPLETE")
        self.assertTrue(any("source_file" in r for r in s["reasons"]))


if __name__ == "__main__":
    unittest.main()
