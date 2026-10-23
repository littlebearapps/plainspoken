"""The Codex hooks (hooks/codex.json) fed Codex-shaped events: no CLAUDE_PROJECT_DIR and no plugin options, the
plugin root and data folder in PLUGIN_* and CLAUDE_PLUGIN_*, and each command string run through a shell as Codex
runs it, from the session's cwd. Codex's PreToolUse takes a deny in hookSpecificOutput and a systemMessage, and
fails the hook on `continue`/`stopReason`; its Stop wants JSON only on stdout (#88)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "lib"))
from plainspoken import profile, report  # noqa: E402
from plainspoken.registry import load_config  # noqa: E402
from tests.hooks.test_publish_gate import git  # noqa: E402

HOOKS = json.loads((REPO / "hooks" / "codex.json").read_text(encoding="utf-8"))["hooks"]
PID = "KZ-20261014-abc123"


def commands(event: str, matcher: str | None = None) -> list[str]:
    return [h["command"] for g in HOOKS.get(event, []) if matcher is None or g.get("matcher") == matcher
            for h in g["hooks"]]


def codex_run(command: str, event: dict, cwd: Path, data: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_", "PLUGIN_"))}
    env.update({"PLUGIN_ROOT": str(REPO), "CLAUDE_PLUGIN_ROOT": str(REPO), "PLUGIN_DATA": str(data),
                "CLAUDE_PLUGIN_DATA": str(data)})
    base = {"session_id": "019a-codex-s1", "transcript_path": None, "cwd": str(cwd), "model": "gpt-test",
            "turn_id": "t1", "permission_mode": "default"}
    return subprocess.run(command, shell=True, input=json.dumps({**base, **event}), capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=60)


def bash_event(command: str) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "call_1",
            "tool_input": {"command": command}}


class Registration(unittest.TestCase):
    def test_bash_runs_the_gate_and_the_guard(self):
        self.assertEqual(commands("PreToolUse", "Bash"),
                         ['python3 "$PLUGIN_ROOT/hooks/publish_gate.py" --host codex',
                          'python3 "$PLUGIN_ROOT/hooks/write_guard.py" --host codex'])

    def test_stop_runs_the_kaizen_nudge(self):
        self.assertEqual(commands("Stop"), ['python3 "$PLUGIN_ROOT/hooks/kaizen_nudge.py" --host codex'])

    def test_no_backstop(self):  # judges run via spawn_agent or codex exec; no plainspoken agent type to count
        self.assertNotIn("kaizen_backstop", json.dumps(HOOKS))
        self.assertNotIn("SubagentStop", HOOKS)


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        remote, self.project = self.tmp / "remote.git", self.tmp / "proj"
        git("init", "--bare", "-q", "-b", "main", str(remote), cwd=self.tmp)
        git("clone", "-q", str(remote), str(self.project), cwd=self.tmp)
        git("checkout", "-q", "-B", "main", cwd=self.project)
        (self.project / "README").write_text("x\n", encoding="utf-8")
        git("add", ".", cwd=self.project); git("commit", "-qm", "init", cwd=self.project)
        git("push", "-q", "-u", "origin", "HEAD", cwd=self.project)
        (self.project / "docs").mkdir()
        self.art = self.project / "docs" / "post.md"
        self.art.write_text("I fixed it on Friday.\n", encoding="utf-8")
        git("add", ".", cwd=self.project); git("commit", "-qm", "post", cwd=self.project)

    def config(self, strictness: str) -> None:
        (self.project / ".plainspoken").mkdir(exist_ok=True)
        (self.project / ".plainspoken" / "config.toml").write_text(
            f'[gate]\nstrictness = "{strictness}"\npaths = ["docs/**/*.md"]\n', encoding="utf-8")

    def push(self, command: str = "git push") -> list[dict]:
        outs = []
        for hook in commands("PreToolUse", "Bash"):
            r = codex_run(hook, bash_event(command), self.project, self.tmp / "data")
            self.assertEqual((r.returncode, r.stderr), (0, ""), hook)
            outs.append(json.loads(r.stdout) if r.stdout.strip() else {})
        return outs

    def test_block_denies_an_unchecked_gated_file(self):
        self.config("block")
        gate, guard = self.push()
        self.assertEqual(set(gate), {"hookSpecificOutput"})
        out = gate["hookSpecificOutput"]
        self.assertEqual(set(out), {"hookEventName", "permissionDecision", "permissionDecisionReason"})
        self.assertEqual((out["hookEventName"], out["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertIn("docs/post.md: no plainspoken report (run $plainspoken:check docs/post.md)",
                      out["permissionDecisionReason"])
        self.assertEqual(guard, {})

    def test_warn_is_a_message_only(self):
        self.config("warn")
        gate, _ = self.push()
        self.assertEqual(set(gate), {"systemMessage"})  # no continue/stopReason: Codex fails the hook on those
        self.assertIn("run $plainspoken:check docs/post.md", gate["systemMessage"])

    def test_a_current_pass_allows(self):
        self.config("block")
        p = report.report_paths(self.art, self.project / ".plainspoken" / "reports", self.project)["report"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"status": "PASS", "article_sha256": report.sha256(self.art),
                                 "profile_sha256": profile.default().sha256,
                                 "ruleset_version": load_config().version}), encoding="utf-8")
        self.assertEqual(self.push(), [{}, {}])

    def test_no_config_is_silent(self):  # no plugin options on Codex: no config file means watch
        self.assertEqual(self.push(), [{}, {}])

    def test_other_commands_are_silent(self):
        self.config("block")
        self.assertEqual(self.push("git status"), [{}, {}])

    def test_no_gate_paths_is_a_message_only(self):  # #94: block with no [gate] paths used to be silent
        for strictness in ("warn", "block"):
            with self.subTest(strictness=strictness):
                (self.project / ".plainspoken").mkdir(exist_ok=True)
                (self.project / ".plainspoken" / "config.toml").write_text(
                    f'[gate]\nstrictness = "{strictness}"\n', encoding="utf-8")
                gate, guard = self.push()
                self.assertEqual(set(gate), {"systemMessage"})
                self.assertEqual(gate["systemMessage"], f"plainspoken gate: strictness is {strictness} but no "
                                 "[gate] paths are set in .plainspoken/config.toml, so nothing is gated")
                self.assertEqual(guard, {})
                self.assertEqual(self.push("git status"), [{}, {}])
        (self.project / ".plainspoken" / "config.toml").write_text('[gate]\nstrictness = "watch"\n', encoding="utf-8")
        self.assertEqual(self.push(), [{}, {}])


class WriteGuard(unittest.TestCase):
    def test_deny_names_apply_patch(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        hook = commands("PreToolUse", "Bash")[1]
        r = codex_run(hook, bash_event("echo '{}' > .plainspoken/reports/post-1234abcd.reply.json"), tmp, tmp / "d")
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("written with apply_patch, never through the shell", out["permissionDecisionReason"])
        self.assertNotIn("Write or Edit tool", out["permissionDecisionReason"])


class KaizenNudge(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        (self.project / ".git").mkdir()
        (self.project / ".plainspoken" / "ledger").mkdir(parents=True)

    def stop(self) -> subprocess.CompletedProcess:
        event = {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "Done."}
        return codex_run(commands("Stop")[0], event, self.project, self.project / ".data")

    def test_a_waiting_proposal_gives_one_codex_message(self):
        folder = self.project / ".plainspoken" / "kaizen" / "proposals"
        folder.mkdir(parents=True)
        (folder / f"{PID}.json").write_text(json.dumps({"id": PID}), encoding="utf-8")
        r = self.stop()
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(json.loads(r.stdout),
                         {"systemMessage": "plainspoken: 1 kaizen proposal(s) await a decision — "
                                           "$plainspoken:kaizen review"})
        self.assertTrue((self.project / ".data" / "kaizen-nudge-state.json").is_file())  # state in PLUGIN_DATA
        self.assertEqual((self.stop().returncode, self.stop().stdout), (0, ""))  # once per session

    def test_nothing_waiting_is_silent(self):
        r = self.stop()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
