import json
import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken import rewrite
from plainspoken.profile import default as default_profile
from tests.test_cli import cli

REPO = Path(__file__).resolve().parents[1]
STIFF = "Moreover, we delve into a robust tapestry of seamless updates — truly pivotal."
PLAIN = "We fixed the booking page and moved the March meeting to Friday 14 March."


def trace(folder: Path, reply: str | None) -> str:
    folder.mkdir(parents=True)
    rows = [{"type": "system", "subtype": "init"}, {"type": "assistant", "message": {}}]
    if reply is not None:
        rows.append({"type": "result", "result": reply})
    (folder / "trace.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(folder / "trace.jsonl")


class Delta(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.result = {"suite": {"root": str(REPO)}, "cases": [{
            "name": "rewrite--email--slash", "dir": "evals/rewrite-slash/rewrite--email--slash",
            "arms": {"with": [{"tracePath": trace(self.tmp / "w", PLAIN)}],
                     "without": [{"tracePath": trace(self.tmp / "o", STIFF)},
                                 {"tracePath": str(self.tmp / "gone" / "trace.jsonl")},
                                 {"tracePath": trace(self.tmp / "e", "API Error: 400 usage limits"), "error": "exit 1"}]}}]}

    def test_counts_per_arm_and_missing_runs(self):
        d = rewrite.delta(self.result, REPO, default_profile())
        self.assertEqual(d["runs"], {"with": 1, "without": 1})
        self.assertEqual(d["missing"], ["rewrite--email--slash without #2", "rewrite--email--slash without #3"])
        s = d["summary"]["blocks"]
        self.assertEqual(s["with"], 0.0)
        self.assertGreater(s["without"], 0)
        self.assertGreater(s["delta"], 0, "positive favours the plugin")
        self.assertEqual(d["passes"], {"with": 1, "without": 0})

    def test_delta_counts_meaning_per_arm(self):  # #147: listed per arm, never part of the verdict
        prompt = (REPO / "evals/rewrite-slash/rewrite--email--slash/prompt.md").read_text(encoding="utf-8")
        source = rewrite.passage(prompt.split("\n---\n", 1)[-1])
        dropped = source.replace(" The cost of $25 can be paid via the school app by 7 March.", "")
        self.assertNotEqual(dropped, source)
        result = {"suite": {"root": str(REPO)}, "cases": [{
            "name": "rewrite--email--slash", "dir": "evals/rewrite-slash/rewrite--email--slash",
            "arms": {"with": [{"tracePath": trace(self.tmp / "mw", dropped)}],
                     "without": [{"tracePath": trace(self.tmp / "mo", source)}]}}]}
        d = rewrite.delta(result, REPO, default_profile())
        rows = {r["arm"]: r for r in d["rows"]}
        self.assertGreaterEqual(rows["with"]["meaning"], 1)
        self.assertEqual(rows["without"]["meaning"], 0)
        self.assertEqual(d["summary"]["meaning"]["without"], 0.0)
        self.assertEqual(rows["with"]["verdict"], rows["without"]["verdict"])  # the number drop fails nothing
        self.assertIn("meaning changes listed: with ", rewrite.summarise_delta(d))

    def test_final_reply_is_the_last_result_row(self):
        path = Path(trace(self.tmp / "t", "first"))
        with path.open("a", encoding="utf-8") as f:
            f.write("not json\n" + json.dumps({"type": "result", "result": "second"}) + "\n")
        self.assertEqual(rewrite.final_reply(path), "second")
        self.assertIsNone(rewrite.final_reply(Path(trace(self.tmp / "none", None))))

    def test_cli(self):
        path = self.tmp / "aggregate-result.json"
        path.write_text(json.dumps(self.result), encoding="utf-8")
        r = cli("eval", "rewrite-delta", str(path), "--profile", "default", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lint BLOCK findings: with 0.0", r.stdout)
        self.assertIn("missing traces", r.stdout)

    def test_derived_numbers_are_listed_not_counted(self):
        """A drafting case's source is the brief's facts: 150 from its 151 is derived, not new (#33)."""
        piece = ("<<<PIECE\nThe 151 repairs so far have kept something like 150 kilos out of the tip, and Ray has "
                 "fixed 913 toasters.\nPIECE>>>")
        plain = piece.replace(", and Ray has fixed 913 toasters", "")
        name = "longform--newsletter-feature-library"
        result = {"suite": {"root": str(REPO)}, "cases": [{
            "name": name, "dir": f"evals/longform/{name}",
            "arms": {"with": [{"tracePath": trace(self.tmp / "dw", piece)}],
                     "without": [{"tracePath": trace(self.tmp / "do", plain)}]}}]}
        d = rewrite.delta(result, REPO, default_profile())
        rows = {r["arm"]: r for r in d["rows"]}
        self.assertEqual((rows["with"]["new_numbers"], rows["with"]["derived_numbers"]), (1, 1))
        self.assertEqual((rows["without"]["new_numbers"], rows["without"]["derived_numbers"]), (0, 1))
        self.assertEqual(rows["without"]["derived"], "150 ≈ 151")
        self.assertEqual(d["summary"]["new_numbers"], {"with": 1.0, "without": 0.0, "delta": -1.0})
        text = rewrite.summarise_delta(d)
        self.assertIn("  new numbers: with 1.0, without 0.0, delta -1.0", text)
        self.assertIn("derived numbers (worked out from the source's own; not counted as new): with 1.0, without 1.0",
                      text)
        self.assertIn("without #1: PASS · BLOCK 0 · WARN 0 · em-dash over 0 · new numbers 0 · derived 1 (150 ≈ 151)",
                      text)


if __name__ == "__main__":
    unittest.main()


class Pieces(unittest.TestCase):
    def test_piece_between_markers_else_whole_reply(self):
        self.assertEqual(rewrite.piece("Report line\n<<<PIECE\nHi Tom.\nSee you.\nPIECE>>>\nmerge: PASS"), "Hi Tom.\nSee you.")
        self.assertEqual(rewrite.piece("just the text"), "just the text")
        self.assertEqual(rewrite.piece("---\n\nSubject: Hi\n\nBody."), "Subject: Hi\n\nBody.")
        self.assertEqual(rewrite.piece("Hi all.\n\n(`/plainspoken:humanize` isn't installed, so I rewrote it.)"), "Hi all.")

    def test_content_type_for(self):
        self.assertEqual(rewrite.content_type_for("drafting--sms-dentist-reschedule"), "social")
        self.assertEqual(rewrite.content_type_for("drafting-hooks--x-thread-bin-changes"), "social")
        self.assertEqual(rewrite.content_type_for("rewrite--linkedin-post--slash"), "social")
        self.assertEqual(rewrite.content_type_for("drafting--newsletter-school"), "article")

    def test_save_writes_each_piece(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        result = {"suite": {"root": str(REPO)}, "cases": [{
            "name": "rewrite--email--slash", "dir": "evals/rewrite-slash/rewrite--email--slash",
            "arms": {"with": [{"tracePath": trace(tmp / "w", "<<<PIECE\n" + PLAIN + "\nPIECE>>>")}], "without": []}}]}
        rewrite.delta(result, REPO, default_profile(), save=tmp / "out")
        self.assertEqual((tmp / "out" / "rewrite--email--slash" / "with-1.md").read_text(encoding="utf-8"), PLAIN + "\n")
