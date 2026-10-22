"""Golden-set format, validator and held-out guard (Phase 6)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken import golden

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "golden"


def cli(*args, cwd: Path):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_"))}
    e["PYTHONPATH"] = str(REPO / "lib")
    return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=cwd, capture_output=True, text=True,
                          env=e)


def case_toml(**over) -> str:
    """One [[case]] table; values are TOML literals (strings get quoted here unless they start with '[' or '\"')."""
    fields = {"id": "J1-5b-001", "rule": "5b", "label": "fail", "content_type": "article", "source": "constructed",
              "status": "provisional", "origin": "constructed for a test", "text": "One plain sentence here."}
    fields.update(over)
    lines = ["[[case]]"]
    for k, v in fields.items():
        if v is None:
            continue
        if isinstance(v, str) and not v.startswith(("[", '"""')):
            v = '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
        lines.append(f"{k} = {v}")
    return "\n".join(lines) + "\n"


def write_group(d: Path, name: str, group: str, *cases: str) -> Path:
    p = d / name
    p.write_text(f'schema = 1\ngroup = "{group}"\n\n' + "\n".join(cases), encoding="utf-8")
    return p


def cl_claim(cid: str = "C001", expect: str = "fail", **over) -> dict:
    """One CL ledger claim with its label keys: an opinion-labelled fact by default."""
    claim = {"claim_id": cid, "expect": expect, "why": "A checkable fact labelled as opinion, with no passage.",
             "text": "I have run the shop for ten years.", "claim_type": "duration", "prominence": "medium",
             "status": "opinion_or_inference", "locations": [{"kind": "body", "anchor": "About"}]}
    claim.update(over)
    return {k: v for k, v in claim.items() if v is not None}


def cl_case(n: int = 1, *claims: dict, text: str = "I have run the shop for ten years. I'd keep it small.",
            **over) -> golden.GoldenCase:
    base = {"id": f"CL-opinion_label-{n:03d}", "group": "CL", "rule": "opinion_label",
            "label": "fail" if any(c.get("expect") == "fail" for c in claims or (cl_claim(),)) else "pass",
            "text": text, "content_type": "article", "source": "constructed", "status": "provisional",
            "origin": "constructed", "file": "CL.toml", "claims": claims or (cl_claim(),)}
    base.update(over)
    return golden.GoldenCase(**base)


def cl_full() -> list:
    """Enough CL cases for the count gate: 6 that should block and 6 that should pass, 12 claims of each verdict."""
    opinion = cl_claim("C002", "pass", text="I'd keep it small.", claim_type="premise", why="A real opinion.")
    fails = [cl_case(i, cl_claim(), opinion, cl_claim("C003", text="I have run the shop", why="Same fact.")) for i in
             range(1, 7)]
    passes = [cl_case(i, opinion, cl_claim("C003", "pass", text="I'd keep it", claim_type="premise", why="Opinion."))
              for i in range(7, 13)]
    return fails + passes


def make(group: str, n: int, label: str, start: int = 1, rule: str = "5b") -> list:
    return [golden.GoldenCase(id=f"{group}-{rule}-{i:03d}", group=group, rule=rule, label=label,
                              text=f"Plain case number {i}.", content_type="article", source="constructed",
                              status="provisional", origin="constructed", file=f"{group}.toml")
            for i in range(start, start + n)]


class TempDir(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)

    def problems_for(self, *files: tuple[str, str, list[str]]) -> list[str]:
        for name, group, cases in files:
            write_group(self.d, name, group, *cases)
        return golden.validate(golden.load(self.d), require_counts=False)


class Load(unittest.TestCase):
    def test_load_fixture(self):
        cases = golden.load(FIX)
        self.assertEqual(len(cases), 4)
        self.assertEqual(cases[0].group, "J1")
        self.assertEqual([c.id for c in cases], ["J1-5b-001", "J1-5b-002", "J2-7c-001", "JR-format-001"])
        jr = cases[-1]
        self.assertEqual(jr.kind, "format")
        self.assertEqual(jr.evidence, ({"line": 3, "quote": "**Hinges:** two"},))
        self.assertEqual(golden.validate(cases, require_counts=False), [])

    def test_fixture_counts(self):
        c = golden.counts(golden.load(FIX))
        self.assertEqual(c["J1"], {"cases": 2, "fail": 1, "pass": 1, "confirmed": 0, "endorsed": 1,
                                   "provisional": 1})
        self.assertEqual(c["JR"]["accept"], 1)
        self.assertEqual(c["JR"]["reject"], 0)

    def test_frozen(self):
        with self.assertRaises(AttributeError):
            golden.load(FIX)[0].label = "pass"


class LoadErrors(TempDir):
    def test_missing_key_names_file_case_and_key(self):
        write_group(self.d, "J1.toml", "J1", case_toml(label=None))
        with self.assertRaises(golden.GoldenError) as cm:
            golden.load(self.d)
        msg = str(cm.exception)
        self.assertIn("J1.toml", msg)
        self.assertIn("J1-5b-001", msg)
        self.assertIn("label", msg)

    def test_unknown_key(self):
        write_group(self.d, "J1.toml", "J1", case_toml(lable="fail"))
        with self.assertRaises(golden.GoldenError) as cm:
            golden.load(self.d)
        self.assertIn("lable", str(cm.exception))

    def test_jr_keys_outside_jr(self):
        write_group(self.d, "J1.toml", "J1", case_toml(kind="format"))
        with self.assertRaises(golden.GoldenError) as cm:
            golden.load(self.d)
        self.assertIn("kind", str(cm.exception))

    def test_bad_toml_and_schema(self):
        (self.d / "J1.toml").write_text("schema = \n", encoding="utf-8")
        with self.assertRaises(golden.GoldenError) as cm:
            golden.load(self.d)
        self.assertIn("J1.toml", str(cm.exception))
        (self.d / "J1.toml").write_text('schema = 2\ngroup = "J1"\n', encoding="utf-8")
        with self.assertRaises(golden.GoldenError):
            golden.load(self.d)

    def test_unknown_group(self):
        write_group(self.d, "J9.toml", "J9", case_toml())
        with self.assertRaises(golden.GoldenError) as cm:
            golden.load(self.d)
        self.assertIn("J9", str(cm.exception))

    def test_wrong_type(self):
        write_group(self.d, "J1.toml", "J1", case_toml(text="[1, 2]"))
        with self.assertRaises(golden.GoldenError) as cm:
            golden.load(self.d)
        self.assertIn("text", str(cm.exception))

    def test_missing_dir(self):
        with self.assertRaises(golden.GoldenError):
            golden.load(self.d / "nope")


class Validate(TempDir):
    def assertOneProblem(self, problems: list[str], file: str, case_id: str):
        self.assertEqual(len(problems), 1, problems)
        self.assertIn(file, problems[0])
        self.assertIn(case_id, problems[0])

    def test_duplicate_id_names_both_files(self):
        p = self.problems_for(("J1.toml", "J1", [case_toml()]),
                              ("J1-more.toml", "J1", [case_toml(label="pass")]))
        self.assertOneProblem(p, "J1.toml", "J1-5b-001")
        self.assertIn("J1-more.toml", p[0])
        self.assertIn("duplicate", p[0])

    def test_bad_id_shape(self):
        self.assertOneProblem(self.problems_for(("J1.toml", "J1", [case_toml(id="J1-5b-1")])), "J1.toml", "J1-5b-1")

    def test_id_with_trailing_newline_rejected(self):
        p = self.problems_for(("J1.toml", "J1", [case_toml(id='"""J1-5b-001\n"""')]))
        self.assertEqual(len(p), 1, p)
        self.assertIn("J1.toml", p[0])

    def test_id_prefix_must_match_group(self):
        self.assertOneProblem(self.problems_for(("J1.toml", "J1", [case_toml(id="J2-5b-001")])),
                              "J1.toml", "J2-5b-001")

    def test_rule_not_in_group(self):
        p = self.problems_for(("J1.toml", "J1", [case_toml(id="J1-7c-001", rule="7c")]))
        self.assertOneProblem(p, "J1.toml", "J1-7c-001")
        self.assertIn("7c", p[0])

    def test_unknown_rule(self):
        self.assertOneProblem(self.problems_for(("J1.toml", "J1", [case_toml(rule="99z")])), "J1.toml", "J1-5b-001")

    def test_bad_label_for_group(self):
        p = self.problems_for(("J1.toml", "J1", [case_toml(label="accept")]))
        self.assertOneProblem(p, "J1.toml", "J1-5b-001")
        self.assertIn("label", p[0])

    def test_status_source_pairing(self):
        for status, source in (("confirmed", "constructed"), ("endorsed", "owner"),
                               ("provisional", "owner-endorsed"), ("confirmed", "owner-endorsed")):
            with self.subTest(status=status, source=source):
                p = self.problems_for(("J1.toml", "J1", [case_toml(status=status, source=source)]))
                self.assertOneProblem(p, "J1.toml", "J1-5b-001")
        for status, source in (("confirmed", "owner"), ("endorsed", "owner-endorsed"),
                               ("provisional", "constructed")):
            with self.subTest(ok=status):
                self.assertEqual(self.problems_for(("J1.toml", "J1", [case_toml(status=status, source=source)])),
                                 [])
        self.assertOneProblem(self.problems_for(("J1.toml", "J1", [case_toml(status="maybe")])),
                              "J1.toml", "J1-5b-001")

    def test_content_type(self):
        self.assertOneProblem(self.problems_for(("J1.toml", "J1", [case_toml(content_type="email")])),
                              "J1.toml", "J1-5b-001")

    def test_origin_cap(self):
        self.assertOneProblem(self.problems_for(("J1.toml", "J1", [case_toml(origin="x" * 161)])),
                              "J1.toml", "J1-5b-001")
        self.assertEqual(self.problems_for(("J1.toml", "J1", [case_toml(origin="x" * 160)])), [])

    def test_text_too_long(self):
        p = self.problems_for(("J1.toml", "J1", [case_toml(text="a" * 4001)]))
        self.assertOneProblem(p, "J1.toml", "J1-5b-001")
        self.assertEqual(self.problems_for(("J1.toml", "J1", [case_toml(text="a" * 4000)])), [])
        self.assertOneProblem(self.problems_for(("J1.toml", "J1", [case_toml(text="   ")])),
                              "J1.toml", "J1-5b-001")

    def jr(self, **over) -> str:
        base = {"id": "JR-format-001", "rule": "12e", "label": "accept", "kind": "format",
                "reason": "The list is a parts list a reader shops from.",
                "evidence": '[{line = 2, quote = "second line"}]',
                "text": '"""\nfirst line\nthe second line here\n"""'}
        base.update(over)
        return case_toml(**base)

    def test_jr_valid(self):
        self.assertEqual(self.problems_for(("JR.toml", "JR", [self.jr()])), [])

    def test_jr_quote_not_on_line(self):
        p = self.problems_for(("JR.toml", "JR", [self.jr(evidence='[{line = 1, quote = "second line"}]')]))
        self.assertOneProblem(p, "JR.toml", "JR-format-001")
        self.assertIn("line 1", p[0])

    def test_jr_line_out_of_range(self):
        self.assertOneProblem(self.problems_for(("JR.toml", "JR", [self.jr(evidence='[{line = 9, quote = "x"}]')])),
                              "JR.toml", "JR-format-001")

    def test_jr_bad_kind_and_label(self):
        self.assertOneProblem(self.problems_for(("JR.toml", "JR", [self.jr(kind="vibes")])),
                              "JR.toml", "JR-format-001")
        self.assertOneProblem(self.problems_for(("JR.toml", "JR", [self.jr(label="fail")])),
                              "JR.toml", "JR-format-001")

    def test_jr_needs_reason_and_evidence(self):
        self.assertOneProblem(self.problems_for(("JR.toml", "JR", [self.jr(reason="  ")])),
                              "JR.toml", "JR-format-001")
        self.assertOneProblem(self.problems_for(("JR.toml", "JR", [self.jr(evidence="[]")])),
                              "JR.toml", "JR-format-001")

    def test_jr_any_rule(self):
        self.assertEqual(self.problems_for(("JR.toml", "JR", [self.jr(rule="5b")])), [])
        self.assertOneProblem(self.problems_for(("JR.toml", "JR", [self.jr(rule="99z")])),
                              "JR.toml", "JR-format-001")


class Counts(unittest.TestCase):
    def full(self, group: str, rule: str, labels=("fail", "pass")) -> list:
        return make(group, 15, labels[0], 1, rule) + make(group, 15, labels[1], 16, rule)

    def everything(self) -> list:
        return [*self.full("J1", "5b"), *self.full("J2", "7c"), *self.full("J3", "2"), *self.full("J4", "9"),
                *[golden.GoldenCase(**{**vars(c), "kind": "format", "reason": "a reason",
                                       "evidence": ({"line": 1, "quote": "Plain"},)})
                  for c in self.full("JR", "12e", ("accept", "reject"))], *cl_full()]

    def test_counts_gate(self):
        self.assertEqual(golden.validate(self.everything(), require_counts=True), [])
        short = [c for c in self.everything() if c.id != "J1-5b-030"]  # 29 J1 cases
        p = golden.validate(short, require_counts=True)
        self.assertEqual(len(p), 1, p)
        self.assertIn("J1", p[0])
        self.assertIn("29", p[0])
        self.assertEqual(golden.validate(short, require_counts=False), [])
        lopsided = [c for c in self.everything() if not c.id.startswith("J2")]
        lopsided += make("J2", 21, "fail", 1, "7c") + make("J2", 9, "pass", 22, "7c")  # 30 cases, 9 pass
        p = golden.validate(lopsided, require_counts=True)
        self.assertEqual(len(p), 1, p)
        self.assertIn("J2", p[0])
        self.assertIn("pass", p[0])
        self.assertEqual(golden.validate(lopsided, require_counts=False), [])

    def test_missing_group_fails_gate(self):
        p = golden.validate([c for c in self.everything() if c.group != "J4"], require_counts=True)
        self.assertEqual(len(p), 1, p)
        self.assertIn("J4", p[0])

    def test_claims_group_has_its_own_gate(self):
        p = golden.validate([c for c in self.everything() if c.group != "CL"], require_counts=True)
        self.assertEqual(len(p), 1, p)
        self.assertIn("CL: no cases", p[0])
        few = [c for c in self.everything() if c.id not in ("CL-opinion_label-011", "CL-opinion_label-012",
                                                           "CL-opinion_label-010")]  # 9 cases, 3 pass cases
        p = golden.validate(few, require_counts=True)  # still 12 pass claims (6 + 3 × 2)
        self.assertEqual(p, ["CL: 9 cases (need at least 10)", "CL: 3 pass cases (need at least 4)"])
        self.assertEqual(golden.validate(few, require_counts=False), [])

    def test_claims_gate_counts_claim_verdicts(self):  # enough cases, but too few claims a checker should pass
        only_fail = [c for c in self.everything() if c.group != "CL"]
        only_fail += [cl_case(i, cl_claim(), cl_claim("C003", text="I have run the shop", why="Same fact."))
                      for i in range(1, 11)]
        only_fail += [cl_case(i, cl_claim("C002", "pass", text="I'd keep it small.", claim_type="premise",
                                          why="A real opinion.")) for i in range(11, 15)]
        p = golden.validate(only_fail, require_counts=True)
        self.assertEqual(p, ["CL: 4 pass claims (need at least 10)"])

    def test_claims_counts_row(self):
        row = golden.counts(cl_full())["CL"]
        self.assertEqual((row["cases"], row["fail"], row["pass"], row["claims fail"], row["claims pass"]),
                         (12, 6, 6, 12, 18))
        self.assertIn("claims fail 12 · claims pass 18", golden.count_line("CL", row))


CL_TOML = """schema = 1
group = "CL"

[[case]]
id = "CL-derivation-001"
rule = "derivation"
content_type = "article"
source = "constructed"
status = "provisional"
origin = "constructed for a test"
text = \"\"\"The hall has 20 chairs at $5 each. That's $100 of chairs.
\"\"\"

[[case.claim]]
claim_id = "C001"
expect = "pass"
why = "The inventory says 20 chairs at $5."
text = "The hall has 20 chairs at $5 each."
claim_type = "count"
prominence = "medium"
status = "verified"
locations = [{kind = "body", anchor = "opening"}]

[case.claim.source]
url = "https://example.org/hall/inventory"
title = "Hall inventory"
source_tier = "primary"

[case.claim.binding]
passage = "Chairs: 20, bought at $5 each."
same_subject = true
same_geography = true
same_period = true
same_denominator = true
supports_strength = true

[[case.claim]]
claim_id = "C002"
expect = "pass"
why = "20 × $5 is $100."
text = "That's $100 of chairs."
claim_type = "derived_metric"
prominence = "low"
status = "derived"
locations = [{kind = "body", anchor = "opening"}]

[case.claim.derivation]
method = "20 chairs (C001) at $5 (C001)."
inputs = ["C001"]
"""


class ClaimsCases(TempDir):
    """The CL group: a short article plus ledger claims, each labelled with `expect` and `why`."""

    def load_one(self, text: str = CL_TOML) -> golden.GoldenCase:
        (self.d / "CL.toml").write_text(text, encoding="utf-8")
        cases = golden.load(self.d)
        self.assertEqual(len(cases), 1)
        return cases[0]

    def problems(self, text: str) -> list[str]:
        (self.d / "CL.toml").write_text(text, encoding="utf-8")
        return golden.validate(golden.load(self.d), require_counts=False)

    def test_loads_and_validates(self):
        case = self.load_one()
        self.assertEqual((case.group, case.rule, case.label), ("CL", "derivation", "pass"))
        self.assertEqual([c["claim_id"] for c in case.claims], ["C001", "C002"])
        self.assertEqual(case.claims[0]["binding"]["passage"], "Chairs: 20, bought at $5 each.")
        self.assertEqual(golden.validate([case], require_counts=False), [])

    def test_label_is_fail_when_any_claim_should_fail(self):
        case = self.load_one(CL_TOML.replace('expect = "pass"\nwhy = "20', 'expect = "fail"\nwhy = "20'))
        self.assertEqual(case.label, "fail")

    def test_ledger_drops_the_labels_and_binds_the_text(self):
        case = self.load_one()
        ledger = golden.claims_ledger(case)
        self.assertEqual(ledger["source_content_hash"], golden.text_sha256(case.text))
        self.assertTrue(all(not set(c) & {"expect", "why"} for c in ledger["claims"]))
        self.assertTrue(all("expect" in c for c in case.claims))  # the case itself keeps them
        self.assertNotIn(case.id, repr(ledger))
        self.assertEqual(ledger["coverage_status"], "complete")

    def test_label_key_is_refused(self):
        with self.assertRaises(golden.GoldenError) as cm:
            self.load_one(CL_TOML.replace('rule = "derivation"', 'rule = "derivation"\nlabel = "pass"'))
        self.assertIn("label", str(cm.exception))
        with self.assertRaises(golden.GoldenError) as cm:
            self.load_one(CL_TOML.replace('rule = "derivation"', 'rule = "derivation"\nkind = "format"'))
        self.assertIn("kind", str(cm.exception))

    def test_claims_are_required_tables(self):
        with self.assertRaises(golden.GoldenError) as cm:
            self.load_one(CL_TOML.split("[[case.claim]]")[0])
        self.assertIn("claim", str(cm.exception))

    def test_claim_problems(self):
        for old, new, says in (
                ('expect = "pass"\nwhy = "The inventory', 'expect = "maybe"\nwhy = "The inventory', "expect"),
                ('why = "20 × $5 is $100."', 'why = ""', "why"),
                ('text = "That\'s $100 of chairs."', 'text = "That\'s $120 of chairs."', "word for word"),
                ('inputs = ["C001"]', 'inputs = ["C009"]', "C009"),
                ('text = "The hall has 20 chairs at $5 each."\nclaim_type', 'text = "x"\nclaim_type', "word for"),
                ('status = "derived"', 'status = "blocking"\nresolution = "Held for the owner."', "status"),
                ('claim_type = "count"', 'claim_type = "headcount"', "ledger: "),
                ('rule = "derivation"', 'rule = "5b"', "rule"),
                ('inputs = ["C001"]\n', 'inputs = ["C001"]\n\n[[case.claim]]\nclaim_id = "C001"\nexpect = "pass"\n'
                 'why = "Again."\ntext = "The hall has 20 chairs"\nclaim_type = "count"\nprominence = "low"\n'
                 'status = "opinion_or_inference"\nlocations = [{kind = "body"}]\n', "duplicate")):
            with self.subTest(says=says):
                self.assertIn(old, CL_TOML)
                p = self.problems(CL_TOML.replace(old, new, 1))
                self.assertEqual(len(p), 1, p)
                self.assertIn("CL-derivation-001", p[0])
                self.assertIn(says, p[0])

    def test_claim_prose_is_held_out(self):
        case = self.load_one()
        root = self.d / "data"
        root.mkdir()
        (root / "rubric.md").write_text("For example: chairs 20, bought at $5 each.\n", encoding="utf-8")
        p = golden.heldout_leaks([case], [root])
        self.assertEqual(len(p), 1, p)
        self.assertIn("CL-derivation-001", p[0])

    def test_shipped_claims_set(self):
        cases = [c for c in golden.load(golden.DEFAULT_DIR) if c.group == "CL"]
        self.assertEqual(golden.validate(cases, require_counts=False), [])
        row = golden.counts(cases)["CL"]
        self.assertGreaterEqual(row["cases"], golden.CL_MIN_CASES)
        self.assertGreaterEqual(min(row["claims fail"], row["claims pass"]), golden.CL_MIN_CLAIMS_PER_LABEL)
        self.assertIn("opinion_label", {c.rule for c in cases})  # #45's rule has cases of both verdicts
        verdicts = {cl["expect"] for c in cases if c.rule == "opinion_label" for cl in c.claims}
        self.assertEqual(verdicts, {"fail", "pass"})


class Heldout(TempDir):
    TEXT = "The ferry left the jetty at dawn while gulls argued over a dropped pie crust."

    def case(self) -> list:
        return [golden.GoldenCase(id="J1-5b-001", group="J1", rule="5b", label="fail", text=self.TEXT,
                                  content_type="article", source="constructed", status="provisional",
                                  origin="constructed", file="J1.toml")]

    def test_heldout_leak(self):
        root = self.d / "skills"
        (root / "a").mkdir(parents=True)
        leak = root / "a" / "SKILL.md"
        # 8 consecutive words, with different case and punctuation: a leak
        leak.write_text("Example: the FERRY left, the jetty at dawn; while gulls... and more.\n", encoding="utf-8")
        near = root / "near.md"
        near.write_text("Unrelated words first. Ferry left the jetty at dawn while. Zebra crossing.\n",
                        encoding="utf-8")  # 7 words only
        (root / "blob.bin").write_bytes(b"\x00\xff\xfe" + self.TEXT.encode())
        p = golden.heldout_leaks(self.case(), [root, self.d / "missing"])
        self.assertEqual(len(p), 1, p)
        self.assertIn(str(leak), p[0])
        self.assertIn("J1-5b-001", p[0])

    def test_seven_word_run_is_clean(self):
        root = self.d / "data"
        root.mkdir()
        (root / "x.toml").write_text("ferry left the jetty at dawn while\n", encoding="utf-8")
        self.assertEqual(golden.heldout_leaks(self.case(), [root]), [])

    def test_templates_are_held_out(self):
        self.assertIn("templates", golden.HELDOUT_ROOTS)
        self.assertIn(golden.PLUGIN_ROOT / "templates", golden.heldout_roots())

    def test_shingle_size(self):
        self.assertEqual(golden.SHINGLE, 8)

    def test_repo_roots_have_no_fixture_text(self):
        self.assertEqual(golden.heldout_leaks(golden.load(FIX), golden.heldout_roots()), [])


class FollowUpsT1(TempDir):
    """Golden set."""

    def jr_case(self, **over) -> golden.GoldenCase:
        base = {"id": "JR-format-001", "group": "JR", "rule": "12e", "label": "accept",
                "text": "First line here.\nThe second line.\n", "content_type": "article", "source": "constructed",
                "status": "provisional", "origin": "constructed", "kind": "format",
                "reason": "The bold labels name the parts a reader has to buy from the hardware shop.",
                "evidence": ({"line": 2, "quote": "second line"},), "file": "JR.toml"}
        base.update(over)
        return golden.GoldenCase(**base)

    def test_short_case_is_still_guarded(self):
        short = [golden.GoldenCase(id="J1-5b-001", group="J1", rule="5b", label="fail", text="Gulls argued over pie.",
                                   content_type="article", source="constructed", status="provisional",
                                   origin="constructed", file="J1.toml")]
        root = self.d / "skills"
        root.mkdir()
        (root / "partial.md").write_text("The gulls argued over a pie.\n", encoding="utf-8")
        self.assertEqual(golden.heldout_leaks(short, [root]), [])
        leak = root / "leak.md"
        leak.write_text("Example: gulls ARGUED over pie, again.\n", encoding="utf-8")
        p = golden.heldout_leaks(short, [root])
        self.assertEqual(len(p), 1, p)
        self.assertIn(str(leak), p[0])

    def test_jr_reason_is_guarded(self):
        root = self.d / "guides"
        root.mkdir()
        leak = root / "g.md"
        leak.write_text("As the case says: the bold labels name the parts a reader has to buy.\n", encoding="utf-8")
        p = golden.heldout_leaks([self.jr_case()], [root])
        self.assertEqual(len(p), 1, p)
        self.assertIn("JR-format-001", p[0])

    def test_schema_true_is_not_one(self):
        (self.d / "J1.toml").write_text('schema = true\ngroup = "J1"\n', encoding="utf-8")
        with self.assertRaises(golden.GoldenError) as cm:
            golden.load(self.d)
        self.assertIn("schema", str(cm.exception))

    def test_jr_case_is_hashable(self):
        a, b = self.jr_case(), self.jr_case()
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b, self.jr_case(id="JR-format-002")}), 2)

    def test_id_may_hold_an_underscore(self):
        case = self.jr_case(id="JR-load_bearing-001", kind="load_bearing")
        self.assertEqual(golden.validate([case], require_counts=False), [])
        self.assertTrue(golden.ID_RE.fullmatch("J1-5b-bold_first-001"))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads every folder")
    def test_unreadable_folder_is_a_problem_not_a_crash(self):
        root = self.d / "skills"
        locked = root / "locked"
        (locked / "sub").mkdir(parents=True)
        (locked / "sub" / "a.md").write_text("nothing\n", encoding="utf-8")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        case = [self.jr_case()]
        for target in (root, locked / "sub"):
            with self.subTest(root=target):
                p = golden.heldout_leaks(case, [target])
                self.assertEqual(len(p), 1, p)
                self.assertIn("can't read", p[0])
                self.assertIn(str(locked), p[0])

    def test_add_parser_is_annotated(self):
        import inspect

        from plainspoken import evalcli
        for fn in (evalcli.add_parser, evalcli._blind_parser, evalcli._claims_parser):
            sig = inspect.signature(fn)
            with self.subTest(fn=fn.__name__):
                self.assertTrue(all(p.annotation is not inspect.Parameter.empty for p in sig.parameters.values()))
                self.assertIsNot(sig.return_annotation, inspect.Signature.empty)


class Cli(TempDir):
    def test_cli_validate(self):
        r = cli("eval", "golden", "validate", "--dir", str(FIX), cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("J1 2 cases: fail 1 · pass 1 · confirmed 0 · endorsed 1 · provisional 1", r.stdout)
        self.assertIn("J2 1 case: fail 1 · pass 0 · confirmed 0 · endorsed 0 · provisional 1", r.stdout)
        self.assertIn("JR 1 case: accept 1 · reject 0 · confirmed 0 · endorsed 0 · provisional 1", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_cli_counts_line_for_four_case_group(self):
        write_group(self.d, "J1.toml", "J1",
                    case_toml(id="J1-5b-001", label="fail"), case_toml(id="J1-5b-002", label="fail"),
                    case_toml(id="J1-5b-003", label="pass"),
                    case_toml(id="J1-5b-004", label="pass", source="owner-endorsed", status="endorsed"))
        r = cli("eval", "golden", "validate", "--dir", str(self.d), cwd=self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("J1 4 cases: fail 2 · pass 2 · confirmed 0 · endorsed 1 · provisional 3", r.stdout)

    def test_cli_broken_exits_1(self):
        write_group(self.d, "J1.toml", "J1", case_toml(label="accept"))
        r = cli("eval", "golden", "validate", "--dir", str(self.d), cwd=self.d)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("J1-5b-001", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_cli_require_counts_exits_1(self):
        r = cli("eval", "golden", "validate", "--dir", str(FIX), "--require-counts", cwd=self.d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("need at least 30", r.stdout)

    def test_cli_missing_dir_exits_2(self):
        r = cli("eval", "golden", "validate", "--dir", str(self.d / "nope"), cwd=self.d)
        self.assertEqual(r.returncode, 2)
        self.assertIn("plainspoken: eval golden validate:", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_cli_malformed_file_exits_2(self):
        write_group(self.d, "J1.toml", "J1", case_toml(text=None))
        r = cli("eval", "golden", "validate", "--dir", str(self.d), cwd=self.d)
        self.assertEqual(r.returncode, 2)
        self.assertIn("text", r.stderr)

    def test_cli_eval_needs_subcommand(self):
        self.assertEqual(cli("eval", cwd=self.d).returncode, 2)
        self.assertEqual(cli("eval", "golden", cwd=self.d).returncode, 2)


if __name__ == "__main__":
    unittest.main()
