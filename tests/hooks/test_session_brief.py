import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "session_brief.py"
sys.path.insert(0, str(REPO / "lib"))
sys.path.insert(0, str(REPO / "hooks"))
from plainspoken import config  # noqa: E402
import session_brief  # noqa: E402


def agent_names() -> list[str]:
    """Every plainspoken agent, from the `name:` in each agents/*.md frontmatter."""
    names = [re.search(r"(?m)^name:\s*(\S+)", p.read_text(encoding="utf-8")).group(1)
             for p in sorted((REPO / "agents").glob("*.md"))]
    assert len(names) >= 4, names
    return names


class Brief(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)

    def config(self, text: str) -> None:
        (self.project / ".plainspoken").mkdir(exist_ok=True)
        (self.project / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def run_hook(self, payload):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env["CLAUDE_PROJECT_DIR"] = str(self.project)
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env)

    def start(self):
        return {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(self.project)}

    def sub(self, agent):
        return {"hook_event_name": "SubagentStart", "agent_type": agent, "cwd": str(self.project)}

    def context(self, r):
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_off_without_config(self):
        r = self.run_hook(self.start())
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_off_without_brief_section(self):
        self.config('[engine]\nprofile = "default"\n')
        self.assertEqual(self.run_hook(self.start()).stdout.strip(), "")

    def test_explicitly_off_is_silent(self):
        self.config("[brief]\nenabled = false\n")
        self.assertEqual(self.run_hook(self.start()).stdout.strip(), "")

    def test_on_adds_the_brief(self):
        self.config("[brief]\nenabled = true\n")
        r = self.run_hook(self.start())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLessEqual(len(self.context(r)), 800)
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_on_for_an_ordinary_subagent(self):
        self.config("[brief]\nenabled = true\n")
        self.assertTrue(self.context(self.run_hook(self.sub("general-purpose"))))

    def test_never_for_plainspoken_agents(self):  # judges stay isolated
        self.config("[brief]\nenabled = true\n")
        for agent in ("plainspoken:tells-judge", "plainspoken:cold-reader", "plainspoken:anything-later"):
            self.assertEqual(self.run_hook(self.sub(agent)).stdout.strip(), "", agent)

    def test_never_at_session_start_for_a_plainspoken_agent_type(self):
        self.config("[brief]\nenabled = true\n")
        for name in agent_names():
            event = {**self.start(), "agent_type": f"plainspoken:{name}"}
            self.assertEqual(self.run_hook(event).stdout.strip(), "", name)
        self.assertTrue(self.context(self.run_hook({**self.start(), "agent_type": "general-purpose"})))

    def test_never_for_any_shipped_agent(self):
        self.config("[brief]\nenabled = true\n")
        for name in agent_names():
            self.assertEqual(self.run_hook(self.sub(f"plainspoken:{name}")).stdout.strip(), "", name)

    def test_the_probed_subagent_stdin_is_silent(self):  # the literal the live probe recorded
        facts = (REPO / "docs" / "claude-code-facts.md").read_text(encoding="utf-8")
        literal = re.search(r"`agent_type` was exactly `([^`]+)`", facts).group(1)
        self.assertEqual(literal, "plainspoken:tells-judge")
        self.assertTrue(literal.startswith(session_brief.OWN_AGENTS))
        self.config("[brief]\nenabled = true\n")
        probed = {"hook_event_name": "SubagentStart", "agent_type": literal, "agent_id": "a1b2c3",
                  "session_id": "s1", "prompt_id": "p1", "cwd": str(self.project),
                  "transcript_path": str(self.project / "t.jsonl")}
        r = self.run_hook(probed)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_a_long_brief_is_cut_at_a_sentence_end(self):  # never mid-sentence
        self.config("[brief]\nenabled = true\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env["CLAUDE_PROJECT_DIR"] = str(self.project)
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(session_brief, "LIMIT", 100), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(self.start()))), contextlib.redirect_stdout(out):
            session_brief.main()
        text = json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
        brief = (REPO / "data" / "brief.md").read_text(encoding="utf-8").strip()
        self.assertLessEqual(len(text), 100)
        self.assertTrue(text.endswith("."), text)
        self.assertTrue(brief.startswith(text))
        self.assertEqual(brief[len(text)], " ")

    def test_bad_config_is_silent(self):
        self.config("[brief\n")
        r = self.run_hook(self.start())
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_non_boolean_config_is_silent(self):
        self.config('[brief]\nenabled = "yes"\n')
        r = self.run_hook(self.start())
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_malformed_stdin_is_silent(self):
        r = self.run_hook("{not json")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_brief_enabled_rejects_a_non_boolean(self):
        self.config('[brief]\nenabled = "yes"\n')
        with self.assertRaises(config.ConfigError) as cm:
            config.brief_enabled(self.project)
        self.assertIn("[brief] enabled", str(cm.exception))

    def test_brief_enabled_reads_true_and_defaults_false(self):
        self.assertFalse(config.brief_enabled(self.project))
        self.config("[brief]\nenabled = true\n")
        self.assertTrue(config.brief_enabled(self.project))

    def test_brief_file_fits(self):
        self.assertLessEqual(len((REPO / "data" / "brief.md").read_text(encoding="utf-8").strip()), 800)

    def test_registered(self):
        hooks = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        for event in ("SessionStart", "SubagentStart"):
            args = [a for entry in hooks[event] for h in entry["hooks"] for a in h["args"]]
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/session_brief.py", args)


class Fit(unittest.TestCase):  # the cut lands on a sentence end, else a word end
    def test_short_text_is_whole(self):
        self.assertEqual(session_brief.fit("One. Two.", 800), "One. Two.")

    def test_cut_after_the_last_sentence_that_fits(self):
        self.assertEqual(session_brief.fit("One two. Three four! Five six seven eight.", 25), "One two. Three four!")

    def test_a_decimal_point_is_not_a_sentence_end(self):
        self.assertEqual(session_brief.fit("It rose 3.5 times. It fell again soon after.", 22), "It rose 3.5 times.")
        self.assertEqual(session_brief.fit("It rose 3.5 times over the year.", 12), "It rose 3.5")

    def test_no_sentence_end_cuts_at_a_space_then_hard(self):
        self.assertEqual(session_brief.fit("alpha beta gamma delta", 13), "alpha beta")
        self.assertEqual(session_brief.fit("x" * 30, 10), "x" * 10)


class OutputStyle(unittest.TestCase):
    def test_style_is_optional_and_short(self):
        from scripts.dev.lint_frontmatter import parse_frontmatter
        text = (REPO / "output-styles" / "plainspoken.md").read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        self.assertLessEqual(set(fm), {"name", "description", "keep-coding-instructions"})
        self.assertNotIn("force-for-plugin", text)
        self.assertLessEqual(len(text.splitlines()), 60)

    def test_no_ban_list_words(self):  # drafting guidance stays positive
        import re
        from plainspoken.registry import load_config
        for rel in ("output-styles/plainspoken.md", "data/brief.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            for w in load_config().lists["ban_literal"]:
                self.assertIsNone(re.search(rf"\b{re.escape(w)}\b", text, re.I), f"{rel}: {w}")


class DraftingRule(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def run_hook(self, event_name="SessionStart", **env_over):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env.pop("XDG_CONFIG_HOME", None)
        env.update({"HOME": str(self.home), "CLAUDE_PROJECT_DIR": str(self.project)}, **env_over)
        event = {"hook_event_name": event_name, "source": "startup", "cwd": str(self.project)}
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True,
                              env=env)

    def context(self, r):
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else None

    def test_off_by_default(self):
        self.assertIsNone(self.context(self.run_hook()))

    def test_option_turns_it_on_with_live_paths(self):
        ctx = self.context(self.run_hook(CLAUDE_PLUGIN_OPTION_RULE="true"))
        self.assertIn(f"python3 {REPO}/lib/run.py check -", ctx)
        self.assertIn("/plainspoken:check", ctx)
        self.assertNotIn("{", ctx)

    def test_user_config_turns_it_on_without_a_project_config(self):
        user = self.home / ".config" / "plainspoken" / "config.toml"
        user.parent.mkdir(parents=True)
        user.write_text("[rule]\nenabled = true\n", encoding="utf-8")
        self.assertIn("Drafting rule", self.context(self.run_hook()))

    def test_not_for_subagents(self):
        self.assertIsNone(self.context(self.run_hook("SubagentStart", CLAUDE_PLUGIN_OPTION_RULE="true")))

    def test_rule_and_brief_together(self):
        (self.project / ".plainspoken").mkdir()
        (self.project / ".plainspoken" / "config.toml").write_text(
            "[rule]\nenabled = true\n[brief]\nenabled = true\n", encoding="utf-8")
        ctx = self.context(self.run_hook())
        self.assertIn("Drafting rule", ctx)
        self.assertIn("When you write prose for a reader", ctx)

    def test_short_piece_lint_never_stands_in_for_write(self):  # #23: write ran the bare lint instead of 6 and 7
        flat = " ".join(session_brief.rule_text(REPO, "default").split())
        self.assertIn("Short piece, outside /plainspoken:write:", flat)
        self.assertIn("Inside /plainspoken:write, this lint never replaces its check and claims steps.", flat)

    def test_rule_fits_whole_under_a_long_plugin_root(self):  # a cut would drop the fabrication guard at the end
        root = "/home/someone-with-a-long-name/.claude/plugins/cache/a-long-marketplace-name/plainspoken/9.99.99"
        text = session_brief.rule_text(REPO, "default")
        self.assertTrue(text.endswith("ask instead."))
        self.assertLessEqual(len(text) - len(str(REPO)) + len(root), session_brief.RULE_LIMIT)
