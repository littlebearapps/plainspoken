import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from plainspoken import config
from plainspoken.profile import ProfileError

FIX = Path(__file__).parent / "fixtures" / "profiles"


class Resolve(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)

    def project(self, toml: str) -> None:
        (self.cwd / ".plainspoken").mkdir(exist_ok=True)
        (self.cwd / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def test_cli_beats_env_beats_config(self):
        self.project('[engine]\nprofile = "default"\n')
        env = {"PLAINSPOKEN_PROFILE": str(FIX / "consulting_like.toml")}
        self.assertEqual(config.resolve_profile(str(FIX / "product_like.toml"), self.cwd, env).name, "product_like")
        self.assertEqual(config.resolve_profile(None, self.cwd, env).name, "consulting_like")
        self.assertEqual(config.resolve_profile(None, self.cwd, {}).name, "default")

    def test_plugin_option_env_is_a_source(self):
        self.assertEqual(config.resolve_profile(None, self.cwd, {"CLAUDE_PLUGIN_OPTION_PROFILE": "default"}).name, "default")

    def test_plugin_option_arg_is_last_resort(self):
        self.assertEqual(config.resolve_profile(None, self.cwd, {}, "default").name, "default")
        env = {"CLAUDE_PLUGIN_OPTION_PROFILE": str(FIX / "consulting_like.toml")}
        self.assertEqual(config.resolve_profile(None, self.cwd, env, "default").name, "consulting_like")

    def test_placeholder_plugin_option_is_default_profile(self):
        self.assertTrue(config.is_placeholder("${user_config.profile}"))
        self.assertFalse(config.is_placeholder("mine"))
        p, used = config.resolve_profile_ex(None, self.cwd, {}, "${user_config.profile}")
        self.assertEqual((p.name, used), ("default", True))

    def test_empty_plugin_option_is_default_profile(self):
        p, used = config.resolve_profile_ex(None, self.cwd, {}, "")
        self.assertEqual((p.name, used), ("default", True))

    def test_placeholder_not_rewritten_elsewhere(self):
        with self.assertRaises(ProfileError):
            config.resolve_profile("${user_config.profile}", self.cwd, {})
        with self.assertRaises(ProfileError):
            config.resolve_profile(None, self.cwd, {"PLAINSPOKEN_PROFILE": "${x}"})

    def test_project_profiles_dir_searched_first(self):
        (self.cwd / ".plainspoken" / "profiles").mkdir(parents=True)
        (self.cwd / ".plainspoken" / "profiles" / "mine.toml").write_text('[profile]\nname = "mine"\n', encoding="utf-8")
        self.assertEqual(config.resolve_profile("mine", self.cwd, {}).name, "mine")

    def test_no_source_fails_closed(self):
        with self.assertRaisesRegex(ProfileError, "no profile"):
            config.resolve_profile(None, self.cwd, {})

    def test_bad_config_names_file_and_key(self):
        self.project('[engine]\nprofil = "default"\n')
        with self.assertRaisesRegex(config.ConfigError, r"config\.toml.*\[engine\] profil"):
            config.resolve_profile(None, self.cwd, {})

    def test_non_string_or_empty_profile_is_a_config_error(self):
        for bad in ("5", '["x"]', '""'):
            self.project(f"[engine]\nprofile = {bad}\n")
            with self.assertRaisesRegex(config.ConfigError, r"config\.toml.*\[engine\] profile"):
                config.resolve_profile(None, self.cwd, {})

    def test_engine_not_a_table_and_config_not_a_file(self):
        self.project("engine = 3\n")
        with self.assertRaisesRegex(config.ConfigError, r"\[engine\] must be a table"):
            config.resolve_profile(None, self.cwd, {})
        (self.cwd / ".plainspoken" / "config.toml").unlink()
        (self.cwd / ".plainspoken" / "config.toml").mkdir()
        with self.assertRaisesRegex(config.ConfigError, "not a file"):
            config.resolve_profile(None, self.cwd, {})

    def test_plainspoken_env_beats_plugin_option_env(self):
        env = {"PLAINSPOKEN_PROFILE": str(FIX / "consulting_like.toml"),
               "CLAUDE_PLUGIN_OPTION_PROFILE": str(FIX / "product_like.toml")}
        self.assertEqual(config.resolve_profile(None, self.cwd, env).name, "consulting_like")

    def test_project_config_beats_plugin_option_env(self):  # project config before userConfig
        self.project(f'[engine]\nprofile = "{FIX / "consulting_like.toml"}"\n')
        env = {"CLAUDE_PLUGIN_OPTION_PROFILE": str(FIX / "product_like.toml")}
        self.assertEqual(config.resolve_profile(None, self.cwd, env).name, "consulting_like")

    def test_plainspoken_env_beats_project_config(self):
        self.project(f'[engine]\nprofile = "{FIX / "product_like.toml"}"\n')
        env = {"PLAINSPOKEN_PROFILE": str(FIX / "consulting_like.toml"),
               "CLAUDE_PLUGIN_OPTION_PROFILE": str(FIX / "narrative_like.toml")}
        self.assertEqual(config.resolve_profile(None, self.cwd, env).name, "consulting_like")

    def test_config_relative_path_resolves_against_dot_plainspoken(self):
        (self.cwd / "profiles").mkdir()
        (self.cwd / "profiles" / "mine.toml").write_text('[profile]\nname = "cwd_one"\n', encoding="utf-8")
        (self.cwd / ".plainspoken" / "profiles").mkdir(parents=True)
        (self.cwd / ".plainspoken" / "profiles" / "mine.toml").write_text('[profile]\nname = "dot_one"\n', encoding="utf-8")
        self.project('[engine]\nprofile = "profiles/mine.toml"\n')
        self.assertEqual(config.resolve_profile(None, self.cwd, {}).name, "dot_one")


class GatePaths(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)

    def project(self, toml: str) -> None:
        (self.cwd / ".plainspoken").mkdir(exist_ok=True)
        (self.cwd / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def test_unset_is_empty(self):
        self.assertEqual(config.gate_paths(self.cwd), [])
        self.project('[engine]\nprofile = "default"\n')
        self.assertEqual(config.gate_paths(self.cwd), [])

    def test_reads_paths_and_coexists_with_engine(self):
        self.project('[engine]\nprofile = "default"\n[gate]\npaths = ["docs/**/*.md", "a.md"]\n')
        self.assertEqual(config.gate_paths(self.cwd), ["docs/**/*.md", "a.md"])
        self.assertEqual(config.resolve_profile(None, self.cwd, {}).name, "default")

    def test_unknown_section_message_lists_every_section(self):  # never a hand-kept list
        self.project('[nope]\nx = 1\n')
        with mock.patch.dict(config._SECTIONS, {"later": set()}):
            with self.assertRaises(config.ConfigError) as cm:
                config.gate_paths(self.cwd)
        msg = str(cm.exception)
        for section in [*config._SECTIONS, "later"]:
            self.assertIn(f"[{section}]", msg)

    def test_gate_only_config_is_valid(self):
        self.project('[gate]\npaths = []\n')
        self.assertEqual(config.gate_paths(self.cwd), [])

    def test_bad_gate_config_fails_closed(self):
        for toml, msg in (('[gate]\npaths = "docs"\n', "list of non-empty strings"),
                          ('[gate]\npaths = [1]\n', "list of non-empty strings"),
                          ('[gate]\npaths = [""]\n', "list of non-empty strings"),
                          ('[gate]\nother = 1\n', "unknown key"),
                          ('gate = 3\n', "must be a table"),
                          ('[nope]\nx = 1\n', "unknown section")):
            self.project(toml)
            with self.assertRaisesRegex(config.ConfigError, msg):
                config.gate_paths(self.cwd)


class GateStrictness(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)

    def project(self, toml: str) -> None:
        (self.cwd / ".plainspoken").mkdir(exist_ok=True)
        (self.cwd / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def test_default_is_watch(self):
        self.assertEqual(config.gate_strictness(self.cwd, {}), ("watch", "default"))

    def test_plugin_option_env(self):
        env = {"CLAUDE_PLUGIN_OPTION_STRICTNESS": "warn"}
        self.assertEqual(config.gate_strictness(self.cwd, env), ("warn", "plugin option"))

    def test_project_config_beats_plugin_option(self):
        self.project('[gate]\nstrictness = "block"\n')
        env = {"CLAUDE_PLUGIN_OPTION_STRICTNESS": "watch"}
        self.assertEqual(config.gate_strictness(self.cwd, env), ("block", "project config"))
        self.project('[gate]\nstrictness = "watch"\n')
        self.assertEqual(config.gate_strictness(self.cwd, {"CLAUDE_PLUGIN_OPTION_STRICTNESS": "block"}),
                         ("watch", "project config"))

    def test_bad_value_fails_closed(self):
        for bad in ('"blok"', "1", '["block"]', '""'):
            with self.subTest(bad=bad):
                self.project(f"[gate]\nstrictness = {bad}\n")
                with self.assertRaisesRegex(config.ConfigError, r"config\.toml.*\[gate\] strictness"):
                    config.gate_strictness(self.cwd, {})


class ClaimsSections(unittest.TestCase):  # [claims], [reader_value], [integrity]
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)

    def project(self, toml: str) -> None:
        (self.cwd / ".plainspoken").mkdir(exist_ok=True)
        (self.cwd / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def test_defaults_without_a_config(self):
        self.assertEqual(config.claims_settings(self.cwd),
                         {"ledger_dir": ".plainspoken/claims", "sources_dir": ".plainspoken/sources",
                          "regulated_matrix": None, "platforms_extra": []})
        self.assertEqual(config.reader_value_settings(self.cwd), {"cta_phrases": []})
        self.assertEqual(config.integrity_settings(self.cwd), {"mode": "warn", "paths": None})

    def test_defaults_with_an_unrelated_config(self):
        self.project('[engine]\nprofile = "default"\n')
        self.assertEqual(config.claims_settings(self.cwd)["ledger_dir"], ".plainspoken/claims")
        self.assertEqual(config.integrity_settings(self.cwd), {"mode": "warn", "paths": None})

    def test_sections_load(self):
        self.project('[engine]\nprofile = "default"\n'
                     '[claims]\nledger_dir = "docs/claims"\nsources_dir = "docs/sources"\n'
                     'regulated_matrix = "docs/regulated.md"\nplatforms_extra = ["Acme CRM"]\n'
                     '[reader_value]\ncta_phrases = ["Book a Free Strategy Call"]\n'
                     '[integrity]\nmode = "block"\npaths = ["posts/**/*.md"]\n')
        self.assertEqual(config.claims_settings(self.cwd),
                         {"ledger_dir": "docs/claims", "sources_dir": "docs/sources",
                          "regulated_matrix": "docs/regulated.md", "platforms_extra": ["Acme CRM"]})
        self.assertEqual(config.reader_value_settings(self.cwd), {"cta_phrases": ["Book a Free Strategy Call"]})
        self.assertEqual(config.integrity_settings(self.cwd), {"mode": "block", "paths": ["posts/**/*.md"]})
        self.assertEqual(config.resolve_profile(None, self.cwd, {}).name, "default")
        self.assertEqual(config.gate_paths(self.cwd), [])

    def test_integrity_paths_empty_list_is_kept(self):
        self.project('[integrity]\npaths = []\n')
        self.assertEqual(config.integrity_settings(self.cwd), {"mode": "warn", "paths": []})

    def test_a_sources_dir_symlink_loop_is_not_the_root(self):  # same answer on every Python
        (self.cwd / "loop").symlink_to("loop")
        self.project('[claims]\nsources_dir = "loop"\n')
        self.assertEqual(config.claims_settings(self.cwd)["sources_dir"], "loop")

    def test_sources_dir_linked_to_the_project_root_fails_closed(self):
        (self.cwd / "here").symlink_to(self.cwd)
        self.project('[claims]\nsources_dir = "here"\n')
        with self.assertRaisesRegex(config.ConfigError, r"\[claims\] sources_dir can't be the project root"):
            config.claims_settings(self.cwd)

    def test_bad_values_fail_closed(self):
        for toml, msg in (('[claims]\nother = 1\n', r"unknown key \[claims\] other"),
                          ('[reader_value]\nphrases = []\n', r"unknown key \[reader_value\] phrases"),
                          ('[integrity]\nstrictness = "warn"\n', r"unknown key \[integrity\] strictness"),
                          ('[integrity]\nmode = "deny"\n', r"\[integrity\] mode must be one of off, warn, block"),
                          ('[integrity]\nmode = 1\n', r"\[integrity\] mode"),
                          ('[integrity]\npaths = "*.md"\n', r"\[integrity\] paths must be a list"),
                          ('[claims]\nplatforms_extra = ["ok", ""]\n', r"\[claims\] platforms_extra must be a list"),
                          ('[reader_value]\ncta_phrases = "buy"\n', r"\[reader_value\] cta_phrases must be a list"),
                          ('[claims]\nledger_dir = ""\n', r"\[claims\] ledger_dir"),
                          ('[claims]\nledger_dir = "/abs/claims"\n', r"\[claims\] ledger_dir must be relative"),
                          ('[claims]\nledger_dir = "a/../../x"\n', r"\[claims\] ledger_dir must be relative"),
                          ('[claims]\nsources_dir = "..\\\\x"\n', r"\[claims\] sources_dir must be relative"),
                          ('[claims]\nsources_dir = "."\n', r"\[claims\] sources_dir can't be the project root"),
                          ('[claims]\nsources_dir = "./"\n', r"\[claims\] sources_dir can't be the project root"),
                          ('[claims]\nsources_dir = "./."\n', r"\[claims\] sources_dir can't be the project root"),
                          ('[claims]\nregulated_matrix = 3\n', r"\[claims\] regulated_matrix"),
                          ('claims = 1\n', "must be a table")):
            with self.subTest(toml=toml):
                self.project(toml)
                for accessor in (config.claims_settings, config.reader_value_settings, config.integrity_settings):
                    with self.assertRaisesRegex(config.ConfigError, msg):
                        accessor(self.cwd)


class KaizenSection(unittest.TestCase):  # [kaizen], [kaizen.github], [kaizen.trello]
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)

    def project(self, toml: str) -> None:
        (self.cwd / ".plainspoken").mkdir(exist_ok=True)
        (self.cwd / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def test_defaults(self):
        s = config.kaizen_settings(self.cwd, {})
        self.assertEqual(s, {"capture": True, "excerpts": False, "adapter": "file", "root": self.cwd,
                             "capture_sources": ["check", "merge", "judge", "lint-watch", "tool-call"],
                             "ledger_dir": self.cwd / ".plainspoken" / "ledger",
                             "proposals_dir": self.cwd / ".plainspoken" / "kaizen",
                             "corpus": [], "human_corpus": [], "approvers": [],
                             "github": {"repo": None, "labels": ["kaizen"]},
                             "trello": {"list_id": None, "label_ids": [], "key_env": "TRELLO_API_KEY",
                                        "token_env": "TRELLO_TOKEN"}})
        self.project('[engine]\nprofile = "default"\n')
        self.assertEqual(config.kaizen_settings(self.cwd, {}), s)

    def test_section_loads(self):
        self.project('[kaizen]\ncapture = false\nexcerpts = true\nadapter = "github"\nledger_dir = "var/ledger"\n'
                     'proposals_dir = "var/kaizen"\ncorpus = ["posts/**/*.md"]\nhuman_corpus = ["human/*.md"]\n'
                     'approvers = ["owner"]\n'
                     '[kaizen.github]\nrepo = "owner/name"\nlabels = ["kaizen", "rules"]\n'
                     '[kaizen.trello]\nlist_id = "abc123"\nlabel_ids = ["l1"]\nkey_env = "MY_KEY"\n'
                     'token_env = "MY_TOKEN"\n')
        s = config.kaizen_settings(self.cwd, {"CLAUDE_PLUGIN_OPTION_LEDGER_EXCERPTS": "false",
                                              "CLAUDE_PLUGIN_OPTION_KAIZEN_ADAPTER": "trello"})
        self.assertEqual((s["capture"], s["excerpts"], s["adapter"]), (False, True, "github"))
        self.assertEqual((s["ledger_dir"], s["proposals_dir"]), (self.cwd / "var/ledger", self.cwd / "var/kaizen"))
        self.assertEqual((s["corpus"], s["human_corpus"], s["approvers"]),
                         (["posts/**/*.md"], ["human/*.md"], ["owner"]))
        self.assertEqual(s["github"], {"repo": "owner/name", "labels": ["kaizen", "rules"]})
        self.assertEqual(s["trello"], {"list_id": "abc123", "label_ids": ["l1"], "key_env": "MY_KEY",
                                       "token_env": "MY_TOKEN"})

    def test_env_fallbacks(self):
        for value, want in (("true", True), ("1", True), ("false", False), ("", False), ("${user_config.x}", False)):
            with self.subTest(excerpts=value):
                self.assertEqual(config.kaizen_settings(
                    self.cwd, {"CLAUDE_PLUGIN_OPTION_LEDGER_EXCERPTS": value})["excerpts"], want)
        self.project('[kaizen]\napprovers = ["owner"]\n')
        for value, want in (("github", "github"), ("trello", "trello"), ("file", "file"), ("slack", "file"),
                            ("", "file")):
            with self.subTest(adapter=value):
                self.assertEqual(config.kaizen_settings(
                    self.cwd, {"CLAUDE_PLUGIN_OPTION_KAIZEN_ADAPTER": value})["adapter"], want)

    def test_project_config_beats_env(self):
        self.project('[kaizen]\nexcerpts = false\nadapter = "file"\n')
        s = config.kaizen_settings(self.cwd, {"CLAUDE_PLUGIN_OPTION_LEDGER_EXCERPTS": "true",
                                              "CLAUDE_PLUGIN_OPTION_KAIZEN_ADAPTER": "github"})
        self.assertEqual((s["excerpts"], s["adapter"]), (False, "file"))

    def test_ledger_and_proposals_dir_cannot_be_the_project_root(self):
        (self.cwd / "here").symlink_to(self.cwd)
        for key in ("ledger_dir", "proposals_dir"):
            for value in (".", "./", "./.", "here"):
                with self.subTest(key=key, value=value):
                    self.project(f'[kaizen]\n{key} = "{value}"\n')
                    with self.assertRaisesRegex(config.ConfigError, rf"\[kaizen\] {key} can't be the project root"):
                        config.kaizen_settings(self.cwd, {})

    def test_outward_adapter_needs_approvers(self):
        self.project('[kaizen]\nadapter = "github"\n')
        with self.assertRaisesRegex(config.ConfigError, "name who may approve"):
            config.kaizen_settings(self.cwd, {})
        self.project('[kaizen]\nadapter = "trello"\n')
        with self.assertRaisesRegex(config.ConfigError, "name who may approve"):
            config.kaizen_settings(self.cwd, {"CLAUDE_PLUGIN_OPTION_KAIZEN_ADAPTER": "file"})

    def test_plugin_option_adapter_without_approvers_falls_back_to_file(self):
        for option in ("github", "trello"):
            with self.subTest(option=option):
                self.assertEqual(config.kaizen_settings(
                    self.cwd, {"CLAUDE_PLUGIN_OPTION_KAIZEN_ADAPTER": option})["adapter"], "file")
                self.project('[engine]\nprofile = "default"\n')
                self.assertEqual(config.kaizen_settings(
                    self.cwd, {"CLAUDE_PLUGIN_OPTION_KAIZEN_ADAPTER": option})["adapter"], "file")
                self.project('[kaizen]\napprovers = ["owner"]\n')
                self.assertEqual(config.kaizen_settings(
                    self.cwd, {"CLAUDE_PLUGIN_OPTION_KAIZEN_ADAPTER": option})["adapter"], option)
                (self.cwd / ".plainspoken" / "config.toml").unlink()

    def test_bad_values_fail_closed(self):
        for toml, msg in (('[kaizen]\nother = 1\n', r"config\.toml.*unknown key \[kaizen\] other"),
                          ('[kaizen]\nadapter = "slack"\n', r"\[kaizen\] adapter must be one of file, github, trello"),
                          ('[kaizen]\ncapture = "yes"\n', r"\[kaizen\] capture must be true or false"),
                          ('[kaizen]\nexcerpts = 1\n', r"\[kaizen\] excerpts must be true or false"),
                          ('[kaizen]\nledger_dir = "/abs"\n', r"\[kaizen\] ledger_dir must be relative"),
                          ('[kaizen]\nproposals_dir = "../x"\n', r"\[kaizen\] proposals_dir must be relative"),
                          ('[kaizen]\ncorpus = "posts"\n', r"\[kaizen\] corpus must be a list"),
                          ('[kaizen]\nhuman_corpus = [""]\n', r"\[kaizen\] human_corpus must be a list"),
                          ('[kaizen]\napprovers = [1]\n', r"\[kaizen\] approvers must be a list"),
                          ('[kaizen.github]\nrepo = "x"\n', r"\[kaizen.github\] repo must be owner/name"),
                          ('[kaizen.github]\nlabels = "kaizen"\n', r"\[kaizen.github\] labels must be a list"),
                          ('[kaizen.github]\nissue = 1\n', r"unknown key \[kaizen.github\] issue"),
                          ('[kaizen]\ngithub = 1\n', r"\[kaizen.github\] must be a table"),
                          ('[kaizen.trello]\nlist_id = ""\n', r"\[kaizen.trello\] list_id"),
                          ('[kaizen.trello]\nlabel_ids = "x"\n', r"\[kaizen.trello\] label_ids must be a list"),
                          ('[kaizen.trello]\nkey_env = "not a name"\n', r"\[kaizen.trello\] key_env"),
                          ('[kaizen.trello]\nboard = "b"\n', r"unknown key \[kaizen.trello\] board"),
                          ('kaizen = 1\n', "must be a table")):
            with self.subTest(toml=toml):
                self.project(toml)
                with self.assertRaisesRegex(config.ConfigError, msg):
                    config.kaizen_settings(self.cwd, {})


class EngineProfiles(unittest.TestCase):  # one profile per path, [engine] profiles
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        (self.cwd / ".git").mkdir()
        prof = self.cwd / ".plainspoken" / "profiles"
        prof.mkdir(parents=True)
        for name in ("a", "b"):
            (prof / f"{name}.toml").write_text(f'[profile]\nname = "{name}"\n', encoding="utf-8")

    def project(self, toml: str) -> None:
        (self.cwd / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def test_profile_for_first_glob_wins(self):
        self.project('[engine]\nprofile = "default"\nprofiles = [\n'
                     '  { glob = "docs/product/**", profile = "a" },\n'
                     '  { glob = "docs/**", profile = "profiles/b.toml" },\n]\n')
        self.assertEqual(config.profile_for(self.cwd / "docs" / "product" / "x.md", self.cwd), "a")
        self.assertEqual(config.profile_for(self.cwd / "docs" / "y.md", self.cwd),
                         str(self.cwd / ".plainspoken" / "profiles" / "b.toml"))
        # the resolver uses the same table for a target file; no target means [engine] profile
        self.assertEqual(config.resolve_profile(None, self.cwd, {}, target=self.cwd / "docs/product/x.md").name, "a")
        self.assertEqual(config.resolve_profile(None, self.cwd, {}, target=self.cwd / "docs/y.md").name, "b")
        self.assertEqual(config.resolve_profile(None, self.cwd, {}).name, "default")
        # flag and env still come first
        self.assertEqual(config.resolve_profile("default", self.cwd, {}, target=self.cwd / "docs/y.md").name,
                         "default")
        self.assertEqual(config.resolve_profile(None, self.cwd, {"PLAINSPOKEN_PROFILE": "default"},
                                                target=self.cwd / "docs/y.md").name, "default")

    def test_profile_for_falls_back(self):
        self.project('[engine]\nprofile = "b"\nprofiles = [{ glob = "docs/product/**", profile = "a" }]\n')
        self.assertEqual(config.profile_for(self.cwd / "notes" / "x.md", self.cwd), "b")
        self.assertEqual(config.resolve_profile(None, self.cwd, {}, target=self.cwd / "notes/x.md").name, "b")
        self.project('[engine]\nprofiles = [{ glob = "docs/product/**", profile = "a" }]\n')
        self.assertIsNone(config.profile_for(self.cwd / "notes" / "x.md", self.cwd))
        self.assertEqual(config.resolve_profile(None, self.cwd, {"CLAUDE_PLUGIN_OPTION_PROFILE": "b"},
                                                target=self.cwd / "notes/x.md").name, "b")
        (self.cwd / ".plainspoken" / "config.toml").unlink()
        self.assertIsNone(config.profile_for(self.cwd / "docs" / "product" / "x.md", self.cwd))

    def test_profile_for_finds_the_project_root(self):
        self.project('[engine]\nprofiles = [{ glob = "docs/**", profile = "a" }]\n')
        (self.cwd / "docs").mkdir()
        self.assertEqual(config.profile_for(self.cwd / "docs" / "x.md"), "a")

    def test_glob_match_is_the_hooks_glob(self):  # the hooks match targets with their own copy (stdlib-only)
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
        import _common
        for rel in ("post.md", "a/b/post.md", "docs/x.md", "docs/a/x.md", "docs/product/x.md", "notes/a.txt", "x?.md"):
            for pattern in ("**/*.md", "docs/*.md", "docs/**", "docs/product/**", "*.md", "**", "x?.md", "docs/**/*.md"):
                with self.subTest(rel=rel, pattern=pattern):
                    self.assertEqual(config.glob_match(rel, pattern), _common.glob_match(rel, pattern))

    def test_profiles_bad_shape_errors(self):
        for body in ('profiles = "docs/**"',
                     'profiles = { glob = "docs/**", profile = "a" }',
                     'profiles = ["a"]',
                     'profiles = [{ glob = "docs/**" }]',
                     'profiles = [{ profile = "a" }]',
                     'profiles = [{ glob = "docs/**", profile = "a", voice = "x" }]',
                     'profiles = [{ glob = "", profile = "a" }]',
                     'profiles = [{ glob = "docs/**", profile = 3 }]',
                     'profiles = [{ glob = "docs/**", profile = "/etc/a.toml" }]',
                     'profiles = [{ glob = "docs/**", profile = "C:\\\\voices\\\\a.toml" }]',
                     'profiles = [{ glob = "/abs/**", profile = "a" }]'):
            with self.subTest(body=body):
                self.project(f"[engine]\n{body}\n")
                with self.assertRaisesRegex(config.ConfigError, r"config\.toml: \[engine\] profiles"):
                    config.profile_for(self.cwd / "docs" / "x.md", self.cwd)


    def test_plainspoken_prefixed_profile_path_errors(self):  # the base is .plainspoken/ already
        for body, where in (('profiles = [{ glob = "docs/**", profile = ".plainspoken/profiles/a.toml" }]',
                             r"\[engine\] profiles entry 1"),
                            ('profiles = [{ glob = "x/**", profile = "a" }, '
                             '{ glob = "docs/**", profile = "./.plainspoken/profiles/a.toml" }]',
                             r"\[engine\] profiles entry 2"),
                            ('profiles = [{ glob = "docs/**", profile = ".plainspoken\\\\profiles\\\\a.toml" }]',
                             r"\[engine\] profiles entry 1"),
                            ('profile = ".plainspoken/profiles/a.toml"', r"\[engine\] profile ")):
            with self.subTest(body=body):
                self.project(f"[engine]\n{body}\n")
                with self.assertRaisesRegex(config.ConfigError, where + r".*relative to \.plainspoken/.*"
                                            r"drop the leading \.plainspoken/"):
                    config.profile_for(self.cwd / "docs" / "x.md", self.cwd)
        self.project('[engine]\nprofile = "profiles/a.toml"\n')  # the right form still loads
        self.assertEqual(config.profile_for(self.cwd / "docs" / "x.md", self.cwd),
                         str((self.cwd / ".plainspoken" / "profiles" / "a.toml").resolve()))


class LintWatchSection(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)

    def project(self, toml: str) -> None:
        (self.cwd / ".plainspoken").mkdir(exist_ok=True)
        (self.cwd / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def test_defaults(self):
        self.assertEqual(config.lint_watch(self.cwd), {"mode": "on", "paths": None})
        self.project('[engine]\nprofile = "default"\n')
        self.assertEqual(config.lint_watch(self.cwd), {"mode": "on", "paths": None})

    def test_section_loads(self):
        self.project('[lint_watch]\nmode = "off"\npaths = ["docs/**/*.md"]\n')
        self.assertEqual(config.lint_watch(self.cwd), {"mode": "off", "paths": ["docs/**/*.md"]})

    def test_bad_values_fail_closed(self):
        for toml, msg in (('[lint_watch]\nmode = "quiet"\n', r"\[lint_watch\] mode must be one of on, off"),
                          ('[lint_watch]\nmode = false\n', r"\[lint_watch\] mode must be one of on, off"),
                          ('[lint_watch]\npaths = "docs"\n', r"\[lint_watch\] paths must be a list"),
                          ('[lint_watch]\ntargets = []\n', r"unknown key \[lint_watch\] targets"),
                          ('lint_watch = 1\n', r"\[lint_watch\] must be a table")):
            with self.subTest(toml=toml):
                self.project(toml)
                with self.assertRaisesRegex(config.ConfigError, msg):
                    config.lint_watch(self.cwd)


class CaptureSources(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)

    def project(self, toml: str) -> None:
        (self.cwd / ".plainspoken").mkdir(exist_ok=True)
        (self.cwd / ".plainspoken" / "config.toml").write_text(toml, encoding="utf-8")

    def test_default_is_all_five(self):
        self.assertEqual(config.kaizen_settings(self.cwd, {})["capture_sources"],
                         ["check", "merge", "judge", "lint-watch", "tool-call"])

    def test_section_loads(self):
        self.project('[kaizen]\ncapture_sources = ["check", "merge"]\n')
        self.assertEqual(config.kaizen_settings(self.cwd, {})["capture_sources"], ["check", "merge"])
        self.project('[kaizen]\ncapture_sources = []\n')
        self.assertEqual(config.kaizen_settings(self.cwd, {})["capture_sources"], [])

    def test_unknown_capture_source_errors(self):
        for body, msg in (('capture_sources = ["check", "lint"]',
                           r"\[kaizen\] capture_sources: unknown source 'lint' \(expected check, merge, judge, "
                           r"lint-watch or tool-call\)"),
                          ('capture_sources = "check"', r"\[kaizen\] capture_sources must be a list"),
                          ('capture_sources = [1]', r"\[kaizen\] capture_sources must be a list")):
            with self.subTest(body=body):
                self.project(f"[kaizen]\n{body}\n")
                with self.assertRaisesRegex(config.ConfigError, msg):
                    config.kaizen_settings(self.cwd, {})


class LocaleResolve(unittest.TestCase):  # #121: project config → profile → user-wide → plugin option → en-AU
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.env = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")}

    def project(self, toml: str) -> Path:
        (self.cwd / ".plainspoken").mkdir(exist_ok=True)
        path = self.cwd / ".plainspoken" / "config.toml"
        path.write_text(toml, encoding="utf-8")
        return path

    def user(self, toml: str) -> Path:
        path = self.home / ".config" / "plainspoken" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(toml, encoding="utf-8")
        return path

    def prof(self, locale: str | None = None):
        path = self.cwd / "p.toml"
        path.write_text('[profile]\nname = "p"\n' + (f'locale = "{locale}"\n' if locale else ""), encoding="utf-8")
        return config.load(path)

    def resolve(self, prof=None, env=None, plugin=None):
        return config.resolve_locale(prof if prof is not None else self.prof(), self.cwd,
                                     {**self.env, **(env or {})}, plugin)

    def test_default_when_nothing_sets_it(self):
        got = self.resolve()
        self.assertEqual((got.variant, got.source, got.label), ("en-AU", "default", "default"))

    def test_plugin_option_flag(self):
        got = self.resolve(plugin="en-US")
        self.assertEqual((got.variant, got.label), ("en-US", "plugin option"))

    def test_env_beats_the_flag(self):
        got = self.resolve(env={"CLAUDE_PLUGIN_OPTION_LOCALE": "en-GB"}, plugin="en-US")
        self.assertEqual((got.variant, got.source), ("en-GB", "plugin option"))

    def test_empty_or_placeholder_counts_as_unset(self):
        for env_value in ("", "${user_config.locale}", "  "):
            with self.subTest(env=env_value):
                got = self.resolve(env={"CLAUDE_PLUGIN_OPTION_LOCALE": env_value}, plugin="en-US")
                self.assertEqual((got.variant, got.source), ("en-US", "plugin option"))
        for flag in ("", "${user_config.locale}", None):
            with self.subTest(flag=flag):
                got = self.resolve(plugin=flag)
                self.assertEqual((got.variant, got.label), ("en-AU", "default"))

    def test_unknown_option_falls_through_with_a_note(self):
        got = self.resolve(plugin="en-NZ")
        self.assertEqual((got.variant, got.source), ("en-AU", "default"))
        self.assertEqual(got.label, "default; plugin option 'en-NZ' isn't a known variant")
        self.user('[locale]\nvariant = "en-GB"\n')  # the note is only for the level the answer came from
        self.assertEqual(self.resolve(plugin="en-NZ").label.count("en-NZ"), 0)

    def test_user_wide_beats_the_plugin_option(self):
        path = self.user('[locale]\nvariant = "en-GB"\n')
        got = self.resolve(env={"CLAUDE_PLUGIN_OPTION_LOCALE": "en-US"}, plugin="en-US")
        self.assertEqual((got.variant, got.source), ("en-GB", "user-wide config"))
        self.assertEqual(got.label, f"user-wide config, {path}")

    def test_profile_beats_user_wide(self):
        self.user('[locale]\nvariant = "en-GB"\n')
        got = self.resolve(prof=self.prof("en-US"), plugin="en-GB")
        self.assertEqual((got.variant, got.label), ("en-US", "profile"))

    def test_project_beats_profile(self):
        self.project('[locale]\nvariant = "en-GB"\n')
        self.user('[locale]\nvariant = "en-AU"\n')
        got = self.resolve(prof=self.prof("en-US"), plugin="en-US")
        self.assertEqual((got.variant, got.source), ("en-GB", "project config"))
        self.assertEqual(got.label, "project config, .plainspoken/config.toml")

    def test_no_profile_skips_that_level(self):
        self.user('[locale]\nvariant = "en-US"\n')
        got = config.resolve_locale(None, self.cwd, self.env, None)
        self.assertEqual((got.variant, got.source), ("en-US", "user-wide config"))

    def test_bad_variant_is_a_config_error_naming_file_and_key(self):
        for writer in (self.project, self.user):
            with self.subTest(file=writer.__name__):
                path = writer('[locale]\nvariant = "en-NZ"\n')
                with self.assertRaises(config.ConfigError) as cm:
                    self.resolve()
                self.assertIn(str(path), str(cm.exception))
                self.assertIn("[locale] variant", str(cm.exception))
                self.assertIn("en-NZ", str(cm.exception))
                path.unlink()

    def test_unknown_key_and_wrong_type(self):
        self.project('[locale]\nspelling = "en-GB"\n')
        with self.assertRaisesRegex(config.ConfigError, r"unknown key \[locale\] spelling"):
            self.resolve()
        self.project('[locale]\nvariant = 1\n')
        with self.assertRaisesRegex(config.ConfigError, r"\[locale\] variant"):
            self.resolve()

    def test_locale_never_reaches_the_profile_stamp(self):  # it isn't in profile_sha256, so no report goes stale
        before = self.prof().sha256
        self.project('[locale]\nvariant = "en-US"\n')
        self.assertEqual(config.resolve_profile(str(self.cwd / "p.toml"), self.cwd, self.env).sha256, before)
