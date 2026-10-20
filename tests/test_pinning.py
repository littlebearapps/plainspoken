"""pinning.py: locate, hash and bind a source passage, and recheck pins offline against saved sources. Ported from
a blog workspace's pin-verify tests (the cases that don't fetch), plus evidence normalisation, case sensitivity and
every recheck result kind."""
import ast
import hashlib
import shutil
import tempfile
import typing
import unittest
from pathlib import Path

from plainspoken import config, pinning
from plainspoken.pinning import (
    MAX_PASSAGE_WORDS,
    Pin,
    binding_fields,
    locate_passage,
    normalise_evidence,
    normalise_text,
    pin_hashes,
    recheck,
)

FIX = Path(__file__).parent / "fixtures" / "claims"
SOURCE = (
    "Report intro.\n\n"
    "Acme Plumbing booked “900 jobs” a\nmonth over winter, the owner said.\n\n"
    "Unrelated footer.\n"
)


def _sha(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


class Normalise(unittest.TestCase):
    def test_straightens_quotes_and_collapses_whitespace(self):
        self.assertEqual(normalise_text("  “a”  ‘b’\n\t«c»  "), "\"a\" 'b' \"c\"")

    def test_keeps_case(self):
        self.assertIsNone(locate_passage("About $100 a month", "about $100"))
        self.assertIsNotNone(locate_passage("About $100 a month", "About $100"))

    def test_evidence_drops_link_syntax_and_case(self):
        self.assertEqual(normalise_evidence("[Home Affairs](https://x.example)"), normalise_evidence("home affairs"))

    def test_evidence_normalises_quotes_whitespace_and_case(self):
        self.assertEqual(normalise_evidence("About  “$100”\n a month"), normalise_evidence('about "$100" a MONTH'))

    def test_evidence_keeps_other_punctuation(self):
        self.assertNotEqual(normalise_evidence("about $100."), normalise_evidence("about $100"))

    def test_evidence_link_url_with_parentheses(self):
        self.assertEqual(normalise_evidence("see [Foo](https://en.wikipedia.org/wiki/Foo_(bar)) for more"),
                         "see foo for more")

    def test_evidence_link_with_a_title(self):
        for link in ('[Foo](https://example.com/a "The title")', "[Foo](https://example.com/a 'The title')",
                     "[Foo](https://example.com/a (The title))", "[Foo](<https://example.com/a b>)",
                     '[Foo](https://example.com/x_(y) "t")'):
            with self.subTest(link=link):
                self.assertEqual(normalise_evidence(f"see {link} now"), "see foo now")

    def test_evidence_image_becomes_its_alt_text(self):
        self.assertEqual(normalise_evidence("A ![Bar chart](img/c_(1).png) here"), "a bar chart here")
        self.assertEqual(normalise_evidence("![]( img.png )x"), "x")

    def test_evidence_leaves_plain_brackets_alone(self):
        self.assertEqual(normalise_evidence("[sic] (2025) and [a] b"), "[sic] (2025) and [a] b")


class Locate(unittest.TestCase):
    def test_verbatim(self):
        pin = locate_passage(SOURCE, "Report intro.")
        self.assertEqual(pin, Pin(start=0, end=len("Report intro."), passage_norm="Report intro."))

    def test_across_a_line_wrap_and_curly_quotes(self):
        pin = locate_passage(SOURCE, 'booked "900 jobs" a month over winter')
        self.assertIsNotNone(pin)
        self.assertEqual(pin.passage_norm, 'booked "900 jobs" a month over winter')
        self.assertEqual(normalise_text(SOURCE)[pin.start:pin.end], pin.passage_norm)

    def test_paraphrase_not_found(self):
        self.assertIsNone(locate_passage(SOURCE, "booked nine hundred jobs a month"))

    def test_empty_not_found(self):
        self.assertIsNone(locate_passage(SOURCE, "  \n "))

    def test_pin_is_frozen(self):
        pin = locate_passage(SOURCE, "Report intro.")
        with self.assertRaises(AttributeError):
            pin.start = 3  # type: ignore[misc]


class Hashes(unittest.TestCase):
    def test_hashes_are_sha256_of_the_normalised_text(self):
        passage = "booked “900 jobs” a\nmonth"
        h = pin_hashes(SOURCE, passage)
        self.assertEqual(h["passage_sha256"], _sha(normalise_text(passage)))
        self.assertEqual(h["source_text_sha256"], _sha(normalise_text(SOURCE)))
        self.assertRegex(h["passage_sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_cosmetic_rerender_keeps_the_hashes(self):
        rerendered = SOURCE.replace("“", '"').replace("”", '"').replace("\n", "  \n")
        self.assertEqual(pin_hashes(SOURCE, "900 jobs"), pin_hashes(rerendered, "900 jobs"))

    def test_not_locatable_raises(self):
        with self.assertRaises(ValueError):
            pin_hashes(SOURCE, "a sentence that isn't there")


class BindingFields(unittest.TestCase):
    def test_locates_across_linebreaks_and_curly_quotes(self):
        fields = binding_fields(SOURCE, 'booked "900 jobs" a month over winter',
                                retrieved_at="2026-10-14T10:00:00+10:00", source_snapshot=None)
        self.assertEqual(fields["passage"], 'booked "900 jobs" a month over winter')
        expected = pin_hashes(SOURCE, fields["passage"])
        self.assertEqual(fields["passage_sha256"], expected["passage_sha256"])
        self.assertEqual(fields["source_text_sha256"], expected["source_text_sha256"])
        self.assertEqual(fields["retrieved_at"], "2026-10-14T10:00:00+10:00")
        self.assertNotIn("source_snapshot", fields)

    def test_records_the_snapshot(self):
        fields = binding_fields(SOURCE, "900 jobs", retrieved_at="x",
                                source_snapshot=".plainspoken/sources/acme.md")
        self.assertEqual(fields["source_snapshot"], ".plainspoken/sources/acme.md")

    def test_refuses_an_unsafe_snapshot_path(self):
        for bad in ("/etc/passwd", "../outside.md", "a/../../b.md", "x\x00.md", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as ctx:
                binding_fields(SOURCE, "900 jobs", retrieved_at="x", source_snapshot=bad)
            self.assertIn("project-relative", str(ctx.exception))

    def test_passage_is_stored_normalised(self):
        fields = binding_fields(SOURCE, "booked “900 jobs”  a\nmonth", retrieved_at="x", source_snapshot=None)
        self.assertEqual(fields["passage"], normalise_text("booked “900 jobs”  a\nmonth"))

    def test_paraphrase_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            binding_fields(SOURCE, "booked nine hundred jobs a month", retrieved_at="x", source_snapshot=None)
        self.assertIn("not locatable", str(ctx.exception))
        self.assertIn("never paraphrase", str(ctx.exception))

    def test_overlong_passage_refused(self):
        with self.assertRaises(ValueError) as ctx:
            binding_fields("word " * 300, "word " * 100, retrieved_at="x", source_snapshot=None)
        self.assertIn("too long", str(ctx.exception))
        self.assertIn(f"> {MAX_PASSAGE_WORDS}", str(ctx.exception))

    def test_honest_76_word_cut_accepted(self):
        words = [f"w{i}" for i in range(200)]
        passage = " ".join(words[10:86])
        self.assertEqual(len(passage.split()), 76)
        fields = binding_fields(" ".join(words), passage, retrieved_at="x", source_snapshot=None)
        self.assertEqual(fields["passage"], passage)

    def test_exactly_the_cap_accepted_one_over_refused(self):
        words = [f"w{i}" for i in range(200)]
        binding_fields(" ".join(words), " ".join(words[:MAX_PASSAGE_WORDS]), retrieved_at="x", source_snapshot=None)
        with self.assertRaises(ValueError):
            binding_fields(" ".join(words), " ".join(words[:MAX_PASSAGE_WORDS + 1]), retrieved_at="x",
                           source_snapshot=None)

    def test_empty_passage_refused(self):
        with self.assertRaises(ValueError) as ctx:
            binding_fields(SOURCE, "   ", retrieved_at="x", source_snapshot=None)
        self.assertIn("empty", str(ctx.exception))

    def test_fixture_source(self):
        text = (FIX / "sources" / "example-source.md").read_text(encoding="utf-8")
        fields = binding_fields(text, 'the share was "highest in regional towns"', retrieved_at="2026-10-14",
                                source_snapshot="sources/example-source.md")
        self.assertEqual(fields["source_text_sha256"], _sha(normalise_text(text)))


SNAP_TEXT = (FIX / "sources" / "example-source.md").read_text(encoding="utf-8")
PASSAGE = "after-hours bookings made up 41% of all bookings"
EXTRA = "Methodology: an online questionnaire, run in February 2026"


class Recheck(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".plainspoken" / "sources").mkdir(parents=True)
        self.snap_rel = ".plainspoken/sources/survey.md"
        self.write_snapshot(SNAP_TEXT)

    def write_snapshot(self, text: str) -> None:
        (self.root / self.snap_rel).write_text(text, encoding="utf-8")

    def ledger(self, **binding_overrides) -> dict:
        binding = binding_fields(SNAP_TEXT, PASSAGE, retrieved_at="2026-10-14", source_snapshot=self.snap_rel)
        binding.update(same_subject=True, same_geography=True, same_period=True, same_denominator=True,
                       supports_strength=True)
        binding.update(binding_overrides)
        binding = {k: v for k, v in binding.items() if v is not None}
        return {"claims": [{"claim_id": "SHOP-001-C002", "binding": binding}]}

    def only(self, results: list[dict]) -> dict:
        self.assertEqual(len(results), 1, results)
        self.assertEqual(set(results[0]), {"claim_id", "result", "detail"})
        self.assertEqual(results[0]["claim_id"], "SHOP-001-C002")
        self.assertIsInstance(results[0]["detail"], str)
        return results[0]

    def test_ok(self):
        self.assertEqual(self.only(recheck(self.ledger(), self.root))["result"], "ok")

    def test_cosmetic_rerender_still_ok(self):
        self.write_snapshot(SNAP_TEXT.replace("“", '"').replace("”", '"').replace("\n", "\n\n"))
        self.assertEqual(self.only(recheck(self.ledger(), self.root))["result"], "ok")

    def test_one_word_changed_in_the_passage_is_passage_missing(self):
        self.write_snapshot(SNAP_TEXT.replace("made up 41%", "made up 14%"))
        self.assertEqual(self.only(recheck(self.ledger(), self.root))["result"], "passage_missing")

    def test_unrelated_word_changed_is_source_changed(self):
        self.write_snapshot(SNAP_TEXT.replace("412 independent", "413 independent"))
        r = self.only(recheck(self.ledger(), self.root))
        self.assertEqual(r["result"], "source_changed")
        self.assertIn("still found", r["detail"])

    def test_passage_hash_mismatch(self):
        r = self.only(recheck(self.ledger(passage_sha256=_sha("something else")), self.root))
        self.assertEqual(r["result"], "passage_hash_mismatch")

    def test_missing_passage_hash_fails_closed(self):
        ledger = self.ledger()
        del ledger["claims"][0]["binding"]["passage_sha256"]
        self.assertEqual(self.only(recheck(ledger, self.root))["result"], "passage_hash_mismatch")

    def test_no_source_hash_is_ok_with_a_note(self):
        ledger = self.ledger()
        del ledger["claims"][0]["binding"]["source_text_sha256"]
        r = self.only(recheck(ledger, self.root))
        self.assertEqual(r["result"], "ok")
        self.assertIn("source_text_sha256", r["detail"])

    def test_snapshot_file_missing(self):
        (self.root / self.snap_rel).unlink()
        r = self.only(recheck(self.ledger(), self.root))
        self.assertEqual(r["result"], "snapshot_missing")
        self.assertIn(self.snap_rel, r["detail"])

    def test_snapshot_is_a_directory(self):
        r = self.only(recheck(self.ledger(source_snapshot=".plainspoken/sources"), self.root))
        self.assertEqual(r["result"], "snapshot_missing")

    def test_snapshot_not_utf8(self):
        (self.root / self.snap_rel).write_bytes(b"\xff\xfe\x00bad")
        r = self.only(recheck(self.ledger(), self.root))
        self.assertEqual(r["result"], "snapshot_missing")
        self.assertIn("UTF-8", r["detail"])

    def test_unsafe_snapshot_paths_are_not_read(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (outside / "s.md").write_text(SNAP_TEXT, encoding="utf-8")
        for bad in (str(outside / "s.md"), "../" + outside.name + "/s.md", "a\x00b", ""):
            with self.subTest(bad=bad):
                r = self.only(recheck(self.ledger(source_snapshot=bad), self.root))
                self.assertEqual(r["result"], "snapshot_missing")
                self.assertIn("project-relative", r["detail"])

    def test_symlink_escaping_the_project_is_not_followed(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        (outside / "s.md").write_text(SNAP_TEXT, encoding="utf-8")
        (self.root / "link.md").symlink_to(outside / "s.md")
        r = self.only(recheck(self.ledger(source_snapshot="link.md"), self.root))
        self.assertEqual(r["result"], "snapshot_missing")
        self.assertIn("outside the project", r["detail"])

    # a snapshot must live under sources_dir and never be the article (no self-citation).
    def write_outside(self, rel: str) -> None:
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(SNAP_TEXT, encoding="utf-8")

    def test_snapshot_outside_sources_dir(self):
        self.write_outside("notes/src.md")
        r = self.only(recheck(self.ledger(source_snapshot="notes/src.md"), self.root))
        self.assertEqual(r["result"], "snapshot_outside_sources")
        self.assertIn(".plainspoken/sources", r["detail"])

    def test_snapshot_that_is_the_article(self):
        self.write_outside("posts/a.md")
        ledger = self.ledger(source_snapshot="posts/a.md")
        ledger["source_file"] = "posts/a.md"
        r = self.only(recheck(ledger, self.root))
        self.assertEqual(r["result"], "snapshot_outside_sources")
        self.assertIn("article", r["detail"])

    def test_an_article_kept_in_sources_dir_is_still_not_its_own_source(self):
        ledger = self.ledger()
        ledger["source_file"] = self.snap_rel
        r = self.only(recheck(ledger, self.root))
        self.assertEqual(r["result"], "snapshot_outside_sources")
        self.assertIn("article", r["detail"])

    def test_symlink_in_sources_dir_pointing_elsewhere_is_refused(self):
        self.write_outside("notes/src.md")
        (self.root / ".plainspoken" / "sources" / "link.md").symlink_to(self.root / "notes" / "src.md")
        r = self.only(recheck(self.ledger(source_snapshot=".plainspoken/sources/link.md"), self.root))
        self.assertEqual(r["result"], "snapshot_outside_sources")

    def test_custom_sources_dir(self):
        self.write_outside("research/saved/s.md")
        (self.root / ".plainspoken" / "config.toml").write_text('[claims]\nsources_dir = "research/saved"\n',
                                                                encoding="utf-8")
        ok = self.only(recheck(self.ledger(source_snapshot="research/saved/s.md"), self.root))
        self.assertEqual(ok["result"], "ok")
        old = self.only(recheck(self.ledger(), self.root))  # the default folder isn't a source folder any more
        self.assertEqual(old["result"], "snapshot_outside_sources")
        self.assertIn("research/saved", old["detail"])
        explicit = recheck(self.ledger(), self.root, sources_dir=".plainspoken/sources")
        self.assertEqual(self.only(explicit)["result"], "ok")

    def test_a_snapshot_symlink_loop_is_missing_on_every_python(self):  # loops: 3.13 resolve() doesn't raise
        (self.root / ".plainspoken" / "sources" / "loop.md").symlink_to("loop.md")
        r = self.only(recheck(self.ledger(source_snapshot=".plainspoken/sources/loop.md"), self.root))
        self.assertEqual(r["result"], "snapshot_missing")
        self.assertIn("can't be read", r["detail"])

    def test_misconfigured_sources_dir_raises_config_error(self):
        (self.root / ".plainspoken" / "config.toml").write_text('[claims]\nsources_dir = "/abs"\n', encoding="utf-8")
        with self.assertRaises(config.ConfigError):
            recheck(self.ledger(), self.root)

    def test_additional_passages_follow_the_primary_snapshot_rule(self):
        self.write_outside("notes/src.md")
        extra = {"passage": EXTRA, "passage_sha256": _sha(EXTRA)}
        results = recheck(self.ledger(source_snapshot="notes/src.md", additional_passages=[extra]), self.root)
        self.assertEqual([r["result"] for r in results], ["snapshot_outside_sources"] * 2)

    def test_passage_without_snapshot_is_unchecked(self):
        ledger = self.ledger()
        del ledger["claims"][0]["binding"]["source_snapshot"]
        self.assertEqual(self.only(recheck(ledger, self.root))["result"], "unchecked")

    def test_claims_without_a_passage_are_skipped(self):
        ledger = {"claims": [{"claim_id": "A", "status": "first_hand"},
                             {"claim_id": "B", "binding": {"same_subject": True}}]}
        self.assertEqual(recheck(ledger, self.root), [])

    def test_bad_input_never_raises(self):
        for ledger in ({}, {"claims": "nope"}, {"claims": [None, 3, "x"]}, [], None, "text"):
            with self.subTest(ledger=ledger):
                self.assertEqual(recheck(ledger, self.root), [])  # type: ignore[arg-type]

    def test_non_dict_binding_is_unchecked(self):
        r = self.only(recheck({"claims": [{"claim_id": "SHOP-001-C002", "binding": ["x"]}]}, self.root))
        self.assertEqual(r["result"], "unchecked")
        self.assertIn("binding", r["detail"])

    def test_non_text_passage_or_snapshot_is_unchecked_or_missing(self):
        r = self.only(recheck(self.ledger(passage=42), self.root))
        self.assertEqual(r["result"], "unchecked")
        r = self.only(recheck(self.ledger(source_snapshot=["x"]), self.root))
        self.assertEqual(r["result"], "snapshot_missing")

    def test_non_text_claim_id_reported_as_none(self):
        ledger = self.ledger()
        ledger["claims"][0]["claim_id"] = 7
        results = recheck(ledger, self.root)
        self.assertIsNone(results[0]["claim_id"])

    def test_additional_passages_checked_against_the_primary_snapshot(self):
        extra = binding_fields(SNAP_TEXT, EXTRA, retrieved_at="2026-10-14", source_snapshot=None)
        del extra["retrieved_at"]
        ledger = self.ledger(additional_passages=[extra])
        results = recheck(ledger, self.root)
        self.assertEqual([r["result"] for r in results], ["ok", "ok"])
        self.assertIn("additional passage 1", results[1]["detail"])

        self.write_snapshot(SNAP_TEXT.replace("February 2026", "March 2026"))
        results = recheck(ledger, self.root)
        self.assertEqual([r["result"] for r in results], ["source_changed", "passage_missing"])

    def test_additional_passage_hash_mismatch(self):
        extra = {"passage": EXTRA, "passage_sha256": _sha("nope")}
        results = recheck(self.ledger(additional_passages=[extra]), self.root)
        self.assertEqual(results[1]["result"], "passage_hash_mismatch")

    def test_additional_passage_on_another_page_is_unchecked(self):
        extra = {"passage": "a line from another page", "passage_sha256": _sha("a line from another page"),
                 "source_url": "https://example.com/other"}
        results = recheck(self.ledger(additional_passages=[extra]), self.root)
        self.assertEqual(results[1]["result"], "unchecked")
        self.assertIn("source_url", results[1]["detail"])

    def test_additional_passages_with_missing_snapshot(self):
        extra = {"passage": EXTRA, "passage_sha256": _sha(EXTRA)}
        (self.root / self.snap_rel).unlink()
        results = recheck(self.ledger(additional_passages=[extra]), self.root)
        self.assertEqual([r["result"] for r in results], ["snapshot_missing", "snapshot_missing"])

    def test_bad_additional_items_never_raise(self):
        results = recheck(self.ledger(additional_passages=["x", {"passage": None}, 3]), self.root)
        self.assertEqual(results[0]["result"], "ok")
        self.assertEqual([r["result"] for r in results[1:]], ["unchecked"] * 3)

    def test_module_never_imports_network_code(self):  # read the imports with ast, not substrings
        self.assertEqual(_imports("from urllib import request\nimport http.client as h\n__import__('socket')\n"
                                  "importlib.import_module('ssl')\n"), {"urllib", "http", "socket", "ssl"})
        seen, todo, found = set(), ["pinning"], set()
        while todo:  # pinning and every plainspoken module it imports, however deep
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            names = _imports((LIB / f"{name}.py").read_text(encoding="utf-8"))
            found |= {n for n in names if n != "plainspoken"}
            todo += [m for m in names_from_package(LIB / f"{name}.py") if (LIB / f"{m}.py").is_file()]
        self.assertIn("config", seen)
        self.assertEqual(found & NETWORK, set(), seen)


NETWORK = {"urllib", "urllib3", "http", "socket", "ssl", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
           "telnetlib", "xmlrpc", "asyncio", "subprocess", "webbrowser"}
LIB = Path(pinning.__file__).parent


def _imports(src: str) -> set[str]:
    """The top-level module names `src` imports: import / from-import, `__import__(...)` and
    `importlib.import_module(...)` with a literal name."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module.split(".")[0])
        elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)
              and (getattr(node.func, "id", None) == "__import__"
                   or getattr(node.func, "attr", None) == "import_module")):
            out.add(node.args[0].value.split(".")[0])
    return out


def names_from_package(path: Path) -> set[str]:
    """The plainspoken modules `path` imports (`from plainspoken import a, b`, `from plainspoken.x import …`)."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module == "plainspoken":
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("plainspoken."):
            out.add(node.module.split(".")[1])
    return out


class BindingType(unittest.TestCase):
    def test_binding_fields_returns_a_typed_dict(self):  # not a bare dict
        hints = typing.get_type_hints(pinning.binding_fields)
        self.assertIs(hints["return"], pinning.BindingFields)
        self.assertEqual(pinning.BindingFields.__required_keys__,
                         {"passage", "passage_sha256", "source_text_sha256", "retrieved_at"})
        self.assertLessEqual({"source_snapshot", "source_url", "locator"}, pinning.BindingFields.__optional_keys__)
        fields = binding_fields("The source says 41% of all bookings.", "41% of all bookings",
                                retrieved_at="2026-10-19", source_snapshot=None)
        self.assertEqual(set(fields), pinning.BindingFields.__required_keys__)


if __name__ == "__main__":
    unittest.main()
