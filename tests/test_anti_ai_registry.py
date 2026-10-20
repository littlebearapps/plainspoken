"""tests/test_anti_ai_registry.py — the rule registry (data/rules.toml) is complete, valid and overridable."""
import os
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

from plainspoken import profile as P
from plainspoken.registry import load_config
from tests._profiles import PRODUCT, NARRATIVE, CONSULTING

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "data" / "rules.toml"
METHODS = {"lint", "lint+judge", "judge", "n/a"}
GROUPS = {"J1", "J2", "J3", "J4"}


class Registry(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()

    def test_methods_and_groups_valid(self):
        for rule in self.cfg.rules.values():
            self.assertIn(rule.method, METHODS, rule.id)
            if "judge" in rule.method:
                self.assertIn(rule.group, GROUPS, f"{rule.id} needs a judge group")
            else:
                self.assertIsNone(rule.group, rule.id)

    def test_thresholds_differ_for_the_narrative_profile(self):
        self.assertEqual(self.cfg.thresholds(PRODUCT)["em_dash_max"], 3)
        self.assertEqual(self.cfg.thresholds(CONSULTING)["em_dash_max"], 3)
        self.assertEqual(self.cfg.thresholds(NARRATIVE)["em_dash_max"], 5)

    def test_ban_list_has_no_duplicates(self):
        words = [w.lower() for w in self.cfg.lists["ban_literal"] + self.cfg.lists["ban_qualified"]]
        self.assertEqual(len(words), len(set(words)))

    def test_list_items_are_strings(self):
        for name, items in self.cfg.lists.items():
            for item in items:
                self.assertIsInstance(item, str, f"{name}: {item!r}")
        self.assertIn("on", self.cfg.lists["title_case_function_words"])

    def test_non_string_list_item_raises(self):
        bad = RULES.read_text(encoding="utf-8")
        self.assertEqual(bad.count('  "of",\n  "on",\n'), 1)
        bad = bad.replace('  "of",\n  "on",\n', '  "of",\n  1,\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.toml"
            path.write_text(bad, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-string"):
                load_config(path)

    def test_rule_ids_match_the_file(self):
        raw = tomllib.loads(RULES.read_text(encoding="utf-8"))
        self.assertEqual(set(self.cfg.rules), {str(r["id"]) for r in raw["rules"]})


class ProfileScoping(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()

    def test_profile_rules_registered_with_generic_ids(self):
        for rid in ("HM", "PB", "NR-1", "NR-2", "NR-3", "NR-4", "NR-5", "NR-6"):
            self.assertIn(rid, self.cfg.rules)
        for gone in ("NS", "AR-1", "AR-6"):  # site-scoped ids retired at the 4.0.0 port
            self.assertNotIn(gone, self.cfg.rules)

    def test_rules_follow_profile_flags_and_lexicon(self):
        ids = lambda p: {r.id for r in self.cfg.rules_for_profile(p)}
        self.assertNotIn("PB", ids(PRODUCT))
        self.assertIn("PB", ids(CONSULTING))
        self.assertIn("NR-2", ids(NARRATIVE))
        self.assertNotIn("NR-2", ids(PRODUCT))

    def test_profile_thresholds_override_defaults(self):
        self.assertEqual(self.cfg.thresholds(PRODUCT)["em_dash_max"], 3)
        self.assertEqual(self.cfg.thresholds(NARRATIVE)["em_dash_max"], 5)

    def test_social_caps_beat_profile_thresholds(self):  # default → profile → content type
        self.assertEqual(self.cfg.thresholds(NARRATIVE)["em_dash_max"], 5)
        self.assertEqual(self.cfg.thresholds(NARRATIVE, "social")["em_dash_max"], 1)
        self.assertEqual(self.cfg.thresholds(NARRATIVE, "social")["staccato_short_run"], 4)

    def test_loosened_article_cap_does_not_lift_the_social_cap(self):  # end to end
        from plainspoken.report import run_lint
        with tempfile.TemporaryDirectory() as tmp:
            post = Path(tmp) / "post.md"
            post.write_text("I tried it — and it worked — mostly.\n", encoding="utf-8")
            rule1 = [f for f in run_lint(post, NARRATIVE, "social")["findings"] if f["rule"] == "1"]
            self.assertEqual([f["severity"] for f in rule1], ["BLOCK"])
            art = Path(tmp) / "art.md"
            art.write_text("I tried it — once — twice — then again — and it worked — mostly.\n", encoding="utf-8")
            self.assertEqual([f for f in run_lint(art, NARRATIVE)["findings"] if f["rule"] == "1"], [])

    def test_disabled_rules_drop_out(self):
        import dataclasses
        quiet = dataclasses.replace(PRODUCT, rules_disabled=frozenset({"7d"}))
        self.assertNotIn("7d", {r.id for r in self.cfg.rules_for_profile(quiet)})

    def test_check_profile_rejects_unknown_threshold_and_rule(self):
        import dataclasses
        with self.assertRaisesRegex(P.ProfileError, r"\[thresholds\] em_dash_maxx"):
            self.cfg.check_profile(dataclasses.replace(PRODUCT, thresholds={"em_dash_maxx": 2}))
        with self.assertRaisesRegex(P.ProfileError, r"\[rules\] disabled.*99z"):
            self.cfg.check_profile(dataclasses.replace(PRODUCT, rules_disabled=frozenset({"99z"})))

    def test_check_profile_rejects_bool_for_number_and_number_for_bool(self):
        import dataclasses
        with self.assertRaisesRegex(P.ProfileError, r"\[thresholds\] mattr_blocking: expected bool"):
            self.cfg.check_profile(dataclasses.replace(PRODUCT, thresholds={"mattr_blocking": 1}))
        with self.assertRaisesRegex(P.ProfileError, r"\[thresholds\] em_dash_max: expected int"):
            self.cfg.check_profile(dataclasses.replace(PRODUCT, thresholds={"em_dash_max": True}))
        self.cfg.check_profile(dataclasses.replace(PRODUCT, thresholds={"mattr_blocking": True, "em_dash_max": 4}))

    def test_check_profile_rejects_float_for_int_but_allows_int_for_float(self):
        import dataclasses
        with self.assertRaisesRegex(P.ProfileError, r"\[thresholds\] em_dash_max: expected int"):
            self.cfg.check_profile(dataclasses.replace(PRODUCT, thresholds={"em_dash_max": 4.5}))
        self.cfg.check_profile(dataclasses.replace(PRODUCT, thresholds={"mattr_min": 1, "uniform_tolerance": 0.25}))

    def test_aliases_and_judge_block_rules_are_data(self):
        self.assertIn(("NR-2", "7d"), self.cfg.aliases)
        self.assertEqual({r.id for r in self.cfg.rules.values() if r.judge_may_block}, {"5e", "19", "22"})


RULE_2 = 'id = "2"\nname = "Hard-ban vocabulary"\nmethod = "lint+judge"\ngroup = "J3"\nseverity = "BLOCK"'
RULE_1 = 'id = "1"\nname = "Em dashes"\nmethod = "lint"\nseverity = "BLOCK"'


class LoaderValidation(unittest.TestCase):
    """A typo in rules.toml raises at load instead of giving a false PASS."""

    def _load(self, old: str, new: str):
        text = RULES.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, f"{old!r} must occur exactly once in data/rules.toml")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.toml"
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            return load_config(path)

    def test_bad_severity_raises(self):
        for bad in ("Block", "block", "CANDIDATE", "INFO", "BLOK"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "bad severity"):
                self._load(RULE_2, RULE_2.replace('severity = "BLOCK"', f'severity = "{bad}"'))

    def test_judge_rule_without_a_valid_group_raises(self):
        with self.assertRaisesRegex(ValueError, "needs a group"):
            self._load(RULE_2, RULE_2.replace('group = "J3"', 'group = "J5"'))
        with self.assertRaisesRegex(ValueError, "needs a group"):
            self._load(RULE_2, RULE_2.replace('group = "J3"\n', ""))

    def test_group_on_a_lint_only_rule_raises(self):
        with self.assertRaisesRegex(ValueError, "no judge"):
            self._load(RULE_1, RULE_1.replace('method = "lint"\n', 'method = "lint"\ngroup = "J1"\n'))

    def test_unknown_requires_raises(self):
        # The brief's bare 'requires = "flag:narrative"' occurs six times (NR-1..6); _load needs a unique
        # anchor, so this substitutes it on NR-1 only.
        anchor = 'name = "Narrative em-dash cap"\nmethod = "lint"\nseverity = "BLOCK"\n'
        with self.assertRaisesRegex(ValueError, "requires"):
            self._load(anchor + 'requires = "flag:narrative"', anchor + 'requires = "flag:poetry"')

    def test_deprecated_status_loads_on_any_method(self):  # Phase 5: the first retirement step, behaves as active
        cfg = self._load(RULE_2, RULE_2 + '\nstatus = "deprecated"')
        self.assertEqual(cfg.rules["2"].status, "deprecated")
        self.assertIn("2", {r.id for r in cfg.rules_for_profile(PRODUCT)})
        cfg = self._load(RULE_1, RULE_1 + '\nstatus = "deprecated"')
        self.assertEqual(cfg.rules["1"].status, "deprecated")

    def test_unknown_status_raises(self):
        for bad in ("retired", "Deprecated", "inactive"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "bad status"):
                self._load(RULE_1, RULE_1 + f'\nstatus = "{bad}"')

    def test_shipped_rules_toml_loads(self):
        self.assertEqual({r.severity for r in load_config().rules.values()}, {"BLOCK", "WARN"})


class TomlRuleset(unittest.TestCase):
    def test_version_is_semver_string(self):
        self.assertEqual(load_config().version, "4.3.0")

    def test_env_override_points_at_another_copy(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        copy = tmp / "rules.toml"
        text = RULES.read_text(encoding="utf-8").replace('version = "4.3.0"', 'version = "9.9.9"')
        copy.write_text(text, encoding="utf-8")
        old = os.environ.get("PLAINSPOKEN_RULES")
        os.environ["PLAINSPOKEN_RULES"] = str(copy)
        self.addCleanup(lambda: os.environ.pop("PLAINSPOKEN_RULES") if old is None else os.environ.__setitem__("PLAINSPOKEN_RULES", old))
        self.assertEqual(load_config().version, "9.9.9")


if __name__ == "__main__":
    unittest.main()
