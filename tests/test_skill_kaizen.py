"""The manual-only kaizen skill and the capture step every other skill ends with."""
import re
import subprocess
import sys
import unittest

from tests._skills import REPO, SkillBasics, files, load

SKILL = REPO / "skills" / "kaizen"
REFS = SKILL / "references"
# A CLI call the skill names: `RUN kaizen <sub> …` or `run.py kaizen <sub> …`, inside a code span.
KAIZEN_SPAN = re.compile(r"`(?:RUN|[^`\n]*run\.py) kaizen ([a-z-]+)([^`\n]*)`")
HINT = "review | calibrate | dismiss | uphold | diff | missed | published | decisions | apply | report [--share] | mine"
CAPTURE = ("If the person disagrees with a finding, or you had to work around a step, record it: "
           "`run.py kaizen dismiss|uphold …`, or say so in your report (`/plainspoken:kaizen`).")


RUN_PATH = "${CLAUDE_PLUGIN_ROOT}/lib/run.py"


def allowed(tools: str) -> list[re.Pattern]:
    """The Bash grants in an allowed-tools value, as regexes over a whole command (`*` matches anything)."""
    return [re.compile(".*".join(re.escape(part) for part in body.split("*")))
            for body in re.findall(r"Bash\(([^)]*)\)", tools)]


def flat(text: str) -> str:
    return " ".join(text.split())


def kaizen_help(*sub: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(REPO / "lib" / "run.py"), "kaizen", *sub, "--help"],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


class KaizenSkill(SkillBasics, unittest.TestCase):
    NAME = "kaizen"
    REQUIRED = ("Core rules", "Modes", "Report")
    DRAFTING = True  # no ban-list word anywhere in the skill's files (the lists live in the checker)
    REFERENCES = ("mining.md", "claude-code.md")

    def test_profile_injected(self):  # kaizen reads no profile: it shows the proposal queue at load instead
        self.assertRegex(self.text, r"(?m)^!`python3 \$\{CLAUDE_PLUGIN_ROOT\}/lib/run\.py kaizen review \|\| true`$")

    def test_frontmatter(self):  # narrower than SkillBasics: no blanket run.py grant
        self.assertEqual(self.fm["name"], "kaizen")
        self.assertLessEqual(len(self.fm["description"]), 1024)
        self.assertEqual(self.fm.get("disable-model-invocation"), "true")
        self.assertNotIn(f"Bash(python3 {RUN_PATH} *)", self.fm["allowed-tools"])

    def test_one_call_per_command_and_no_broader_grant(self):  # in the skill itself
        self.assertIn("One CLI call per command", flat(self.text))
        self.assertIn("`; echo`", flat(self.text))
        self.assertIn("never suggest broadening the grant", flat(self.text))
        self.assertIn("`kaizen *`", flat(self.text))
        core = self.text.split("## Modes", 1)[0]
        self.assertIn("never suggest broadening the grant", flat(core))  # in the always-read part, before the modes

    def test_apply_and_calibrate_need_the_hosts_permission(self):  # a second check after the person's yes
        grants = allowed(self.fm["allowed-tools"])
        self.assertTrue(grants)
        for cmd in ("kaizen apply KZ-20261014-abc123 --dry-run", "kaizen apply KZ-20261014-abc123 --target profile",
                    "kaizen calibrate", "kaizen calibrate --json --now 2026-10-14", "check post.md", "kaizen"):
            full = f"python3 {RUN_PATH} {cmd}"
            self.assertFalse(any(g.fullmatch(full) for g in grants), full)

    def test_every_other_call_is_pre_approved(self):
        grants = allowed(self.fm["allowed-tools"])
        calls = [f"python3 {RUN_PATH} {line}" for line in re.findall(r"(?m)^!`python3 \$\{CLAUDE_PLUGIN_ROOT\}/lib/run\.py"
                                                                      r" (kaizen [a-z]+)", self.text)]
        for f in files(self.NAME):
            for sub, rest in KAIZEN_SPAN.findall(f.read_text(encoding="utf-8")):
                if sub not in ("apply", "calibrate"):
                    calls.append(f"python3 {RUN_PATH} kaizen {sub}{rest}")
        self.assertGreaterEqual(len(calls), 10)
        for call in calls:
            self.assertTrue(any(g.fullmatch(call) for g in grants), call)
        self.assertIn("Write(.plainspoken/kaizen/mining/**)", self.fm["allowed-tools"])

    def test_the_reference_says_the_person_is_the_gate(self):
        text = flat((REFS / "claude-code.md").read_text(encoding="utf-8"))
        self.assertNotIn("asks for permission like any other command", text)
        self.assertIn("`kaizen apply` and `kaizen calibrate` are left out", text)
        self.assertIn("second check", text)
        self.assertIn("in-chat yes", text)
        self.assertIn("Never suggest widening the permission grant beyond the one `kaizen apply` or `kaizen calibrate` "
                      "call the person approved (never `kaizen *` or `run.py *`)", text)

    def test_stale_advice_is_superseded_then_wait(self):  # a stale apply closes the proposal itself
        skill, guide = flat(self.text), flat((REPO / "guides" / "kaizen.md").read_text(encoding="utf-8"))
        for text in (skill, guide):
            self.assertNotIn("calibrate again", text)
            self.assertNotIn("Reject it", text)
        self.assertIn("A stale proposal needs no decision: with the person's OK, run `RUN kaizen apply <id>` once "
                      "without `--dry-run`. It writes nothing but marks the proposal superseded, and **calibrate** "
                      "can propose for the rule again once new evidence builds", skill)
        self.assertIn("A real apply (not `--dry-run`) then marks it **superseded**", guide)
        self.assertIn("A superseded one (stale at apply) is listed for one calibrate cycle", skill)

    def test_dismiss_from_snapshot_is_documented(self):
        self.assertIn("a fix pass removed it (even after the check that followed), add `--from-snapshot`: it uses "
                      "the last check's saved findings, then the check's before it", flat(self.text))

    def test_manual_only_with_its_argument_hint(self):
        self.assertEqual(self.fm["disable-model-invocation"], "true")
        self.assertEqual(self.fm["argument-hint"], HINT)
        self.assertLessEqual(len(self.fm["description"]), 250)
        self.assertNotIn("when_to_use", self.fm)

    def test_every_kaizen_call_names_a_real_subcommand_and_flag(self):
        code, top = kaizen_help()
        self.assertEqual(code, 0, top)
        subs = set(re.search(r"\{([a-z,-]+)\}", top).group(1).split(","))
        seen: set[str] = set()
        for f in files(self.NAME):
            for sub, rest in KAIZEN_SPAN.findall(f.read_text(encoding="utf-8")):
                if f.name == "SKILL.md" and sub == "dismiss" and rest.startswith("|uphold"):
                    continue  # the shared capture line names two at once
                self.assertIn(sub, subs, f"{f.name}: kaizen {sub}")
                code, out = kaizen_help(sub)
                self.assertEqual(code, 0, out)
                for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", rest):
                    self.assertIn(flag, out, f"{f.name}: kaizen {sub}{rest}: {flag}")
                seen.add(sub)
        self.assertEqual(subs - seen, set(), "every subcommand has a recipe")

    def test_core_rules_come_first_and_hold_the_five_rules(self):
        head = flat(self.text[: self.text.index("## Modes")]).lower()
        for needle in ("you never approve a proposal", "`approve:`", "`reject:`",
                       "only after `run.py kaizen decisions` shows", "--dry-run",
                       "before the first github or trello", "confirm with the person",
                       "calibrate re-sends", "never quote ledger excerpts", "`kaizen report --share`",
                       "you never file it"):
            self.assertIn(needle.lower(), head, needle)

    def test_never_approves_on_anyones_behalf(self):
        lower = flat(self.text).lower()
        self.assertNotRegex(self.text, r"(?m)^\s*(?:APPROVE|REJECT): ")  # no ready-made decision line to copy
        self.assertIn("never post", lower)
        self.assertIn("an agent", lower)

    def test_each_mode_is_a_numbered_recipe(self):
        modes = self.text.split("## Modes", 1)[1].split("\n## ", 1)[0]
        names = re.findall(r"(?m)^### (\S+)", modes)
        self.assertEqual(names, ["review", "calibrate", "dismiss", "uphold", "diff", "missed", "published",
                                 "decisions", "apply", "report", "mine"])
        for block in re.split(r"(?m)^### ", modes)[1:]:
            self.assertRegex(block, r"(?m)^1\. ", block.splitlines()[0])

    def test_apply_shows_the_diff_first(self):
        block = flat(self.text.split("### apply", 1)[1].split("\n### ", 1)[0])
        self.assertLess(block.index("kaizen decisions"), block.index("--dry-run"))
        self.assertLess(block.index("--dry-run"), block.rindex("kaizen apply"))

    def test_mine_points_to_its_reference(self):
        block = self.text.split("### mine", 1)[1].split("\n## ", 1)[0]
        self.assertIn("references/mining.md", block)

    def test_with_no_argument_it_lists_the_modes(self):
        self.assertIn("no argument", self.text.lower())

    def test_claude_code_reference(self):
        text = (REFS / "claude-code.md").read_text(encoding="utf-8")
        self.assertIn("/plainspoken:kaizen", text)
        self.assertIn("disable-model-invocation", text)
        self.assertIn("model", text)


class MiningReference(unittest.TestCase):
    def setUp(self):
        self.text = (REFS / "mining.md").read_text(encoding="utf-8")
        self.flat = flat(self.text)

    def test_the_recipe(self):
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/evals/briefs/", self.text)
        self.assertIn("fresh subagent", self.flat)
        self.assertIn("verbatim", self.flat)
        self.assertIn("no other instruction", self.flat)
        self.assertIn("no plainspoken skill", self.flat)
        self.assertIn(".plainspoken/kaizen/mining/<YYYY-MM>/<model id>/<brief stem>.md", self.text)
        self.assertRegex(self.text, r"`RUN kaizen mine --drafts \.plainspoken/kaizen/mining/<YYYY-MM> --corpus ")
        self.assertIn("[kaizen] human_corpus", self.text)
        self.assertIn("session's model", self.flat)
        self.assertIn("Phase 6", self.text)  # other vendors wait for the panel adapter
        self.assertIn("at least 10 drafts per model", self.flat)  # mining.MIN_MODEL_DRAFTS
        self.assertIn("run every brief twice for each model", self.flat)

    def test_steps_in_order(self):
        steps = re.findall(r"(?m)^(\d)\. ", self.text)
        self.assertEqual(steps[:4], ["1", "2", "3", "4"])

    def test_mined_proposals_stay_local(self):
        self.assertIn(".md", self.text)
        self.assertIn("never sent", self.flat.lower())


class CaptureStep(unittest.TestCase):
    def test_every_other_skill_ends_with_the_capture_step(self):
        others = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md") if p.parent.name != "kaizen")
        self.assertEqual(len(others), 10)
        for name in others:
            _, text = load(name)
            with self.subTest(skill=name):
                self.assertIn(CAPTURE, flat(text))
                # its own paragraph after the last step, followed by nothing but the Claude Code pointer
                # line or a `## Source` section (not just "somewhere in the last 40%")
                paras = re.split(r"\n\s*\n", text.strip())
                at = next(i for i, para in enumerate(paras) if flat(para) == CAPTURE)
                for para in paras[at + 1:]:
                    if para.startswith("## Source"):
                        break  # the source notes close the skill
                    self.assertRegex(para, r"\AClaude Code specifics: .*\Z", para[:80])

    def test_check_step_8_says_merge_captured_the_verdicts(self):
        _, text = load("check")
        step8 = flat(text.split("\n8. **Report.**", 1)[1])
        self.assertIn("merge has already captured the verdicts", step8.lower())


if __name__ == "__main__":
    unittest.main()
