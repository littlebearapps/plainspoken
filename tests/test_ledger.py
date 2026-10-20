"""The kaizen ledger (schema, privacy, size, concurrency, month split, damage, capture off)."""
import json
import multiprocessing
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken import ledger

SEP = "2026-09-30T23:59:59+00:00"
OCT = "2026-10-14T09:00:00+00:00"


def _settings(root: Path, **over) -> dict:
    base = {"capture": True, "excerpts": False, "adapter": "file", "root": root,
            "ledger_dir": root / ".plainspoken" / "ledger", "proposals_dir": root / ".plainspoken" / "kaizen",
            "corpus": [], "human_corpus": [], "approvers": [], "github": {"repo": None, "labels": ["kaizen"]},
            "trello": {"list_id": None, "label_ids": [], "key_env": "TRELLO_API_KEY", "token_env": "TRELLO_TOKEN"}}
    base.update(over)
    return base


def _event(**over) -> dict:
    kw = {"event": "lint", "actor": "lint", "outcome": "fired", "ruleset_version": "1.2.0", "profile": "default",
          "rule": "2", "severity": "BLOCK", "doc_id": "0123456789abcdef", "doc_sha": "a" * 64,
          "span_hash": ledger.span_hash("2", "We delve into it."), "facets": {"term": "delve", "section": "intro"},
          "ts": OCT}
    kw.update(over)
    return ledger.make_event(**kw)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _worker(args):  # module level so multiprocessing can pickle it
    root, n, excerpt = args
    s = _settings(Path(root), excerpts=True)
    for i in range(200):
        ledger.append(_event(rule=str(n), span_hash=ledger.span_hash(str(n), f"span {i}"), excerpt=excerpt,
                             profile="p" * 1000), s)


class Schema(unittest.TestCase):
    def test_make_event_round_trips(self):
        e = _event()
        self.assertEqual(ledger.validate(e), [])
        self.assertEqual(e["v"], ledger.SCHEMA_VERSION)
        self.assertEqual(e["v"], 1)
        self.assertRegex(e["id"], r"^[0-9a-f]{16}$")
        self.assertEqual(e["ts"], OCT)
        self.assertEqual(json.loads(json.dumps(e)), e)

    def test_id_ignores_ts_and_excerpt_but_not_identity(self):
        a = _event()
        self.assertEqual(a["id"], _event(ts=SEP)["id"])
        self.assertEqual(a["id"], _event(excerpt="We delve into it.")["id"])
        self.assertNotEqual(a["id"], _event(span_hash=ledger.span_hash("2", "Another span."))["id"])

    def test_ts_defaults_to_now_utc_seconds(self):
        e = _event(ts=None)
        self.assertRegex(e["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

    def test_validate_rejects(self):
        good = _event()
        cases = {
            "unknown field": {**good, "colour": "red"},
            "justified nonsense": {**good, "event": "justify", "outcome": "justified:nonsense"},
            "judge J9": {**good, "actor": "judge:J9"},
            "facet term not a string": {**good, "facets": {"term": 3}},
            "unknown facet": {**good, "facets": {"colour": "x"}},
            "future schema": {**good, "v": 2},
            "bad id": {**good, "id": "nothex"},
            "hand-edited (id mismatch)": {**good, "rule": "3"},
            "bad event": {**good, "event": "nope"},
            "bad severity": {**good, "severity": "LOUD"},
            "null rule on lint": {**good, "rule": None},
            "reason on lint": {**good, "reason": "because"},
        }
        for name, ev in cases.items():
            with self.subTest(name):
                self.assertTrue(ledger.validate(ev), name)

    def test_justified_kinds_are_the_justify_kinds(self):
        from plainspoken import justify
        for kind in justify.KINDS:
            self.assertIn(f"justified:{kind}", ledger.OUTCOMES)
        e = _event(event="justify", outcome="justified:voice", severity="WARN", facets={"kind": "voice"})
        self.assertEqual(ledger.validate(e), [])

    def test_make_event_raises_on_bad_input(self):
        with self.assertRaises(ledger.LedgerError):
            _event(actor="judge:J9")
        self.assertTrue(issubclass(ledger.LedgerError, ValueError))

    def test_unencodable_values_are_ledger_errors(self):  # callers only ever see LedgerError
        for over in ({"doc_sha": Path("x")}, {"facets": {"term": {1, 2}}}):
            with self.subTest(over=over):
                with self.assertRaises(ledger.LedgerError):
                    _event(**over)

    def test_decision_may_have_no_rule(self):
        e = _event(event="decision", actor="human", outcome="approved", rule=None, severity=None, doc_id=None,
                   doc_sha=None, span_hash=None, facets={"by": "owner"}, proposal="p-0001", reason="Looks right.")
        self.assertEqual(ledger.validate(e), [])

    def test_caps(self):
        e = _event(event="override", actor="human", outcome="dismissed", reason="r" * 5000, excerpt="x" * 500)
        self.assertEqual(len(e["reason"]), 200)
        self.assertEqual(len(e["excerpt"]), 120)

    def test_hashes(self):
        self.assertEqual(ledger.normalise("  “Hello” \n  World’s  "), "\"hello\" world's")
        self.assertEqual(ledger.span_hash("2", "Hello  world"), ledger.span_hash("2", "hello world"))
        self.assertNotEqual(ledger.span_hash("2", "hello"), ledger.span_hash("3", "hello"))
        self.assertRegex(ledger.span_hash("2", "x"), r"^[0-9a-f]{16}$")
        self.assertRegex(ledger.label_id("history:001"), r"^[0-9a-f]{16}$")
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        inside = ledger.doc_id(root / "posts" / "a.md", root)
        self.assertEqual(inside, ledger.label_id("posts/a.md"))
        outside = Path(tempfile.gettempdir()).resolve() / "elsewhere.md"
        self.assertEqual(ledger.doc_id(outside, root), ledger.label_id(outside.as_posix()))

    def test_distinct_keeps_first_per_id(self):
        a, b = _event(ts=SEP), _event(ts=OCT)
        c = _event(rule="3", span_hash=ledger.span_hash("3", "x"))
        self.assertEqual(ledger.distinct([a, b, c]), [a, c])


class Append(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.s = _settings(self.root)

    def test_excerpts_off_drops_excerpt(self):
        path = ledger.append(_event(excerpt="We delve into it."), self.s)
        self.assertEqual(path, self.s["ledger_dir"] / "2026-10.jsonl")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("excerpt", json.loads(text.splitlines()[0]))
        self.assertNotIn("delve into it", text)

    def test_excerpts_on_stores_capped_excerpt(self):
        path = ledger.append(_event(excerpt="y" * 300), _settings(self.root, excerpts=True))
        row = json.loads(_lines(path)[0])
        self.assertEqual(row["excerpt"], "y" * 120)

    def test_long_reason_is_cut(self):
        path = ledger.append(_event(event="override", actor="human", outcome="dismissed", reason="z" * 5000), self.s)
        row = json.loads(_lines(path)[0])
        self.assertEqual(len(row["reason"]), 200)
        self.assertEqual(ledger.validate(row), [])

    def test_line_that_cannot_fit_raises(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.append(_event(profile="p" * 5000), self.s)
        self.assertFalse((self.s["ledger_dir"] / "2026-10.jsonl").exists())

    def test_multibyte_reason_is_shortened_to_fit(self):
        ev = _event(event="override", actor="human", outcome="dismissed", reason="\U0001F600" * 200,
                    profile="é" * 1700, excerpt="\U0001F600" * 120)
        path = ledger.append(ev, _settings(self.root, excerpts=True))
        raw = path.read_bytes()
        self.assertLessEqual(len(raw), 4096)
        row = json.loads(raw)
        self.assertEqual(ledger.validate(row), [])
        self.assertLess(len(row.get("reason", "")), 200)

    def test_invalid_event_raises(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.append({**_event(), "actor": "judge:J9"}, self.s)

    def test_capture_off_writes_nothing(self):
        self.assertIsNone(ledger.append(_event(), _settings(self.root, capture=False)))
        self.assertFalse(self.s["ledger_dir"].exists())

    def test_symlinked_folder_refused(self):
        real = self.root / "real"
        real.mkdir()
        (self.root / ".plainspoken").mkdir()
        self.s["ledger_dir"].symlink_to(real)
        with self.assertRaises(ledger.LedgerError):
            ledger.append(_event(), self.s)
        self.assertEqual(list(real.iterdir()), [])

    def test_symlinked_parent_refused(self):
        real = self.root / "real"
        (real / "ledger").mkdir(parents=True)
        (self.root / ".plainspoken").symlink_to(real)
        with self.assertRaises(ledger.LedgerError):
            ledger.append(_event(), self.s)

    def test_symlinked_file_refused(self):
        self.s["ledger_dir"].mkdir(parents=True)
        target = self.root / "target.jsonl"
        target.write_text("", encoding="utf-8")
        (self.s["ledger_dir"] / "2026-10.jsonl").symlink_to(target)
        with self.assertRaises(ledger.LedgerError):
            ledger.append(_event(), self.s)
        self.assertEqual(target.read_text(encoding="utf-8"), "")

    def test_folder_swapped_for_a_symlink_after_the_check_is_refused(self):  # check-then-act race
        outside = self.root / "outside"
        outside.mkdir()
        real_check = ledger._safe_target

        def check_then_swap(settings, name):
            path = real_check(settings, name)  # the folder passes its symlink check here...
            folder = Path(settings["ledger_dir"])
            shutil.rmtree(folder)
            folder.symlink_to(outside)  # ...and is swapped for a link before the write opens it
            return path

        ledger._safe_target = check_then_swap
        self.addCleanup(setattr, ledger, "_safe_target", real_check)
        with self.assertRaises(ledger.LedgerError):
            ledger.append(_event(), self.s)
        self.assertEqual(list(outside.iterdir()), [])

    def test_parent_swapped_for_a_symlink_after_the_check_is_refused(self):
        outside = self.root / "outside"
        (outside / "ledger").mkdir(parents=True)
        real_check = ledger._safe_target

        def check_then_swap(settings, name):
            path = real_check(settings, name)
            parent = Path(settings["ledger_dir"]).parent
            shutil.rmtree(parent)
            parent.symlink_to(outside)
            return path

        ledger._safe_target = check_then_swap
        self.addCleanup(setattr, ledger, "_safe_target", real_check)
        with self.assertRaises(ledger.LedgerError):
            ledger.append(_event(), self.s)
        self.assertEqual(list((outside / "ledger").iterdir()), [])

    def test_hard_linked_month_file_refused(self):
        self.s["ledger_dir"].mkdir(parents=True)
        target = self.root / "elsewhere.jsonl"
        target.write_text("", encoding="utf-8")
        os.link(target, self.s["ledger_dir"] / "2026-10.jsonl")
        with self.assertRaisesRegex(ledger.LedgerError, "hard link"):
            ledger.append(_event(), self.s)
        self.assertEqual(target.read_text(encoding="utf-8"), "")
        os.link(target, self.s["ledger_dir"] / "friction.jsonl")
        ledger.friction("skill", "test", "detail", self.s)  # never raises, and never writes through the link
        self.assertEqual(target.read_text(encoding="utf-8"), "")

    def test_concurrent_appends_stay_whole(self):
        # Excerpts are capped at 120 characters, so a 4-byte character makes a 480-byte excerpt; the padded profile
        # in _worker brings each line to ~1.7 KB.
        excerpt = "\U0001F600" * 120
        ctx = multiprocessing.get_context("fork" if hasattr(os, "fork") else "spawn")
        with ctx.Pool(8) as pool:
            pool.map(_worker, [(str(self.root), n, excerpt) for n in range(8)])
        path = self.s["ledger_dir"] / "2026-10.jsonl"
        lines = _lines(path)
        self.assertEqual(len(lines), 1600)
        for line in lines:
            self.assertEqual(ledger.validate(json.loads(line)), [])
        events, bad = ledger.read(self.s)
        self.assertEqual((len(events), bad), (1600, 0))
        self.assertEqual(len(ledger.distinct(events)), 1600)


class Read(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.s = _settings(self.root)

    def test_month_split_and_since(self):
        ledger.append(_event(ts=SEP), self.s)
        ledger.append(_event(ts=OCT, rule="3", span_hash=ledger.span_hash("3", "x")), self.s)
        d = self.s["ledger_dir"]
        self.assertTrue((d / "2026-09.jsonl").is_file())
        self.assertTrue((d / "2026-10.jsonl").is_file())
        with (d / "2026-09.jsonl").open("a", encoding="utf-8") as f:
            f.write("not json\n")  # only counted if September is read
        events, bad = ledger.read(self.s, since="2026-10-01")
        self.assertEqual(([e["rule"] for e in events], bad), (["3"], 0))
        events, bad = ledger.read(self.s)
        self.assertEqual(([e["rule"] for e in events], bad), (["2", "3"], 1))
        events, bad = ledger.read(self.s, until="2026-10-01")
        self.assertEqual(([e["rule"] for e in events], bad), (["2"], 1))
        events, bad = ledger.read(self.s, since="2026-09-30T23:59:59+00:00", until=OCT)
        self.assertEqual([e["rule"] for e in events], ["2"])

    def test_damage_is_counted_and_skipped(self):
        ledger.append(_event(), self.s)
        ledger.append(_event(rule="3", span_hash=ledger.span_hash("3", "x")), self.s)
        path = self.s["ledger_dir"] / "2026-10.jsonl"
        future = {**_event(rule="4", span_hash=ledger.span_hash("4", "x")), "v": 2}
        edited = {**_event(rule="5", span_hash=ledger.span_hash("5", "x")), "severity": "INFO"}
        whole = json.dumps(_event(rule="6", span_hash=ledger.span_hash("6", "x")))
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(future) + "\n" + json.dumps(edited) + "\n" + whole[: len(whole) // 2])
        events, bad = ledger.read(self.s)
        self.assertEqual(bad, 3)
        self.assertEqual([e["rule"] for e in events], ["2", "3"])

    def test_deeply_nested_line_is_a_bad_line(self):  # RecursionError never escapes read
        ledger.append(_event(), self.s)
        with (self.s["ledger_dir"] / "2026-10.jsonl").open("a", encoding="utf-8") as f:
            f.write("[" * 100000 + "]" * 100000 + "\n")
        events, bad = ledger.read(self.s)
        self.assertEqual((len(events), bad), (1, 1))

    def test_missing_ledger_is_empty(self):
        self.assertEqual(ledger.read(self.s), ([], 0))

    def test_symlinked_folder_reads_nothing(self):
        real = self.root / "real"
        real.mkdir()
        ledger.append(_event(), _settings(self.root, ledger_dir=real))
        (self.root / ".plainspoken").mkdir()
        self.s["ledger_dir"].symlink_to(real)
        self.assertEqual(ledger.read(self.s), ([], 0))


class Friction(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.s = _settings(self.root)

    def test_writes_one_capped_line(self):
        self.assertIsNone(ledger.friction("merge_incomplete", "merge", "d" * 500, self.s))
        rows = [json.loads(x) for x in _lines(self.s["ledger_dir"] / "friction.jsonl")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {"v", "ts", "kind", "source", "detail"})
        self.assertEqual((rows[0]["v"], rows[0]["kind"], len(rows[0]["detail"])), (1, "merge_incomplete", 200))

    def test_never_raises(self):
        real = self.root / "real"
        real.mkdir()
        (self.root / ".plainspoken").mkdir()
        self.s["ledger_dir"].symlink_to(real)
        ledger.friction("capture_error", "check", "x", self.s)  # refused, silently
        self.assertEqual(list(real.iterdir()), [])
        ledger.friction("not-a-kind", "check", "x", _settings(self.root, ledger_dir=self.root / "f"))
        self.assertFalse((self.root / "f").exists())
        ledger.friction("skill", "check", "x", {})  # unusable settings
        ledger.friction("skill", "check", "x", None)
        ledger.friction("skill", "check", "x", {"capture": True, "root": self.root})  # no ledger_dir
        ledger.friction("skill", "check", "x", {"capture": True, "ledger_dir": 5})
        (self.root / "file").write_text("", encoding="utf-8")
        ledger.friction("skill", "check", "x", _settings(self.root, ledger_dir=self.root / "file" / "sub"))

    def test_capture_off_writes_nothing(self):
        ledger.friction("skill", "check", "x", _settings(self.root, capture=False))
        self.assertFalse(self.s["ledger_dir"].exists())

    def test_read_friction_round_trips_and_counts_damage(self):
        ledger.friction("merge_incomplete", "merge", "missing verdicts: 9", self.s)
        ledger.friction("agent_handback", "plainspoken:tells-judge", "", self.s)
        path = self.s["ledger_dir"] / "friction.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"v": 2, "ts": "2026-10-14T09:00:00+00:00", "kind": "skill", "source": "s", "detail": ""}\n')
            fh.write('{"v": 1, "ts": "x", "kind": "skill", "source": "s", "detail": ""}\n')
            fh.write('{"v": 1, "ts": "2026-10-14T09:00:00+00:00", "kind": "nope", "source": "s", "detail": ""}\n')
            fh.write('{"v": 1, "ts": "2026-10-14T09:00:00+00:00"')  # truncated last line
        rows, bad = ledger.read_friction(self.s)
        self.assertEqual([r["kind"] for r in rows], ["merge_incomplete", "agent_handback"])
        self.assertEqual(bad, 4)
        self.assertTrue(all(ledger.valid_friction(r) for r in rows))
        self.assertEqual(ledger.read_friction(self.s, since="2999-01-01T00:00:00+00:00"), ([], 4))

    def test_read_friction_missing_or_symlinked(self):
        self.assertEqual(ledger.read_friction(self.s), ([], 0))
        real = self.root / "real"
        real.mkdir()
        ledger.friction("skill", "check", "x", _settings(self.root, ledger_dir=real))
        (self.root / ".plainspoken").mkdir()
        self.s["ledger_dir"].symlink_to(real)
        self.assertEqual(ledger.read_friction(self.s), ([], 0))  # symlinked folder
        other = self.root / "other"
        other.mkdir()
        (other / "friction.jsonl").symlink_to(real / "friction.jsonl")
        self.assertEqual(ledger.read_friction(_settings(self.root, ledger_dir=other)), ([], 0))  # symlinked file


if __name__ == "__main__":
    unittest.main()
