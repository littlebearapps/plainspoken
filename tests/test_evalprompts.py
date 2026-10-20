"""Self-contained judge and JR prompts, and strict reply parsing (Phase 6)."""
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from plainspoken import doc, evalprompts, golden

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "golden"
INLINE = REPO / "data" / "rubrics" / "judge-inline.md"


def _cases() -> dict[str, golden.GoldenCase]:
    return {c.id: c for c in golden.load(FIX)}


def _j_reply(*verdicts: dict, fenced: bool = False) -> str:
    body = json.dumps({"group": "J1", "article_sha256": "x", "judged_at": "2026-10-16T00:00:00Z",
                       "verdicts": list(verdicts)})
    return f"```json\n{body}\n```" if fenced else body


def _v(rule: str = "5b", verdict: str = "fail") -> dict:
    return {"rule": rule, "verdict": verdict, "severity": "BLOCK",
            "evidence": [{"line": 1, "quote": "In this post", "reason": "frames"}]}


class TestTemplates(unittest.TestCase):
    def test_template_lines_match_agent(self):
        inline = INLINE.read_text(encoding="utf-8").splitlines()
        agent = (REPO / "agents" / "tells-judge.md").read_text(encoding="utf-8").splitlines()
        j_agent = [ln.strip() for ln in agent if ln.strip().startswith('{"group":"<J1-J4>"')]
        j_inline = [ln.strip() for ln in inline if ln.strip().startswith('{"group":"<J1-J4>"')]
        self.assertEqual(len(j_agent), 1)
        self.assertEqual(j_inline, j_agent)

        def jr_block(lines: list[str]) -> list[str]:
            start = next(i for i, ln in enumerate(lines) if ln.startswith('{"group": "JR"'))
            end = next(i for i in range(start, len(lines)) if lines[i].rstrip().endswith("}]}"))
            return lines[start:end + 1]

        judges_md = (REPO / "data" / "rubrics" / "judges.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(jr_block(inline), jr_block(judges_md))

    def test_inline_file_is_short(self):
        self.assertLessEqual(len(INLINE.read_text(encoding="utf-8").splitlines()), 40)


class TestRubric(unittest.TestCase):
    def test_section_and_entry(self):
        how = evalprompts.rubric_section("How every judge works")
        self.assertTrue(how.startswith("## How every judge works"))
        self.assertNotIn("## J1", how)
        entry = evalprompts.rubric_entry("12")
        self.assertTrue(entry.startswith("### 12 Compulsive balance"))
        self.assertNotIn("### 16", entry)
        self.assertTrue(evalprompts.rubric_entry("12b").startswith("### 12b Ghost citations"))
        self.assertTrue(evalprompts.rubric_entry("NR-6").startswith("### NR-6"))
        self.assertNotIn("## JR", evalprompts.rubric_entry("NR-6"))

    def test_unknown_names_raise(self):
        with self.assertRaises(KeyError):
            evalprompts.rubric_entry("12e")
        with self.assertRaises(KeyError):
            evalprompts.rubric_section("No such section")


class TestJudgePrompt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_judge_prompt_has_entry_and_numbered_text(self):
        case = _cases()["J1-5b-001"]
        p = evalprompts.judge_prompt(case, self.work)
        self.assertIn("### 5b", p)
        self.assertIn("## How every judge works", p)
        first = case.text.splitlines()[0]
        self.assertIn(f"\n1: {first}\n", p)
        self.assertIn(f"\n3: {case.text.splitlines()[2]}", p)
        self.assertIn(hashlib.sha256(case.text.encode("utf-8")).hexdigest(), p)
        self.assertNotIn(case.origin, p)
        self.assertNotIn('"label":', p)
        self.assertNotIn(case.id, p)  # nothing that identifies the case (or hints at its label)
        self.assertNotIn("J1-5b-002", p)
        inp = json.loads(p.split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertEqual(set(inp), {"group", "article_sha256", "content_type", "rules", "severities", "candidates"})
        self.assertEqual((inp["group"], inp["rules"], inp["content_type"]), ("J1", ["5b"], "article"))
        self.assertEqual(inp["severities"], {"5b": "BLOCK"})

    def test_candidates_from_lint(self):
        base = _cases()["J1-5b-001"]
        case = replace(base, id="J3-2-001", group="J3", rule="2",
                       text="Small firms keep asking how to navigate the changes this year.\n\nI kept it simple.\n")
        p = evalprompts.judge_prompt(case, self.work)
        inp = json.loads(p.split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertEqual(inp["rules"], ["2"])
        self.assertTrue(inp["candidates"])
        self.assertTrue(all(c["rule"] == "2" and c["severity"] == "CANDIDATE" for c in inp["candidates"]))
        self.assertTrue(any("navigate" in c["message"] for c in inp["candidates"]))
        self.assertEqual(inp["candidates"][0]["line"], 1)

    def test_candidates_only_for_the_case_rule(self):
        # A 5b case whose text also holds a qualified ban word: the rule-2 lead doesn't reach the J1 prompt.
        base = _cases()["J1-5b-001"]
        case = replace(base, text="In this post I want to show how to navigate the changes.\n")
        inp = json.loads(evalprompts.judge_prompt(case, self.work).split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertTrue(all(c["rule"] == "5b" for c in inp["candidates"]))

    def test_j4_prompt_carries_human_markers(self):
        # Fidelity with judges.judge_input: the real J4 agent gets the lint's HM and rule-15 findings, so the
        # validation prompt does too, and only for J4.
        base = _cases()["J1-5b-001"]
        text = "The plan is simple. The work is hard. The team is small.\n\nIt is what it is.\n"
        case = replace(base, id="J4-9-001", group="J4", rule="9", text=text)
        inp = json.loads(evalprompts.judge_prompt(case, self.work).split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertIn("human_markers", inp)
        self.assertTrue(inp["human_markers"])
        self.assertTrue(all(f["rule"] in ("HM", "15") for f in inp["human_markers"]))
        self.assertEqual(inp["human_markers"][0]["rule"], "HM")
        self.assertIn("message", inp["human_markers"][0])
        j3 = replace(case, id="J3-17-001", group="J3", rule="17")
        inp3 = json.loads(evalprompts.judge_prompt(j3, self.work).split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertNotIn("human_markers", inp3)

    def test_judge_prompt_rejects_jr(self):
        with self.assertRaises(ValueError):
            evalprompts.judge_prompt(_cases()["JR-format-001"], self.work)


class TestJRPrompt(unittest.TestCase):
    def test_jr_prompt(self):
        case = _cases()["JR-format-001"]
        p = evalprompts.jr_prompt(case)
        self.assertIn("## JR Justification review", p)
        self.assertNotIn("## How every judge works", p)
        inp = json.loads(p.split("```json\n", 1)[1].split("\n```", 1)[0])
        self.assertEqual(set(inp), {"article_sha256", "justify_sha256", "items"})
        item = {"rule": "12e", "kind": "format", "reason": case.reason, "evidence": [dict(e) for e in case.evidence]}
        self.assertEqual(inp["items"], [item])
        canon = json.dumps([item], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(inp["justify_sha256"], hashlib.sha256(canon.encode("utf-8")).hexdigest())
        self.assertEqual(inp["article_sha256"], hashlib.sha256(case.text.encode("utf-8")).hexdigest())
        self.assertIn(f"\n3: {case.text.splitlines()[2]}", p)
        self.assertNotIn(case.origin, p)
        self.assertNotIn('"label":', p)
        self.assertNotIn(case.id, p)

    def test_jr_prompt_carries_the_rule_entry_when_there_is_one(self):
        case = replace(_cases()["JR-format-001"], rule="6")
        self.assertIn("### 6 Rule of three", evalprompts.jr_prompt(case))

    def test_jr_prompt_rejects_j(self):
        with self.assertRaises(ValueError):
            evalprompts.jr_prompt(_cases()["J1-5b-001"])


class TestFollowUpsT2(unittest.TestCase):
    """Prompts."""

    def test_numbered_lines_match_the_lint(self):
        text = "Form\x0cfeed one.\nLine\u2028separator two.\nThree.\n"
        self.assertEqual(evalprompts._numbered(text),
                         "1: Form\x0cfeed one.\n2: Line\u2028separator two.\n3: Three.")
        for t in (text, "\ufeffWindows\r\nline ends\rhere\n"):  # the lint's own lines, numbered from 1
            lines = doc.parse(t).lines
            self.assertEqual(evalprompts._numbered(t), "\n".join(f"{n}: {ln}" for n, ln in enumerate(lines, 1)))

    def test_golden_evidence_counts_lines_as_the_lint_does(self):
        case = golden.GoldenCase(id="JR-format-001", group="JR", rule="12e", label="accept",
                                 text="Page\x0cbreak here.\nThe second line.\n", content_type="article",
                                 source="constructed", status="provisional", origin="constructed", kind="format",
                                 reason="a reason", evidence=({"line": 2, "quote": "second line"},))
        self.assertEqual(golden.validate([case], require_counts=False), [])

    def test_backticks_in_the_input_never_close_its_fence(self):
        payload = {"candidates": [{"excerpt": "run ``` then ````` here"}]}
        prompt = evalprompts._assemble(["## Part"], payload, "Text.")
        block = prompt.split("## Input\n\n", 1)[1].split("\n\n## Article", 1)[0]
        first, *body, last = block.split("\n")
        self.assertEqual(first, "``````json")
        self.assertEqual(last, "``````")
        self.assertEqual(json.loads("\n".join(body)), payload)
        plain = evalprompts._assemble([], {"x": "no ticks"}, "Text.")
        self.assertIn("## Input\n\n```json\n", plain)


class TestParse(unittest.TestCase):
    def setUp(self):
        cases = _cases()
        self.j, self.jr = cases["J1-5b-001"], cases["JR-format-001"]

    def test_parse_bare(self):
        self.assertEqual(evalprompts.parse_judge(_j_reply(_v()), self.j), ("fail", ""))

    def test_parse_fenced(self):
        self.assertEqual(evalprompts.parse_judge(_j_reply(_v(verdict="pass"), fenced=True), self.j), ("pass", ""))

    def test_parse_fail_without_evidence_is_a_fail(self):
        v = {**_v(), "evidence": []}
        self.assertEqual(evalprompts.parse_judge(_j_reply(v), self.j), ("fail", ""))

    def test_parse_prose_around_json(self):
        reply = "Here is my verdict:\n" + _j_reply(_v()) + "\nThanks."
        self.assertEqual(evalprompts.parse_judge(reply, self.j), (None, "not one JSON object"))

    def test_parse_fenced_with_prose(self):
        reply = "Sure.\n" + _j_reply(_v(), fenced=True)
        self.assertEqual(evalprompts.parse_judge(reply, self.j), (None, "not one JSON object"))

    def test_parse_not_an_object(self):
        self.assertEqual(evalprompts.parse_judge("[1, 2]", self.j), (None, "not one JSON object"))
        self.assertEqual(evalprompts.parse_judge("", self.j), (None, "not one JSON object"))

    def test_parse_no_verdicts_list(self):
        self.assertEqual(evalprompts.parse_judge('{"group":"J1"}', self.j), (None, "no verdicts list"))
        self.assertEqual(evalprompts.parse_judge('{"verdicts":{"rule":"5b"}}', self.j), (None, "no verdicts list"))

    def test_parse_wrong_rule(self):
        label, why = evalprompts.parse_judge(_j_reply(_v(rule="5d")), self.j)
        self.assertIsNone(label)
        self.assertEqual(why, "no verdict for rule 5b")

    def test_parse_extra_rules_ignored(self):
        reply = _j_reply(_v(rule="5d", verdict="maybe"), _v(verdict="pass"))
        self.assertEqual(evalprompts.parse_judge(reply, self.j), ("pass", ""))

    def test_parse_two_verdicts_for_rule(self):
        label, why = evalprompts.parse_judge(_j_reply(_v(), _v(verdict="pass")), self.j)
        self.assertIsNone(label)
        self.assertEqual(why, "more than one verdict for rule 5b")

    def test_parse_bad_verdict_value(self):
        label, why = evalprompts.parse_judge(_j_reply(_v(verdict="maybe")), self.j)
        self.assertIsNone(label)
        self.assertIn("'maybe'", why)
        self.assertIn("fail or pass", why)
        label, _ = evalprompts.parse_judge(_j_reply(_v(verdict="accept")), self.j)
        self.assertIsNone(label)

    def test_parse_non_object_verdict(self):
        label, why = evalprompts.parse_judge('{"verdicts":["5b fail"]}', self.j)
        self.assertIsNone(label)
        self.assertEqual(why, "a verdict isn't a JSON object")

    def test_parse_non_object_beside_the_rule_is_ignored(self):
        reply = json.dumps({"verdicts": ["5d fail", 7, _v(verdict="pass")]})
        self.assertEqual(evalprompts.parse_judge(reply, self.j), ("pass", ""))

    def test_parse_jr_accept(self):
        reply = json.dumps({"group": "JR", "verdicts": [{"rule": "12e", "verdict": "accept", "reason": "parts"}]})
        self.assertEqual(evalprompts.parse_judge(reply, self.jr), ("accept", ""))
        reply = reply.replace("accept", "reject")
        self.assertEqual(evalprompts.parse_judge(reply, self.jr), ("reject", ""))

    def test_parse_jr_rejects_j_values(self):
        reply = json.dumps({"group": "JR", "verdicts": [{"rule": "12e", "verdict": "pass"}]})
        label, why = evalprompts.parse_judge(reply, self.jr)
        self.assertIsNone(label)
        self.assertIn("accept or reject", why)


if __name__ == "__main__":
    unittest.main()
