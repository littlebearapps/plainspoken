"""The smoke cases' first-call graders and `eval first-call` (#58): both read a run's trace the way `claude plugin eval`
does (each row as compact JSON, one per line; a tool call is an assistant row's `tool_use` item), on small fixture
traces. The regex graders run here through Python `re` and, when `node` is on the PATH, through JavaScript too."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from plainspoken import evaltrace
from scripts.dev.lint_frontmatter import parse_frontmatter
from tests.test_cli import cli

REPO = Path(__file__).resolve().parents[1]
SMOKE = REPO / "evals" / "smoke"
RUN = "python3 /plugin/lib/run.py"
SKILL_TEXT = f"First, before any other step: run `{RUN} profile`. Below, `{RUN} check garden.md`."


def bash(command: str, description: str | None = None, first: str = "command") -> dict:
    inp = {"command": command} if description is None else (
        {"description": description, "command": command} if first == "description"
        else {"command": command, "description": description})
    return {"name": "Bash", "input": inp}


def rows(*calls: dict) -> list[dict]:
    """A run as the stream shows it: the slash command's expansion (which quotes the skill's own run.py lines), then
    one assistant row per tool call and a user row with its result."""
    out = [{"type": "system", "subtype": "init"},
           {"type": "user", "message": {"role": "user", "content": SKILL_TEXT}}]
    for i, c in enumerate(calls):
        out.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"toolu_{i}", "name": c["name"], "input": c["input"]}]}})
        out.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"toolu_{i}", "content": f"ran {RUN} check x.md"}]}})
    out.append({"type": "result", "result": "Done."})
    return out


def trace_text(rs: list[dict]) -> str:
    """What a `target: trace` grader reads: each row as compact JSON, one per line."""
    return "\n".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in rs)


WRITE = {"name": "Write", "input": {"file_path": "garden.md", "content": "Plots cost $40 a year."}}
PROFILE = f"{RUN} profile --plugin-profile 'default'"
CASES = {  # name: (calls, the call expected first, passes?, what the message names)
    "profile first": ((WRITE, bash(PROFILE, "Load the profile"), bash(f"{RUN} check garden.md")), "profile", True,
                      "first engine call (tool call 2 of 3): run.py profile --plugin-profile 'default'"),
    "profile chained first": ((bash(f"{PROFILE}; echo ---; {RUN} config profile-for 'garden.md'"),), "profile",
                              True, "run.py profile --plugin-profile 'default'"),
    "description before command": ((bash(f'python3 "/plugin/lib/run.py" profile', "Load", "description"),),
                                   "profile", True, "(tool call 1 of 1): run.py profile"),
    "check first": ((WRITE, bash(f"{RUN} check garden.md"), bash(PROFILE)), "profile", False,
                    "first engine call (tool call 2 of 3) was run.py check garden.md, not run.py profile"),
    "check chained before profile": ((bash(f"{RUN} check garden.md && {PROFILE}"),), "profile", False,
                                     "was run.py check garden.md, not run.py profile"),
    "config profile-for first": ((bash(f"{RUN} config profile-for 'garden.md'"), bash(PROFILE)), "profile", False,
                                 "was run.py config profile-for 'garden.md'"),
    "no engine call": ((WRITE, bash("cat /plugin/skills/check/SKILL.md"), bash("ls -l /plugin/lib/run.py")),
                       "profile", False, "no run.py call in the trace (3 tool calls)"),
    "no tool calls": ((), "profile", False, "no run.py call in the trace (0 tool calls)"),
    "kaizen review first": ((bash(f"{RUN} kaizen review"), bash(f"{RUN} kaizen report")), "kaizen review", True,
                            "run.py kaizen review"),
    "kaizen report first": ((bash(f"{RUN} kaizen report"),), "kaizen review", False,
                            "was run.py kaizen report, not run.py kaizen review"),
}


def node_results(pattern: str, texts: list[str]) -> list[bool]:
    script = ("const [p, t] = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "process.stdout.write(JSON.stringify(t.map(x => new RegExp(p).test(x))));")
    done = subprocess.run(["node", "-e", script], input=json.dumps([pattern, texts]), capture_output=True,
                          text=True, check=True)
    return json.loads(done.stdout)


class FirstCall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name: str, rs: list[dict]) -> Path:
        path = self.tmp / name / "trace.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(trace_text(rs) + "\nnot json\n", encoding="utf-8")
        return path

    def test_first_call_says_what_it_saw(self):
        for name, (calls, first, passes, seen) in CASES.items():
            with self.subTest(case=name):
                r = evaltrace.first_call(self.write(name, rows(*calls)), first)
                self.assertEqual(r["passed"], passes)
                self.assertIn(seen, r["message"])

    def test_grader_pattern_agrees_with_first_call(self):
        for name, (calls, first, passes, _) in CASES.items():
            with self.subTest(case=name):
                rx = re.compile(evaltrace.grader_pattern(first))
                self.assertEqual(rx.search(trace_text(rows(*calls))) is not None, passes)

    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_grader_pattern_reads_the_same_in_javascript(self):
        """`claude plugin eval` runs the pattern as a JavaScript RegExp (no flags)."""
        for first in ("profile", "kaizen review"):
            named = [(n, c) for n, c in CASES.items() if c[1] == first]
            got = node_results(evaltrace.grader_pattern(first), [trace_text(rows(*c[0])) for _, c in named])
            self.assertEqual(got, [c[2] for _, c in named], [n for n, _ in named])

    def test_engine_call_stops_at_the_next_command(self):
        self.assertEqual(evaltrace.engine_call(f"{PROFILE}; {RUN} check x"),
                         "run.py profile --plugin-profile 'default'")
        self.assertEqual(evaltrace.engine_call(f"cd /p && {RUN} check x | head"), "run.py check x")
        self.assertIsNone(evaltrace.engine_call("cat /plugin/lib/run.py"))

    def test_audit_and_cli(self):
        good = self.write("good", rows(bash(PROFILE), bash(f"{RUN} check garden.md")))
        bad = self.write("bad", rows(bash(f"{RUN} check garden.md")))
        result = {"cases": [
            {"name": "adapt--smoke", "arms": {"with": [{"tracePath": str(good)}]}},
            {"name": "check--smoke", "arms": {"with": [{"tracePath": str(bad)}]}},
            {"name": "voice--smoke", "arms": {"with": [{"tracePath": str(self.tmp / "gone" / "trace.jsonl")}]}},
            {"name": "humanize--smoke", "arms": {"with": [{"tracePath": str(bad)}]}},
            {"name": "rewrite--email", "arms": {"with": [{"tracePath": str(bad)}]}}]}
        d = evaltrace.audit(result)
        self.assertEqual([(r["case"], r["passed"]) for r in d["rows"]],
                         [("adapt--smoke", True), ("check--smoke", False)])
        self.assertEqual(d["missing"], ["voice--smoke with #1"])
        self.assertEqual(d["skipped"], ["rewrite--email"])
        text = evaltrace.summarise(d)
        self.assertIn("check--smoke with #1: FAIL · first engine call (tool call 1 of 1) was run.py check garden.md, "
                      "not run.py profile", text)
        self.assertIn("exempt: humanize--smoke: it has no profile step", text)
        self.assertIn("missing traces (run with --keep-temp): voice--smoke with #1", text)
        path = self.tmp / "smoke.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        r = cli("eval", "first-call", str(path), cwd=self.tmp)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("1 of 2 runs start with the expected call", r.stdout)
        r = cli("eval", "first-call", str(good), cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PASS · first engine call (tool call 1 of 2): run.py profile", r.stdout)
        r = cli("eval", "first-call", str(good), "--expect", "kaizen review", "--json", cwd=self.tmp)
        self.assertEqual((r.returncode, json.loads(r.stdout)["rows"][0]["passed"]), (1, False))
        r = cli("eval", "first-call", str(self.tmp / "nope.json"), cwd=self.tmp)
        self.assertEqual(r.returncode, 2)


class SmokeGraders(unittest.TestCase):
    def test_every_smoke_case_checks_its_first_call_or_says_why_not(self):
        skills = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md"))
        self.assertEqual(sorted(evaltrace.FIRST_CALL), skills)
        self.assertEqual(set(evaltrace.EXEMPT), {s for s, f in evaltrace.FIRST_CALL.items() if f is None})
        for skill, first in evaltrace.FIRST_CALL.items():
            d = SMOKE / f"{skill}--smoke"
            prompt = (d / "prompt.md").read_text(encoding="utf-8")
            skill_md = (REPO / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
            graders = sorted((d / "graders").glob("*-first.md"))
            with self.subTest(skill=skill):
                if first is None:
                    self.assertEqual(graders, [])
                    self.assertIn("# No first-call grader (#58).", prompt.split("\n---\n", 1)[0])
                    self.assertNotIn("First, before any other step", skill_md)
                    continue
                self.assertEqual(len(graders), 1)
                g = parse_frontmatter(graders[0].read_text(encoding="utf-8"))
                self.assertEqual((g["type"], g["target"]), ("regex", "trace"))
                self.assertEqual(g["pattern"], evaltrace.grader_pattern(first))
                step = skill_md.split("First, before any other step:", 1)[1][:200]
                self.assertRegex(step, r"lib/run\.py " + first + r"\b", "the skill's documented first call")


if __name__ == "__main__":
    unittest.main()
