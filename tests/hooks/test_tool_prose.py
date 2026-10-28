"""The tool-call check hook (#124): wiring, fast exits, modes per host, drafts, block-once state, profile order, kaizen
records and a speed smoke check. Every payload is synthetic."""
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
HOOK = REPO / "hooks" / "tool_prose.py"
sys.path.insert(0, str(REPO / "lib"))
from plainspoken import ledger  # noqa: E402

STIFF = ("Additionally, we are delighted to announce our comprehensive new booking page. Moreover, it will "
         "streamline everything for you. Furthermore, it leverages the latest tools to empower every customer we "
         "serve across the region this year.")
FIXED = ("The booking page is live. You pick a time, pay the deposit and get a text the day before. If the time "
         "doesn't suit, reply to the text and I'll move it for you, no trouble at all.")
SHORT = "Running ten minutes late, sorry. See you at the cafe soon."


def event(body=STIFF, tool="mcp__outbox__send", session="s1", prompt="p1", **extra):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "session_id": session, "prompt_id": prompt,
            "tool_input": {"to": "sam@example.com", "subject": "Booking page", "body": body}, **extra}


class Base(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.project / ".plainspoken").mkdir()

    def config(self, text):
        (self.project / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def env(self, **over):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_", "PLUGIN_"))}
        env.update({"CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_PLUGIN_DATA": str(self.project / ".data"),
                    "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")})
        env.update(over)
        return {k: v for k, v in env.items() if v is not None}

    def run_hook(self, payload, *args, **env_over):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        done = subprocess.run([sys.executable, str(HOOK), *args], input=stdin, capture_output=True, text=True,
                              env=self.env(**env_over), cwd=self.project, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def rows(self):
        from plainspoken import config
        return ledger.read_rows(config.kaizen_settings(self.project, {}), "tool-calls.jsonl")[0]


class Wiring(unittest.TestCase):
    def test_claude_code_group(self):
        hooks = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        group = [g for g in hooks if g.get("matcher") == "mcp__.*"]
        self.assertEqual(len(group), 1)
        (hook,) = group[0]["hooks"]
        self.assertEqual(hook["args"], ["${CLAUDE_PLUGIN_ROOT}/hooks/tool_prose.py"])
        self.assertEqual(hook["timeout"], 10)
        self.assertNotIn("onFailure", hook)

    def test_codex_group(self):
        hooks = json.loads((REPO / "hooks" / "codex.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        group = [g for g in hooks if g.get("matcher") == "^mcp__"]
        self.assertEqual(len(group), 1)
        (hook,) = group[0]["hooks"]
        self.assertEqual(hook["command"], 'python3 "$PLUGIN_ROOT/hooks/tool_prose.py" --host codex')
        self.assertEqual(hook["timeout"], 10)
        self.assertNotIn("onFailure", hook)


class FastExits(Base):
    def test_nothing_to_do_prints_nothing(self):
        self.config('[tool_call]\nmode = "warn"\n')
        for payload in ("not json", "[]", {"tool_name": "mcp__outbox__send"},
                        {"tool_name": "mcp__outbox__send", "tool_input": "text"},
                        event(tool="mcp__firecrawl__firecrawl_scrape"), event(tool="Bash"),
                        event(body=SHORT)):
            with self.subTest(payload=str(payload)[:60]):
                self.assertIsNone(self.run_hook(payload))

    def test_off_unless_turned_on(self):
        self.assertIsNone(self.run_hook(event()))  # no config at all
        self.config('[tool_call]\nmode = "off"\n')
        self.assertIsNone(self.run_hook(event(), CLAUDE_PLUGIN_OPTION_TOOL_CALL="block-once"))
        (self.project / ".plainspoken" / "config.toml").unlink()
        user = self.home / ".config" / "plainspoken" / "config.toml"
        user.parent.mkdir(parents=True)
        user.write_text('[tool_call]\nmode = "off"\n', encoding="utf-8")
        self.assertIsNone(self.run_hook(event()))

    def test_skip_paths_never_import_the_lint_engine(self):
        self.config('[tool_call]\nmode = "warn"\n')
        probe = ("import io, json, sys; sys.path.insert(0, %r); import tool_prose; "
                 "sys.stdin = io.StringIO(sys.argv[1]); tool_prose.main([]); "
                 "print(json.dumps(sorted(m for m in sys.modules if m.startswith('plainspoken'))))"
                 % str(REPO / "hooks"))
        for payload in (event(tool="mcp__firecrawl__firecrawl_scrape"), event(body=SHORT)):
            done = subprocess.run([sys.executable, "-c", probe, json.dumps(payload)], capture_output=True,
                                  text=True, env=self.env(), cwd=self.project)
            loaded = json.loads(done.stdout.strip().splitlines()[-1])
            for heavy in ("plainspoken.report", "plainspoken.registry", "plainspoken.config", "plainspoken.capture"):
                self.assertNotIn(heavy, loaded, payload["tool_name"])


class Modes(Base):
    def test_clean_text_says_nothing(self):
        self.config('[tool_call]\nmode = "block-once"\n')
        self.assertIsNone(self.run_hook(event(body=FIXED)))

    def test_warn(self):
        self.config('[tool_call]\nmode = "warn"\n')
        out = self.run_hook(event())
        self.assertIn("mcp__outbox__send", out["systemMessage"])
        self.assertIn("BLOCK", out["systemMessage"])
        specific = out["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", specific)
        self.assertIn("body", specific["additionalContext"])
        self.assertNotIn("Additionally, we are delighted", specific["additionalContext"])

    def test_block_once_then_the_same_text_passes(self):
        self.config('[tool_call]\nmode = "block-once"\n')
        out = self.run_hook(event())
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("hasn't run", reason)
        self.assertIn("same text sent again goes through", reason)
        self.assertIsNone(self.run_hook(event()))  # resent unchanged: through, silently
        outcomes = [r["outcome"] for r in self.rows() if r["field"] == "body"]
        self.assertEqual(outcomes, ["blocked", "resent-unchanged"])

    def test_a_changed_text_with_findings_in_the_same_turn_is_warned_not_blocked(self):
        self.config('[tool_call]\nmode = "block-once"\n')
        self.run_hook(event())
        out = self.run_hook(event(body=STIFF.replace("Additionally", "Also")))
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        self.assertIn("systemMessage", out)
        # a new turn may block again
        out = self.run_hook(event(body=STIFF.replace("Additionally", "Further"), prompt="p2"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_ask_on_claude_code(self):
        self.config('[tool_call]\nmode = "ask"\n')
        out = self.run_hook(event())
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        self.assertIn("BLOCK", out["hookSpecificOutput"]["permissionDecisionReason"])
        # the same text again: the person is asked again, never waved through; a changed one is only warned
        self.assertEqual(self.run_hook(event())["hookSpecificOutput"]["permissionDecision"], "ask")
        out = self.run_hook(event(body=STIFF.replace("Additionally", "Also")))
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])

    def test_ask_is_block_once_on_codex_and_hermes(self):
        self.config('[tool_call]\nmode = "ask"\n')
        for host, session in (("codex", "c1"), ("hermes", "h1")):
            with self.subTest(host=host):
                payload = event(session=session, prompt=None, turn_id="t1")
                out = self.run_hook(payload, "--host", host)
                self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
                self.assertIsNone(self.run_hook(payload, "--host", host))

    def test_codex_skill_names(self):
        self.config('[tool_call]\nmode = "warn"\n')
        out = self.run_hook(event(prompt=None, turn_id="t1"), "--host", "codex")
        self.assertIn("$plainspoken:check", out["hookSpecificOutput"]["additionalContext"])

    def test_drafts_are_only_warned(self):
        self.config('[tool_call]\nmode = "block-once"\n')
        for tool in ("mcp__claude_ai_Gmail__create_draft", "mcp__mail__update_draft"):
            with self.subTest(tool=tool):
                out = self.run_hook(event(tool=tool))
                self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
                self.assertIn("systemMessage", out)

    def test_never_rewrites_allows_or_modifies(self):
        for mode in ("warn", "block-once", "ask"):
            self.config(f'[tool_call]\nmode = "{mode}"\n')
            for host in ("claude-code", "codex", "hermes"):
                for body in (STIFF, FIXED, STIFF + " Extra words for " + mode + host + "."):
                    out = self.run_hook(event(body=body, session=f"{mode}{host}"), "--host", host)
                    text = json.dumps(out)
                    self.assertNotIn("updatedInput", text)
                    self.assertNotIn('"allow"', text)
                    self.assertNotIn('"modify"', text)

    def test_skip_and_include_from_config(self):
        self.config('[tool_call]\nmode = "warn"\nskip = ["*outbox*"]\n')
        self.assertIsNone(self.run_hook(event()))
        self.config('[tool_call]\nmode = "warn"\ninclude = ["*trello*"]\n')
        self.assertIsNotNone(self.run_hook(event(tool="mcp__trello__add_comment")))

    def test_min_words_from_config(self):
        self.config('[tool_call]\nmode = "warn"\nmin_words = 200\n')
        self.assertIsNone(self.run_hook(event()))


class Profiles(Base):
    def test_tool_call_profile_is_used_and_a_bad_one_never_denies(self):
        self.config('[tool_call]\nmode = "block-once"\nprofile = "no-such-profile"\n')
        out = self.run_hook(event())
        self.assertNotIn("permissionDecision", out.get("hookSpecificOutput", {}))
        self.assertIn("skipped", out["hookSpecificOutput"]["additionalContext"])
        self.config('[tool_call]\nmode = "warn"\nprofile = "no-such-profile"\n')
        out = self.run_hook(event(session="s2"))
        self.assertIn("skipped", out["hookSpecificOutput"]["additionalContext"])

    def test_env_profile_beats_the_section(self):
        self.config('[tool_call]\nmode = "warn"\nprofile = "no-such-profile"\n')
        out = self.run_hook(event(), PLAINSPOKEN_PROFILE="default")
        self.assertIn("BLOCK", out["systemMessage"])


class Kaizen(Base):
    def test_rows_and_events_carry_no_text(self):
        self.config('[tool_call]\nmode = "warn"\n[kaizen]\nexcerpts = true\n')
        self.run_hook(event())
        rows = self.rows()
        body = [r for r in rows if r["field"] == "body"]
        self.assertEqual(len(body), 1)
        self.assertEqual((body[0]["outcome"], body[0]["tool_name"], body[0]["host"]), ("warned", "send",
                                                                                     "claude-code"))
        self.assertNotEqual(body[0]["tool_server_hash"], "outbox")
        raw = "".join(p.read_text(encoding="utf-8") for p in (self.project / ".plainspoken" / "ledger").iterdir())
        for word in ("delighted", "Additionally", "sam@example.com"):
            self.assertNotIn(word, raw)
        from plainspoken import config
        events, _ = ledger.read(config.kaizen_settings(self.project, {}))
        self.assertTrue(events)
        self.assertTrue(all(e["doc_id"] == ledger.label_id("tool-call:mcp__outbox__send|body") for e in events))

    def test_near_miss_is_logged_and_tiny_fields_are_not(self):
        self.config('[tool_call]\nmode = "warn"\n')
        near = "The plants went in this morning and the soil is still damp, so I'll water them tomorrow instead."
        self.run_hook(event(body=near))
        outcomes = {r["field"]: r["outcome"] for r in self.rows()}
        self.assertEqual(outcomes, {"body": "below-cutoff"})

    def test_no_plainspoken_folder_means_no_ledger_but_the_check_still_runs(self):
        shutil.rmtree(self.project / ".plainspoken")
        user = self.home / ".config" / "plainspoken" / "config.toml"
        user.parent.mkdir(parents=True)
        user.write_text('[tool_call]\nmode = "warn"\n', encoding="utf-8")
        self.assertIn("systemMessage", self.run_hook(event()))
        self.assertFalse((self.project / ".plainspoken").exists())

    def test_linted_texts_are_remembered_for_the_reply_check(self):
        sys.path.insert(0, str(REPO / "hooks"))
        import _common
        self.config('[tool_call]\nmode = "warn"\n')
        self.run_hook(event())
        self.assertTrue(_common.linted_before(self.project / ".data", "s1", STIFF))


class Speed(Base):
    """A smoke check with loose bounds, not a benchmark."""

    def median_ms(self, payload, runs=5):
        times = []
        for _ in range(runs):
            start = time.perf_counter()
            self.run_hook(payload)
            times.append((time.perf_counter() - start) * 1000)
        return statistics.median(times)

    def test_skip_path_and_lint_path(self):
        self.config('[tool_call]\nmode = "warn"\n')
        self.assertLess(self.median_ms(event(tool="mcp__firecrawl__firecrawl_scrape")), 100)
        body = " ".join([FIXED] * 9)  # about 300 words
        self.assertLess(self.median_ms(event(body=body)), 600)


if __name__ == "__main__":
    unittest.main()
