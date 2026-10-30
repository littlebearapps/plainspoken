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


def _transcript(project: Path, records: list[dict]) -> str:
    path = project / "t.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return str(path)


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _skill(name):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t-" + name, "name": "Skill", "input": {"skill": name}}]}}


def _loaded(folder):  # how Claude Code loads a skill's instructions into the turn
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "text", "text": f"Base directory for this skill: /p/skills/{folder}\n\n# plainspoken {folder}"}]}}


def _status():
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t-b", "content": "check: PASS · coverage 41/41\nclaims: PASS\n"
                                                                 "needs the owner: none\nwords: 236 (body text)"}]}}


class MissingBlock(unittest.TestCase):
    """#171: a write turn whose report leaves out the status block goes back once, to start with it."""
    PROSE = "The post is written, but it comes to 236 words, not 500. All the checks passed."

    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)

    def stop(self, records, message=None, active=False):
        event = {"hook_event_name": "Stop", "session_id": "s1", "cwd": str(self.project),
                 "transcript_path": _transcript(self.project, records) if records is not None else None,
                 "stop_hook_active": active, "last_assistant_message": message or self.PROSE}
        return run(event, self.project)

    def test_a_write_report_without_the_block_is_sent_back(self):
        for records in ([_user("Write the post."), _skill("plainspoken:write"), _loaded("write"), _status()],
                        [_user("/plainspoken:write notes.md"), _loaded("write"), _status()]):
            with self.subTest(first=records[1]["type"]):
                r = self.stop(records)
                self.assertEqual(r.returncode, 0, r.stderr)
                out = json.loads(r.stdout)
                self.assertEqual(out["decision"], "block")
                self.assertIn("leaves out the status block", out["reason"])

    def test_left_alone(self):
        write = [_user("Write the post."), _skill("plainspoken:write"), _loaded("write"), _status()]
        cases = {
            "the block is there": (write, BLOCK + SHORT, False),
            "sent back already": (write, None, True),
            "no transcript": (None, None, False),
            "a check, not a write": ([_user("Check it."), _skill("plainspoken:check"), _loaded("check"), _status()],
                                     None, False),
            "write never got to status": ([_user("Write the post."), _skill("plainspoken:write"), _loaded("write")],
                                          None, False),
            "write was an earlier turn": (write + [_user("Thanks, what's next?")], None, False),
        }
        for why, (records, message, active) in cases.items():
            with self.subTest(why):
                r = self.stop(records, message, active)
                self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def test_an_unreadable_transcript_fails_open(self):
        event = {"hook_event_name": "Stop", "session_id": "s1", "cwd": str(self.project),
                 "transcript_path": str(self.project / "missing.jsonl"), "stop_hook_active": False,
                 "last_assistant_message": self.PROSE}
        (self.project / "bad.jsonl").write_text("{not json\n", encoding="utf-8")
        for path in ("missing.jsonl", "bad.jsonl"):
            event["transcript_path"] = str(self.project / path)
            self.assertEqual(run(event, self.project).stdout, "")


if __name__ == "__main__":
    unittest.main()
