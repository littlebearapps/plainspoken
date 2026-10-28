"""The tool-call check's stdlib side (#124): tool names, the shipped skip lists, `[tool_call]` settings and the walk
over a tool's arguments. Fixtures are synthetic."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lib"))
from plainspoken import config, toolcall  # noqa: E402

PROSE = ("Hi Sam, thanks for sending the plans over on Tuesday. I had a look at the garden layout and the shed "
         "position works well for me. Could we move the meeting to Thursday at ten? I'll bring the samples.")


def words(n: int) -> str:
    """`n` prose words ending in a full stop."""
    base = ("the shed sits by the back fence and gets the morning sun so the plants do well there most years "
            "we think").split()
    out = [base[i % len(base)] for i in range(n)]
    return " ".join(out) + "."


class Names(unittest.TestCase):
    def test_normalise(self):
        self.assertEqual(toolcall.normalise_name("mcp__claude_ai_Gmail__send_message"),
                         "mcp__claude_ai_gmail__send_message")
        self.assertEqual(toolcall.normalise_name("mcp__my-api__Query-Data"), "mcp__my_api__query_data")

    def test_split(self):
        cases = {
            "mcp__plugin_x_trello__add_comment": ("plugin_x_trello", "add_comment"),
            "mcp__claude_ai_Gmail__send_message": ("claude_ai_gmail", "send_message"),
            "mcp__my_api__query_data": ("my_api", "query_data"),
            "mcp_github_create_issue": ("github", "create_issue"),
            "discord": ("", "discord"),
        }
        for name, want in cases.items():
            with self.subTest(name=name):
                self.assertEqual(toolcall.split_name(toolcall.normalise_name(name)), want)

    def test_clamped_hermes_name_still_matches_its_server_glob(self):
        name = "mcp__trello_workspace_server__" + "a" * 25 + "_8f3a2b1c"  # 64 characters with a hash suffix
        self.assertEqual(len(name[:64]), 64)
        s = toolcall.settings_defaults()
        self.assertEqual(toolcall.name_decision(name[:64], "hermes", s), "skip-list")

    def test_server_hash_is_stable_and_short(self):
        a = toolcall.server_hash("mcp__clientcrm__send_note")
        self.assertRegex(a, r"^[0-9a-f]{8}$")
        self.assertEqual(a, toolcall.server_hash("mcp__ClientCRM__send_note"))
        self.assertNotIn("clientcrm", a)

    def test_draft_tools(self):
        self.assertTrue(toolcall.is_draft("mcp__claude_ai_gmail__create_draft"))
        self.assertTrue(toolcall.is_draft("mcp__x__update_draft"))
        self.assertFalse(toolcall.is_draft("mcp__drafts_app__send_message"))  # the server's name doesn't count


class Decisions(unittest.TestCase):
    def setUp(self):
        self.s = toolcall.settings_defaults()

    def decide(self, name, host="claude-code", **over):
        return toolcall.name_decision(name, host, {**self.s, **over})

    def test_send_tools_are_checked(self):
        for name in ("mcp__claude_ai_Gmail__send_message", "mcp__outbox__send", "mcp__slack__post_message",
                     "mcp__claude_ai_Gmail__create_draft", "mcp__bluesky__create_post"):
            with self.subTest(name=name):
                self.assertIsNone(self.decide(name))

    def test_shipped_skips(self):
        for name in ("mcp__firecrawl__firecrawl_scrape", "mcp__memory-service__memory_store",
                     "mcp__github__create_issue", "mcp__trello__add_comment", "mcp__plugin_x_trello__add_comment",
                     "mcp__playwright__browser_type", "mcp__dataforseo__api_request"):
            with self.subTest(name=name):
                self.assertEqual(self.decide(name), "skip-list")

    def test_lookup_verbs(self):
        for name in ("mcp__claude_ai_Gmail__search_threads", "mcp__x__list_events", "mcp__x__get_message"):
            with self.subTest(name=name):
                self.assertEqual(self.decide(name), "lookup")

    def test_include_beats_every_skip_and_skip_adds(self):
        self.assertIsNone(self.decide("mcp__trello__add_comment", include=["*trello*"]))
        self.assertIsNone(self.decide("mcp__x__get_message", include=["*__get_message"]))
        self.assertEqual(self.decide("mcp__mycrm__send_note", skip=["*mycrm*"]), "skip-list")
        self.assertIsNone(self.decide("mcp__mycrm__send_note", skip=["*mycrm*"], include=["*send_note"]))

    def test_claude_code_and_codex_check_mcp_tools_only(self):
        self.assertEqual(self.decide("Bash"), "not-mcp")
        self.assertEqual(self.decide("spawn_agent", host="codex"), "not-mcp")

    def test_hermes_checks_every_tool_but_its_core_list(self):
        self.assertIsNone(self.decide("discord", host="hermes"))
        self.assertIsNone(self.decide("yb_send_dm", host="hermes"))
        for name in ("terminal", "read_file", "browser_click", "kanban_comment", "delegate_task", "skill_view"):
            with self.subTest(name=name):
                self.assertEqual(self.decide(name, host="hermes"), "core")
        self.assertIsNone(self.decide("mcp_outbox_send", host="hermes"))


class Settings(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.root / ".plainspoken").mkdir()
        self.env = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")}

    def project(self, text):
        (self.root / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def user(self, text):
        p = self.home / ".config" / "plainspoken" / "config.toml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_off_by_default(self):
        s = toolcall.settings(self.root, self.env)
        self.assertEqual((s["mode"], s["min_words"], s["source"], s["error"]), ("off", 25, "default", None))

    def test_project_beats_user_beats_option(self):
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_TOOL_CALL": "ask"}
        self.assertEqual(toolcall.settings(self.root, env)["mode"], "ask")
        self.user('[tool_call]\nmode = "block-once"\n')
        self.assertEqual(toolcall.settings(self.root, env)[("mode")], "block-once")
        self.project('[tool_call]\nmode = "warn"\nmin_words = 30\nskip = ["*mycrm*"]\n')
        s = toolcall.settings(self.root, env)
        self.assertEqual((s["mode"], s["min_words"], s["skip"], s["source"]), ("warn", 30, ["*mycrm*"],
                                                                              "project config"))

    def test_keys_merge_so_a_project_skip_keeps_the_user_wide_mode(self):
        self.user('[tool_call]\nmode = "warn"\nmin_words = 40\n')
        self.project('[tool_call]\nskip = ["*mycrm*"]\nmin_words = 30\n')
        s = toolcall.settings(self.root, self.env)
        self.assertEqual((s["mode"], s["source"], s["skip"], s["min_words"]),
                         ("warn", "user-wide config", ["*mycrm*"], 30))

    def test_unknown_option_value_is_ignored(self):
        env = {**self.env, "CLAUDE_PLUGIN_OPTION_TOOL_CALL": "${user_config.tool_call}"}
        self.assertEqual(toolcall.settings(self.root, env)["mode"], "off")

    def test_bad_config_turns_it_off_and_says_why(self):
        self.project('[tool_call]\nmode = "loud"\n')
        s = toolcall.settings(self.root, self.env)
        self.assertEqual(s["mode"], "off")
        self.assertIn("[tool_call] mode", s["error"])
        self.project("not toml [")
        self.assertIn("not valid TOML", toolcall.settings(self.root, self.env)["error"])

    def test_section_errors(self):
        bad = [({"mode": "loud"}, "mode"), ({"min_words": 0}, "min_words"), ({"min_words": True}, "min_words"),
               ({"skip": "x"}, "skip"), ({"include": [""]}, "include"), ({"skip_fields": [1]}, "skip_fields"),
               ({"profile": ""}, "profile"), ({"colour": 1}, "colour")]
        for body, key in bad:
            with self.subTest(body=body):
                errors = toolcall.section_errors(body)
                self.assertTrue(errors and key in errors[0], errors)
        self.assertEqual(toolcall.section_errors({"mode": "warn", "min_words": 25, "skip": ["a"], "include": [],
                                                  "skip_fields": ["notes"], "profile": "email"}), [])

    def test_config_validates_the_section_in_both_files(self):
        self.project('[tool_call]\nmode = "loud"\n')
        with self.assertRaises(config.ConfigError) as e:
            config.tool_call_settings(self.root, self.env)
        self.assertIn("config.toml", str(e.exception))
        self.assertIn("[tool_call] mode", str(e.exception))
        self.project('[tool_call]\nmode = "warn"\n')
        self.user('[tool_call]\nmode = "ask"\nprofile = "email"\n')
        self.assertEqual(config.tool_call_settings(self.root, self.env)["mode"], "warn")
        (self.root / ".plainspoken" / "config.toml").unlink()
        self.assertEqual(config.tool_call_settings(self.root, self.env)["profile"], "email")

    def test_lean_and_full_readers_agree(self):
        for project, user, option in [("", "", None), ('[tool_call]\nmode = "warn"\n', "", None),
                                      ("", '[tool_call]\nmode = "ask"\nmin_words = 40\n', "warn"),
                                      ('[engine]\nprofile = "default"\n', '[tool_call]\ninclude = ["*x*"]\n', "ask")]:
            with self.subTest(project=project, user=user, option=option):
                self.project(project)
                self.user(user)
                env = {**self.env, **({"CLAUDE_PLUGIN_OPTION_TOOL_CALL": option} if option else {})}
                self.assertEqual(toolcall.settings(self.root, env), config.tool_call_settings(self.root, env))

    def test_profile_order_for_text(self):
        profiles = self.root / ".plainspoken" / "profiles"
        profiles.mkdir()
        base = (REPO / "data" / "profiles" / "default.toml").read_text(encoding="utf-8")
        for name in ("engine-one", "section-one", "option-one", "user-one"):
            (profiles / f"{name}.toml").write_text(base.replace('name = "default"', f'name = "{name}"'),
                                                   encoding="utf-8")
        name = lambda env: config.profile_for_text(self.root, {**self.env, **env}).name  # noqa: E731
        self.assertEqual(name({}), "default")
        self.assertEqual(name({"CLAUDE_PLUGIN_OPTION_PROFILE": "option-one"}), "option-one")
        self.user('[tool_call]\nprofile = "user-one"\n')
        self.assertEqual(name({"CLAUDE_PLUGIN_OPTION_PROFILE": "option-one"}), "user-one")
        self.project('[engine]\nprofile = "engine-one"\n[tool_call]\nmode = "warn"\n')
        self.assertEqual(name({"CLAUDE_PLUGIN_OPTION_PROFILE": "option-one"}), "user-one")  # key by key
        self.project('[engine]\nprofile = "engine-one"\n[tool_call]\nprofile = "section-one"\n')
        self.assertEqual(name({}), "section-one")
        self.assertEqual(name({"PLAINSPOKEN_PROFILE": "default"}), "default")

    def test_project_root_matches_config(self):
        sub = self.root / "a" / "b"
        sub.mkdir(parents=True)
        (self.root / ".plainspoken" / "config.toml").write_text("", encoding="utf-8")
        self.assertEqual(Path(toolcall.project_root(sub, {})), config.project_root(sub, {}))
        self.assertEqual(Path(toolcall.project_root(sub, {"CLAUDE_PROJECT_DIR": str(self.root)})), self.root.resolve())
        self.assertEqual(Path(toolcall.project_root(sub, {"CLAUDE_PROJECT_DIR": str(self.root) + "x"})),
                         config.project_root(sub, {"CLAUDE_PROJECT_DIR": str(self.root) + "x"}))


class Walk(unittest.TestCase):
    def walk(self, tool_input, min_words=25, skip_fields=()):
        return {f.path: f for f in toolcall.walk(tool_input, list(skip_fields), min_words)}

    def test_prose_field_is_a_candidate(self):
        got = self.walk({"to": "sam@example.com", "subject": "Plans", "body": PROSE})
        self.assertEqual(set(got), {"subject", "body"})
        self.assertEqual(got["body"].outcome, "candidate")
        self.assertEqual(got["subject"].outcome, "not-prose:no-sentence")

    def test_cut_off_is_inclusive_and_counts_prose_words_only(self):
        self.assertEqual(self.walk({"text": words(24)})["text"].outcome, "below-cutoff")
        self.assertEqual(self.walk({"text": words(25)})["text"].outcome, "candidate")
        padded = words(24) + " https://example.com/a https://example.com/b\n> quoted words here that do not count."
        self.assertEqual(self.walk({"text": padded})["text"].outcome, "below-cutoff")
        self.assertEqual(self.walk({"text": words(24)}, min_words=10)["text"].outcome, "candidate")

    def test_field_names_that_are_never_prose(self):
        for key in ("query", "prompt", "id", "raw", "threadId", "thread_id", "url", "instructions", "code", "q"):
            with self.subTest(key=key):
                self.assertEqual(self.walk({key: PROSE}), {})
        self.assertEqual(self.walk({"notes": PROSE}, skip_fields=["notes"]), {})

    def test_nested_paths_and_lists(self):
        got = self.walk({"message": {"blocks": [{"text": PROSE}, {"text": PROSE}]}})
        self.assertEqual(list(got), ["message.blocks[].text"])

    def test_two_dimensional_cells_are_skipped(self):
        self.assertEqual(self.walk({"values": [[PROSE, PROSE], [PROSE, PROSE]]}), {})
        self.assertEqual(self.walk({"items": [PROSE]})["items[]"].outcome, "candidate")

    def test_not_prose_reasons(self):
        got = self.walk({"payload": '{"a": "' + PROSE + '"}', "blob": "QUJD" * 30,
                         "list": "- milk and bread from the shop\n- call the plumber about the leaking pipe"})
        self.assertEqual(got["payload"].outcome, "not-prose:json")
        self.assertEqual(got["blob"].outcome, "not-prose:encoded")
        self.assertEqual(got["list"].outcome, "not-prose:no-sentence")

    def test_too_long(self):
        self.assertEqual(self.walk({"text": words(10_001)})["text"].outcome, "too-long")

    def test_bad_shapes_walk_to_nothing(self):
        self.assertEqual(toolcall.walk(None, [], 25), [])
        self.assertEqual(toolcall.walk("text", [], 25), [])
        deep = {}
        node = deep
        for _ in range(50):
            node["a"] = {}
            node = node["a"]
        node["text"] = PROSE
        self.assertEqual(toolcall.walk(deep, [], 25), [])  # past the depth limit


class ShippedData(unittest.TestCase):
    def test_lists_load_and_hold_globs(self):
        lists = toolcall.shipped()
        for key in ("skip_tools", "lookup_prefixes", "skip_fields", "hermes_core"):
            self.assertTrue(lists[key], key)
            self.assertTrue(all(isinstance(x, str) and x == x.lower() for x in lists[key]), key)


if __name__ == "__main__":
    unittest.main()
