import contextlib
import hashlib
import hmac
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.dev import leak_guard as lg

# Invented terms only: the real private list lives outside the repo and never appears in a test.
NS = "acme"
DASHED = NS + "-"
OFFER = "Example Starter Offer"
SCOUT = "Kestrel"
HANDLE = "acme-owner"
FAKE_ID = "0123456789abcdef" + "01234567"  # assembled, so the generic 24-hex pattern skips this file
SHA40 = "0123456789abcdef" * 2 + "01234567"


class LeakGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "data" / "leak-denylist.txt").write_text(
            f"# comment\n{DASHED}\n{OFFER}\nregex:\\b{SCOUT}\\b\n", encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def _main(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = lg.main(str(self.root), env={})
        return code, buf.getvalue()

    def test_clean_tree_passes(self):
        self._write("skills/a/SKILL.md", "plain words only\n")
        self.assertEqual(self._main()[0], 0)

    def test_literal_hit_fails_case_insensitive(self):
        self._write("README.md", f"see {DASHED.upper()}core for more\n")
        self.assertEqual(self._main()[0], 1)

    def test_regex_is_case_sensitive(self):
        self._write("a.md", f"a {SCOUT.lower()} troop\n")
        self.assertEqual(self._main()[0], 0)
        self._write("b.md", f"ask {SCOUT} about it\n")
        self.assertEqual(self._main()[0], 1)

    def test_allowlisted_paths_skipped(self):
        self._write("tests/fixtures/leak/sample.md", f"{OFFER}\n")
        self._write(".github/CODEOWNERS", f"* @{HANDLE}\n")
        self._write("README.md", "plain words only\n")
        self.assertEqual(self._main()[0], 0)

    def test_inline_allow_marker_suppresses_and_is_audited(self):
        self._write("a.md", f"{DASHED} example <!-- leak-guard: allow -->\n")
        code, out = self._main()
        self.assertEqual(code, 0)
        self.assertIn("a.md:1: suppressed by leak-guard: allow", out)
        self.assertIn("1 suppressed", out)

    def test_binary_file_skipped(self):
        p = self.root / "assets" / "x.png"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe " + DASHED.encode() + b" \x00")
        self.assertEqual(self._main()[0], 0)

    def test_non_utf8_text_file_is_scanned(self):
        p = self.root / "latin.txt"
        p.write_bytes(f"caf\xe9 {DASHED} here\n".encode("latin-1"))
        self.assertEqual(self._main()[0], 1)

    def test_git_skipped(self):
        self._write(".git/config", f"{DASHED}\n")
        self._write("README.md", "plain words only\n")
        self.assertEqual(self._main()[0], 0)

    def test_docs_are_scanned(self):  # the public release dropped the docs allow-list (provenance, plans)
        for rel in ("docs/provenance.md", "docs/plans/p.md", "vendor-intake/x.md"):
            with self.subTest(rel=rel):
                self._write(rel, f"{DASHED} mention\n")
                hits, _ = lg.scan(str(self.root), lg.load_terms(str(self.root)))
                self.assertIn(rel, [h.path for h in hits])

    def test_hit_reports_path_and_line(self):
        self._write("x/y.md", f"ok\n{OFFER} here\n")
        hits, _ = lg.scan(str(self.root), lg.load_terms(str(self.root)))
        self.assertEqual([(h.path, h.line) for h in hits], [("x/y.md", 2)])

    def test_multiword_term_split_across_lines_is_caught(self):
        self._write("x.md", "ok\nExample Starter\nOffer here\n")
        hits, _ = lg.scan(str(self.root), lg.load_terms(str(self.root)))
        self.assertEqual([(h.path, h.line) for h in hits], [("x.md", 2)])

    def test_allow_marker_on_start_line_suppresses_wrapped_match(self):
        self._write("x.md", "Example Starter <!-- leak-guard: allow -->\nOffer here\n")
        self.assertEqual(self._main()[0], 0)

    def test_file_name_is_checked(self):
        self._write(f"{DASHED}thing.md", "clean content\n")
        hits, _ = lg.scan(str(self.root), lg.load_terms(str(self.root)))
        self.assertEqual([(h.path, h.line) for h in hits], [(f"{DASHED}thing.md", 0)])

    def test_non_allowlisted_test_file_scanned(self):
        self._write("tests/test_other.py", f"{DASHED} in non-allowlisted test file\n")
        hits, _ = lg.scan(str(self.root), lg.load_terms(str(self.root)))
        self.assertEqual([h.path for h in hits], ["tests/test_other.py"])

    def test_leak_guard_test_file_is_not_allowlisted(self):
        self.assertNotIn("tests/test_leak_guard.py", lg.ALLOW_PATHS)


def _hashed(term: str) -> str:
    norm = " ".join(term.casefold().split())
    return f"sha256:{len(norm.split())}:{hashlib.sha256(norm.encode('utf-8')).hexdigest()}"


# Invented names only: the shipped denylist's private names never appear in this file.
BIZ = "Bluegum Widgets"
PERSON = "Jo Example"
DOMAIN = "bluegum.example.au"
KEY = "test-key-not-a-secret"


class HashedTermTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "data" / "leak-denylist.txt").write_text(
            f"# comment\n{_hashed(BIZ)}\n{_hashed(PERSON)}\n{_hashed(DOMAIN)}\n", encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def _hits(self) -> list[tuple[str, int]]:
        hits, _ = lg.scan(str(self.root), lg.load_terms(str(self.root)))
        return [(h.path, h.line) for h in hits]

    def _main(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = lg.main(str(self.root), env={})
        return code, buf.getvalue()

    def test_hash_line_normalises_case_and_whitespace(self):
        self.assertEqual(lg.hash_line(BIZ), _hashed(BIZ))
        self.assertEqual(lg.hash_line("  BLUEGUM \t  widgets \n"), _hashed(BIZ))

    def test_multiword_name_caught_case_insensitive_with_punctuation(self):
        self._write("a.md", "ok\nThanks to bluegum WIDGETS, again.\n")
        self.assertEqual(self._hits(), [("a.md", 2)])

    def test_name_split_across_lines_reports_start_line(self):
        self._write("a.md", "ok\nsee Bluegum\nWidgets here\n")
        self.assertEqual(self._hits(), [("a.md", 2)])

    def test_partial_or_embedded_name_not_caught(self):
        self._write("a.md", "Bluegum alone, Widgets alone, and Bluegumwidgets.\n")
        self.assertEqual(self._hits(), [])

    def test_trailing_full_stop_and_possessive(self):
        self._write("a.md", "I met Jo Example.\n")
        self._write("b.md", "Jo Example's notes\n")
        self.assertEqual(self._hits(), [("a.md", 1), ("b.md", 1)])

    def test_domain_caught_inside_url(self):
        self._write("a.md", "https://www.bluegum.example.au/about and sub.bluegum.example.au\n")
        self.assertEqual(self._hits(), [("a.md", 1), ("a.md", 1)])

    def test_file_path_checked(self):
        self._write("clients/bluegum_widgets.md", "clean\n")
        self._write("notes/jo-example-call.md", "clean\n")
        self.assertEqual(self._hits(), [("clients/bluegum_widgets.md", 0), ("notes/jo-example-call.md", 0)])

    def test_label_never_reveals_the_name(self):
        self._write("a.md", "Bluegum Widgets\n")
        code, out = self._main()
        self.assertEqual(code, 1)
        digest = _hashed(BIZ).rsplit(":", 1)[1]
        self.assertIn(f"a.md:1: denylisted term 'sha256:{digest[:12]}'", out)
        self.assertNotIn("bluegum", out.casefold())

    def test_allow_marker_suppresses_hashed_hit(self):
        self._write("a.md", "ok Bluegum Widgets <!-- leak-guard: allow -->\n")
        code, out = self._main()
        self.assertEqual(code, 0)
        self.assertIn("a.md:1: suppressed by leak-guard: allow", out)

    def test_malformed_hashed_line_rejected(self):
        (self.root / "data" / "leak-denylist.txt").write_text("sha256:2:nothex\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            lg.load_terms(str(self.root))


class HashCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.list = Path(self.tmp.name) / "data" / "leak-denylist.txt"
        self.list.parent.mkdir()
        self.list.write_text(f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n", encoding="utf-8")

    def test_hash_needs_the_key_check_line(self):
        """Review fix 1: --hash never writes a keyed line under an unverified key."""
        self.list.write_text("# no check line\n", encoding="utf-8")
        code, out = self._cli(["--hash", PERSON])
        self.assertEqual(code, 2)
        self.assertIn("hmac-key-check", out)
        self.list.unlink()
        self.assertEqual(self._cli(["--hash", PERSON])[0], 2)

    def test_key_check_needs_no_list(self):
        self.list.unlink()
        self.assertEqual(self._cli(["--key-check"])[0], 0)

    def _cli(self, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = lg.cli(argv, env={"PLAINSPOKEN_LEAK_KEY": KEY}, key_root=self.tmp.name)
        return code, buf.getvalue()

    def test_hash_prints_only_the_keyed_line(self):
        self.assertEqual(self._cli(["--hash", PERSON]), (0, _keyed(PERSON) + "\n"))

    def test_hash_without_a_key_refuses(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = lg.cli(["--hash", PERSON], env={}, key_root=self.tmp.name)
        self.assertEqual(code, 2)
        self.assertIn("no key", buf.getvalue())
        self.assertNotIn("sha256:", buf.getvalue())

    def test_key_check_prints_the_check_line(self):
        self.assertEqual(self._cli(["--key-check"]), (0, f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n"))

    def test_help_prints_usage_without_a_traceback(self):
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                code, out = self._cli([flag])
                self.assertEqual(code, 0)
                self.assertIn("usage:", out)
                self.assertIn("--hash", out)

    def test_unknown_option_exits_2(self):
        code, out = self._cli(["--nope"])
        self.assertEqual(code, 2)
        self.assertIn("usage:", out)

    def test_missing_root_exits_2(self):
        code, out = self._cli(["/nonexistent/plainspoken-root"])
        self.assertEqual(code, 2)
        self.assertIn("FAILED", out)

    def test_hash_without_term_exits_2(self):
        code, out = self._cli(["--hash"])
        self.assertEqual(code, 2)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertTrue(out.startswith("leak-guard:"))

    def test_hash_rejects_term_the_scanner_cannot_match(self):
        code, out = self._cli(["--hash", "Bluegum, Widgets"])
        self.assertEqual(code, 2)
        self.assertNotIn("bluegum", out.casefold())


class StdinTermTests(unittest.TestCase):
    """`-` reads the term from stdin, so a name stays out of shell history and `ps`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        self.list = self.root / "data" / "leak-denylist.txt"
        self.check = f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n"
        self.list.write_text(f"{self.check}{_hashed(BIZ)}\n", encoding="utf-8")

    def _cli(self, argv: list[str], stdin: io.StringIO) -> tuple[int, str]:
        from unittest import mock
        buf = io.StringIO()
        with mock.patch("sys.stdin", stdin), contextlib.redirect_stdout(buf), \
                contextlib.redirect_stderr(buf):
            code = lg.cli(argv, env={"PLAINSPOKEN_LEAK_KEY": KEY}, key_root=str(self.root))
        return code, buf.getvalue()

    def test_hash_reads_a_piped_term(self):
        code, out = self._cli(["--hash", "-"], io.StringIO(PERSON + "\n"))
        self.assertEqual((code, out), (0, _keyed(PERSON) + "\n"))

    def test_convert_reads_a_piped_term(self):
        code, out = self._cli(["--convert", "-"], io.StringIO(BIZ + "\n"))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.list.read_text(), f"{self.check}{_keyed(BIZ)}\n")
        self.assertNotIn("bluegum", out.casefold())

    def test_a_terminal_reads_without_echo(self):
        from unittest import mock
        tty = io.StringIO()
        tty.isatty = lambda: True
        with mock.patch.object(lg.getpass, "getpass", return_value=BIZ) as gp:
            code, out = self._cli(["--convert", "-"], tty)
        gp.assert_called_once()
        self.assertEqual(code, 0, out)
        self.assertNotIn("bluegum", out.casefold())
        self.assertEqual(self.list.read_text(), f"{self.check}{_keyed(BIZ)}\n")

    def test_empty_stdin_exits_2(self):
        code, out = self._cli(["--hash", "-"], io.StringIO(""))
        self.assertEqual(code, 2)
        self.assertTrue(out.startswith("leak-guard:"))

    def test_help_documents_stdin(self):
        code, out = self._cli(["--help"], io.StringIO(""))
        self.assertIn("-", out)
        self.assertIn("stdin", out)


REPO = Path(__file__).resolve().parent.parent
# Read before setUpModule hides it, so only PrivateListShapeTests sees the owner's private list.
PRIVATE_LIST = os.environ.get(lg.LIST_ENV, "").strip()
_ENV = mock.patch.dict(os.environ)


def setUpModule():
    _ENV.start()
    os.environ.pop(lg.LIST_ENV, None)


def tearDownModule():
    _ENV.stop()


class ShippedDenylistTests(unittest.TestCase):
    """The tracked list keeps format comments and generic patterns only; names live in the private list."""

    def setUp(self):
        self.terms = lg.load_terms(str(REPO), env={})

    def _hits(self, text: str) -> bool:
        return any(t.pattern.search(text) for t in self.terms if isinstance(t, lg.Term))

    def test_shipped_list_names_nothing(self):
        lines = (REPO / "data" / "leak-denylist.txt").read_text(encoding="utf-8").splitlines()
        entries = [s for s in (line.strip() for line in lines) if s and not s.startswith("#")]
        self.assertGreater(len(entries), 0)
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertTrue(entry.startswith("regex:"), "only generic regex: lines may be tracked")
        self.assertFalse(any(isinstance(t, lg.HashedTerm) for t in self.terms))
        self.assertIsNone(lg.load_denylist(str(REPO), env={}).key_check)

    def test_object_id_matches_but_git_sha_does_not(self):
        self.assertTrue(self._hits("card " + FAKE_ID))
        self.assertFalse(self._hits("sha " + SHA40))

    def test_ci_passes_the_key_to_the_guard(self):
        ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("PLAINSPOKEN_LEAK_KEY: ${{ secrets.PLAINSPOKEN_LEAK_KEY }}", ci)

    def test_ci_writes_the_private_list_to_runner_temp(self):
        ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("${{ secrets.PLAINSPOKEN_LEAK_LIST }}", ci)
        self.assertIn('"$RUNNER_TEMP/leak-list.txt"', ci)
        self.assertIn('export PLAINSPOKEN_LEAK_LIST="$RUNNER_TEMP/leak-list.txt"', ci)

    def test_key_file_is_git_ignored(self):
        ignore = (REPO / ".gitignore").read_text().splitlines()
        self.assertIn(lg.KEY_FILE, ignore)


@unittest.skipUnless(PRIVATE_LIST, "no private list configured")
class PrivateListShapeTests(unittest.TestCase):
    """Runs only where the owner's private list is configured; asserts its shape, never its content."""

    def test_private_list_loads_and_is_well_formed(self):
        deny = lg.load_denylist(str(REPO), env={lg.LIST_ENV: PRIVATE_LIST})
        self.assertIsNone(deny.private_missing)
        private = [t for t in deny.terms if t.origin == "private"]
        self.assertGreater(len(private), 0)
        for t in private:
            self.assertRegex(t.label, r"^private#[1-9][0-9]*$")
            if isinstance(t, lg.HashedTerm):
                self.assertGreaterEqual(t.words, 1)
                self.assertRegex(t.digest, r"^[0-9a-f]{64}$")


# Invented private-list entries, kept in a temporary file outside the temporary repo.
PRIVATE_NAME = "Wattle Creek Plumbing"


class ExternalListTests(unittest.TestCase):
    """The private list lives outside the repo (PLAINSPOKEN_LEAK_LIST); a hit names its line, never the term."""

    CI = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": lg.OWNER_REPO, "GITHUB_EVENT_NAME": "push"}
    FORK = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "someone/plainspoken", "GITHUB_EVENT_NAME": "push"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        (self.root / "data").mkdir(parents=True)
        self._repo_list(f"# comment\n{DASHED}\n")
        self._write("README.md", "plain words only\n")
        self.private = Path(self.tmp.name) / "private-list.txt"
        self._private(f"# private names\n{PRIVATE_NAME}\nregex:\\b{SCOUT}\\b\n{_hashed(BIZ)}\n")
        self.env = {lg.LIST_ENV: str(self.private)}

    def _repo_list(self, text: str) -> None:
        (self.root / "data" / "leak-denylist.txt").write_text(text, encoding="utf-8")

    def _private(self, text: str) -> None:
        self.private.write_text(text, encoding="utf-8")

    def _write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def _main(self, env: dict[str, str]) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = lg.main(str(self.root), env=env)
        return code, buf.getvalue()

    def test_external_list_hit_is_labelled_by_index(self):
        self._write("a.md", f"ok\nthanks to {PRIVATE_NAME.upper()}\n")
        self._write("b.md", f"ask {SCOUT} about it\n")
        self._write("c.md", "Bluegum Widgets\n")
        self._write(f"notes/{SCOUT}.md", "clean\n")
        self._write("d.md", f"{DASHED}core\n")
        code, out = self._main(self.env)
        self.assertEqual(code, 1)
        self.assertIn("a.md:2: denylisted term 'private#2'", out)
        self.assertIn("b.md:1: denylisted term 'private#3'", out)
        self.assertIn("c.md:1: denylisted term 'private#4'", out)
        self.assertIn(f"notes/{SCOUT}.md:0: denylisted term 'private#3'", out)
        self.assertIn(f"d.md:1: denylisted term '{DASHED}'", out)  # repo-list entries keep their labels
        for word in ("wattle", "plumbing", "bluegum", "sha256:", "regex:"):
            self.assertNotIn(word, out.casefold())
        private = [t for t in lg.load_terms(str(self.root), env=self.env) if t.origin == "private"]
        self.assertEqual([(t.index, t.label) for t in private],
                         [(2, "private#2"), (3, "private#3"), (4, "private#4")])

    def test_owner_repo_without_private_list_fails(self):
        (empty := Path(self.tmp.name) / "empty.txt").write_text("\n", encoding="utf-8")
        missing = Path(self.tmp.name) / "missing.txt"
        (comments := Path(self.tmp.name) / "comments-only.txt").write_text("# names go here\n\n", encoding="utf-8")
        for extra in ({}, {lg.LIST_ENV: ""}, {lg.LIST_ENV: str(missing)}, {lg.LIST_ENV: str(empty)},
                      {lg.LIST_ENV: str(comments)}):
            with self.subTest(extra=extra):
                code, out = self._main({**self.CI, **extra})
                self.assertEqual(code, 1)
                self.assertIn("private leak list not configured", out)
                self.assertNotIn("SKIPPED", out)
                self.assertNotRegex(out, r"(?m)^leak-guard: 0 hit")
                self.assertNotIn(str(self.tmp.name), out)
        self.assertEqual(self._main({**self.CI, **self.env})[0], 0)

    def test_fork_without_private_list_skips_with_notice(self):
        for env, why in ((self.FORK, "fork"), ({}, "local run")):
            with self.subTest(why=why):
                code, out = self._main(env)
                self.assertEqual(code, 0)
                notices = [line for line in out.splitlines() if "private leak list" in line]
                self.assertEqual(len(notices), 1, out)
                self.assertIn("SKIPPED (no private list)", notices[0])
                self.assertIn(why, notices[0])
                self.assertNotRegex(out, r"(?m)^leak-guard: 0 hit")
        self._write("d.md", f"{DASHED}core\n")
        self.assertEqual(self._main(self.FORK)[0], 1)

    def test_hmac_key_needed_only_with_hmac_entries(self):
        check = f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n"
        code, out = self._main({**self.CI, **self.env})
        self.assertEqual(code, 0, out)
        self.assertNotIn("no key", out)
        for where in ("private", "repo"):
            with self.subTest(hmac_in=where):
                if where == "private":
                    self._private(f"{check}{PRIVATE_NAME}\n{_keyed(BIZ)}\n")
                else:
                    self._repo_list(f"{check}{_keyed(BIZ)}\n")
                    self._private(f"{PRIVATE_NAME}\n")
                code, out = self._main({**self.CI, **self.env})
                self.assertEqual(code, 1)
                self.assertIn("FAILED (no key)", out)
                code, out = self._main({**self.CI, **self.env, "PLAINSPOKEN_LEAK_KEY": KEY})
                self.assertEqual(code, 0, out)

    def test_key_check_in_the_private_list_verifies_the_key(self):
        self._private(f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n{_keyed(BIZ)}\n")
        self._write("a.md", "Bluegum Widgets\n")
        code, out = self._main({**self.env, "PLAINSPOKEN_LEAK_KEY": KEY})
        self.assertEqual(code, 1)
        self.assertIn("a.md:1: denylisted term 'private#2'", out)
        code, out = self._main({**self.env, "PLAINSPOKEN_LEAK_KEY": "wrong-key"})
        self.assertEqual(code, 2)
        self.assertIn("key check", out)

    def test_different_key_check_lines_fail(self):
        self._repo_list(f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n")
        self._private(f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT, 'other-key')}\n{PRIVATE_NAME}\n")
        code, out = self._main({**self.env, "PLAINSPOKEN_LEAK_KEY": KEY})
        self.assertEqual(code, 2)
        self.assertIn("hmac-key-check", out)

    def test_private_list_errors_never_quote_the_line(self):
        for bad in ("regex:(Wattle\n", "hmac:2:wattle\n", "regex:(?P=wattle)\n", "regex:(?P<wattle x>a)\n"):
            with self.subTest(bad=bad):
                self._private(f"# names\n{bad}")
                code, out = self._main(self.env)
                self.assertEqual(code, 2)
                self.assertIn("private list:2", out)
                self.assertNotIn("wattle", out.casefold())

    def test_convert_error_never_prints_the_private_path(self):
        self._private(f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n{_hashed(BIZ)}\n")
        denied = PermissionError(13, "Permission denied", str(self.private))
        buf = io.StringIO()
        with mock.patch.object(lg.Path, "write_text", side_effect=denied), contextlib.redirect_stdout(buf):
            code = lg.cli(["--convert", BIZ], env={**self.env, "PLAINSPOKEN_LEAK_KEY": KEY}, key_root=str(self.root))
        self.assertEqual(code, 2)
        self.assertIn("PermissionError", buf.getvalue())
        self.assertNotIn(str(self.tmp.name), buf.getvalue())

    def test_convert_rewrites_the_entry_in_the_private_list(self):
        check = f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n"
        self._private(f"{check}{_hashed(BIZ)}\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = lg.cli(["--convert", BIZ], env={**self.env, "PLAINSPOKEN_LEAK_KEY": KEY}, key_root=str(self.root))
        self.assertEqual(code, 0, buf.getvalue())
        self.assertEqual(self.private.read_text(encoding="utf-8"), f"{check}{_keyed(BIZ)}\n")
        self.assertIn("private list line 2", buf.getvalue())
        self.assertNotIn(str(self.private), buf.getvalue())


class ProvenanceTests(unittest.TestCase):
    """The public provenance note is scanned like any other file and names no local path or source repo."""

    def test_provenance_is_not_allowlisted(self):
        self.assertNotIn("docs/provenance.md", lg.ALLOW_PATHS)
        self.assertFalse("docs/provenance.md".startswith(lg.ALLOW_PREFIXES))

    def test_no_home_directory_paths_or_repo_pointers(self):
        text = (Path(__file__).resolve().parents[1] / "docs" / "provenance.md").read_text(encoding="utf-8")
        self.assertNotIn("/" + "home/", text)
        self.assertNotRegex(text, r"\w@[0-9a-f]{7,}:")  # repo@sha:path intake records


def _mac(text: str, key: str = KEY) -> str:
    return hmac.new(key.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()


def _keyed(term: str) -> str:
    norm = " ".join(term.casefold().split())
    return f"hmac:{len(norm.split())}:{_mac(norm)}"


class KeyedHashTests(unittest.TestCase):
    """Keyed entries, and the guard is never green when it couldn't check."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        self._list(f"# comment\nhmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n{_keyed(BIZ)}\n{DASHED}\n")
        self._write("README.md", "plain words only\n")  # the guard scans something, or it fails as empty

    def tearDown(self):
        self.tmp.cleanup()

    def _list(self, text: str) -> None:
        (self.root / "data" / "leak-denylist.txt").write_text(text, encoding="utf-8")

    def _write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def _main(self, env: dict[str, str]) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = lg.main(str(self.root), env=env)
        return code, buf.getvalue()

    def test_hmac_entry_matches(self):
        self._write("a.md", "ok\nThanks to bluegum WIDGETS, again.\n")
        code, out = self._main({"PLAINSPOKEN_LEAK_KEY": KEY})
        self.assertEqual(code, 1)
        self.assertIn(f"a.md:2: denylisted term 'hmac:{_keyed(BIZ).rsplit(':', 1)[1][:12]}'", out)
        self.assertNotIn("bluegum", out.casefold())

    def test_keyed_entries_without_a_key_check_line_fail_under_any_key(self):
        """Review fix 1: without the check line a wrong key would match nothing and report green."""
        self._list(f"{_keyed(BIZ)}\n")
        self._write("a.md", "Bluegum Widgets\n")
        for key in ("some-other-key", KEY):
            with self.subTest(key=key):
                code, out = self._main({"PLAINSPOKEN_LEAK_KEY": key})
                self.assertEqual(code, 2)
                self.assertIn("hmac-key-check", out)
                self.assertNotRegex(out, r"(?m)^leak-guard: 0 hit")

    def test_unkeyed_list_needs_no_key_check_line(self):
        self._list(f"{DASHED}\n")
        self.assertEqual(self._main({"PLAINSPOKEN_LEAK_KEY": KEY})[0], 0)

    def test_key_from_the_untracked_file(self):
        (self.root / ".leak-guard-key").write_text(KEY + "\n", encoding="utf-8")
        self._write("a.md", "Bluegum Widgets\n")
        self.assertEqual(self._main({})[0], 1)

    def test_environment_key_wins_over_the_file(self):
        (self.root / ".leak-guard-key").write_text("wrong-key\n", encoding="utf-8")
        self._write("a.md", "Bluegum Widgets\n")
        self.assertEqual(self._main({"PLAINSPOKEN_LEAK_KEY": KEY})[0], 1)

    def test_no_key_reports_skipped_not_green(self):
        self._write("a.md", "Bluegum Widgets\n")
        for env in ({}, {"PLAINSPOKEN_LEAK_KEY": ""}, {"PLAINSPOKEN_LEAK_KEY": "  "}):
            with self.subTest(env=env):
                code, out = self._main(env)
                self.assertEqual(code, 0)
                last = out.splitlines()[-1]
                self.assertIn("SKIPPED (no key)", last)
                self.assertIn("1 keyed entry not checked", last)
                self.assertNotRegex(out, r"(?m)^leak-guard: 0 hit")

    def test_no_key_still_checks_the_unkeyed_entries(self):
        self._write("a.md", f"{DASHED}core\n")
        code, out = self._main({})
        self.assertEqual(code, 1)
        self.assertIn("SKIPPED (no key)", out)

    def test_ci_without_key_fails(self):
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": lg.OWNER_REPO, "GITHUB_EVENT_NAME": "push"}
        for extra in ({}, {"PLAINSPOKEN_LEAK_KEY": ""}):
            with self.subTest(extra=extra):
                code, out = self._main({**env, **extra})
                self.assertEqual(code, 1)
                self.assertIn("FAILED (no key)", out)
                self.assertNotIn("SKIPPED", out)

    def test_ci_with_key_runs(self):
        private = Path(self.tmp.name) / "private-list.txt"
        private.write_text("# no entries yet\nregex:\\bNothingHere\\b\n", encoding="utf-8")
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": lg.OWNER_REPO, "PLAINSPOKEN_LEAK_KEY": KEY,
               lg.LIST_ENV: str(private)}
        code, out = self._main(env)
        self.assertEqual(code, 0)
        self.assertNotIn("SKIPPED", out)

    def test_ci_on_a_fork_skips_with_a_log_line(self):
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "someone/plainspoken", "GITHUB_EVENT_NAME": "push"}
        code, out = self._main(env)
        self.assertEqual(code, 0)
        self.assertIn("SKIPPED (no key)", out)
        self.assertIn("fork", out)

    def test_ci_pull_request_from_a_fork_skips(self):
        event = self.root / "event.json"
        event.write_text(json.dumps({"pull_request": {"head": {"repo": {"full_name": "someone/plainspoken"}}}}))
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": lg.OWNER_REPO, "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_EVENT_PATH": str(event)}
        code, out = self._main(env)
        self.assertEqual(code, 0)
        self.assertIn("SKIPPED (no key)", out)
        self.assertIn("pull request from a fork", out)

    def test_ci_pull_request_from_this_repo_fails_without_key(self):
        event = self.root / "event.json"
        event.write_text(json.dumps({"pull_request": {"head": {"repo": {"full_name": lg.OWNER_REPO}}}}))
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": lg.OWNER_REPO, "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_EVENT_PATH": str(event)}
        self.assertEqual(self._main(env)[0], 1)

    def test_ci_pull_request_with_an_unreadable_event_fails_closed(self):
        env = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": lg.OWNER_REPO, "GITHUB_EVENT_NAME": "pull_request",
               "GITHUB_EVENT_PATH": str(self.root / "missing.json")}
        self.assertEqual(self._main(env)[0], 1)

    def test_wrong_key_fails_the_key_check(self):
        code, out = self._main({"PLAINSPOKEN_LEAK_KEY": "wrong-key"})
        self.assertEqual(code, 2)
        self.assertIn("FAILED", out)
        self.assertIn("key check", out)

    def test_empty_key_file_fails(self):
        (self.root / ".leak-guard-key").write_text("\n", encoding="utf-8")
        code, out = self._main({})
        self.assertEqual(code, 2)
        self.assertIn("FAILED", out)

    def test_unreadable_denylist_fails(self):
        (self.root / "data" / "leak-denylist.txt").unlink()
        code, out = self._main({"PLAINSPOKEN_LEAK_KEY": KEY})
        self.assertEqual(code, 2)
        self.assertIn("FAILED", out)
        self.assertNotRegex(out, r"(?m)^leak-guard: 0 hit")

    def test_malformed_keyed_line_fails(self):
        self._list("hmac:2:nothex\n")
        code, out = self._main({"PLAINSPOKEN_LEAK_KEY": KEY})
        self.assertEqual(code, 2)
        self.assertIn("malformed", out)

    @unittest.skipIf(os.geteuid() == 0, "root reads any file")
    def test_unreadable_file_fails(self):
        self._write("a.md", "fine\n")
        (self.root / "a.md").chmod(0)
        try:
            code, out = self._main({"PLAINSPOKEN_LEAK_KEY": KEY})
        finally:
            (self.root / "a.md").chmod(0o600)
        self.assertEqual(code, 2)
        self.assertIn("FAILED", out)

    def test_key_never_printed(self):
        self._write("a.md", "Bluegum Widgets\n")
        for env in ({"PLAINSPOKEN_LEAK_KEY": KEY}, {"PLAINSPOKEN_LEAK_KEY": "wrong-key"}):
            with self.subTest(env=env):
                _, out = self._main(env)
                self.assertNotIn(env["PLAINSPOKEN_LEAK_KEY"], out)


class ConvertTests(unittest.TestCase):
    """An unkeyed sha256 entry becomes keyed when the owner supplies its name."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        self.list = self.root / "data" / "leak-denylist.txt"
        self.check = f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n"
        self.list.write_text(f"{self.check}{_hashed(BIZ)}\n{_hashed(PERSON)}\n", encoding="utf-8")

    def _cli(self, argv: list[str], env: dict[str, str]) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = lg.cli(argv, env=env, key_root=str(self.root))
        return code, buf.getvalue()

    def test_convert_replaces_the_matching_line_in_place(self):
        code, out = self._cli(["--convert", "  bluegum WIDGETS "], {"PLAINSPOKEN_LEAK_KEY": KEY})
        self.assertEqual(code, 0)
        self.assertEqual(self.list.read_text(), f"{self.check}{_keyed(BIZ)}\n{_hashed(PERSON)}\n")
        self.assertIn("line 2", out)
        self.assertNotIn("bluegum", out.casefold())

    def test_convert_without_a_match_changes_nothing(self):
        before = self.list.read_text()
        code, out = self._cli(["--convert", "Someone Else"], {"PLAINSPOKEN_LEAK_KEY": KEY})
        self.assertEqual(code, 1)
        self.assertEqual(self.list.read_text(), before)
        self.assertNotIn("someone", out.casefold())

    def test_convert_needs_the_key_check_line(self):
        self.list.write_text(f"{_hashed(BIZ)}\n", encoding="utf-8")
        code, out = self._cli(["--convert", BIZ], {"PLAINSPOKEN_LEAK_KEY": KEY})
        self.assertEqual(code, 2)
        self.assertEqual(self.list.read_text(), f"{_hashed(BIZ)}\n")

    def test_convert_needs_the_key(self):
        before = self.list.read_text()
        self.assertEqual(self._cli(["--convert", BIZ], {})[0], 2)
        self.assertEqual(self.list.read_text(), before)

    def test_hash_refuses_a_wrong_key_but_key_check_prints_for_rotation(self):
        self.list.write_text(f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n", encoding="utf-8")
        self.assertEqual(self._cli(["--hash", BIZ], {"PLAINSPOKEN_LEAK_KEY": "new-key"})[0], 2)
        code, out = self._cli(["--key-check"], {"PLAINSPOKEN_LEAK_KEY": "new-key"})
        self.assertEqual((code, out), (0, f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT, 'new-key')}\n"))

    def test_convert_refuses_a_wrong_key(self):
        self.list.write_text(f"hmac-key-check:{_mac(lg.KEY_CHECK_TEXT)}\n{_hashed(BIZ)}\n", encoding="utf-8")
        before = self.list.read_text()
        self.assertEqual(self._cli(["--convert", BIZ], {"PLAINSPOKEN_LEAK_KEY": "wrong"})[0], 2)
        self.assertEqual(self.list.read_text(), before)


@unittest.skipIf(shutil.which("git") is None, "git not installed")
class GitIgnoredTests(unittest.TestCase):
    """Git-ignored local output (eval results, history) isn't scanned."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "data").mkdir()
        (self.root / "data" / "leak-denylist.txt").write_text(f"{DASHED}\n", encoding="utf-8")
        (self.root / ".gitignore").write_text("results/\n*.log\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def _hits(self) -> list[str]:
        hits, _ = lg.scan(str(self.root), lg.load_terms(str(self.root)))
        return [h.path for h in hits]

    def test_ignored_files_are_skipped(self):
        self._write("results/run.json", f"{DASHED}x\n")
        self._write("debug.log", f"{DASHED}x\n")
        self.assertEqual(self._hits(), [])

    def test_untracked_and_tracked_files_are_scanned(self):
        self._write("new.md", f"{DASHED}x\n")
        self._write("kept.md", f"{DASHED}x\n")
        subprocess.run(["git", "-C", str(self.root), "add", "kept.md"], check=True)
        self.assertEqual(self._hits(), ["kept.md", "new.md"])

    def test_tracked_file_under_an_ignored_folder_is_scanned(self):
        self._write("results/keep.md", f"{DASHED}x\n")
        subprocess.run(["git", "-C", str(self.root), "add", "-f", "results/keep.md"], check=True)
        self.assertEqual(self._hits(), ["results/keep.md"])

    def test_folder_an_enclosing_repo_ignores_is_still_scanned(self):
        """Review fix 2: git's list is used only when ROOT is the top of its work tree."""
        (self.root / ".gitignore").write_text("inner/\n", encoding="utf-8")
        inner = self.root / "inner"
        (inner / "data").mkdir(parents=True)
        (inner / "data" / "leak-denylist.txt").write_text(f"{DASHED}\n", encoding="utf-8")
        (inner / "a.md").write_text(f"{DASHED}x\n", encoding="utf-8")
        hits, _ = lg.scan(str(inner), lg.load_terms(str(inner)))
        self.assertEqual([h.path for h in hits], ["a.md"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(lg.main(str(inner), env={}), 1)

    def test_subfolder_of_a_repo_is_scanned_whole(self):
        sub = self.root / "sub"
        (sub / "data").mkdir(parents=True)
        (sub / "data" / "leak-denylist.txt").write_text(f"{DASHED}\n", encoding="utf-8")
        (sub / "a.md").write_text(f"{DASHED}x\n", encoding="utf-8")
        hits, _ = lg.scan(str(sub), lg.load_terms(str(sub)))
        self.assertEqual([h.path for h in hits], ["a.md"])

    def test_empty_scan_set_fails(self):
        """Review fix 2: zero files scanned is never green."""
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        with self.assertRaises(lg.GuardError):
            lg.scan(str(empty), [])

    def test_only_allow_listed_files_fails(self):
        """The emptiness check comes after the allow-list, so a root it empties is never green."""
        only = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, only, ignore_errors=True)
        (only / "data").mkdir()
        (only / "data" / "leak-denylist.txt").write_text(f"{DASHED}\n", encoding="utf-8")
        (only / "tests" / "fixtures" / "leak").mkdir(parents=True)
        (only / "tests" / "fixtures" / "leak" / "p.md").write_text("plain\n", encoding="utf-8")
        with self.assertRaisesRegex(lg.GuardError, "no files to scan"):
            lg.scan(str(only), lg.load_terms(str(only)))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(lg.main(str(only), env={}), 2)
        self.assertIn("FAILED", buf.getvalue())

    def test_outside_a_work_tree_every_file_is_scanned(self):
        shutil.rmtree(self.root / ".git")
        self._write("results/run.json", f"{DASHED}x\n")
        self.assertEqual(self._hits(), ["results/run.json"])


if __name__ == "__main__":
    unittest.main()
