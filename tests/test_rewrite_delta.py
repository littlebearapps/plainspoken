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
                                 {"tracePath": str(self.tmp / "gone" / "trace.jsonl")}]}}]}

    def test_counts_per_arm_and_missing_runs(self):
        d = rewrite.delta(self.result, REPO, default_profile())
        self.assertEqual(d["runs"], {"with": 1, "without": 1})
        self.assertEqual(d["missing"], ["rewrite--email--slash without #2"])
        s = d["summary"]["blocks"]
        self.assertEqual(s["with"], 0.0)
        self.assertGreater(s["without"], 0)
        self.assertGreater(s["delta"], 0, "positive favours the plugin")
        self.assertEqual(d["passes"], {"with": 1, "without": 0})

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


if __name__ == "__main__":
    unittest.main()


class Pieces(unittest.TestCase):
    def test_piece_between_markers_else_whole_reply(self):
        self.assertEqual(rewrite.piece("Report line\n<<<PIECE\nHi Tom.\nSee you.\nPIECE>>>\nmerge: PASS"), "Hi Tom.\nSee you.")
        self.assertEqual(rewrite.piece("just the text"), "just the text")
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
