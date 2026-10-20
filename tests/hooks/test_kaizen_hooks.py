"""The kaizen Stop nudge and the subagent backstop: thin, silent unless there's a ledger, never
blocking, never adding context."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NUDGE = REPO / "hooks" / "kaizen_nudge.py"
BACKSTOP = REPO / "hooks" / "kaizen_backstop.py"
sys.path.insert(0, str(REPO / "lib"))
from plainspoken import config, kaizen, ledger  # noqa: E402

PID = "KZ-20261014-abc123"


def run(hook: Path, payload, project: Path, **env_over) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    env.update({"CLAUDE_PROJECT_DIR": str(project), "CLAUDE_PLUGIN_DATA": str(project / ".data")})
    env.update(env_over)
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(hook)], input=stdin, capture_output=True, text=True, env=env,
                          cwd=project, timeout=60)


def cli(project: Path, *argv: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    return subprocess.run([sys.executable, str(REPO / "lib" / "run.py"), *argv], capture_output=True, text=True,
                          env=env, cwd=project, timeout=120)


class Base(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        (self.project / ".git").mkdir()

    def settings(self) -> dict:
        return config.kaizen_settings(self.project, {})

    def make_ledger(self) -> Path:
        folder = self.project / ".plainspoken" / "ledger"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def add_events(self, n: int, ts: datetime | None = None, event: str = "lint", start: int = 0) -> None:
        s = self.settings()
        for i in range(start, start + n):
            ledger.append(ledger.make_event(event=event, actor="lint" if event == "lint" else "engine",
                                            outcome="fired" if event == "lint" else "proposed",
                                            ruleset_version="1.0.0", profile="default",
                                            rule="1" if event == "lint" else None,
                                            severity="WARN" if event == "lint" else None,
                                            doc_id="0" * 16, span_hash=f"{i:016x}", ts=ts), s)

    def pending_proposal(self) -> None:
        folder = self.project / ".plainspoken" / "kaizen" / "proposals"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{PID}.json").write_text(json.dumps({"id": PID}), encoding="utf-8")

    def sibling(self) -> Path:
        """A sibling repository with no .plainspoken, where the session's Bash has `cd`-ed."""
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        (other / ".git").mkdir()
        return other

    def lines(self, folder: Path, name: str) -> list[str]:
        path = folder / name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


class Nudge(Base):
    def stop(self, session: str = "s1", **env) -> subprocess.CompletedProcess:
        return run(NUDGE, {"hook_event_name": "Stop", "session_id": session, "cwd": str(self.project),
                           "stop_hook_active": False}, self.project, **env)

    def test_no_ledger_is_silent(self):
        self.pending_proposal()  # a proposal with no ledger folder still says nothing
        r = self.stop()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertFalse((self.project / ".plainspoken" / "ledger").exists())

    def test_empty_ledger_is_silent(self):
        self.make_ledger()
        r = self.stop()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_pending_proposal_nudges_once_per_session(self):
        self.make_ledger()
        self.pending_proposal()
        r = self.stop()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(set(out), {"systemMessage"})  # never additionalContext, never a decision
        self.assertEqual(out["systemMessage"],
                         "plainspoken: 1 kaizen proposal(s) await a decision — /plainspoken:kaizen review")
        self.assertNotIn("additionalContext", r.stdout)
        self.assertNotIn("hookSpecificOutput", r.stdout)
        again = self.stop()
        self.assertEqual((again.returncode, again.stdout), (0, ""))
        other = self.stop(session="s2")  # a new session hears it again
        self.assertIn("await a decision", json.loads(other.stdout)["systemMessage"])

    def test_a_cwd_in_a_sibling_repo_still_nudges_for_the_project(self):
        self.make_ledger()
        self.pending_proposal()
        other = self.sibling()
        r = run(NUDGE, {"hook_event_name": "Stop", "session_id": "s1", "cwd": str(other),
                        "stop_hook_active": False}, self.project)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("await a decision", json.loads(r.stdout)["systemMessage"])
        self.assertFalse((other / ".plainspoken").exists())

    def test_decided_proposal_is_quiet(self):
        folder = self.make_ledger()
        self.pending_proposal()
        ledger.append(ledger.make_event(event="decision", actor="human", outcome="rejected", ruleset_version="1.0.0",
                                        profile="default", proposal=PID, facets={"by": "robin"}), self.settings())
        r = self.stop()
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertTrue(any(folder.iterdir()))

    def test_calibrate_due_after_50_distinct_events_and_no_calibrate(self):
        self.make_ledger()
        self.add_events(49)
        self.add_events(49)  # the same 49 again: duplicates don't count
        self.assertEqual(self.stop().stdout, "")
        self.add_events(50)
        r = self.stop(session="s2")
        msg = json.loads(r.stdout)["systemMessage"]
        self.assertTrue(msg.startswith("plainspoken: kaizen calibrate is due"), msg)
        self.assertIn("/plainspoken:kaizen calibrate", msg)
        # with no calibrate yet, the wording doesn't assume one
        self.assertNotIn("since the last one", msg)
        self.assertIn("(50 events, and it has never run)", msg)
        self.assertEqual(self.stop(session="s2").stdout, "")

    def test_a_recent_calibrate_event_holds_the_nudge(self):
        self.make_ledger()
        self.add_events(1, event="calibrate", ts=datetime.now(timezone.utc) - timedelta(days=10))
        self.add_events(80)
        self.assertEqual(self.stop().stdout, "")

    def test_an_old_calibrate_counts_only_newer_events(self):
        self.make_ledger()
        old = datetime.now(timezone.utc) - timedelta(days=40)
        self.add_events(60, ts=old - timedelta(days=1))
        self.add_events(1, event="calibrate", ts=old)
        self.assertEqual(self.stop().stdout, "")  # 60 events, all before the last calibrate
        self.add_events(50, start=100)
        msg = json.loads(self.stop(session="s2").stdout)["systemMessage"]
        self.assertIn("calibrate is due (50 new events since the last one)", msg)

    def test_a_calibrate_run_with_no_proposals_resets_the_count(self):  # else the nudge could never be satisfied
        self.make_ledger()
        self.add_events(60)
        r = cli(self.project, "kaizen", "calibrate")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no proposals", r.stdout)
        self.assertEqual(self.stop().stdout, "")

    def test_the_calibrate_stamp_is_real_time_not_now(self):  # a future --now must not silence the nudge
        self.make_ledger()
        self.add_events(60)
        before = datetime.now(timezone.utc).replace(microsecond=0)
        r = cli(self.project, "kaizen", "calibrate", "--now", "2099-01-01")
        self.assertEqual(r.returncode, 0, r.stderr)
        stamp = datetime.fromisoformat(
            (self.project / ".plainspoken" / "kaizen" / kaizen.LAST_CALIBRATE).read_text(encoding="utf-8").strip())
        self.assertLessEqual(before, stamp)
        self.assertLessEqual(stamp, datetime.now(timezone.utc))
        r = cli(self.project, "kaizen", "calibrate", "--now", "2000-01-01")  # a past --now doesn't re-arm it either
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("calibrate is due", self.stop().stdout)  # (the 2099 run may have left proposals to review)

    def test_both_messages_in_one_line_set(self):
        self.make_ledger()
        self.pending_proposal()
        self.add_events(50)
        msg = json.loads(self.stop().stdout)["systemMessage"]
        self.assertIn("await a decision", msg)
        self.assertIn("calibrate is due", msg)

    def test_never_writes_the_ledger(self):
        folder = self.make_ledger()
        self.pending_proposal()
        self.add_events(50)
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        self.stop()
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, before)

    def test_bad_stdin_and_bad_config_exit_0(self):
        self.make_ledger()
        self.pending_proposal()
        for payload in ("{not json", "[]", ""):
            r = run(NUDGE, payload, self.project)
            self.assertEqual((r.returncode, r.stdout), (0, ""), payload)
        (self.project / ".plainspoken" / "config.toml").write_text("[kaizen\n", encoding="utf-8")
        r = self.stop()
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_symlinked_state_is_ignored_not_followed(self):
        self.make_ledger()
        self.pending_proposal()
        data = self.project / ".data"
        data.mkdir()
        target = self.project / "elsewhere.json"
        target.write_text("{}", encoding="utf-8")
        (data / "kaizen-nudge-state.json").symlink_to(target)
        r = self.stop()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "{}")


class Backstop(Base):
    def handback(self, agent_type: str = "plainspoken:tells-judge", agent_id: str | None = "a1", **extra):
        payload = {"hook_event_name": "PostToolUse", "tool_name": "SubagentHandback", "session_id": "s1",
                   "cwd": str(self.project), "agent_type": agent_type,
                   "tool_input": {"message": "{\"group\": \"J1\", \"verdicts\": []}"}, **extra}
        if agent_id is not None:
            payload["agent_id"] = agent_id
        return run(BACKSTOP, payload, self.project)

    def subagent_stop(self, agent_type: str = "plainspoken:tells-judge", agent_id: str = "a1"):
        return run(BACKSTOP, {"hook_event_name": "SubagentStop", "session_id": "s1", "cwd": str(self.project),
                              "agent_type": agent_type, "agent_id": agent_id,
                              "last_assistant_message": "secret article text"}, self.project)

    def friction(self) -> list[dict]:
        return [json.loads(x) for x in self.lines(self.project / ".plainspoken" / "ledger", "friction.jsonl")]

    def test_a_cwd_in_a_sibling_repo_still_counts_for_the_project(self):
        self.make_ledger()
        other = self.sibling()
        r = self.handback(cwd=str(other))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(len(self.friction()), 1)
        self.assertFalse((other / ".plainspoken").exists())

    def test_judge_handback_logs_one_friction_line_per_agent(self):
        self.make_ledger()
        r = self.handback()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        rows = self.friction()
        self.assertEqual(len(rows), 1)
        self.assertEqual({k: rows[0][k] for k in ("kind", "source", "detail")},
                         {"kind": "agent_handback", "source": "plainspoken:tells-judge", "detail": ""})
        self.assertTrue(ledger.valid_friction(rows[0]))
        self.assertEqual(self.handback().stdout, "")  # the same agent_id again
        self.assertEqual(self.subagent_stop().stdout, "")  # and its SubagentStop
        self.assertEqual(len(self.friction()), 1)
        self.subagent_stop(agent_id="a2")  # an agent with no handback is caught at SubagentStop
        self.assertEqual(len(self.friction()), 2)

    def test_the_returned_count_reaches_the_report(self):  # kaizen.JUDGE_AGENTS must match the source string
        self.make_ledger()
        self.handback(agent_id="a1")
        self.handback(agent_id="a2")
        self.handback(agent_type="plainspoken:cold-reader", agent_id="a3")
        rows, bad = ledger.read_friction(self.settings())
        self.assertEqual(bad, 0)
        summary = kaizen.friction_summary(rows, [])
        self.assertEqual(summary["judge_returned"], 2)
        self.assertEqual(summary["kinds"], {"agent_handback": 3})
        r = cli(self.project, "kaizen", "report", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["friction"]["judge_returned"], 2)
        text = cli(self.project, "kaizen", "report")
        self.assertIn("judge replies returned (backstop) 2 vs recorded 0", text.stdout)

    def test_other_agents_are_ignored(self):
        self.make_ledger()
        for agent_type in ("general-purpose", "Explore", "", "plainspoken", "other:plainspoken:tells-judge"):
            r = self.handback(agent_type=agent_type)
            self.assertEqual((r.returncode, r.stdout), (0, ""), agent_type)
        r = run(BACKSTOP, {"hook_event_name": "PostToolUse", "tool_name": "SubagentHandback", "agent_id": "a9",
                           "cwd": str(self.project)}, self.project)  # no agent_type: the main session
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(self.friction(), [])

    def test_no_ledger_writes_nothing(self):
        r = self.handback()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertFalse((self.project / ".plainspoken").exists())

    def test_no_agent_id_logs_nothing(self):  # it can't be counted once, so it isn't counted
        self.make_ledger()
        self.assertEqual(self.handback(agent_id=None).stdout, "")
        self.assertEqual(self.friction(), [])

    def test_capture_off_logs_nothing(self):
        self.make_ledger()
        (self.project / ".plainspoken" / "config.toml").write_text("[kaizen]\ncapture = false\n", encoding="utf-8")
        self.assertEqual(self.handback().returncode, 0)
        self.assertEqual(self.friction(), [])

    def test_never_stores_the_message(self):
        self.make_ledger()
        self.handback()
        self.subagent_stop(agent_id="a2")
        text = (self.project / ".plainspoken" / "ledger" / "friction.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("verdicts", text)
        self.assertNotIn("secret article text", text)

    def test_bad_stdin_exits_0(self):
        self.make_ledger()
        for payload in ("{not json", "[]", "", json.dumps({"agent_type": 5, "agent_id": ["x"]})):
            r = run(BACKSTOP, payload, self.project)
            self.assertEqual((r.returncode, r.stdout), (0, ""), payload)
        self.assertEqual(self.friction(), [])


class Registration(unittest.TestCase):
    def setUp(self):
        self.hooks = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]

    def commands(self, event: str, matcher: str | None = None) -> list[dict]:
        out = []
        for group in self.hooks.get(event, []):
            if matcher is None or group.get("matcher") == matcher:
                out += group["hooks"]
        return out

    def assert_runs(self, hooks: list[dict], script: str) -> None:
        mine = [h for h in hooks if h.get("args") == [f"${{CLAUDE_PLUGIN_ROOT}}/hooks/{script}"]]
        self.assertEqual(len(mine), 1, hooks)
        self.assertEqual((mine[0]["type"], mine[0]["command"]), ("command", "python3"))
        self.assertLessEqual(mine[0]["timeout"], 15)

    def test_stop_runs_the_nudge(self):
        self.assert_runs(self.commands("Stop"), "kaizen_nudge.py")

    def test_subagent_stop_and_handback_run_the_backstop(self):
        self.assert_runs(self.commands("SubagentStop"), "kaizen_backstop.py")
        self.assert_runs(self.commands("PostToolUse", "SubagentHandback"), "kaizen_backstop.py")

    def test_the_backstop_isnt_on_write_or_edit(self):
        self.assertNotIn("kaizen_backstop.py", json.dumps(self.commands("PostToolUse", "Write|Edit")))


if __name__ == "__main__":
    unittest.main()
