import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "nudge.py"
sys.path.insert(0, str(REPO / "lib"))
sys.path.insert(0, str(REPO / "hooks"))
import nudge  # noqa: E402

DRAFT = [
    "Can you draft an email to the class parents about Friday's excursion?",
    "write a LinkedIn post about the new booking page",
    "Draft a text message to Sam saying I'll be late",
    "Write me a 60-second video script for the launch",
    "can you write the podcast intro for episode 12",
    "Put together a newsletter for March from these notes",
    "write a pamphlet for the open day",
    "Draft a reply to this customer email: ...",
    "Write three tweets announcing the release",
    "draft the about page copy",
    "Write a short bio for the conference program",
    "help me word a message to my landlord",
]
REWRITE = [
    "Can you rewrite this email to the class parents so it sounds like a person wrote it?",
    "Make this sound less like ChatGPT wrote it",
    "This reads like a bot. Fix it.",
    "humanise this paragraph",
    "De-AI this short paragraph",
    "Make it less stiff: we are delighted to announce...",
    "Here's our newsletter opening. Make it less stiff. Just send back the rewritten version.",
    "Rewrite this product update so our customers actually want to read it. Plain words, please.",
]
QUIET = [
    "What's the capital of France?",
    "Write a Python function that parses dates",
    "write a bash script to back up the folder",
    "Fix the failing unit test in test_cli.py",
    "draft a commit message for these changes",
    "/plainspoken:check post.md",
    "Run plainspoken check on post.md",
    "Can you explain how the em-dash rule works?",
    "Translate this email into French",
    "Summarise this article for me",
]


class Matcher(unittest.TestCase):
    def test_drafting_prompts_fire_as_draft(self):
        for p in DRAFT:
            with self.subTest(p=p):
                self.assertIn(nudge.intent(p), ("draft", "draft-long"))

    def test_long_pieces_go_to_write(self):
        for p in ("Write a blog post (about 600 words) for our club website about the rosters",
                  "Draft the service page for my bookkeeping business's website",
                  "Can you write a newsletter feature on the repair cafe?",
                  "Write a 300-word email to the board about the budget"):
            with self.subTest(p=p):
                self.assertEqual(nudge.intent(p), "draft-long")
        for p in ("Draft a text message to Sam saying I'll be late", "Write three tweets announcing the release",
                  "Write a short bio for the conference program"):
            with self.subTest(p=p):
                self.assertEqual(nudge.intent(p), "draft")

    def test_rewrite_prompts_fire_as_rewrite(self):
        for p in REWRITE:
            with self.subTest(p=p):
                self.assertEqual(nudge.intent(p), "rewrite")

    def test_other_prompts_stay_quiet(self):
        for p in QUIET:
            with self.subTest(p=p):
                self.assertIsNone(nudge.intent(p))

    def test_ask_buried_in_a_long_paste_is_found_at_either_end(self):
        filler = "Lorem ipsum dolor sit amet. " * 200
        self.assertEqual(nudge.intent("Rewrite this so it sounds human:\n\n" + filler), "rewrite")
        self.assertEqual(nudge.intent(filler + "\n\nCan you draft a reply email to this?"), "draft")


class Text(unittest.TestCase):
    def test_claude_code_text_names_the_commands(self):
        t = nudge.nudge_text("draft", "claude-code", "/p/root", "default")
        self.assertIn("python3 /p/root/lib/run.py check -", t)
        self.assertIn("/plainspoken:write", t)
        self.assertIn("--plugin-profile 'default'", t)
        self.assertLessEqual(len(t), nudge.LIMIT)

    def test_short_draft_lint_never_stands_in_for_write(self):  # #23
        for host in nudge.HOSTS:
            t = nudge.nudge_text("draft", host, "/a/very/long/plugin/root/path/x", "default")
            self.assertTrue(t.endswith("this lint never replaces its check and claims steps."), host)

    def test_long_text_names_write(self):
        self.assertIn("/plainspoken:write", nudge.nudge_text("draft-long", "claude-code", "/p/root", "default"))
        self.assertIn("$plainspoken:write", nudge.nudge_text("draft-long", "codex", "/p/root", "default"))

    def test_codex_uses_dollar_syntax(self):
        t = nudge.nudge_text("rewrite", "codex", "/p/root", "default")
        self.assertIn("$plainspoken:humanize", t)
        self.assertNotIn("/plainspoken:", t)

    def test_hermes_names_skills(self):
        t = nudge.nudge_text("draft", "hermes", "/p/root", "default")
        self.assertIn("plainspoken:write", t)
        self.assertNotIn("$plainspoken", t)

    def test_every_text_fits(self):
        for kind in ("draft", "draft-long", "rewrite"):
            for host in nudge.HOSTS:
                self.assertLessEqual(len(nudge.nudge_text(kind, host, "/a/very/long/plugin/root/path/x", "default")),
                                     nudge.LIMIT)


class Hook(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)

    def run_hook(self, prompt: str, env: dict | None = None, args: tuple = ()):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_"))}
        e.update({"HOME": str(self.home), "CLAUDE_PROJECT_DIR": str(self.project)})
        e.pop("XDG_CONFIG_HOME", None)
        e.update(env or {})
        event = {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "cwd": str(self.project), "session_id": "s"}
        return subprocess.run([sys.executable, str(HOOK), *args], input=json.dumps(event), capture_output=True,
                              text=True, env=e)

    def test_off_by_default(self):
        r = self.run_hook(DRAFT[0])
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def test_on_by_option(self):
        r = self.run_hook(DRAFT[0], {"CLAUDE_PLUGIN_OPTION_NUDGE": "true"})
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "UserPromptSubmit")
        self.assertIn("/plainspoken:write", out["additionalContext"])

    def test_on_by_project_config_and_codex_host(self):
        (self.project / ".plainspoken").mkdir()
        (self.project / ".plainspoken" / "config.toml").write_text('[nudge]\nmode = "on"\n', encoding="utf-8")
        r = self.run_hook(REWRITE[0], args=("--host", "codex"))
        self.assertIn("$plainspoken:humanize", json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_quiet_prompt_prints_nothing_even_when_on(self):
        r = self.run_hook(QUIET[0], {"CLAUDE_PLUGIN_OPTION_NUDGE": "true"})
        self.assertEqual(r.stdout, "")

    def test_bad_config_or_stdin_never_blocks(self):
        (self.project / ".plainspoken").mkdir()
        (self.project / ".plainspoken" / "config.toml").write_text("[nudge\n", encoding="utf-8")
        r = self.run_hook(DRAFT[0], {"CLAUDE_PLUGIN_OPTION_NUDGE": "true"})
        self.assertEqual(r.returncode, 0)
        r2 = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
        self.assertEqual((r2.returncode, r2.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()


class Manifests(unittest.TestCase):
    def test_claude_and_codex_register_the_hooks(self):
        claude = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(claude["UserPromptSubmit"][0]["hooks"][0]["args"], ["${CLAUDE_PLUGIN_ROOT}/hooks/nudge.py"])
        manifest = json.loads((REPO / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["hooks"], "./hooks/codex.json")
        codex = json.loads((REPO / "hooks" / "codex.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(set(codex), {"UserPromptSubmit", "PostToolUse"})
        self.assertEqual(codex["PostToolUse"][0]["matcher"], "apply_patch")
        for group in (*codex["UserPromptSubmit"], *codex["PostToolUse"]):
            for h in group["hooks"]:
                script = h["command"].split('"$PLUGIN_ROOT/')[1].split('"')[0]
                self.assertTrue((REPO / script).is_file(), script)
                self.assertNotIn("args", h)  # Codex runs one command string

    def test_claude_option_is_off_by_default(self):
        uc = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["userConfig"]
        self.assertEqual((uc["nudge"]["type"], uc["nudge"]["default"]), ("boolean", False))
