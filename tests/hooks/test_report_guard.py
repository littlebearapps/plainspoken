"""The Stop report guard (#75): a write report that asks the owner to check a line its `needs the owner` lines
don't list goes back to Claude once, with a block decision; anything else stops as normal, silently."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_owner_asks import ASK, BLOCK, LEDGER_LEAF, LEDGER_LEAF_ASK, REPAIR, REPAIR_ASK, SHORT

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "report_guard.py"


def run(payload, project: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    env.update({"CLAUDE_PROJECT_DIR": str(project), "CLAUDE_PLUGIN_DATA": str(project / ".data")})
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env,
                          cwd=project, timeout=60)


class Guard(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)

    def stop(self, message, active: bool = False) -> subprocess.CompletedProcess:
        event = {"hook_event_name": "Stop", "session_id": "s1", "cwd": str(self.project), "transcript_path": None,
                 "stop_hook_active": active}
        if message is not None:
            event["last_assistant_message"] = message
        return run(event, self.project)

    def test_an_unlisted_owner_ask_is_sent_back(self):
        r = self.stop(BLOCK + SHORT + ASK)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("so check Jo is happy with them.", out["reason"])
        self.assertIn("`blocking`", out["reason"])
        self.assertEqual(r.stderr, "")
        self.assertFalse((self.project / ".data").exists())  # it keeps no state
        self.assertFalse((self.project / ".plainspoken").exists())

    def test_the_round_8_asks_are_sent_back(self):  # #75: fired 0 times in 9 runs before
        for report, ask in ((REPAIR, REPAIR_ASK), (LEDGER_LEAF, LEDGER_LEAF_ASK)):
            with self.subTest(ask=ask):
                r = self.stop(report)
                self.assertEqual(r.returncode, 0, r.stderr)
                out = json.loads(r.stdout)
                self.assertEqual(out["decision"], "block")
                self.assertIn(ask, out["reason"])
                self.assertNotIn("Please confirm", out["reason"])  # the ask about the listed claim stays

    def test_it_sends_a_report_back_only_once(self):  # Claude Code sets stop_hook_active on the turn it caused
        self.assertEqual((r := self.stop(BLOCK + ASK, active=True)).stdout, "", r.stderr)

    def test_a_clean_report_and_other_messages_stop_silently(self):
        for message in (BLOCK + SHORT, ASK, "Done.", "", None):
            with self.subTest(message=message):
                r = self.stop(message)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_bad_input_fails_open(self):
        for payload in ("not json", "[]", json.dumps({"last_assistant_message": 7})):
            with self.subTest(payload=payload):
                r = run(payload, self.project)
                self.assertEqual((r.returncode, r.stdout), (0, ""))


class Registration(unittest.TestCase):
    def test_stop_runs_the_guard_beside_the_nudge(self):
        hooks = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        stop = [h for group in hooks["Stop"] for h in group["hooks"]]
        mine = [h for h in stop if h.get("args") == ["${CLAUDE_PLUGIN_ROOT}/hooks/report_guard.py"]]
        self.assertEqual(len(mine), 1, stop)
        self.assertEqual((mine[0]["type"], mine[0]["command"]), ("command", "python3"))
        self.assertLessEqual(mine[0]["timeout"], 10)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/kaizen_nudge.py", json.dumps(stop))


if __name__ == "__main__":
    unittest.main()
