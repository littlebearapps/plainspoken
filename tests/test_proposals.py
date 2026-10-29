"""The proposal store, decisions and `kaizen apply`, which writes only after a recorded approval and
refuses a stale proposal."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from plainspoken import calibrate, ledger, proposals, report, rulesedit
from plainspoken.registry import load_config
from tests.test_calibrate import (CFG, NOW, REPO, RULES, TOTAL_ONLY, TmpCase, cli, decision, fp_events, kept_4b_events,
                                  shipped_hashes)

NEXT = rulesedit.bump(CFG.version, "minor")  # the version one apply makes
AFTER_NEXT = rulesedit.bump(NEXT, "minor")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Base(TmpCase):
    def setUp(self):
        super().setUp()
        self.rules = self.copy()

    def proposal(self, rules=None, when=NOW, events=None, profile=None):
        events = fp_events() if events is None else events
        cfg = load_config(rules or self.rules) if rules is not False else CFG
        c = self.cands(events, cfg=cfg)[0]
        p = calibrate.materialise(c, None if rules is False else (rules or self.rules), cfg, profile, [], when)
        proposals.save(p, self.settings)
        return p

    def approve(self, pid, outcome="approved", when=NOW, by="Robin"):
        ledger.append(decision(pid, outcome, when, by), self.settings)

    def apply_cli(self, pid, *extra, rules=True):
        args = ["kaizen", "apply", pid, *extra]
        if rules:
            args += ["--rules", str(self.rules)]
        return cli(*args, cwd=self.root)


class Store(Base):
    def test_save_load_pending_decision(self):
        p = self.proposal()
        path = self.root / ".plainspoken" / "kaizen" / "proposals" / f"{p['id']}.json"
        self.assertTrue(path.is_file())
        self.assertEqual(proposals.load(p["id"], self.settings), p)
        self.assertEqual([x["id"] for x in proposals.pending(self.settings)], [p["id"]])
        self.approve(p["id"], "approved", NOW - timedelta(days=2))
        self.approve(p["id"], "rejected", NOW - timedelta(days=1), by="Sam")
        events = ledger.read(self.settings)[0]
        d = proposals.decision(p["id"], events)
        self.assertEqual((d["outcome"], d["facets"]["by"]), ("rejected", "Sam"))
        self.assertEqual(proposals.pending(self.settings), [])

    def test_symlinked_proposals_folder_is_refused(self):
        p = self.proposal()
        outside = self.tmp / "outside"
        outside.mkdir()
        kaizen_dir = Path(self.settings["proposals_dir"])
        shutil.rmtree(kaizen_dir)
        kaizen_dir.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(OSError, "symlink"):
            proposals.save(p, self.settings)
        self.assertEqual(list(outside.iterdir()), [])
        (outside / "proposals").mkdir()
        (outside / "proposals" / f"{p['id']}.json").write_text(json.dumps(p), encoding="utf-8")
        self.assertEqual(proposals.stored(self.settings), [])  # nothing read through the link either
        with self.assertRaises(proposals.UnknownProposal):
            proposals.load(p["id"], self.settings)

    def test_a_malformed_stored_proposal_isnt_intact(self):  # no KeyError on a missing id
        self.assertFalse(proposals._intact({"created": NOW.isoformat(), "edits": []}))
        self.assertFalse(proposals._intact({}))

    def test_load_rejects_a_bad_id(self):
        with self.assertRaises(ValueError):
            proposals.load("../../etc/passwd", self.settings)
        with self.assertRaises(ValueError):
            proposals.load("KZ-20261014-abcdef", self.settings)


class Apply(Base):
    def test_no_decision_is_refused(self):
        p = self.proposal()
        before = sha(self.rules)
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no recorded approval", r.stderr)
        self.assertEqual(sha(self.rules), before)
        self.assertFalse((self.rules.parent / "RULESET-CHANGELOG.md").exists())

    def test_approved_applies_bumps_logs_and_writes_the_changelog(self):
        p = self.proposal()
        self.approve(p["id"])
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 0, r.stderr)
        raw = tomllib.loads(self.rules.read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], NEXT)
        self.assertEqual(raw["thresholds"]["default"]["claude_warn_total"], 5)
        log = (self.rules.parent / "RULESET-CHANGELOG.md").read_text(encoding="utf-8")
        self.assertTrue(log.startswith("# Ruleset changelog"))
        self.assertIn(f"## {NEXT}", log)
        self.assertIn(p["id"], log)
        self.assertIn("Approved by Robin.", log)
        applied = [e for e in ledger.read(self.settings)[0] if e["event"] == "apply"]
        self.assertEqual([(e["outcome"], e["proposal"], e["rule"]) for e in applied], [("applied", p["id"], "2b")])

    def test_changelog_entry_goes_under_the_title(self):
        (self.rules.parent / "RULESET-CHANGELOG.md").write_text(
            "# Ruleset changelog\n\nIntro line.\n\n## 4.1.0 (2026-10-10)\n\n- older\n", encoding="utf-8")
        p = self.proposal()
        self.approve(p["id"])
        self.assertEqual(self.apply_cli(p["id"]).returncode, 0)
        log = (self.rules.parent / "RULESET-CHANGELOG.md").read_text(encoding="utf-8")
        self.assertTrue(log.startswith(f"# Ruleset changelog\n\nIntro line.\n\n## {NEXT}"))
        self.assertLess(log.index(f"## {NEXT}"), log.index("## 4.1.0"))

    def test_second_proposal_on_the_same_threshold_is_stale(self):
        cfg = load_config(self.rules)
        c = self.cands(fp_events(), cfg=cfg)[0]  # two proposals with the same edit, made on different days
        first, second = (calibrate.materialise(c, self.rules, cfg, None, [], when)
                         for when in (NOW - timedelta(days=1), NOW))
        proposals.save(first, self.settings)
        proposals.save(second, self.settings)
        self.assertNotEqual(first["id"], second["id"])
        self.approve(first["id"])
        self.approve(second["id"])
        self.assertEqual(self.apply_cli(first["id"]).returncode, 0)
        before = sha(self.rules)
        log = (self.rules.parent / "RULESET-CHANGELOG.md").read_bytes()
        r = self.apply_cli(second["id"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("stale proposal", r.stderr)
        self.assertIn("marked superseded, nothing else written", r.stderr)
        self.assertEqual(sha(self.rules), before)
        self.assertEqual((self.rules.parent / "RULESET-CHANGELOG.md").read_bytes(), log)
        self.assertEqual([(e["outcome"], e["proposal"]) for e in ledger.read(self.settings)[0]
                          if e["event"] == "apply"], [("applied", first["id"]), ("superseded", second["id"])])

    def hand_edit(self, key, old, new):
        text = rulesedit.apply_edits(self.rules.read_text(encoding="utf-8"), [
            {"kind": "set_threshold", "table": "default", "key": key, "old": old, "new": new}])
        self.rules.write_text(text, encoding="utf-8")

    def test_hand_edit_to_the_same_key_is_stale(self):
        p = self.proposal()  # claude_warn_total 4 → 5
        self.approve(p["id"])
        self.hand_edit("claude_warn_total", 4, 6)
        before = sha(self.rules)
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("stale proposal", r.stderr)
        self.assertIn("claude_warn_total", r.stderr)
        self.assertEqual(sha(self.rules), before)
        self.assertFalse((self.rules.parent / "RULESET-CHANGELOG.md").exists())
        self.assertEqual([e["outcome"] for e in ledger.read(self.settings)[0] if e["event"] == "apply"],
                         ["superseded"])  # the only write: the target and the changelog are untouched

    def test_unrelated_hand_edit_applies_rebased(self):
        """Staleness is per edit. Another threshold (and a comment) changed since calibrate, so the proposal's
        own `old` value still matches and it applies onto the current text, saying so."""
        p = self.proposal()
        self.approve(p["id"])
        self.hand_edit("filler_warn", 3, 4)
        self.rules.write_text(self.rules.read_text(encoding="utf-8") + "\n# a hand edit\n", encoding="utf-8")
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("rebased onto the current ruleset", r.stdout)
        raw = tomllib.loads(self.rules.read_text(encoding="utf-8"))
        self.assertEqual(raw["thresholds"]["default"]["claude_warn_total"], 5)
        self.assertEqual(raw["thresholds"]["default"]["filler_warn"], 4)  # the hand edit is kept
        self.assertIn("# a hand edit", self.rules.read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], NEXT)
        self.assertIn(p["id"], (self.rules.parent / "RULESET-CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertEqual(len([e for e in ledger.read(self.settings)[0] if e["event"] == "apply"]), 1)

    def test_unchanged_ruleset_is_not_rebased(self):
        p = self.proposal()
        self.approve(p["id"])
        out = proposals.apply(p["id"], self.root, self.settings, self.rules, now=NOW)
        self.assertFalse(out["rebased"])

    def test_two_proposals_on_different_keys_both_apply_in_either_order(self):
        cfg = load_config(self.rules)
        cands = self.cands(fp_events("2b") + fp_events("23"), cfg=cfg)
        self.assertEqual(sorted(c["rule"] for c in cands), ["23", "2b"])
        original = self.rules.read_text(encoding="utf-8")
        for order in (("2b", "23"), ("23", "2b")):
            with self.subTest(order=order):
                self.rules.write_text(original, encoding="utf-8")
                (self.rules.parent / "RULESET-CHANGELOG.md").unlink(missing_ok=True)
                shutil.rmtree(self.settings["ledger_dir"], ignore_errors=True)
                made = {c["rule"]: calibrate.materialise(c, self.rules, cfg, None, [], NOW) for c in cands}
                for p in made.values():
                    proposals.save(p, self.settings)
                    self.approve(p["id"])
                first = proposals.apply(made[order[0]]["id"], self.root, self.settings, self.rules, now=NOW)
                second = proposals.apply(made[order[1]]["id"], self.root, self.settings, self.rules, now=NOW)
                self.assertEqual((first["rebased"], second["rebased"]), (False, True))
                raw = tomllib.loads(self.rules.read_text(encoding="utf-8"))
                self.assertEqual(raw["thresholds"]["default"]["claude_warn_total"], 5)
                self.assertEqual(raw["thresholds"]["default"]["filler_warn"], 4)
                self.assertEqual(raw["version"], AFTER_NEXT)

    def test_a_rebased_apply_edits_the_text_once(self):  # no second apply_edits on a rebase
        p = self.proposal()
        self.approve(p["id"])
        text = self.rules.read_text(encoding="utf-8")
        self.rules.write_text(text.replace("# plainspoken ruleset.", "# plainspoken ruleset (hand note).", 1),
                              encoding="utf-8")
        with mock.patch.object(rulesedit, "apply_edits", wraps=rulesedit.apply_edits) as edits:
            out = proposals.apply(p["id"], self.root, self.settings, self.rules)
        self.assertTrue(out["rebased"])
        self.assertEqual(edits.call_count, 1)

    def test_a_second_proposal_on_a_rule_applied_since_is_superseded(self):  # its evidence is spent
        p = self.proposal()
        q = {**p, "edits": [{"kind": "set_threshold", "table": "default", "key": "claude_warn_total", "old": 4,
                             "new": 6}], "created": (NOW + timedelta(minutes=1)).isoformat()}
        q["id"] = proposals.proposal_id(NOW + timedelta(minutes=1), q)
        proposals.save(q, self.settings)
        r = self.apply_cli(p["id"])  # nothing approved yet
        self.approve(p["id"])
        self.approve(q["id"])
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 0, r.stderr)
        before = sha(self.rules)
        r = self.apply_cli(q["id"])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("another proposal for rule 2b was applied", r.stderr)
        self.assertEqual(sha(self.rules), before)
        self.assertEqual(proposals.status(q["id"], ledger.read(self.settings)[0]), "superseded")

    def test_a_rule_remove_whose_rule_changed_since_is_stale(self):  # rule_remove checks the old state
        p = {"rule": "22", "trigger": "dormant", "action": "remove", "bump": "major", "targets": ["ruleset"],
             "edits": [{"kind": "rule_remove", "rule": "22", "old": {"severity": "WARN", "status": "deprecated"}}],
             "created": NOW.isoformat(), "profile": "default", "ruleset_version": CFG.version,
             "base_sha256": "0" * 64, "summary": "rule 22: remove"}
        p["id"] = proposals.proposal_id(NOW, p)
        proposals.save(p, self.settings)
        self.approve(p["id"])
        before = sha(self.rules)  # rule 22 isn't deprecated in this copy: it moved since the proposal was made
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("stale", r.stderr)
        self.assertIn("rule 22 status", r.stderr)
        self.assertEqual(sha(self.rules), before)

    def test_list_that_gained_a_value_is_stale(self):
        text = self.rules.read_text(encoding="utf-8").replace(TOTAL_ONLY, "density_total_only = []")
        self.rules.write_text(text, encoding="utf-8")
        cfg = load_config(self.rules)
        p = calibrate.materialise(self.cands(kept_4b_events(), cfg=cfg)[0], self.rules, cfg, None, [], NOW)
        self.assertEqual(p["edits"], [{"kind": "list_add", "list": "density_total_only", "values": ["so", "then"]}])
        proposals.save(p, self.settings)
        self.approve(p["id"])
        self.rules.write_text(text.replace("density_total_only = []", 'density_total_only = ["then"]'),
                              encoding="utf-8")
        before = sha(self.rules)
        with self.assertRaisesRegex(proposals.Stale, re.escape(proposals.STALE) + r" .*already has then"):
            proposals.apply(p["id"], self.root, self.settings, self.rules, now=NOW)
        self.assertEqual(sha(self.rules), before)

    def test_rejected_is_refused(self):
        p = self.proposal()
        self.approve(p["id"], "approved", NOW - timedelta(days=1))
        self.approve(p["id"], "rejected", NOW)
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("rejected", r.stderr)

    def test_review_proposal_is_refused(self):
        p = self.proposal(events=fp_events(rule="20"))
        self.assertEqual(p["action"], "review")
        self.approve(p["id"])
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("by hand in a PR", r.stderr)

    def _leftovers(self):
        return sorted(x.name for x in self.rules.parent.iterdir() if x.name.endswith(".tmp"))

    def test_changelog_that_cant_be_written_refuses_before_the_ruleset(self):  # the pair goes together
        p = self.proposal()
        self.approve(p["id"])
        changelog = self.rules.parent / "RULESET-CHANGELOG.md"
        real = report.stage_atomic
        before = sha(self.rules)

        def failing(path, text):
            if Path(path) == changelog:
                raise PermissionError(13, "Permission denied", str(path))
            return real(path, text)

        with mock.patch.object(report, "stage_atomic", failing), self.assertRaisesRegex(proposals.Refused,
                                                                                          "Permission denied"):
            proposals.apply(p["id"], self.root, self.settings, self.rules)
        self.assertEqual(sha(self.rules), before)
        self.assertFalse(changelog.exists())
        self.assertEqual(self._leftovers(), [])
        self.assertEqual([e for e in ledger.read(self.settings)[0] if e["event"] == "apply"], [])

    def test_a_crash_between_the_renames_still_reports_applied_and_logs(self):  # the honest report
        p = self.proposal()
        self.approve(p["id"])
        changelog = self.rules.parent / "RULESET-CHANGELOG.md"
        real = report.commit_staged

        def failing(staged, path):
            if Path(path) == changelog:
                raise OSError(28, "No space left on device")
            return real(staged, path)

        with mock.patch.object(report, "commit_staged", failing):
            out = proposals.apply(p["id"], self.root, self.settings, self.rules)
        self.assertIn("No space left on device", out["changelog_error"])
        self.assertTrue(out["logged"])
        self.assertEqual(tomllib.loads(self.rules.read_text(encoding="utf-8"))["version"], NEXT)
        self.assertFalse(changelog.exists())
        self.assertEqual(self._leftovers(), [])
        self.assertEqual([e["proposal"] for e in ledger.read(self.settings)[0] if e["event"] == "apply"], [p["id"]])

    def test_changelog_rename_failure_cli_says_applied_not_refused(self):
        p = self.proposal()
        self.approve(p["id"])
        boot = ("import sys; sys.path.insert(0, %r); from plainspoken import report; real = report.commit_staged\n"
                "def w(staged, path):\n"
                "    if str(path).endswith('RULESET-CHANGELOG.md'): raise OSError(28, 'No space left on device')\n"
                "    return real(staged, path)\n"
                "report.commit_staged = w\n"
                "from plainspoken.__main__ import main; sys.exit(main(sys.argv[1:]))") % str(REPO / "lib")
        r = subprocess.run([sys.executable, "-c", boot, "kaizen", "apply", p["id"], "--rules", str(self.rules)],
                           cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"applied to {self.rules}; changelog not written: ", r.stderr)
        self.assertNotIn("refused", r.stderr)
        self.assertEqual(len([e for e in ledger.read(self.settings)[0] if e["event"] == "apply"]), 1)

    def test_unreadable_changelog_refuses_before_writing(self):
        (self.rules.parent / "RULESET-CHANGELOG.md").mkdir()  # a directory where the changelog should be
        p = self.proposal()
        self.approve(p["id"])
        before = sha(self.rules)
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("refused", r.stderr)
        self.assertIn("changelog", r.stderr)
        self.assertEqual(sha(self.rules), before)
        self.assertEqual([e for e in ledger.read(self.settings)[0] if e["event"] == "apply"], [])

    def test_hand_edited_proposal_is_refused(self):
        p = self.proposal()
        self.approve(p["id"])
        path = self.root / ".plainspoken" / "kaizen" / "proposals" / f"{p['id']}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["edits"][0]["new"] = 9
        path.write_text(json.dumps(data), encoding="utf-8")
        before = sha(self.rules)
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("proposal file changed after it was made", r.stderr)
        self.assertEqual(sha(self.rules), before)
        self.assertFalse((self.rules.parent / "RULESET-CHANGELOG.md").exists())

    def test_hand_edited_bump_rule_action_or_targets_is_refused(self):  # the id binds all of what apply acts on
        p = self.proposal()
        self.approve(p["id"])
        path = self.root / ".plainspoken" / "kaizen" / "proposals" / f"{p['id']}.json"
        original = path.read_text(encoding="utf-8")
        before = sha(self.rules)
        other_targets = ["ruleset"] if p["targets"] == ["ruleset", "profile"] else ["ruleset", "profile"]
        changes = {"bump": "major" if p["bump"] != "major" else "minor", "targets": other_targets, "rule": "zz",
                   "action": "remove" if p["action"] != "remove" else "tighten"}
        for field, value in changes.items():
            with self.subTest(field=field):
                data = json.loads(original)
                data[field] = value
                path.write_text(json.dumps(data), encoding="utf-8")
                r = self.apply_cli(p["id"])
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("proposal file changed after it was made", r.stderr)
                self.assertEqual(sha(self.rules), before)
        path.write_text(original, encoding="utf-8")
        self.assertEqual(self.apply_cli(p["id"]).returncode, 0)  # the untouched proposal still applies

    def test_unknown_id(self):
        r = self.apply_cli("KZ-20261014-000000")
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)

    def test_dry_run_writes_nothing_and_prints_the_diff(self):
        p = self.proposal()
        self.approve(p["id"])
        before = sha(self.rules)
        r = self.apply_cli(p["id"], "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("+claude_warn_total = 5", r.stdout)
        self.assertIn(f'+version = "{NEXT}"', r.stdout)
        self.assertEqual(sha(self.rules), before)
        self.assertFalse((self.rules.parent / "RULESET-CHANGELOG.md").exists())
        self.assertEqual([e for e in ledger.read(self.settings)[0] if e["event"] == "apply"], [])

    def test_installed_plugin_without_git_is_refused(self):
        plugin = self.tmp / "installed"
        shutil.copytree(REPO / "data", plugin / "data")
        shutil.copytree(REPO / "lib", plugin / "lib", ignore=shutil.ignore_patterns("__pycache__"))
        p = self.proposal(rules=plugin / "data" / "rules.toml")
        self.approve(p["id"])
        before = sha(plugin / "data" / "rules.toml")
        r = subprocess.run([sys.executable, str(plugin / "lib" / "run.py"), "kaizen", "apply", p["id"]],
                           cwd=self.root, capture_output=True, text=True,
                           env={"PATH": "/usr/bin:/bin", "HOME": str(self.tmp)})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("kaizen report --share", r.stderr)
        self.assertEqual(sha(plugin / "data" / "rules.toml"), before)


class ProfileTarget(Base):
    def setUp(self):
        super().setUp()
        profiles = self.root / ".plainspoken" / "profiles"
        profiles.mkdir(parents=True)
        text = (REPO / "data" / "profiles" / "default.toml").read_text(encoding="utf-8")
        self.profile = profiles / "mine.toml"
        self.profile.write_text(text.replace('name = "default"', 'name = "mine"'), encoding="utf-8")
        (self.root / ".plainspoken" / "config.toml").write_text('[engine]\nprofile = "mine"\n', encoding="utf-8")
        self.default_text = text

    def proposal(self, rules=None, when=NOW, events=None, profile="mine"):
        """Made by calibrate for `profile` (a name; None for a proposal made with no profile)."""
        made_for = None if profile is None else SimpleNamespace(name=profile)
        return super().proposal(rules=rules, when=when, events=events, profile=made_for)

    def add_profile(self, name, file=None):
        path = self.root / ".plainspoken" / "profiles" / f"{file or name}.toml"
        path.write_text(self.default_text.replace('name = "default"', f'name = "{name}"'), encoding="utf-8")
        return path

    def two_profiles(self):
        """A project with two profiles: `mine` by default and `blog` for files under blog/."""
        blog = self.add_profile("blog")
        (self.root / ".plainspoken" / "config.toml").write_text(
            '[engine]\nprofile = "mine"\nprofiles = [{ glob = "blog/**", profile = "blog" }]\n', encoding="utf-8")
        return blog

    def changelog(self):
        return self.root / ".plainspoken" / "kaizen" / "CHANGELOG.md"

    def test_profile_target_edits_the_proposals_own_profile(self):
        """Two profiles: a proposal made for `blog` edits blog.toml, whatever the project resolves now (its
        [engine] profile or PLAINSPOKEN_PROFILE), and leaves `mine` alone."""
        blog = self.two_profiles()
        p = self.proposal(rules=False, profile="blog")
        self.approve(p["id"])
        mine = sha(self.profile)
        r = cli("kaizen", "apply", p["id"], "--target", "profile", "--dry-run", cwd=self.root,
                env={"PLAINSPOKEN_PROFILE": "mine"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(str(blog), r.stdout)
        r = cli("kaizen", "apply", p["id"], "--target", "profile", cwd=self.root, env={"PLAINSPOKEN_PROFILE": "mine"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(tomllib.loads(blog.read_text(encoding="utf-8"))["thresholds"]["claude_warn_total"], 5)
        self.assertEqual(sha(self.profile), mine)
        self.assertIn("profile blog", self.changelog().read_text(encoding="utf-8"))
        applied = [e for e in ledger.read(self.settings)[0] if e.get("event") == "apply"]
        self.assertEqual([(e["outcome"], e["profile"]) for e in applied], [("applied", "blog")])

    def _refused_for_missing(self, name):
        """The proposal's profile isn't a project file: it refuses, naming it, writes nothing and stays approved,
        even though the project resolves `mine`."""
        self.two_profiles()
        p = self.proposal(rules=False, profile=name)
        self.approve(p["id"])
        before = {f.name: sha(f) for f in (self.root / ".plainspoken" / "profiles").iterdir()}
        r = cli("kaizen", "apply", p["id"], "--target", "profile", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"profile {name!r}", r.stderr)
        self.assertIn("isn't a project file", r.stderr)
        self.assertEqual({f.name: sha(f) for f in (self.root / ".plainspoken" / "profiles").iterdir()}, before)
        self.assertFalse(self.changelog().exists())
        self.assertEqual(proposals.status(p["id"], ledger.read(self.settings)[0]), "approved")

    def test_proposal_for_the_plugins_own_profile_is_refused(self):
        self._refused_for_missing("default")

    def test_proposal_for_a_deleted_profile_is_refused(self):
        self._refused_for_missing("gone")

    def test_proposal_with_no_profile_is_refused(self):
        """Made when calibrate had no profile (`profile` is null): it refuses rather than guess, writing nothing."""
        p = self.proposal(rules=False, profile=None)
        self.assertIsNone(p["profile"])
        self.approve(p["id"])
        before = sha(self.profile)
        r = cli("kaizen", "apply", p["id"], "--target", "profile", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("doesn't name the profile", r.stderr)
        self.assertEqual(sha(self.profile), before)
        self.assertFalse(self.changelog().exists())

    def test_two_project_files_with_the_proposals_profile_name_are_refused(self):
        self.two_profiles()
        self.add_profile("blog", file="blog-copy")
        p = self.proposal(rules=False, profile="blog")
        self.approve(p["id"])
        before = {f.name: sha(f) for f in (self.root / ".plainspoken" / "profiles").iterdir()}
        r = cli("kaizen", "apply", p["id"], "--target", "profile", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("more than one", r.stderr)
        self.assertEqual({f.name: sha(f) for f in (self.root / ".plainspoken" / "profiles").iterdir()}, before)

    def test_profile_target_edits_the_project_profile_only(self):
        p = self.proposal(rules=False)  # made against the shipped ruleset
        self.approve(p["id"])
        before = shipped_hashes()
        r = cli("kaizen", "apply", p["id"], "--target", "profile", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(shipped_hashes(), before)
        raw = tomllib.loads(self.profile.read_text(encoding="utf-8"))
        self.assertEqual(raw["thresholds"]["claude_warn_total"], 5)
        log = (self.root / ".plainspoken" / "kaizen" / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(p["id"], log)
        self.assertIn("profile mine", log)

    def test_removing_a_rule_the_project_profile_disables_is_refused(self):
        self.profile.write_text(self.profile.read_text(encoding="utf-8").replace(
            "[rules]\ndisabled = []", '[rules]\ndisabled = ["22"]', 1), encoding="utf-8")
        p = {"rule": "22", "trigger": "dormant", "action": "remove", "bump": "major", "targets": ["ruleset"],
             "edits": [{"kind": "rule_remove", "rule": "22"}], "created": NOW.isoformat(), "profile": "mine",
             "ruleset_version": CFG.version, "base_sha256": sha(self.rules), "summary": "rule 22: remove"}
        p["id"] = proposals.proposal_id(NOW, p)
        proposals.save(p, self.settings)
        self.approve(p["id"])
        before = sha(self.rules)
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("profile 'mine'", r.stderr)
        self.assertIn("[rules] disabled", r.stderr)
        self.assertEqual(sha(self.rules), before)
        self.assertEqual(proposals.status(p["id"], ledger.read(self.settings)[0]), "approved")  # not superseded
        self.profile.write_text(self.profile.read_text(encoding="utf-8").replace('disabled = ["22"]', "disabled = []"),
                                encoding="utf-8")
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_profile_target_rebases_per_edit(self):
        """With --target profile: the ruleset changed since calibrate (another threshold), so the proposal applies
        to the profile, rebased; once the profile moved the same key, it's stale."""
        p = self.proposal()  # made against the copy, which PLAINSPOKEN_RULES points at
        self.approve(p["id"])
        text = rulesedit.apply_edits(self.rules.read_text(encoding="utf-8"), [
            {"kind": "set_threshold", "table": "default", "key": "filler_warn", "old": 3, "new": 4}])
        self.rules.write_text(text, encoding="utf-8")
        env = {"PLAINSPOKEN_RULES": str(self.rules)}
        original = self.profile.read_text(encoding="utf-8")
        self.profile.write_text(original.replace("[thresholds]", "[thresholds]\nclaude_warn_total = 6", 1),
                                encoding="utf-8")
        before = sha(self.profile)
        r = cli("kaizen", "apply", p["id"], "--target", "profile", "--dry-run", cwd=self.root, env=env)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("stale proposal", r.stderr)
        self.assertIn("without --dry-run marks it superseded", r.stderr)  # a dry run writes nothing, not even that
        self.assertEqual(sha(self.profile), before)
        self.assertEqual(proposals.status(p["id"], ledger.read(self.settings)[0]), "approved")
        self.profile.write_text(original, encoding="utf-8")
        r = cli("kaizen", "apply", p["id"], "--target", "profile", cwd=self.root, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("rebased onto the current ruleset", r.stdout)
        self.assertEqual(tomllib.loads(self.profile.read_text(encoding="utf-8"))["thresholds"]["claude_warn_total"], 5)

    def test_already_applied_is_refused_on_either_target(self):
        p = self.proposal(rules=False)
        self.approve(p["id"])
        r = cli("kaizen", "apply", p["id"], "--target", "profile", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        before = sha(self.rules)  # a byte copy of the shipped ruleset, so the base hash still matches
        r = cli("kaizen", "apply", p["id"], "--rules", str(self.rules), cwd=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("already applied", r.stderr)
        self.assertEqual(sha(self.rules), before)
        r = cli("kaizen", "apply", p["id"], "--target", "profile", cwd=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("already applied", r.stderr)

    def test_profile_target_refused_for_a_non_threshold_proposal(self):
        p = self.proposal(rules=False, events=fp_events(rule="13"))  # status → shadow
        self.approve(p["id"])
        before = sha(self.profile)
        r = cli("kaizen", "apply", p["id"], "--target", "profile", cwd=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("profile", r.stderr)
        self.assertEqual(sha(self.profile), before)

    def test_json_proposal_is_plain_json(self):
        p = self.proposal(rules=False)
        path = self.root / ".plainspoken" / "kaizen" / "proposals" / f"{p['id']}.json"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["id"], p["id"])


class Review(Base):
    def test_an_approved_proposal_not_applied_is_listed(self):  # the approved-not-applied branch
        p = self.proposal()
        self.approve(p["id"], by="Robin")
        r = cli("kaizen", "review", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{p['id']} · rule {p['rule']}", r.stdout)
        self.assertIn("approved by Robin, not applied", r.stdout)
        rows = json.loads(cli("kaizen", "review", "--json", cwd=self.root).stdout)
        self.assertEqual([(x["id"], x["state"]) for x in rows], [(p["id"], "approved")])
        self.apply_cli(p["id"])  # to a checkout copy, not the ruleset in use: listed until it's released
        self.assertIn(f"applied as ruleset {NEXT} on ", cli("kaizen", "review", cwd=self.root).stdout)
        in_use = {"PLAINSPOKEN_RULES": str(self.rules)}
        self.assertIn("no proposals waiting", cli("kaizen", "review", cwd=self.root, env=in_use).stdout)


def apply_event(pid: str, version: str, rule: str = "2b", kind: str | None = "ruleset", when=NOW) -> dict:
    facets = {"by": "Robin", **({"kind": kind} if kind else {})}
    return ledger.make_event(event="apply", actor="engine", outcome="applied", ruleset_version=version,
                             profile="default", rule=rule, proposal=pid, facets=facets,
                             ts=when.replace(microsecond=0).isoformat())


class AwaitingRelease(Base):
    """An apply to a checkout records the version it wrote; until the ruleset in use reaches it (or its changelog
    has the entry), the proposal is awaiting release: listed by review, its key open, its evidence not spent."""
    PID = "KZ-20261014-abcdef"

    def test_released_by_version_or_changelog_entry(self):
        e = apply_event(self.PID, NEXT)
        self.assertFalse(proposals.released(e, (CFG.version, "")))
        self.assertTrue(proposals.released(e, (NEXT, "")))
        self.assertTrue(proposals.released(e, (AFTER_NEXT, "")))
        entry = f"# Ruleset changelog\n\n## {NEXT} (2026-10-14)\n\n- {self.PID}: rule 2b, loosen\n"
        self.assertTrue(proposals.released(e, (CFG.version, entry)))  # merged, then released under another number
        self.assertFalse(proposals.released(e, (CFG.version, f"mentions {self.PID} in passing\n")))
        self.assertTrue(proposals.released(apply_event(self.PID, NEXT, kind="profile"), (CFG.version, "")))
        # an apply logged before the target was recorded is a ruleset apply; a version that isn't semver is released
        self.assertFalse(proposals.released(apply_event(self.PID, NEXT, kind=None), (CFG.version, "")))
        self.assertTrue(proposals.released(apply_event(self.PID, "unknown"), (CFG.version, "")))
        self.assertTrue(proposals.released(e, (None, "")))

    def test_in_use_reads_the_ruleset_and_its_changelog(self):
        (self.rules.parent / proposals.CHANGELOG).write_text("# Ruleset changelog\n", encoding="utf-8")
        self.assertEqual(proposals.in_use(self.rules), (CFG.version, "# Ruleset changelog\n"))
        with mock.patch.dict("os.environ", {"PLAINSPOKEN_RULES": str(self.rules)}):
            self.assertEqual(proposals.in_use()[0], CFG.version)
        self.assertEqual(proposals.in_use(self.tmp / "missing.toml"), (None, ""))

    def test_status_and_review(self):
        p = self.proposal()
        self.approve(p["id"])
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{p['id']} is awaiting release", r.stdout)
        events = ledger.read(self.settings)[0]
        self.assertEqual(proposals.status(p["id"], events), proposals.AWAITING)
        self.assertEqual(proposals.status(p["id"], events, proposals.in_use(self.rules)), "applied")
        self.assertIn(p["key"], proposals.open_keys(self.settings, events))
        self.assertNotIn(p["key"], proposals.open_keys(self.settings, events, proposals.in_use(self.rules)))
        rows = json.loads(cli("kaizen", "review", "--json", cwd=self.root).stdout)
        self.assertEqual([(x["id"], x["state"]) for x in rows], [(p["id"], "awaiting_release")])
        r = self.apply_cli(p["id"])  # still applied: never twice
        self.assertEqual(r.returncode, 1)
        self.assertIn("already applied", r.stderr)

    def test_apply_to_the_ruleset_in_use_is_released_at_once(self):
        p = self.proposal()
        self.approve(p["id"])
        r = cli("kaizen", "apply", p["id"], cwd=self.root, env={"PLAINSPOKEN_RULES": str(self.rules)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("awaiting release", r.stdout)

    def test_evidence_isnt_spent_and_the_rule_waits(self):
        events = fp_events()
        cands = self.cands(events + [apply_event(self.PID, NEXT)])
        self.assertNotIn("2b", [c["rule"] for c in cands])  # awaiting release: no new proposal for the rule
        evs, _ = calibrate._unspent(ledger.distinct(events + [apply_event(self.PID, NEXT)]), {}, CFG, NOW,
                                    (CFG.version, ""))
        self.assertEqual(len([e for e in evs if e.get("rule") == "2b" and e["event"] != "apply"]), len(events))
        # released: the evidence before the apply is spent, so there's nothing to propose for 2b either
        released = apply_event(self.PID, CFG.version)
        self.assertNotIn("2b", [c["rule"] for c in self.cands(events + [released])])
        evs, _ = calibrate._unspent(ledger.distinct(events + [released]), {}, CFG, NOW, (CFG.version, ""))
        self.assertEqual([e for e in evs if e.get("rule") == "2b" and e["event"] != "apply"], [])
        self.assertIn("2b", [c["rule"] for c in self.cands(events)])


class RemoveRubric(Base):
    def test_removing_a_judged_rule_names_its_rubric_section(self):  # apply never edits the rubrics
        shutil.copytree(REPO / "data" / "rubrics", self.rules.parent / "rubrics")
        p = {"rule": "22", "trigger": "dormant", "action": "remove", "bump": "major", "targets": ["ruleset"],
             "edits": [{"kind": "rule_remove", "rule": "22"}], "created": NOW.isoformat(), "profile": "default",
             "ruleset_version": CFG.version, "base_sha256": sha(self.rules), "summary": "rule 22: remove"}
        p["id"] = proposals.proposal_id(NOW, p)
        proposals.save(p, self.settings)
        self.approve(p["id"])
        rubric = (self.rules.parent / "rubrics" / "judges.md").read_bytes()
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("rubrics/judges.md", r.stdout)
        self.assertIn("### 22", r.stdout)
        self.assertIn("by hand", r.stdout)
        self.assertEqual((self.rules.parent / "rubrics" / "judges.md").read_bytes(), rubric)


class Superseded(Base):
    """An approved proposal that apply refuses as stale moves to `superseded`, which closes it and frees its key,
    and `review` lists it for one calibrate cycle."""

    def stale_one(self) -> dict:
        p = self.proposal()  # claude_warn_total 4 → 5
        self.approve(p["id"])
        self.hand_edit("claude_warn_total", 4, 6)
        return p

    hand_edit = Apply.hand_edit

    def test_a_stale_apply_marks_it_superseded(self):
        p = self.stale_one()
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("marked superseded", r.stderr)
        self.assertIn("calibrate can propose for the rule again", r.stderr)
        events = ledger.read(self.settings)[0]
        (e,) = [e for e in events if e["event"] == "apply"]
        self.assertEqual((e["actor"], e["outcome"], e["rule"], e["proposal"], e["facets"]),
                         ("engine", "superseded", "2b", p["id"], {"by": "Robin"}))
        self.assertEqual(proposals.status(p["id"], events), "superseded")
        self.assertEqual(ledger.validate(e), [])

    def test_superseded_frees_its_key_and_stays_closed(self):
        p = self.stale_one()
        self.assertIn(p["key"], proposals.open_keys(self.settings, ledger.read(self.settings)[0]))
        self.assertEqual(self.apply_cli(p["id"]).returncode, 1)
        self.assertNotIn(p["key"], proposals.open_keys(self.settings, ledger.read(self.settings)[0]))
        self.approve(p["id"], when=NOW + timedelta(days=400))  # a later approval doesn't reopen it
        events = ledger.read(self.settings)[0]
        self.assertEqual(proposals.status(p["id"], events), "superseded")
        self.assertEqual(proposals.pending(self.settings, events), [])
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("is superseded", r.stderr)
        self.assertEqual(len([e for e in ledger.read(self.settings)[0] if e["event"] == "apply"]), 1)

    def test_a_dry_run_marks_nothing(self):
        p = self.stale_one()
        r = self.apply_cli(p["id"], "--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("without --dry-run marks it superseded", r.stderr)
        self.assertEqual(proposals.status(p["id"], ledger.read(self.settings)[0]), "approved")

    def test_not_stale_refusals_mark_nothing(self):
        p = self.proposal()
        self.assertEqual(self.apply_cli(p["id"]).returncode, 1)  # no approval
        self.approve(p["id"])
        self.rules.write_text("version = \"broken\n", encoding="utf-8")  # a ruleset that doesn't load isn't stale
        r = self.apply_cli(p["id"])
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("superseded", r.stderr)
        self.assertEqual(proposals.status(p["id"], ledger.read(self.settings)[0]), "approved")

    def test_review_lists_it_for_one_cycle(self):
        p = self.stale_one()
        self.apply_cli(p["id"])
        r = cli("kaizen", "review", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kaizen review: no proposals waiting", r.stdout)
        self.assertIn(f"{p['id']} · rule 2b", r.stdout)
        self.assertIn("superseded (approved by Robin, then stale at apply; closed, nothing to do)", r.stdout)
        rows = json.loads(cli("kaizen", "review", "--json", cwd=self.root).stdout)
        self.assertEqual([(x["id"], x["state"]) for x in rows], [(p["id"], "superseded")])
        # one cycle later it's no longer listed
        ledger_dir = Path(self.settings["ledger_dir"])
        shutil.rmtree(ledger_dir)
        self.approve(p["id"], when=NOW - timedelta(days=60))
        cycle = self.settings["triggers"]["cycle_days"]
        old = datetime.now(timezone.utc) - timedelta(days=cycle + 1)
        ledger.append(ledger.make_event(event="apply", actor="engine", outcome="superseded",
                                        ruleset_version=CFG.version, profile="unknown", rule="2b", proposal=p["id"],
                                        facets={"by": "Robin"}, ts=old.replace(microsecond=0).isoformat()),
                      self.settings)
        r = cli("kaizen", "review", cwd=self.root)
        self.assertEqual(r.stdout.strip(), "kaizen review: no proposals waiting")


V040 = REPO / "tests" / "fixtures" / "kaizen" / "v040-store"


class V040Store(TmpCase):
    """A proposal store and ledger written by the released v0.4.0 code (provenance in the fixture's
    README) still read after the `superseded` change."""
    A, B, C, D = "KZ-20261019-be1338", "KZ-20261019-93df91", "KZ-20261019-61422e", "KZ-20261019-12891c"

    def setUp(self):
        super().setUp()
        dot = self.root / ".plainspoken"
        shutil.copytree(V040 / "kaizen", dot / "kaizen")
        shutil.copytree(V040 / "ledger", dot / "ledger")
        shutil.copy(V040 / "config.toml", dot / "config.toml")
        self.settings = {**proposals.config.kaizen_settings(self.root, {}), **calibrate.load_settings()}

    def test_v040_store_loads(self):
        stored = proposals.stored(self.settings)
        self.assertEqual(sorted(p["id"] for p in stored), sorted((self.A, self.B, self.C, self.D)))
        events, bad = ledger.read(self.settings)
        self.assertEqual(bad, 0)
        states = {p["id"]: proposals.status(p["id"], events) for p in stored}
        self.assertEqual(states, {self.A: "pending", self.B: "approved", self.C: "rejected", self.D: "applied"})
        self.assertTrue(all(proposals._intact(p) for p in stored))
        self.assertEqual([p["id"] for p in proposals.pending(self.settings, events)], [self.A])
        self.assertEqual(proposals.open_keys(self.settings, events),
                         {p["key"] for p in stored if p["id"] in (self.A, self.B)})
        r = cli("kaizen", "review", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{self.A} · rule 1 · fp · loosen · awaiting decision", r.stdout)
        self.assertIn(f"{self.B} · rule 23 · fp · loosen · approved by Robin, not applied", r.stdout)
        self.assertNotIn(self.C, r.stdout)
        self.assertNotIn(self.D, r.stdout)

    def test_a_v040_approval_applies_or_is_superseded(self):
        rules = self.tmp / "rules" / "rules.toml"
        rules.parent.mkdir()
        shutil.copy(RULES, rules)  # today's ruleset: rebased onto it, filler_warn is still 3
        r = cli("kaizen", "apply", self.B, "--rules", str(rules), "--dry-run", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("rebased onto the current ruleset", r.stdout)
        self.assertIn("+filler_warn = 4", r.stdout)
        text = rulesedit.apply_edits(rules.read_text(encoding="utf-8"), [
            {"kind": "set_threshold", "table": "default", "key": "filler_warn", "old": 3, "new": 5}])
        rules.write_text(text, encoding="utf-8")
        r = cli("kaizen", "apply", self.B, "--rules", str(rules), cwd=self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("marked superseded", r.stderr)
        events = ledger.read(self.settings)[0]
        self.assertEqual(proposals.status(self.B, events), "superseded")
        self.assertEqual(proposals.status(self.D, events), "applied")
