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

    def test_long_pieces_go_to_write(self):  # #37: size, a long-form kind or sources to research, never the type alone
        for p in ("Write a blog post (about 600 words) for our club website about the rosters",
                  "Draft the service page (about 450 words) for my bookkeeping business's website",
                  "Can you write a newsletter feature on the repair cafe?",
                  "Write a 300-word email to the board about the budget",
                  "Write a press release, around 1,000 words, on the merger",
                  "Write an article for the local paper about the community garden",
                  "Draft a short guide for new volunteers on the sign-in process",
                  "Write a report for the committee on this year's fundraising",
                  "Write a newsletter piece on the new rules, using these sources: the council notice and the act",
                  "Write a pamphlet about heat safety; research what the health department recommends",
                  "Draft a few paragraphs for the newsletter about the new library",
                  "Write a page for the site from https://example.org/a and https://example.org/b"):
            with self.subTest(p=p):
                self.assertEqual(nudge.intent(p), "draft-long")

    def test_short_pieces_take_the_short_path_whatever_their_type(self):  # #37
        for p in ("Draft a text message to Sam saying I'll be late", "Write three tweets announcing the release",
                  "Write a short bio for the conference program",
                  "Write the principal's message for this term's school newsletter.",
                  "Write a press release announcing our festival.",
                  "Write the text for a one-page pamphlet about pool safety for parents.",
                  "Write a newsletter item about the working bee: Saturday, 9am, bring gloves",
                  "Draft the About page for my plumbing business's website",
                  "Write a 120-word blurb for the newsletter about the fete",
                  "Write a LinkedIn post about the new feature in our booking app",
                  "Draft an email inviting members to sign up at https://example.org/join",
                  "Draft an email to the research team about Friday's meeting"):
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

    def test_questions_and_tech_tasks_that_mention_writing_stay_quiet(self):  # #125
        for p in ("Does the lint hook run when I write emails in Outlook via MCP?",  # verb in a subordinate clause
                  "Write up how the Stop hook handles replies",  # generic noun, after a clause break
                  "Can you write a plan for linting chat replies?",  # noun isn't the verb's object
                  "Draft the plan for issue 125 (lint drafts in chat replies)",
                  "Write a GitHub issue about the nudge misfiring on emails",
                  "Write tests for the email extraction",
                  "Write the docs page for the Stop hook",  # tech object
                  "Write a page for the docs",  # tech destination
                  "Write the hook that posts replies",
                  "I write emails all day, so how does the hook pick them up?",
                  "When I draft a post, does the nudge fire?",
                  'Does the hook fire if someone types "write an email"?',
                  'The test input is "draft a LinkedIn post" and it should nudge.',
                  'The test input is “draft a LinkedIn post” and it should nudge.',
                  'Does the hook fire if someone types “write an email”?',
                  "Clean up the hook that tidies replies"):
            with self.subTest(p=p):
                self.assertIsNone(nudge.intent(p))

    def test_requests_in_other_shapes_still_fire(self):  # #125: the tightening keeps real asks
        for p in ("Write a LinkedIn post about the new MCP server",
                  "Write a short reply to Sam saying Thursday works",
                  "Hey, can you write an email to the parents about Friday?",
                  "I'd like you to draft a reply to this customer email: ...",
                  "If you have time, write a post for the club page",
                  "Thanks. Now please write the newsletter for March",
                  "Could you help me write a text to my landlord?",
                  "Write a summary for the board of this quarter's numbers",
                  "- write an email to the volunteers about the roster",
                  'Draft the "About the market" page for our market',  # a quoted name before the noun
                  '"Write an email to Sam about the invoice."',
                  'Write an email to Sam: "the invoice is overdue"',
                  "Write something for the parents' newsletter"):  # the piece named by where it goes
            with self.subTest(p=p):
                self.assertEqual(nudge.intent(p), "draft")
        self.assertEqual(nudge.intent("Write a feature for our council newsletter (about 450 words) on the library"),
                         "draft-long")
        self.assertEqual(nudge.intent("Can you tidy up this email to the parents?"), "rewrite")

    def test_ask_buried_in_a_long_paste_is_found_at_either_end(self):
        filler = "Lorem ipsum dolor sit amet. " * 200
        self.assertEqual(nudge.intent("Rewrite this so it sounds human:\n\n" + filler), "rewrite")
        self.assertEqual(nudge.intent(filler + "\n\nCan you draft a reply email to this?"), "draft")


# The shape Claude Code uses to hand a subagent's final report back as a user turn (#55).
HANDBACK = ('<system-reminder id="b4a1b873d28cd20d">\nAnother Claude session sent a message while you were working:\n'
            '<agent-message from="a76304e6a21036de0">\n[Subagent hand-back] #37 is fixed in PR #40. I didn\'t write '
            'the report yet; the nudge now treats an article, blog post or report as long-form.\n</agent-message>\n\n'
            'That "other Claude session" is an agent working inside this same session.\n</system-reminder>')
NOTICE = ('<task-notification>\n<task-id>a31</task-id>\n<status>completed</status>\n<summary>Agent "Fix #37" '
          'finished</summary>\n<result>Done: write a short report and a blog post later.</result>\n'
          '</task-notification>')


class Wrappers(unittest.TestCase):  # #55: text the host wraps around a turn isn't the person's ask
    def test_wrapped_hand_back_alone_is_silent(self):
        for p in (HANDBACK, NOTICE, HANDBACK + "\n" + NOTICE, "  \n" + HANDBACK + "\n\n"):
            with self.subTest(p=p[:40]):
                self.assertIsNone(nudge.intent(p))

    def test_real_ask_next_to_a_wrapper_still_nudges(self):
        ask = "Write a blog post (about 600 words) for our club website about the rosters"
        self.assertEqual(nudge.intent(HANDBACK + "\n\n" + ask), "draft-long")
        self.assertEqual(nudge.intent(ask + "\n\n" + NOTICE), "draft-long")
        self.assertEqual(nudge.intent("<system-reminder>Today is Tuesday.</system-reminder>\nhumanise this"),
                         "rewrite")

    def test_long_wrapper_does_not_push_the_ask_out_of_view(self):
        reminder = "<system-reminder>" + "Lorem ipsum dolor sit amet. " * 200 + "</system-reminder>"
        self.assertEqual(nudge.intent(reminder + "\nDraft a text message to Sam saying I'll be late"), "draft")

    def test_unclosed_or_stray_tags_keep_the_ask(self):
        # Only a complete block is dropped. A lone tag is removed and the text around it kept: a missed real ask is
        # worse than one optional nudge line on a garbled hand-back.
        ask = "Draft a text message to Sam saying I'll be late"
        for p in ("<system-reminder>Note: the time is 4pm.\n" + ask, "<agent-message from=\"x\">" + ask,
                  ask + "</system-reminder>", "</agent-message><system-reminder " + ask,
                  "<system-reminder>Note.</system-reminder><agent-message>" + ask):
            with self.subTest(p=p):
                self.assertEqual(nudge.intent(p), "draft")
        self.assertIsNone(nudge.intent("<system-reminder>"))
        self.assertIsNone(nudge.intent("</agent-message>"))
        # A complete outer block is dropped whole, whatever it holds.
        self.assertIsNone(nudge.intent("<system-reminder><agent-message>" + ask + "</system-reminder>"))

    def test_tags_are_named_exactly(self):
        # A writer's own markup, or a tag that only starts with a wrapper's name, is left alone.
        self.assertEqual(nudge.intent("<note>write a LinkedIn post about the new booking page</note>"), "draft")
        self.assertEqual(nudge.intent("<system-reminders>x</system-reminders> write a LinkedIn post about it"),
                         "draft")


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

    def run_hook(self, prompt: str, env: dict | None = None, args: tuple = (), **ids):
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_", "CLAUDE_PLUGIN_DATA", "PLUGIN_DATA"))}
        e.update({"HOME": str(self.home), "CLAUDE_PROJECT_DIR": str(self.project),
                  "CLAUDE_PLUGIN_DATA": str(self.home / "data")})
        e.pop("XDG_CONFIG_HOME", None)
        e.update(env or {})
        event = {"hook_event_name": "UserPromptSubmit", "prompt": prompt, "cwd": str(self.project), "session_id": "s",
                 **ids}
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

    def test_subagent_hand_back_prints_nothing_even_when_on(self):  # #55
        r = self.run_hook(HANDBACK, {"CLAUDE_PLUGIN_OPTION_NUDGE": "true"})
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)

    def flags(self) -> dict:
        path = self.home / "data" / "writing-ask-state.json"
        return json.loads(path.read_text(encoding="utf-8"))["last"] if path.exists() else {}

    def test_writing_ask_flag_only_when_the_chat_reply_check_is_on(self):  # #125
        on = {"CLAUDE_PLUGIN_OPTION_CHAT_REPLY": "true"}
        r = self.run_hook(DRAFT[0], prompt_id="p1")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertEqual(self.flags(), {})
        r = self.run_hook(DRAFT[0], on, prompt_id="p1")
        self.assertEqual(r.stdout, "")  # the nudge itself is still off: nothing for the model
        self.run_hook(REWRITE[0], on, ("--host", "codex"), turn_id="t9")
        self.run_hook(DRAFT[1], on)
        self.run_hook(QUIET[0], on, prompt_id="p2")
        self.assertEqual(self.flags(), {"s|p1": "draft", "s|t9": "rewrite", "s|latest": "draft"})
        self.assertNotIn("excursion", (self.home / "data" / "writing-ask-state.json").read_text(encoding="utf-8"))

    def test_flag_and_nudge_together(self):
        r = self.run_hook(DRAFT[0], {"CLAUDE_PLUGIN_OPTION_CHAT_REPLY": "true", "CLAUDE_PLUGIN_OPTION_NUDGE": "true"},
                          prompt_id="p1")
        self.assertIn("/plainspoken:write", json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.flags(), {"s|p1": "draft"})

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
        self.assertEqual(set(codex), {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"})
        self.assertEqual(codex["PostToolUse"][0]["matcher"], "apply_patch")
        for group in (g for groups in codex.values() for g in groups):
            for h in group["hooks"]:
                script = h["command"].split('"$PLUGIN_ROOT/')[1].split('"')[0]
                self.assertTrue((REPO / script).is_file(), script)
                self.assertNotIn("args", h)  # Codex runs one command string

    def test_claude_option_is_off_by_default(self):
        uc = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["userConfig"]
        self.assertEqual((uc["nudge"]["type"], uc["nudge"]["default"]), ("boolean", False))
