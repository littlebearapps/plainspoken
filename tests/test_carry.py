"""tests/test_carry.py — #188: a JR accept carries across a fix when the rule, its kind and reason, the profile, the
ruleset and every evidence item (the finding and the section it's about) are unchanged, so the fix needs no new
reason and no JR call for it. Anything else goes to JR as before; a reject never carries."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from plainspoken import capture, carry, justify, meaning, schema
from plainspoken.registry import load_config
from plainspoken.report import merge, merge_lines, report_paths, run_lint
from tests._profiles import PRODUCT
from tests.test_cli import cli

REASON_7D = "The closing section has two sentences, and joined with 'and' they make 20 words, still under 25."
REASON_13 = "The heading is the product's own name, which takes capitals in every place the owner writes it."
REASON_12D = "Each short paragraph holds one fact from the owner's brief, and joining any two would bury one."
A = "I moved the shop to Brunswick in March."
B = "The rent went up by a third that year."
AB = "I moved the shop to Brunswick in March, and the rent went up by a third that year."
NO_LONG = ('No sentence over 25 words in this section — join two neighbours with "and" or "but" in their own words, '
           "or keep it; never pad one")


def _article(one: str = f"{A} {B} Most customers found the new door.", two: str = "Parking was hard. People asked.",
             intro: str = "I run a small shop.") -> str:
    return f"{intro}\n\n## Moving The Shop\n\n{one}\n\n## What the rent did\n\n{two}\n"


class Carry(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cfg = load_config()
        self.art = self.tmp / "post.md"
        self.dir = self.tmp / ".plainspoken" / "reports"
        self.dir.mkdir(parents=True)
        self.paths = report_paths(self.art, self.dir, self.tmp)

    # --- a round: the draft, its lint (the findings given), the judges, the justifications, JR --------------------

    def _line(self, text: str) -> int:
        return self.art.read_text(encoding="utf-8").splitlines().index(text) + 1

    def _finding(self, rule: str) -> dict:
        at = {"7d": "## What the rent did", "13": "## Moving The Shop"}.get(rule)
        line = self._line(at) if at else 5
        excerpt = {"7d": "What the rent did", "13": "Moving The Shop"}.get(rule, "x")
        message = {"7d": NO_LONG, "13": "Title Case heading — use sentence case"}.get(
            rule, "4+ consecutive paragraphs of near-identical length")
        return {"rule": rule, "severity": "WARN", "line": line, "excerpt": excerpt, "message": message,
                "source": "lint"}

    def _draft(self, text: str, rules: tuple[str, ...] = ("7d",), judges: bool = True) -> str:
        self.art.write_text(text, encoding="utf-8")
        lint = run_lint(self.art, PRODUCT)
        lint["findings"] = [self._finding(r) for r in rules]
        self.paths["lint"].write_text(json.dumps(lint), encoding="utf-8")
        if judges:
            self._judges(lint["article_sha256"])
        return lint["article_sha256"]

    def _judges(self, sha: str) -> None:
        groups: dict[str, list] = {}
        for r in self.cfg.rules_for_profile(PRODUCT):
            if "judge" in r.method:
                groups.setdefault(r.group, []).append(r)
        for g, rules in groups.items():
            self.paths[g].write_text(json.dumps(
                {"group": g, "article_sha256": sha, "judged_at": "2026-11-22T00:00:00Z",
                 "verdicts": [{"rule": r.id, "verdict": "pass", "severity": r.severity, "evidence": []} for r in rules],
                 "profile_sha256": PRODUCT.sha256, "ruleset_version": self.cfg.version}))

    def _merge(self) -> dict:
        return merge(self.art, self.dir, PRODUCT, cwd=self.tmp)

    def _justify(self, sha: str, items: dict[str, tuple[str, str]]) -> None:
        self.paths["justify"].write_text(json.dumps({"article_sha256": sha, "items": [
            {"rule": r, "kind": k, "reason": why} for r, (k, why) in items.items()]}))

    def _jr(self, sha: str, verdicts: dict[str, str]) -> None:
        self.paths["JR"].write_text(json.dumps({
            "group": "JR", "article_sha256": sha, "justify_sha256": justify.file_sha(self.paths["justify"]),
            "judged_at": "2026-11-22T00:00:00Z", "profile_sha256": PRODUCT.sha256,
            "ruleset_version": self.cfg.version,
            "verdicts": [{"rule": r, "verdict": v, "reason": "checked against the evidence"} for r, v in verdicts.items()]}))

    def _accepted(self, text: str, items: dict[str, tuple[str, str]], verdicts: dict[str, str] | None = None) -> str:
        """A judged draft whose kept WARNs JR reviewed (accepts unless `verdicts` says otherwise), merged."""
        rules = tuple(items)
        for name in ("justify", "JR"):
            self.paths[name].unlink(missing_ok=True)
        sha = self._draft(text, rules)
        self.assertEqual(self._merge()["status"], "UNRESOLVED")
        self._justify(sha, items)
        self._jr(sha, verdicts or {r: "accept" for r in rules})
        self._merge()
        return sha

    def _record(self) -> dict:
        return carry.load(self.paths["carry"], {"profile_sha256": PRODUCT.sha256, "ruleset_version": self.cfg.version,
                                                "content_type": "article"})

    def _review_input(self, merged: dict) -> list[str]:
        data = json.loads(self.paths["justify"].read_text(encoding="utf-8"))
        payload = justify.review_input(merged, data, justify.file_sha(self.paths["justify"]), self._record())
        return [i["rule"] for i in payload["items"]]

    def _carried(self, merged: dict) -> list[str]:
        return sorted(j["rule"] for j in merged["justified"] if j.get("carried"))

    # --- the cases -------------------------------------------------------------------------------------------------

    def test_a_fix_elsewhere_keeps_the_accept_with_no_rewrite_and_no_jr(self):
        self._accepted(_article(), {"7d": ("metric", REASON_7D)})
        self.assertEqual(sorted(self._record()), ["7d"])
        jr_before = self.paths["JR"].read_bytes()
        # the fix rewords a sentence in the other section and adds an intro line, so every line number moves
        self._draft(_article(one=f"{A} {B} Most customers found the side door.", intro="I run a shop.\n\nIt's small."))
        m = self._merge()
        self.assertEqual((m["status"], m["problems"]), ("PASS", []))
        self.assertEqual(self._carried(m), ["7d"])
        self.assertEqual(m["justified"][0]["review_reason"], "checked against the evidence")
        self.assertIn("  carried: 7d (JR accepted the same reason on an earlier draft, and the fix since didn't "
                      "change its evidence)", merge_lines(m))
        self.assertEqual(self.paths["JR"].read_bytes(), jr_before)  # no JR call, nothing rewritten
        self.assertEqual(schema.validate(m, schema.load("report")), [])

    def test_a_fix_in_the_justified_section_refuses_that_one(self):
        self._accepted(_article(), {"7d": ("metric", REASON_7D)})
        self._draft(_article(two="Parking was hard. People asked often."))
        m = self._merge()
        self.assertEqual((m["status"], self._carried(m)), ("INCOMPLETE", []))
        self.assertEqual(m["problems"], ["justify: written for an older version of the article — rewrite it "
                                         "(`justify --template`) and rerun JR"])

    def test_mixed_the_untouched_rule_carries_and_jr_sees_only_the_other(self):
        self._accepted(_article(), {"7d": ("metric", REASON_7D), "13": ("false_positive", REASON_13)})
        self.assertEqual(sorted(self._record()), ["13", "7d"])
        sha = self._draft(_article(one=f"{A} {B} Most customers found the side door."), rules=("7d", "13"))
        m = self._merge()  # 13's section changed (its heading's section), 7d's didn't
        self.assertEqual(m["status"], "INCOMPLETE")
        self.assertEqual(m["problems"], ["justify: written for an older version of the article — rewrite it "
                                         "(`justify --template`) and rerun JR (7d carried)"])
        old = json.loads(self.paths["justify"].read_text(encoding="utf-8"))
        self.assertEqual(justify.template(m, old, self._record())["items"], [
            {"rule": "13", "kind": "", "reason": ""}, {"rule": "7d", "kind": "metric", "reason": REASON_7D}])
        self._justify(sha, {"13": ("false_positive", REASON_13), "7d": ("metric", REASON_7D)})
        self.assertEqual(self._review_input(m), ["13"])  # JR never sees 7d again
        self._jr(sha, {"13": "accept"})
        m = self._merge()
        self.assertEqual((m["status"], m["problems"], self._carried(m)), ("PASS", [], ["7d"]))
        self.assertEqual([(j["rule"], j["review"]) for j in m["justified"]], [("13", "accept"), ("7d", "accept")])
        self.assertEqual(self._record()["13"]["article_sha256"], sha)  # the fresh accept replaced the old one

    def test_a_ruleset_profile_or_content_type_change_carries_nothing(self):
        for key, value in (("ruleset_version", "0.0.0"), ("profile_sha256", "0" * 64), ("content_type", "social")):
            with self.subTest(key=key):
                self._accepted(_article(), {"7d": ("metric", REASON_7D)})
                data = json.loads(self.paths["carry"].read_text(encoding="utf-8"))
                self.paths["carry"].write_text(json.dumps({**data, key: value}), encoding="utf-8")
                self.assertEqual(self._record(), {})
                self._draft(_article(one=f"{A} {B} Most customers found the side door."))
                m = self._merge()
                self.assertEqual((m["status"], self._carried(m)), ("INCOMPLETE", []))

    def test_a_reject_never_carries_and_deletes_an_earlier_accept(self):
        sha = self._accepted(_article(), {"7d": ("metric", REASON_7D)}, verdicts={"7d": "reject"})
        self.assertEqual(self._record(), {})
        self._justify(sha, {"7d": ("metric", REASON_7D + " Checked twice.")})
        self._jr(sha, {"7d": "accept"})
        self._merge()
        self.assertEqual(sorted(self._record()), ["7d"])
        self._justify(sha, {"7d": ("metric", REASON_7D + " Checked three times.")})  # a third reason, rejected
        self._jr(sha, {"7d": "reject"})
        self.assertEqual(self._merge()["status"], "UNRESOLVED")
        self.assertEqual(self._record(), {})
        self._justify(sha, {"7d": ("metric", REASON_7D + " Checked twice.")})  # the accepted one, back again
        self.assertEqual(self._merge()["problems"][0][:9], "JR: stale")

    def test_a_changed_kind_or_reason_goes_back_to_jr(self):
        self._accepted(_article(), {"7d": ("metric", REASON_7D)})
        sha = self._draft(_article(one=f"{A} {B} Most customers found the side door."))
        m = self._merge()
        self.assertEqual(self._carried(m), ["7d"])
        for kind, why in (("load_bearing", REASON_7D), ("metric", REASON_7D + " Mostly.")):
            with self.subTest(kind=kind, why=why):
                self._justify(sha, {"7d": (kind, why)})
                self.assertEqual(self._review_input(m), ["7d"])
                m = self._merge()
                self.assertEqual((m["status"], self._carried(m)), ("INCOMPLETE", []))
                self.assertTrue(m["problems"][0].startswith("JR: review missing") or
                                m["problems"][0].startswith("JR: stale"), m["problems"])

    def test_a_whole_article_rule_carries_only_while_the_draft_is_the_same(self):
        sha = self._accepted(_article(), {"7d": ("metric", REASON_7D), "12d": ("metric", REASON_12D)},
                             verdicts={"7d": "accept", "12d": "reject"})
        self._justify(sha, {"7d": ("metric", REASON_7D), "12d": ("metric", REASON_12D + " Each is a fact.")})
        m = json.loads(self.paths["report"].read_text(encoding="utf-8"))
        self.assertEqual(self._review_input(m), ["12d"])  # the reason rewrite asks JR about 12d alone
        self._jr(sha, {"12d": "accept"})
        m = self._merge()
        self.assertEqual((m["status"], self._carried(m)), ("PASS", ["7d"]))
        self._draft(_article(one=f"{A} {B} Most customers found the side door."), rules=("7d", "12d"))
        m = self._merge()  # 12d's evidence is bound to the whole article, so any edit sends it back to JR
        self.assertEqual(m["problems"], ["justify: written for an older version of the article — rewrite it "
                                         "(`justify --template`) and rerun JR (7d carried)"])

    def test_a_judge_owned_rule_never_carries(self):
        rules = {"7d": {"source": "lint", "spans": ["a" * 16]}, "7b": {"source": "judge:J2", "spans": ["a" * 16]}}
        record = {r: {"kind": "metric", "reason": REASON_7D, "review_reason": "ok", "spans": ["a" * 16]}
                  for r in ("7d", "7b")}
        items = {r: {"rule": r, "kind": "metric", "reason": REASON_7D} for r in ("7d", "7b")}
        self.assertEqual(sorted(carry.decide(rules, items, record)), ["7d"])
        self.assertEqual(carry.updated({}, rules, {"7b": {"review": "accept", "kind": "metric", "reason": REASON_7D,
                                                          "review_reason": "ok"}}, "f" * 64), {})

    def test_a_new_evidence_item_for_the_rule_goes_back_to_jr(self):
        rules = {"7d": {"source": "lint", "spans": ["a" * 16, "b" * 16]}}
        record = {"7d": {"kind": "metric", "reason": REASON_7D, "review_reason": "ok", "spans": ["a" * 16]}}
        items = {"7d": {"rule": "7d", "kind": "metric", "reason": REASON_7D}}
        self.assertEqual(carry.decide(rules, items, record), {})
        rules["7d"]["spans"] = ["a" * 16]  # an item JR saw, the other one fixed away
        self.assertEqual(sorted(carry.decide(rules, items, record)), ["7d"])

    def test_the_shortcut_and_a_carried_accept_together(self):
        self._accepted(_article(), {"7d": ("metric", REASON_7D)})
        # the fix joins two sentences in the other section: the judges' verdicts carry (no judge files rewritten)
        # and so does JR's accept, so nothing reruns but the lint
        self._draft(_article(one=f"{AB} Most customers found the new door."), judges=False)
        m = self._merge()
        self.assertEqual((m["status"], m["problems"], self._carried(m)), ("PASS", [], ["7d"]))
        self.assertTrue(any(e.get("carried") for e in m["rules"].values()))
        self.assertTrue(any(line.startswith("  shortcut:") for line in merge_lines(m)))
        # a join in the justified section takes the shortcut for the judges, but JR must read the 7d again
        meaning.start(self.art, self.tmp, self.dir)  # a new run: one shortcut each
        self._accepted(_article(), {"7d": ("metric", REASON_7D)})
        self._draft(_article(two="Parking was hard, and people asked."), judges=False)
        m = self._merge()
        self.assertTrue(any(e.get("carried") for e in m["rules"].values()))
        self.assertEqual((m["status"], self._carried(m)), ("INCOMPLETE", []))

    def test_meaning_diff_start_deletes_the_carry_file(self):
        self._accepted(_article(), {"7d": ("metric", REASON_7D)})
        self.assertTrue(self.paths["carry"].is_file())
        meaning.start(self.art, self.tmp, self.dir)
        self.assertFalse(self.paths["carry"].exists())

    def test_the_ledger_logs_no_jr_event_for_a_carried_accept(self):
        self._accepted(_article(), {"7d": ("metric", REASON_7D)})
        self._draft(_article(one=f"{A} {B} Most customers found the side door."))
        m = self._merge()
        self.assertEqual(self._carried(m), ["7d"])
        events = capture.merge_events(m, None, self.cfg, self.tmp)
        self.assertEqual([e for e in events if e["event"] in ("justify", "jr")], [])

    def test_a_damaged_carry_file_carries_nothing(self):
        self._accepted(_article(), {"7d": ("metric", REASON_7D)})
        for text in ("{garbage", "[]", json.dumps({"rules": {"7d": "x"}})):
            with self.subTest(text=text):
                self.paths["carry"].write_text(text, encoding="utf-8")
                self.assertEqual(self._record(), {})

    def test_cli_template_and_review_input_say_what_carries(self):
        sha = self._accepted(_article(), {"7d": ("metric", REASON_7D), "13": ("false_positive", REASON_13)})
        self._draft(_article(one=f"{A} {B} Most customers found the side door."), rules=("7d", "13"))
        self._merge()
        args = ("post.md", "--reports", str(self.dir))
        r = cli("justify", *args, "--template", "--write", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("plainspoken: carried: 7d (JR accepted that reason on an earlier draft", r.stderr)
        data = json.loads(self.paths["justify"].read_text(encoding="utf-8"))
        self.assertNotEqual(data["article_sha256"], sha)
        self.assertEqual(data["items"], [{"rule": "13", "kind": "", "reason": ""},
                                         {"rule": "7d", "kind": "metric", "reason": REASON_7D}])
        data["items"][0].update(kind="false_positive", reason=REASON_13)
        self.paths["justify"].write_text(json.dumps(data), encoding="utf-8")
        r = cli("justify", *args, "--review-input", "--profile", "default", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([i["rule"] for i in json.loads(r.stdout)["items"]], ["13"])
        self.assertIn("plainspoken: carried: 7d", r.stderr)
        data["items"] = data["items"][1:]  # only the carried one left: nothing for JR
        self.paths["justify"].write_text(json.dumps(data), encoding="utf-8")
        r = cli("justify", *args, "--review-input", "--profile", "default", cwd=self.tmp)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("nothing to review: every justification that covers a failing WARN rule carries an earlier JR "
                      "accept (7d): run merge", r.stderr)


if __name__ == "__main__":
    unittest.main()
