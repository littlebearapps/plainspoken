"""tests/test_rulesedit.py: comment-preserving edits to rules.toml and profiles, version bumps, diff, changelog,
and the `deprecated` rule status (Phase 5). Every edit runs on an in-memory copy of the real ruleset, so
data/rules.toml stays byte-identical."""
import difflib
import hashlib
import json
import os
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from plainspoken import judges, report, rulesedit
from plainspoken.__main__ import _profile_summary
from plainspoken.profile import load as load_profile
from plainspoken.registry import load_config
from plainspoken.rulesedit import EditError
from tests._profiles import PRODUCT

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "data" / "rules.toml"
DEFAULT_PROFILE = REPO / "data" / "profiles" / "default.toml"
CFG = load_config()


def _changed_lines(old: str, new: str) -> tuple[list[str], list[str]]:
    """(removed, added) lines between two texts."""
    removed, added = [], []
    for line in difflib.ndiff(old.splitlines(), new.splitlines()):
        if line.startswith("- "):
            removed.append(line[2:])
        elif line.startswith("+ "):
            added.append(line[2:])
    return removed, added


def _load_text(text: str):
    tmp = Path(tempfile.mkdtemp())
    try:
        path = tmp / "rules.toml"
        path.write_text(text, encoding="utf-8")
        return load_config(path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = RULES.read_text(encoding="utf-8")
        cls.sha = hashlib.sha256(RULES.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):  # no test may touch the shipped ruleset
        if hashlib.sha256(RULES.read_bytes()).hexdigest() != cls.sha:  # not `assert`: it must hold under -O too
            raise AssertionError("data/rules.toml changed")


class SetThreshold(Base):
    def test_mattr_blocking_changes_exactly_one_line(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "set_threshold", "table": "default", "key": "mattr_blocking",
                                                 "old": False, "new": True}])
        self.assertEqual(_changed_lines(self.text, new), (["mattr_blocking = false"], ["mattr_blocking = true"]))
        d = rulesedit.diff(self.text, new, "rules.toml")
        self.assertIn("-mattr_blocking = false\n", d)
        self.assertIn("+mattr_blocking = true\n", d)
        self.assertIn("--- a/rules.toml", d)
        self.assertTrue(_load_text(new)._thresholds["default"]["mattr_blocking"])

    def test_a_value_too_small_to_write_is_refused(self):  # never rounded to 0 silently
        for value in (1e-12, 3e-11):
            with self.subTest(value=value), self.assertRaisesRegex(EditError, "can't be written"):
                rulesedit.apply_edits(self.text, [{"kind": "set_threshold", "table": "default", "key": "mattr_min",
                                                   "old": 0.46, "new": value}])

    def test_a_result_that_isnt_toml_is_refused(self):  # the post-edit tomllib check
        broken = mock.patch.dict(rulesedit._RULESET_EDITS, {"set_threshold": lambda text, edit: text + "\n[[[x\n"})
        with broken, self.assertRaisesRegex(EditError, "the edited ruleset isn't valid TOML"):
            rulesedit.apply_edits(self.text, [{"kind": "set_threshold", "table": "default", "key": "mattr_blocking",
                                               "old": False, "new": True}])
        profile = DEFAULT_PROFILE.read_text(encoding="utf-8")
        with mock.patch.object(rulesedit, "_profile_threshold", lambda text, edit, defaults: text + "\n[[[x\n"), \
                self.assertRaisesRegex(EditError, "the edited profile isn't valid TOML"):
            rulesedit.apply_profile_edits(profile, [{"kind": "set_threshold", "table": "default",
                                                     "key": "staccato_short_run", "old": 5, "new": 6}])

    def test_thresholds_are_read_through_the_public_method(self):  # no private cfg._thresholds
        self.assertEqual(CFG.thresholds(), dict(CFG.thresholds(None, "article")))
        self.assertEqual(CFG.thresholds()["mattr_min"], 0.46)
        src = (REPO / "lib" / "plainspoken" / "rulesedit.py").read_text(encoding="utf-8")
        self.assertNotIn("._thresholds", src)

    def test_float_step_written_cleanly(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "set_threshold", "table": "default", "key": "mattr_min",
                                                 "old": 0.46, "new": 0.46 - 0.02}])
        self.assertEqual(_changed_lines(self.text, new), (["mattr_min = 0.46"], ["mattr_min = 0.44"]))

    def test_int_step(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "set_threshold", "table": "default",
                                                 "key": "staccato_short_run", "old": 5, "new": 6}])
        self.assertEqual(_changed_lines(self.text, new), (["staccato_short_run = 5"], ["staccato_short_run = 6"]))

    def test_only_the_named_table_changes(self):  # staccato_short_run is in both default and social
        new = rulesedit.apply_edits(self.text, [{"kind": "set_threshold", "table": "social",
                                                 "key": "staccato_short_run", "old": 4, "new": 5}])
        raw = tomllib.loads(new)
        self.assertEqual((raw["thresholds"]["default"]["staccato_short_run"],
                          raw["thresholds"]["social"]["staccato_short_run"]), (5, 5))
        self.assertEqual(len(_changed_lines(self.text, new)[1]), 1)

    def test_old_compared_by_value_not_text(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "set_threshold", "table": "default",
                                                 "key": "uniform_tolerance", "old": 0.20, "new": 0.25}])
        self.assertIn("uniform_tolerance = 0.25\n", new)

    def test_unknown_key_or_type_change_refused(self):
        for edit, msg in (({"key": "no_such_key", "old": 1, "new": 2}, "unknown threshold"),
                          ({"key": "mattr_blocking", "old": False, "new": 1}, "type"),
                          ({"key": "em_dash_max", "old": 3, "new": 3.5}, "type"),
                          ({"key": "mattr_min", "old": 0.46, "new": float("nan")}, "finite")):
            with self.subTest(edit=edit), self.assertRaisesRegex(EditError, msg):
                rulesedit.apply_edits(self.text, [{"kind": "set_threshold", "table": "default", **edit}])

    def test_comment_on_the_line_is_kept(self):
        text = self.text.replace("em_dash_max = 3\n", "em_dash_max = 3  # spec cap\n", 1)
        new = rulesedit.apply_edits(text, [{"kind": "set_threshold", "table": "default", "key": "em_dash_max",
                                            "old": 3, "new": 4}])
        self.assertIn("em_dash_max = 4  # spec cap\n", new)


class ListAdd(Base):
    def test_multi_line_list_keeps_every_other_line(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "list_add", "list": "density_total_only", "values": ["here"]}])
        self.assertEqual(_changed_lines(self.text, new), ([], ['  "here",']))
        self.assertIn('density_total_only = [\n  "then",\n  "so",\n  "now",\n  "here",\n]\n', new)
        self.assertEqual(_load_text(new).lists["density_total_only"], ["then", "so", "now", "here"])

    def test_single_line_list(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "list_add", "list": "gotcha_framing",
                                                 "values": ["the twist", 'say "hi"']}])
        removed, added = _changed_lines(self.text, new)
        self.assertEqual(len(removed), 1)
        self.assertTrue(added[0].endswith('"the kicker", "the twist", "say \\"hi\\""]'), added[0])
        self.assertEqual(tomllib.loads(new)["lists"]["gotcha_framing"][-2:], ["the twist", 'say "hi"'])

    def test_values_already_present_are_skipped(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "list_add", "list": "density_total_only",
                                                 "values": ["so", "here", "here"]}])
        self.assertEqual(_changed_lines(self.text, new), ([], ['  "here",']))
        with self.assertRaisesRegex(EditError, "nothing to change"):
            rulesedit.apply_edits(self.text, [{"kind": "list_add", "list": "density_total_only", "values": ["so"]}])

    def test_last_item_without_trailing_comma(self):
        text = self.text.replace('  "so",\n  "now",\n]\nrepeat_stopwords', '  "so",\n  "now"\n]\nrepeat_stopwords')
        self.assertNotEqual(text, self.text)
        new = rulesedit.apply_edits(text, [{"kind": "list_add", "list": "density_total_only", "values": ["here"]}])
        self.assertEqual(tomllib.loads(new)["lists"]["density_total_only"], ["then", "so", "now", "here"])

    def test_empty_lists(self):
        text = self.text.replace('density_total_only = [\n  "then",\n  "so",\n  "now",\n]\n',
                                 'density_total_only = []\n')
        new = rulesedit.apply_edits(text, [{"kind": "list_add", "list": "density_total_only", "values": ["here"]}])
        self.assertIn('density_total_only = ["here"]\n', new)

    def test_unknown_list_or_bad_values_refused(self):
        for edit, msg in (({"list": "no_such_list", "values": ["x"]}, "unknown list"),
                          ({"list": "density_total_only", "values": []}, "values"),
                          ({"list": "density_total_only", "values": [1]}, "values"),
                          ({"list": "density_total_only", "values": "here"}, "values")):
            with self.subTest(edit=edit), self.assertRaisesRegex(EditError, msg):
                rulesedit.apply_edits(self.text, [{"kind": "list_add", **edit}])


class RuleField(Base):
    def test_delete_status_on_32(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "rule_field", "rule": "32", "field": "status",
                                                 "old": "shadow", "new": None}])
        self.assertEqual(_changed_lines(self.text, new), (['status = "shadow"'], []))
        self.assertEqual(_load_text(new).rules["32"].status, "active")
        self.assertEqual(_load_text(new).rules["31"].status, "shadow")

    def test_severity_on_7(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "rule_field", "rule": "7", "field": "severity",
                                                 "old": "WARN", "new": "BLOCK"}])
        self.assertEqual(_changed_lines(self.text, new), (['severity = "WARN"'], ['severity = "BLOCK"']))
        cfg = _load_text(new)
        self.assertEqual((cfg.rules["7"].severity, cfg.rules["7b"].severity), ("BLOCK", "WARN"))

    def test_insert_after_severity(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "rule_field", "rule": "22", "field": "status",
                                                 "old": None, "new": "deprecated"}])
        self.assertIn('id = "22"\nname = "Challenges / Future outlook"\nmethod = "lint+judge"\ngroup = "J2"\n'
                      'severity = "WARN"\nstatus = "deprecated"\njudge_may_block = true\n', new)
        self.assertEqual(_load_text(new).rules["22"].status, "deprecated")

    def test_models_list(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "rule_field", "rule": "28", "field": "models",
                                                 "old": ["claude-opus-5.5"], "new": ["claude-opus-5.5", "gpt-6"]}])
        self.assertIn('models = ["claude-opus-5.5", "gpt-6"]\n', new)
        self.assertEqual(_load_text(new).rules["28"].models, ("claude-opus-5.5", "gpt-6"))

    def test_multi_line_models_stay_multi_line(self):  # the layout is kept, one item per line
        text = self.text.replace('models = ["claude-opus-5.5"]\nsource = "Arize',
                                 'models = [\n  "claude-opus-5.5",\n]  # who\nsource = "Arize', 1)
        self.assertNotEqual(text, self.text)
        new = rulesedit.apply_edits(text, [{"kind": "rule_field", "rule": "28", "field": "models",
                                            "old": ["claude-opus-5.5"], "new": ["claude-opus-5.5", "gpt-6"]}])
        self.assertIn('models = [\n  "claude-opus-5.5",\n  "gpt-6",\n]  # who\nsource = "Arize', new)
        self.assertEqual(_load_text(new).rules["28"].models, ("claude-opus-5.5", "gpt-6"))

    def test_bad_field_rule_or_value_refused(self):
        for edit, msg in (({"rule": "7", "field": "name", "old": "x", "new": "y"}, "field"),
                          ({"rule": "nope", "field": "severity", "old": "WARN", "new": "BLOCK"}, "unknown rule"),
                          ({"rule": "28", "field": "models", "old": ["claude-opus-5.5"], "new": "gpt-6"}, "models"),
                          ({"rule": "7", "field": "severity", "old": "WARN", "new": None}, "severity")):
            with self.subTest(edit=edit), self.assertRaisesRegex(EditError, msg):
                rulesedit.apply_edits(self.text, [{"kind": "rule_field", **edit}])


class RuleRemove(Base):
    def test_remove_22_loads_without_it(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "rule_remove", "rule": "22"}])
        cfg = _load_text(new)
        self.assertNotIn("22", cfg.rules)
        self.assertEqual(len(cfg.rules), len(load_config().rules) - 1)
        removed, added = _changed_lines(self.text, new)
        self.assertEqual(added, [])
        self.assertEqual(len(removed), 10)  # the 9-line block and the blank line before it
        self.assertIn('era = "pre-2026"\n\n[[rules]]\nid = "23"', new)
        self.assertNotIn("\n\n\n", new)

    def test_remove_last_rule_keeps_the_next_comment(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "rule_remove", "rule": "32"}])
        self.assertNotIn("32", _load_text(new).rules)
        self.assertIn("# A profile rule that re-thresholds a universal rule", new)

    def test_remove_an_aliased_rule_refused(self):  # NR-1 → 1: removing 1 would leave a dangling alias
        with self.assertRaisesRegex(EditError, "alias"):
            rulesedit.apply_edits(self.text, [{"kind": "rule_remove", "rule": "1"}])


RULE_99 = {"name": "Test rule", "method": "judge", "group": "J2", "severity": "WARN", "era": "2026",
           "models": ["claude-opus-5.5"], "source": "a test"}


class ThresholdAdd(Base):
    """A new knob for an existing rule (12d's FAQ run) lands through kaizen apply like any threshold."""

    def test_threshold_add_after_a_key(self):
        edit = {"kind": "threshold_add", "key": "x_faq_run", "value": 6, "after": "paragraph_uniform_run"}
        new = rulesedit.apply_edits(self.text, [edit])
        removed, added = _changed_lines(self.text, new)
        self.assertEqual((removed, added), ([], ["x_faq_run = 6"]))
        self.assertIn("paragraph_uniform_run = 4\nx_faq_run = 6\n", new)
        self.assertEqual(_load_text(new).thresholds(PRODUCT)["x_faq_run"], 6)

    def test_threshold_add_at_the_end_without_after(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "threshold_add", "key": "x_run", "value": 2}])
        default = list(tomllib.loads(new)["thresholds"]["default"])
        self.assertEqual(default[-1], "x_run")

    def test_threshold_add_refusals(self):
        for edit, msg in (({"key": "em_dash_max", "value": 4}, "already exists"),
                          ({"key": "x_run", "value": "two"}, "number"),
                          ({"key": "bad key", "value": 1}, "plain key"),
                          ({"key": "x_run", "value": 1, "after": "no_such_key"}, "no_such_key"),
                          ({"value": 1}, "key")):
            with self.subTest(edit=edit), self.assertRaisesRegex(EditError, msg):
                rulesedit.apply_edits(self.text, [{"kind": "threshold_add", **edit}])


class RuleAdd(Base):
    def test_rule_add_appends(self):
        new = rulesedit.apply_edits(self.text, [{"kind": "rule_add", "rule": "99", "block": RULE_99}])
        removed, added = _changed_lines(self.text, new)
        self.assertEqual(removed, [])
        self.assertEqual(added, ["", "[[rules]]", 'id = "99"', 'name = "Test rule"', 'method = "judge"',
                                 'group = "J2"', 'severity = "WARN"', 'era = "2026"', 'models = ["claude-opus-5.5"]',
                                 'source = "a test"'])
        # after the last rule, before the [aliases] comment, one blank line either side
        self.assertIn('source = "a test"\n\n# A profile rule that re-thresholds', new)
        self.assertNotIn("\n\n\n", new)
        rule = _load_text(new).rules["99"]
        self.assertEqual((rule.method, rule.group, rule.models), ("judge", "J2", ("claude-opus-5.5",)))
        self.assertEqual(list(_load_text(new).rules)[-1], "99")

    def test_rule_add_writes_fields_in_the_usual_order(self):  # a stored proposal's JSON sorts its keys
        edit = {"kind": "rule_add", "rule": "99", "block": dict(sorted(RULE_99.items()))}
        new = rulesedit.apply_edits(self.text, [edit])
        self.assertIn('id = "99"\nname = "Test rule"\nmethod = "judge"\ngroup = "J2"\nseverity = "WARN"\nera = "2026"\n'
                      'models = ["claude-opus-5.5"]\nsource = "a test"\n', new)

    def test_rule_add_existing_id_refused(self):
        with self.assertRaisesRegex(EditError, "rule 32 already exists"):
            rulesedit.apply_edits(self.text, [{"kind": "rule_add", "rule": "32", "block": RULE_99}])
        with self.assertRaisesRegex(EditError, "already exists"):
            rulesedit.apply_edits(self.text, [{"kind": "rule_add", "rule": "99", "block": RULE_99},
                                              {"kind": "rule_add", "rule": "99", "block": RULE_99}])

    def test_rule_add_round_trips_tomllib(self):
        block = {**RULE_99, "source": 'Quotes "and" back\\slashes — dashes'}
        edit = {"kind": "rule_add", "rule": "99", "block": block, "lists": {"test_phrases": ["a b", 'say "c"']},
                "thresholds": {"test_phrases_warn": 2}}
        new = rulesedit.apply_edits(self.text, [edit])
        raw, old = tomllib.loads(new), tomllib.loads(self.text)
        self.assertEqual(raw["rules"][-1], {"id": "99", **block})
        self.assertEqual(raw["rules"][:-1], old["rules"])
        self.assertEqual(raw["lists"], {**old["lists"], "test_phrases": ["a b", 'say "c"']})
        self.assertEqual(raw["thresholds"]["default"], {**old["thresholds"]["default"], "test_phrases_warn": 2})
        self.assertEqual({k: v for k, v in raw.items() if k not in ("rules", "lists", "thresholds")},
                         {k: v for k, v in old.items() if k not in ("rules", "lists", "thresholds")})
        self.assertEqual(_load_text(new).thresholds(PRODUCT)["test_phrases_warn"], 2)
        self.assertIn('test_phrases = ["a b", "say \\"c\\""]\n', new)

    def test_rule_add_refusals(self):
        for edit, msg in (({"rule": "99"}, "block"),
                          ({"rule": "99", "block": "x"}, "block"),
                          ({"rule": "99", "block": {**RULE_99, "id": "98"}}, "id"),
                          ({"rule": "99", "block": {k: v for k, v in RULE_99.items() if k != "name"}}, "name"),
                          ({"rule": "99", "block": {**RULE_99, "bad key": "x"}}, "key"),
                          ({"rule": "99", "block": {**RULE_99, "severity": "MAYBE"}}, "bad severity"),
                          ({"rule": "99", "block": RULE_99, "lists": {"gotcha_framing": ["x"]}}, "already"),
                          ({"rule": "99", "block": RULE_99, "lists": {"new_list": []}}, "values"),
                          ({"rule": "99", "block": RULE_99, "thresholds": {"em_dash_max": 4}}, "already"),
                          ({"rule": "99", "block": RULE_99, "thresholds": {"x_warn": "two"}}, "number"),
                          ({"rule": "99", "block": {**RULE_99, "method": "lint", "group": None}}, "no lint check")):
            edit = {"kind": "rule_add", **edit}
            if isinstance(edit.get("block"), dict):
                edit["block"] = {k: v for k, v in edit["block"].items() if v is not None}
            with self.subTest(edit=edit), self.assertRaisesRegex(EditError, msg):
                rulesedit.apply_edits(self.text, [edit])


class FailClosed(Base):
    def test_wrong_old_is_stale(self):
        cases = ({"kind": "set_threshold", "table": "default", "key": "mattr_blocking", "old": True, "new": False},
                 {"kind": "set_threshold", "table": "default", "key": "em_dash_max", "old": True, "new": 4},
                 {"kind": "rule_field", "rule": "7", "field": "severity", "old": "BLOCK", "new": "WARN"},
                 {"kind": "rule_field", "rule": "7", "field": "status", "old": "shadow", "new": None})
        for edit in cases:
            with self.subTest(edit=edit), self.assertRaisesRegex(EditError, "stale"):
                rulesedit.apply_edits(self.text, [edit])

    def test_second_edit_sees_the_first(self):  # two edits on the same key: the second's old must be the new value
        e1 = {"kind": "set_threshold", "table": "default", "key": "em_dash_max", "old": 3, "new": 4}
        with self.assertRaisesRegex(EditError, "stale"):
            rulesedit.apply_edits(self.text, [e1, dict(e1)])
        new = rulesedit.apply_edits(self.text, [e1, {**e1, "old": 4, "new": 5}])
        self.assertIn("em_dash_max = 5\n", new)

    def test_edit_that_breaks_the_ruleset_refused(self):
        for edit, msg in (({"rule": "7", "field": "severity", "old": "WARN", "new": "MAYBE"}, "bad severity"),
                          ({"rule": "5c", "field": "status", "old": None, "new": "shadow"}, "lint-only"),
                          ({"rule": "7", "field": "status", "old": None, "new": "retired"}, "bad status")):
            with self.subTest(edit=edit), self.assertRaisesRegex(EditError, msg):
                rulesedit.apply_edits(self.text, [{"kind": "rule_field", **edit}])

    def test_text_that_is_not_toml_refused(self):
        with self.assertRaisesRegex(EditError, "TOML"):
            rulesedit.apply_edits(self.text + "\n[[[broken\n", [{"kind": "rule_remove", "rule": "22"}])

    def test_bad_edit_shapes_refused(self):
        for edits in ([], [{"kind": "explode"}], [{"kind": "set_threshold", "key": "em_dash_max"}], ["x"]):
            with self.subTest(edits=edits), self.assertRaises(EditError):
                rulesedit.apply_edits(self.text, edits)

    def test_input_text_not_mutated_and_real_file_unchanged(self):
        before = self.text
        rulesedit.apply_edits(self.text, [{"kind": "rule_remove", "rule": "22"}])
        self.assertEqual(before, RULES.read_text(encoding="utf-8"))


class Versions(Base):
    def test_bump(self):
        self.assertEqual(rulesedit.bump("4.1.0", "minor"), "4.2.0")
        self.assertEqual(rulesedit.bump("4.1.0", "major"), "5.0.0")
        self.assertEqual(rulesedit.bump("4.1.3", "patch"), "4.1.4")
        self.assertEqual(rulesedit.bump("4.9.9", "minor"), "4.10.0")
        for version, part in (("4.1", "minor"), ("v4.1.0", "minor"), ("4.1.0", "huge"), ("4.01.0", "minor")):
            with self.subTest(version=version, part=part), self.assertRaises(EditError):
                rulesedit.bump(version, part)

    def test_set_version(self):
        new = rulesedit.set_version(self.text, "4.5.0")
        self.assertEqual(_changed_lines(self.text, new), (['version = "4.4.0"'], ['version = "4.5.0"']))
        self.assertEqual(_load_text(new).version, "4.5.0")
        with self.assertRaises(EditError):
            rulesedit.set_version(self.text, "four")
        with self.assertRaisesRegex(EditError, "version"):
            rulesedit.set_version("[thresholds]\n", "4.2.0")

    def test_set_version_ignores_a_table_key_named_version(self):
        text = '[meta]\nversion = "1.0.0"\n'
        with self.assertRaisesRegex(EditError, "version"):
            rulesedit.set_version(text, "2.0.0")


class Changelog(unittest.TestCase):
    def test_entry_shape(self):
        proposal = {"id": "KZ-20261014-abc123", "rule": "4b", "action": "loosen", "trigger": "kept",
                    "summary": "Count 'so' and 'then' toward the total only.",
                    "evidence": {"kept_docs": 3, "terms": {"so": 3, "then": 2},
                                 "excerpts": ["So the cache was stale."]}}
        entry = rulesedit.changelog_entry("4.2.0", "2026-10-14", proposal, "owner")
        lines = entry.splitlines()
        self.assertEqual(lines[0], "## 4.2.0 (2026-10-14)")
        self.assertEqual(lines[1], "")
        bullets = lines[2:]
        self.assertTrue(bullets and all(b.startswith("- ") for b in bullets), entry)
        self.assertIn("KZ-20261014-abc123", entry)
        self.assertIn("rule 4b", entry)
        self.assertIn("loosen", entry)
        self.assertIn("kept_docs 3", entry)
        self.assertIn("approved by owner", entry.lower())
        self.assertNotIn("cache was stale", entry)  # excerpts are article text: never in the changelog
        self.assertTrue(entry.endswith("\n"))

    def test_nested_evidence_is_flattened_not_repr(self):
        proposal = {"id": "KZ-1", "rule": "4b", "action": "loosen", "summary": "s",
                    "evidence": {"facets": {"kind": {"false_positive": 4, "excerpt": "We delve in."},
                                            "section": {"faq": 2, "intro": 1}, "terms": ["so", {"then": 2}]}}}
        entry = rulesedit.changelog_entry("4.2.0", "2026-10-14", proposal, "owner")
        (line,) = [ln for ln in entry.splitlines() if ln.startswith("- Evidence: ")]
        self.assertEqual(line, "- Evidence: facets kind false_positive 4, section faq 2 intro 1, terms so then 2")
        self.assertNotIn("delve", entry)  # an excerpt key is dropped at any depth

    def test_one_line_fields(self):
        proposal = {"id": "KZ-1", "rule": "7", "action": "demote", "summary": "two\nlines", "evidence": {}}
        entry = rulesedit.changelog_entry("5.0.0", "2026-10-14", proposal, "a\nb")
        self.assertEqual(len([ln for ln in entry.splitlines() if ln and not ln.startswith(("- ", "## "))]), 0)


class ProfileEdits(Base):
    def setUp(self):
        self.profile = DEFAULT_PROFILE.read_text(encoding="utf-8")

    def test_insert_under_empty_thresholds(self):
        new = rulesedit.apply_profile_edits(self.profile, [{"kind": "set_threshold", "table": "default",
                                                            "key": "staccato_short_run", "old": 5, "new": 6}])
        self.assertEqual(_changed_lines(self.profile, new), ([], ["staccato_short_run = 6"]))
        self.assertIn("[thresholds]\nstaccato_short_run = 6\n\n[lexicon]", new)

    def test_replace_existing(self):
        text = self.profile.replace("[thresholds]\n", "[thresholds]\nem_dash_max = 5  # narrative\n")
        new = rulesedit.apply_profile_edits(text, [{"kind": "set_threshold", "table": "default",
                                                    "key": "em_dash_max", "old": 5, "new": 6}])
        self.assertEqual(_changed_lines(text, new), (["em_dash_max = 5  # narrative"], ["em_dash_max = 6  # narrative"]))
        with self.assertRaisesRegex(EditError, "stale"):  # old is the profile's value, not the ruleset's 3
            rulesedit.apply_profile_edits(text, [{"kind": "set_threshold", "table": "default",
                                                  "key": "em_dash_max", "old": 3, "new": 6}])

    def test_old_is_the_ruleset_default_when_unset(self):
        with self.assertRaisesRegex(EditError, "stale"):
            rulesedit.apply_profile_edits(self.profile, [{"kind": "set_threshold", "table": "default",
                                                          "key": "staccato_short_run", "old": 4, "new": 6}])

    def test_no_thresholds_table_appends_one(self):
        text = '[profile]\nname = "mine"\n'
        new = rulesedit.apply_profile_edits(text, [{"kind": "set_threshold", "table": "default",
                                                    "key": "mattr_blocking", "old": False, "new": True}])
        self.assertTrue(new.startswith(text))
        self.assertEqual(tomllib.loads(new)["thresholds"], {"mattr_blocking": True})

    def test_loads_as_a_profile(self):
        new = rulesedit.apply_profile_edits(self.profile, [{"kind": "set_threshold", "table": "default",
                                                            "key": "mattr_min", "old": 0.46, "new": 0.46 - 0.02}])
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "p.toml").write_text(new, encoding="utf-8")
        prof = load_profile(tmp / "p.toml")
        self.assertEqual(prof.thresholds, {"mattr_min": 0.44})
        load_config().check_profile(prof)

    def test_refusals(self):
        for edits, msg in (([{"kind": "rule_remove", "rule": "22"}], "set_threshold"),
                           ([{"kind": "set_threshold", "table": "social", "key": "em_dash_max", "old": 1, "new": 2}],
                            "default"),
                           ([{"kind": "set_threshold", "table": "default", "key": "nope", "old": 1, "new": 2}],
                            "unknown threshold"),
                           ([{"kind": "set_threshold", "table": "default", "key": "em_dash_max", "old": 3,
                              "new": 3.5}], "type"),
                           ([], "nothing to change")):
            with self.subTest(edits=edits), self.assertRaisesRegex(EditError, msg):
                rulesedit.apply_profile_edits(self.profile, edits)

    def test_invalid_profile_refused(self):
        text = self.profile.replace('[profile]\nname = "default"', '[profile]\nname = "Bad Name"')
        with self.assertRaisesRegex(EditError, "name"):
            rulesedit.apply_profile_edits(text, [{"kind": "set_threshold", "table": "default",
                                                  "key": "em_dash_max", "old": 3, "new": 4}])

    def test_profile_with_calibration_notes_validates(self):  # the notes file isn't next to the text
        text = self.profile + '\n[judges]\ncalibration_notes = "notes.md"\n'
        new = rulesedit.apply_profile_edits(text, [{"kind": "set_threshold", "table": "default",
                                                    "key": "em_dash_max", "old": 3, "new": 4}])
        self.assertIn("em_dash_max = 4\n", new)


class Deprecated(Base):
    """`deprecated` behaves as active everywhere; only the profile summary lists it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        text = rulesedit.apply_edits(self.text, [
            {"kind": "rule_field", "rule": "1", "field": "status", "old": None, "new": "deprecated"},
            {"kind": "rule_field", "rule": "28", "field": "status", "old": "shadow", "new": "deprecated"},
            {"kind": "rule_field", "rule": "22", "field": "status", "old": None, "new": "deprecated"},
        ])
        self.rules = self.tmp / "rules.toml"
        self.rules.write_text(text, encoding="utf-8")
        self.cfg = load_config(self.rules)
        self.art = self.tmp / "post.md"
        self.art.write_text("Here's the thing: one — two — three — four — five.\n\n"
                            "## Challenges\n\nSome text.\n", encoding="utf-8")

    def test_registry_accepts_it(self):
        self.assertEqual({r for r, x in self.cfg.rules.items() if x.status == "deprecated"}, {"1", "22", "28"})

    def test_rules_for_profile_includes_it(self):
        ids = {r.id for r in self.cfg.rules_for_profile(PRODUCT)}
        self.assertTrue({"1", "22", "28"} <= ids)

    def test_run_lint_finds_it_as_if_active(self):
        lint = report.run_lint(self.art, PRODUCT, cfg=self.cfg)
        by_rule = {f["rule"]: f for f in lint["findings"]}
        self.assertEqual(by_rule["1"]["severity"], "BLOCK")
        self.assertIn("1", lint["lint_rules"])
        self.assertFalse(by_rule["28"]["message"].startswith("[shadow]"))  # deprecated isn't shadow
        active = _load_text(rulesedit.apply_edits(self.text, [
            {"kind": "rule_field", "rule": "28", "field": "status", "old": "shadow", "new": None}]))
        pick = lambda fs: [f for f in fs if f["rule"] in ("1", "28")]  # noqa: E731
        self.assertEqual(pick(lint["findings"]), pick(report.run_lint(self.art, PRODUCT, cfg=active)["findings"]))

    def test_merge_and_judges_treat_it_as_active(self):
        reports = self.tmp / ".plainspoken" / "reports"
        with mock.patch.dict(os.environ, {"PLAINSPOKEN_RULES": str(self.rules)}):
            lint = report.run_lint(self.art, PRODUCT)
            paths = report.report_paths(self.art, reports, self.tmp)
            paths["lint"].parent.mkdir(parents=True)
            paths["lint"].write_text(json.dumps(lint), encoding="utf-8")
            merged = report.merge(self.art, reports, PRODUCT, cwd=self.tmp)
            judged = {r for o in judges.judge_input(self.art, PRODUCT, reports, self.tmp) for r in o["rules"]}
        expected = merged["coverage"]["expected"]
        base = report.merge(self.art, reports, PRODUCT, cwd=self.tmp)["coverage"]["expected"]  # the shipped ruleset
        self.assertEqual(expected, base + 1)  # 28 joins coverage; 1 and 22 were already expected
        self.assertIn("22", judged)

    def test_profile_summary_lists_deprecated_rules(self):
        prof = load_profile(DEFAULT_PROFILE)
        self.assertIn("deprecated rules: 1, 22, 28", _profile_summary(prof, self.cfg))
        self.assertIn("deprecated rules: none", _profile_summary(prof, load_config()))


if __name__ == "__main__":
    unittest.main()
