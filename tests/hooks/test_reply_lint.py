"""The chat-reply check (#125): wiring, fast exits, warn-only output, dedupe, overlap with text already linted,
kaizen records and a speed smoke check. Every reply and prompt is synthetic."""
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "reply_lint.py"
sys.path.insert(0, str(REPO / "lib"))
sys.path.insert(0, str(REPO / "hooks"))
import _common  # noqa: E402
from plainspoken import ledger  # noqa: E402

STIFF = ("Hi Jo,\n\nAdditionally, we are delighted to announce our comprehensive new roster. Moreover, it will "
         "streamline the working bee for everyone. Furthermore, it leverages the spare rakes and empowers every "
         "volunteer we have this year.\n\nCheers,\nSam")
FIXED = ("Hi Jo,\n\nThe roster is done. Saturday works for the working bee: I'll bring gloves and the spare rakes, "
         "and Sam can run the sausage sizzle if someone grabs bread on the way.\n\nCheers,\nSam")
ASK = "Can you draft an email to Jo about the working bee?"


def stop(text, session="s1", prompt_id="p1", **extra):
    return {"hook_event_name": "Stop", "session_id": session, "prompt_id": prompt_id, "stop_hook_active": False,
            "last_assistant_message": text, **extra}


def framed(body):
    return "Here's a draft:\n\n```\n" + body + "\n```\n\nWant me to make it shorter?"


class Base(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.project / ".plainspoken").mkdir()
        (self.project / ".git").mkdir()
        self.data = self.home / "data"

    def config(self, text):
        (self.project / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def env(self, **over):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_", "PLUGIN_"))}
        env.update({"CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_PLUGIN_DATA": str(self.data),
                    "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")})
        env.update(over)
        return {k: v for k, v in env.items() if v is not None}

    def ask(self, kind="draft", session="s1", prompt="p1"):
        """What nudge.py records on UserPromptSubmit when the check is on."""
        _common.record_state(self.data, _common.ASK_STATE, f"{session}|{prompt}", kind)

    def run_raw(self, stdin, *args, **env_over):
        return subprocess.run([sys.executable, str(HOOK), *args], input=stdin, capture_output=True, text=True,
                              env=self.env(**env_over), cwd=self.project, timeout=60)

    def run_hook(self, payload, *args, **env_over):
        done = self.run_raw(json.dumps(payload), *args, **env_over)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout) if done.stdout.strip() else None
        if out is not None:
            self.assertEqual(set(out), {"systemMessage"})  # never a decision, reason, context or continue
        return out

    def rows(self):
        from plainspoken import config
        return ledger.read_rows(config.kaizen_settings(self.project, {}), "chat-replies.jsonl")[0]


class Wiring(unittest.TestCase):
    def test_claude_code_stop_group(self):
        stops = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["Stop"]
        hooks = [h for g in stops for h in g["hooks"]]
        mine = [h for h in hooks if h["args"] == ["${CLAUDE_PLUGIN_ROOT}/hooks/reply_lint.py"]]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["timeout"], 10)
        self.assertNotIn("async", mine[0])  # an async systemMessage goes to the model on Claude Code

    def test_codex_stop_group(self):
        stops = json.loads((REPO / "hooks" / "codex.json").read_text(encoding="utf-8"))["hooks"]["Stop"]
        commands = [h["command"] for g in stops for h in g["hooks"]]
        self.assertIn('python3 "$PLUGIN_ROOT/hooks/reply_lint.py" --host codex', commands)

    def test_claude_option_is_off_by_default(self):
        uc = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["userConfig"]
        self.assertEqual((uc["chat_reply"]["type"], uc["chat_reply"]["default"]), ("boolean", False))


class FastExits(Base):
    def test_off_by_default(self):
        self.ask()
        self.assertIsNone(self.run_hook(stop(framed(STIFF))))
        self.assertEqual(self.rows(), [])

    def test_no_writing_ask_no_reply_or_a_bad_event_says_nothing(self):
        self.config('[chat_reply]\nmode = "warn"\n')
        self.assertIsNone(self.run_hook(stop(framed(STIFF))))  # no flag for this turn
        self.ask(prompt="other")
        self.assertIsNone(self.run_hook(stop(framed(STIFF))))
        self.ask()
        for payload in (stop(None), stop(""), stop(42), ["not", "a", "dict"]):
            self.assertIsNone(self.run_hook(payload))
        for raw in ("not json", ""):
            done = self.run_raw(raw)
            self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertEqual(self.rows(), [])  # only turns with a writing ask and a reply are logged

    def test_off_by_default_never_loads_the_config_reader_or_the_engine(self):
        self.ask()
        probe = ("import io, json, sys; sys.path.insert(0, %r); import reply_lint; "
                 "sys.stdin = io.StringIO(sys.argv[1]); reply_lint.main([]); "
                 "print(json.dumps(sorted(m for m in sys.modules if m.startswith('plainspoken'))))"
                 % str(REPO / "hooks"))
        done = subprocess.run([sys.executable, "-c", probe, json.dumps(stop(framed(STIFF)))], capture_output=True,
                              text=True, env=self.env(), cwd=self.project)
        loaded = json.loads(done.stdout.strip().splitlines()[-1])
        for heavy in ("plainspoken.config", "plainspoken.report", "plainspoken.registry", "plainspoken.capture"):
            self.assertNotIn(heavy, loaded)

    def test_bad_config_or_a_broken_profile_never_fails(self):
        self.ask()
        self.config("[chat_reply\n")
        self.assertIsNone(self.run_hook(stop(framed(STIFF))))
        self.config('[chat_reply]\nmode = "warn"\n')
        self.assertIsNone(self.run_hook(stop(framed(STIFF)), PLAINSPOKEN_PROFILE="no-such-profile"))
        from plainspoken import config
        rows, _ = ledger.read_friction(config.kaizen_settings(self.project, {}))
        self.assertEqual([(r["kind"], r["source"]) for r in rows], [("capture_error", "chat-reply")])

    def test_a_write_report_is_left_to_the_report_guard(self):
        self.config('[chat_reply]\nmode = "warn"\n')
        self.ask()
        report = framed(STIFF) + "\n\nDraft: email.md (40 words)\ncheck: PASS\nneeds the owner: none\n"
        self.assertIsNone(self.run_hook(stop(report)))
        self.assertEqual([r["outcome"] for r in self.rows()], ["write-report"])


class Warn(Base):
    def setUp(self):
        super().setUp()
        self.config('[chat_reply]\nmode = "warn"\n')
        self.ask()

    def test_a_draft_with_tells_gets_one_message(self):
        out = self.run_hook(stop(framed(STIFF)))
        lines = out["systemMessage"].splitlines()
        self.assertTrue(lines[0].startswith("plainspoken: the draft in this reply (email, "), lines[0])
        self.assertIn("judges not run", lines[0])
        self.assertIn("BLOCK", out["systemMessage"])
        self.assertIn("/plainspoken:check", lines[-1])
        self.assertLessEqual(len(lines), 6)

    def test_a_clean_draft_or_no_draft_says_nothing(self):
        self.assertIsNone(self.run_hook(stop(framed(FIXED))))
        self.assertIsNone(self.run_hook(stop("The hook reads the last message and lints it.")))
        self.assertEqual([r["outcome"] for r in self.rows()], ["clean", "no-draft"])

    def test_stop_hook_active_still_lints(self):
        self.assertIsNotNone(self.run_hook(stop(framed(STIFF), stop_hook_active=True)))

    def test_the_same_draft_is_reported_once_and_a_changed_one_again(self):
        self.assertIsNotNone(self.run_hook(stop(framed(STIFF))))
        self.assertIsNone(self.run_hook(stop(framed(STIFF))))
        changed = STIFF.replace("Sam", "Priya")
        self.assertIsNotNone(self.run_hook(stop(framed(changed))))
        self.assertEqual([r["outcome"] for r in self.rows()], ["warned", "repeat", "warned"])

    def test_text_already_linted_this_session_is_skipped(self):
        body = STIFF.split("\n\n")[1]
        _common.remember_linted(self.data, "s1", [body])  # what lint-watch or the tool-call check recorded
        self.assertIsNone(self.run_hook(stop("Here's what I saved to email.md:\n\n> " + body)))
        self.assertEqual([r["outcome"] for r in self.rows()], ["seen"])

    def test_codex(self):
        self.ask(prompt="t1")
        self.assertIsNone(self.run_hook(stop(None, prompt_id=None, turn_id="t1"), "--host", "codex"))
        out = self.run_hook(stop(framed(STIFF), prompt_id=None, turn_id="t1"), "--host", "codex")
        self.assertIn("$plainspoken:check", out["systemMessage"])

    def test_latest_slot_when_the_host_sends_no_turn_id(self):
        self.ask(prompt="latest")
        self.assertIsNotNone(self.run_hook(stop(framed(STIFF), prompt_id=None)))

    def test_hermes_reads_the_prompt_itself(self):
        payload = {**stop(framed(STIFF), session="h1", prompt_id=None, turn_id="u1"),
                   "prompt": "What does the hook do?"}
        self.assertIsNone(self.run_hook(payload, "--host", "hermes"))
        out = self.run_hook({**payload, "prompt": ASK}, "--host", "hermes")
        self.assertIn("plainspoken:check", out["systemMessage"])
        self.assertNotIn("/plainspoken:check", out["systemMessage"])

    def test_min_words_from_config(self):
        self.config('[chat_reply]\nmode = "warn"\nmin_words = 200\n')
        self.assertIsNone(self.run_hook(stop(framed(STIFF))))


class Kaizen(Base):
    def setUp(self):
        super().setUp()
        self.ask()

    def test_events_and_rows_carry_no_text(self):
        self.config('[chat_reply]\nmode = "warn"\n[kaizen]\nexcerpts = true\n')
        self.run_hook(stop(framed(STIFF)))
        (row,) = self.rows()
        self.assertEqual((row["outcome"], row["shape"], row["ask"], row["host"]), ("warned", "fence", "draft",
                                                                                   "claude-code"))
        raw = "".join(p.read_text(encoding="utf-8") for p in (self.project / ".plainspoken" / "ledger").iterdir())
        for word in ("delighted", "Additionally", "roster", "Jo,"):
            self.assertNotIn(word, raw)
        from plainspoken import config
        events, _ = ledger.read(config.kaizen_settings(self.project, {}))
        self.assertTrue(events)
        self.assertEqual({e["doc_id"] for e in events}, {row["doc"]})
        self.assertTrue(all("excerpt" not in e for e in events))

    def test_capture_sources_without_chat_reply_records_nothing(self):
        self.config('[chat_reply]\nmode = "warn"\n[kaizen]\ncapture_sources = ["check"]\n')
        self.assertIsNotNone(self.run_hook(stop(framed(STIFF))))
        self.assertFalse((self.project / ".plainspoken" / "ledger").exists())

    def test_no_plainspoken_folder_means_no_ledger_but_the_check_still_runs(self):
        shutil.rmtree(self.project / ".plainspoken")
        user = self.home / ".config" / "plainspoken" / "config.toml"
        user.parent.mkdir(parents=True)
        user.write_text('[chat_reply]\nmode = "warn"\n', encoding="utf-8")
        self.assertIsNotNone(self.run_hook(stop(framed(STIFF))))
        self.assertFalse((self.project / ".plainspoken").exists())


class Speed(Base):
    """A smoke check with loose bounds, not a benchmark."""

    def median_ms(self, payload, runs=5):
        times = []
        for _ in range(runs):
            start = time.perf_counter()
            self.run_hook(payload)
            times.append((time.perf_counter() - start) * 1000)
        return statistics.median(times)

    def test_no_ask_and_lint_paths(self):
        self.config('[chat_reply]\nmode = "warn"\n')
        self.assertLess(self.median_ms(stop(framed(STIFF), prompt_id="none")), 150)
        self.ask()
        self.assertLess(self.median_ms(stop(framed(FIXED))), 600)


if __name__ == "__main__":
    unittest.main()
