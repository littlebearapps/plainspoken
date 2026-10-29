"""The GitHub workflows' shape: paid evals run only by hand and inside a budget; CI runs the free ones and nothing
that calls a model. Stdlib only, so the YAML is read as text: these tests pin lines, not a parsed tree."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SHA_PIN = re.compile(r"^\s*-?\s*uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40}(\s+#.*)?$")
# What calling a model looks like from a workflow: a Claude session, a plugin eval, a paid panel command, the
# drafting harness, or a model key handed to a step.
MODEL_CALLS = ("claude plugin eval", "claude -p", "eval judges", "eval blind run", "draft_runs",
               "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")
# The engine-side eval tests: free, deterministic, no model call, no network.
FREE_EVAL_TESTS = ("test_golden", "test_evalprompts", "test_evalmetrics", "test_llm_panel", "test_evaljudges",
                   "test_rewrite", "test_eval_cases", "test_blind", "test_draft_runs", "test_evalhistory")


def _logical_lines(text: str) -> list[str]:
    """Join shell continuation lines (a trailing backslash) so one command is one line; drop comment lines."""
    lines = re.sub(r"\\\n\s*", " ", text).splitlines()
    return [line for line in lines if not line.lstrip().startswith("#")]


def _on_block(text: str) -> str:
    m = re.search(r"(?ms)^[\"']?on[\"']?:\s*\n(.*?)(?=^\S)", text)
    return m.group(1) if m else ""


def _on_keys(text: str) -> set[str]:
    """The workflow's triggers: the `on:` block's keys at its smallest indent, or an inline `on: x` / `on: [x, y]`.
    Keys may be quoted (`"push":`); skipping a quoted key would let a trigger through."""
    m = re.search(r"(?m)^[\"']?on[\"']?:[ \t]*([^\n#]*)", text)
    if not m:
        return set()
    inline = m.group(1).strip()
    if inline:
        return {k.strip().strip("'\"") for k in inline.strip("[]").split(",") if k.strip()}
    lines = [l for l in _on_block(text).splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return set()
    indent = min(len(l) - len(l.lstrip()) for l in lines)
    keys = set()
    for line in lines:
        if len(line) - len(line.lstrip()) != indent:
            continue
        km = re.match(r"^ {%d}([\"']?)([\w-]+)\1:" % indent, line)  # a quoted key is a key too
        keys.add(km.group(2) if km else line.strip())  # anything else at that indent fails closed, as itself
    return keys


def _steps(text: str) -> list[str]:
    """Each step's text in a one-job workflow: the `steps:` block split at its `- ` items."""
    m = re.search(r"(?ms)^(\s*)steps:\s*\n(.*)", text)
    if not m:
        return []
    body = m.group(2)
    first = re.search(r"(?m)^(\s*)- ", body)
    if not first:
        return []
    return [s for s in re.split(rf"(?m)^(?={re.escape(first.group(1))}- )", body) if s.strip()]


class EvalsWorkflow(unittest.TestCase):
    def setUp(self):
        self.path = WORKFLOWS / "evals.yml"
        self.assertTrue(self.path.is_file(), "missing .github/workflows/evals.yml")
        self.text = self.path.read_text(encoding="utf-8")

    def test_evals_workflow_shape(self):
        on = _on_block(self.text)
        self.assertEqual(_on_keys(self.text), {"workflow_dispatch"}, "evals.yml runs only by hand")
        # The suite input picks the tag.
        self.assertRegex(on, r"(?s)suite:.*options:.*trigger.*rewrite.*all")
        self.assertRegex(on, r"(?s)runs:.*default:\s*['\"]?1")

        evals = [line for line in _logical_lines(self.text) if "claude plugin eval" in line]
        self.assertGreaterEqual(len(evals), 2, "expected a trigger and a rewrite `claude plugin eval` line")
        for line in evals:
            with self.subTest(line=line.strip()):
                self.assertIn("--no-publish", line)
                self.assertRegex(line, r"--max-cost-usd\s+5(\s|$)")
                self.assertRegex(line, r"--threshold\s+0\.8(\s|$)")
                self.assertIn("--trust-plugin", line)
        self.assertTrue(any("--tag trigger" in l and "--ablation none" in l for l in evals))
        self.assertTrue(any("--tag rewrite" in l and "--ablation none" not in l for l in evals))

    def test_on_keys_catches_any_other_trigger(self):
        on = re.search(r"(?m)^on:\s*\n", self.text)
        for trigger in ("pull_request_target", "workflow_call", "issue_comment", "schedule", "push"):
            with self.subTest(trigger=trigger):
                added = self.text[:on.end()] + f"  {trigger}:\n" + self.text[on.end():]
                self.assertEqual(_on_keys(added), {"workflow_dispatch", trigger})
                appended = self.text[:on.end()] + "  workflow_dispatch:\n    inputs: {}\n" + f"  {trigger}:\n"
                self.assertIn(trigger, _on_keys(appended + "permissions: {}\n"))
        for quoted in ('"pull_request_target"', "'push'", '"workflow_call"'):
            with self.subTest(quoted=quoted):  # a quoted key is still a trigger: never skip it (fail-open)
                added = self.text[:on.end()] + f"  {quoted}:\n" + self.text[on.end():]
                self.assertEqual(_on_keys(added), {"workflow_dispatch", quoted.strip("'\"")})
        for inline in ("on: [workflow_dispatch, pull_request_target]", "on: workflow_call",
                       'on: ["workflow_dispatch", "push"]'):
            with self.subTest(inline=inline):
                self.assertNotEqual(_on_keys(f"name: x\n{inline}\njobs: {{}}\n"), {"workflow_dispatch"})

    def test_evals_actions_are_sha_pinned(self):
        uses = [line for line in self.text.splitlines() if re.match(r"^\s*-?\s*uses:", line)]
        self.assertTrue(uses)
        for line in uses:
            with self.subTest(line=line.strip()):
                self.assertRegex(line, SHA_PIN)

    def test_evals_cli_is_pinned(self):
        self.assertRegex(self.text, r"npm install -g @anthropic-ai/claude-code@\d+\.\d+\.\d+(\s|$)")

    def test_evals_skip_with_a_notice_without_the_key(self):
        self.assertIn("${{ secrets.ANTHROPIC_API_KEY }}", self.text)
        steps = _steps(self.text)
        check = [s for s in steps if "::notice::" in s]
        self.assertEqual(len(check), 1, "one step checks for the key and prints a ::notice::")
        self.assertRegex(check[0], r'-z\s+"\$ANTHROPIC_API_KEY"')
        self.assertRegex(check[0], r"id:\s*key")
        later = steps[steps.index(check[0]) + 1:]
        self.assertTrue(later)
        for step in later:
            with self.subTest(step=step.strip().splitlines()[0]):
                self.assertRegex(step, r"if:\s*steps\.key\.outputs\.present\s*==\s*'true'")
        self.assertTrue(any("evals/results" in s and "upload-artifact" in s for s in later))

    def test_evals_permissions_read_only(self):
        self.assertRegex(self.text, r"(?m)^permissions:\s*\n\s+contents:\s*read\s*$")


class CiWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    def test_ci_runs_free_evals(self):
        # The unittest job discovers the whole tests/ folder, so the engine-side eval tests run on every PR.
        self.assertRegex(self.text, r"python -m unittest discover -s tests -t \.")
        self.assertNotRegex(self.text, r"unittest discover[^\n]*\s-p\s", "a -p pattern could drop the eval tests")
        for name in FREE_EVAL_TESTS:
            with self.subTest(test=name):
                self.assertTrue((ROOT / "tests" / f"{name}.py").is_file())
        # Nothing in CI calls a model: paid evals run only from evals.yml, by hand.
        for needle in MODEL_CALLS:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, self.text)
        self.assertIn("evals.yml", self.text, "ci.yml says where the paid evals live")

    def test_ci_actions_are_sha_pinned(self):
        for line in self.text.splitlines():
            if re.match(r"^\s*-?\s*uses:", line):
                with self.subTest(line=line.strip()):
                    self.assertRegex(line, SHA_PIN)


class ReleaseNotes(unittest.TestCase):
    """A ruleset change has its own commit type, so the release notes get a Ruleset section (release-please groups
    by type, never by scope). Any type in a section that isn't hidden makes a release; one that isn't `feat` (or
    breaking) bumps the patch version."""

    def test_ruleset_type_has_a_visible_section(self):
        config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
        sections = config["packages"]["."]["changelog-sections"]
        ruleset = [s for s in sections if s["type"] == "ruleset"]
        self.assertEqual(len(ruleset), 1)
        self.assertEqual(ruleset[0]["section"], "Ruleset")
        self.assertFalse(ruleset[0].get("hidden", False), "a hidden type never cuts a release")
        types = [s["type"] for s in sections]
        self.assertEqual(len(types), len(set(types)))
        self.assertLess(types.index("fix"), types.index("ruleset"))

    def test_contributing_names_the_convention(self):
        text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^    ruleset: ")
        self.assertIn("Ruleset section", text)


if __name__ == "__main__":
    unittest.main()
