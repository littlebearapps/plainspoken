import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.dev.lint_frontmatter import parse_frontmatter
from tests._skills import LOAD_LINE, PROFILE_CALL, assert_first_step

REPO = Path(__file__).resolve().parents[1]


def skill(name: str) -> tuple[dict, str]:
    text = (REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    return parse_frontmatter(text), text


class CheckSkill(unittest.TestCase):
    def setUp(self):
        self.fm, self.text = skill("check")

    def test_jr_route_when_the_lint_is_not_current(self):  # deferred minor: JR "no current lint" route
        refs = (REPO / "skills" / "check" / "references" / "fix-or-justify.md").read_text(encoding="utf-8")
        para = next(p for p in refs.split("\n\n") if "no current report" in p)
        self.assertIn("step 1", para)
        self.assertIn("isn't a fix pass", para)

    def test_frontmatter(self):
        self.assertEqual(self.fm["name"], "check")
        self.assertLessEqual(len(self.fm["description"]), 1024)
        self.assertNotIn("disable-model-invocation", self.fm)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/lib/run.py", self.fm.get("allowed-tools", ""))

    def test_calls_the_cli_not_python_snippets(self):
        for sub in ("check", "judge-input", "judge-record", "merge", "justify", "paths", "status"):
            self.assertRegex(self.text, rf"run\.py {sub}\b")
        self.assertNotIn("python3 - ", self.text)
        self.assertNotIn("import json", self.text)

    def test_core_rules_come_first(self):
        head = self.text[: self.text.index("## Steps")]
        for needle in ("never edit", "two fix passes", "INCOMPLETE", "plainspoken:tells-judge"):
            self.assertIn(needle, head)

    def test_profile_read_first(self):  # #12: an explicit first step, not a load-time command
        assert_first_step(self, self.text, PROFILE_CALL)

    def test_report_only_route(self):  # #107: findings without edits, never described as a pass
        m = __import__("re").search(r"(?ms)^#+ [^\n]*Report only[^\n]*\n(.*?)(?=^#+ |\Z)", self.text)
        self.assertIsNotNone(m, "no 'Report only' heading in skills/check/SKILL.md")
        route = " ".join(m.group(1).split())
        for needle in ("--keep", "step 6", "step 7", "humanize", "PASS"):
            self.assertIn(needle, route)
        self.assertRegex(route, r"(?i)unchanged|same bytes|byte for byte|never edit")
        self.assertRegex(route, r"(?i)nothing (was|is) (fixed|changed)")
        self.assertRegex(route, r"(?i)overrides the fixing in the core rules")
        self.assertRegex(route, r"(?i)skip step 6 \(fix pass\) and step 7")
        self.assertRegex(route, r"(?i)never call `/plainspoken:humanize`")
        self.assertRegex(route, r"(?i)judge-input`'s exit-1 list")  # the lint's own list is cut short at 15 a severity
        self.assertNotIn("Step 1: run its `check` call", route)  # #162: step 1 is judge-input, which prints the lint
        self.assertRegex(route, r"Steps 1 and 2: fix nothing\b")
        self.assertIn("take the rules from `judge-input`'s exit-1 list", route)
        self.assertRegex(route, r"(?i)never call it a PASS")

    def test_no_ban_list_words(self):  # lists live in the checker
        lists = __import__("plainspoken.registry", fromlist=["load_config"]).load_config().lists
        for word in lists["ban_literal"]:
            self.assertIsNone(re.search(rf"\b{re.escape(word)}\b", self.text, re.I), word)

    def test_first_step_survives_an_unsubstituted_placeholder(self):
        line = PROFILE_CALL.strip("`").replace("${CLAUDE_PLUGIN_ROOT}", str(REPO))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_"))}
        with tempfile.TemporaryDirectory() as cwd:  # no project config, no profile from the caller's environment
            r = subprocess.run(["bash", "-c", line], capture_output=True, text=True, cwd=cwd, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(plugin default)", r.stdout)

    def test_placeholder_never_double_quoted(self):
        refs = (REPO / "skills" / "check" / "references" / "fix-or-justify.md").read_text(encoding="utf-8")
        for t in (self.text, refs):
            self.assertNotIn('"${user_config', t)
            self.assertIn("'${user_config.profile}'", t)

    def test_profile_flag_scope_and_routing(self):
        self.assertIn("`paths` and `judge-record` don't take it", self.text)
        self.assertIn("judge-record FILE --group Jn --from", self.text)
        self.assertIn("judge-record FILE --all --from", self.text)  # #28: one record call per judge round
        self.assertNotIn("<<'EOF'", self.text)  # E2E: Claude Code's shell check denies JSON in a heredoc
        self.assertIn("UNRESOLVED → step 6", self.text)
        self.assertIn("run every call from the same working directory", self.text.lower())

    def test_final_review_routing_and_scope(self):
        head = self.text[: self.text.index("## Steps")]
        self.assertIn("quote", head.lower())
        self.assertRegex(" ".join(head.split()), r"For `merge`, `justify` and `judge-record`, exit 2 means stop")
        self.assertIn("fix passes come before justify", head.lower())
        self.assertIn("justify only what you keep after the last fix pass", head.lower())
        self.assertNotIn("Write tool", self.text)
        tools = self.fm.get("allowed-tools", "")
        self.assertIn("Write(.plainspoken/reports/", tools)
        self.assertIn("Edit(.plainspoken/reports/", tools)

    def test_which_edits_count_as_fix_passes(self):  # #29: uncounted pre-judge edits, edits after JR
        head = " ".join(self.text[: self.text.index("## Steps")].split())
        self.assertIn("Before the judges start, step 1 fixes lint findings the same way in at most two lint-only "
                      "passes", head)
        self.assertIn("they aren't fix passes", head)
        self.assertNotIn("fix lint findings once", head)
        self.assertIn("Once the judges start, every edit to FILE is a fix pass (after justify or JR too)", head)
        self.assertNotIn("Run step 1 with `--no-record`", head)  # #162: step 1 is judge-input; the quick lint is check
        self.assertIn("`RUN check FILE --plugin-profile '${user_config.profile}' --no-record`", head)

    def test_lint_findings_fixed_before_the_judges(self):  # #42: a lint-only WARN cost a second round of judges
        step = self.step1()
        self.assertIn("RUN judge-input FILE --plugin-profile '${user_config.profile}'", step)  # #162: one call
        self.assertIn("It lints FILE and prints the lint first", step)
        self.assertIn("Before the first judges, fix its BLOCK and WARN lines under the fix rule and run step 1 again "
                      "(at most two lint-only passes, counting a caller's, such as write step 6's)", step)  # #162
        self.assertIn("so the judges read a lint-clean draft", step)
        self.assertIn("one still there after two, or any once the judges have started) gets `--keep <rule>`",
                      step)  # #74: judge-input holds an open lint line back without it
        self.assertIn("Justify a kept WARN in step 7 rather than fix it", step)
        self.assertIn("Exit 1 → it names lint lines still open", step)
        step2 = " ".join(self.text[self.text.index("2. **Judge input.**"):self.text.index("3. **Judges.**")].split())
        self.assertIn("Step 1 already printed it; this is the same call.", step2)  # the numbers other files cite stay

    def step1(self) -> str:
        return " ".join(self.text[self.text.index("1. **Lint and judge input.**"):
                                  self.text.index("2. **Judge input.**")].split())

    def test_the_lint_is_read_and_keeps_name_only_what_it_printed(self):  # #162: `check … >/dev/null; … --keep r7d`
        step = self.step1()
        self.assertIn("read it in full, the lint first", step)
        self.assertIn("never send it, or any part of it, to `/dev/null`", step)
        self.assertIn("`--keep <rule>`, only for a rule the lint above printed", step)
        self.assertIn("a `--keep` for a rule with no open line", step)

    def test_judges_wait_for_a_current_claims_status(self):  # #160: judge-input exits 3 on an open claims step
        step = self.step1()
        self.assertIn("Exit 3 → FILE has a claim ledger that isn't current", step)
        self.assertIn("From write, finish the claims step", step)
        self.assertIn("On its own, rerun step 1 with `--ignore-claims` and say so in step 8", step)
        self.assertIn("exit 3 always means rerun with `--ignore-claims`", " ".join(self.text.split()))  # report only
        notes = (REPO / "skills" / "claims" / "references" / "claude-code.md").read_text(encoding="utf-8")
        self.assertIn("in the foreground (never `run_in_background`)", " ".join(notes.split()))

    def test_report_reads_status_and_reruns_when_stale(self):  # #29: no clean finish after an uncounted edit
        step = " ".join(self.text[self.text.index("8. **Report.**"):].split())
        self.assertIn("RUN status FILE --plugin-profile", step)
        self.assertIn("`check:` lines exactly as printed", step)
        self.assertIn("run steps 1 to 5 again without editing", step)
        self.assertIn("how many fix passes ran", step)

if __name__ == "__main__":
    unittest.main()


class HumanizeSkill(unittest.TestCase):
    def setUp(self):
        self.fm, self.text = skill("humanize")
        self.patterns = (REPO / "skills" / "humanize" / "references" / "patterns.md").read_text(encoding="utf-8")

    def test_frontmatter_and_size(self):
        self.assertEqual(self.fm["name"], "humanize")
        self.assertLessEqual(len(self.fm["description"]), 1024)
        self.assertLessEqual(len(self.text.splitlines()), 500)

    def test_removal_only(self):
        lower = self.text.lower()
        self.assertIn("remove", lower)
        self.assertNotIn("reaction is allowed", lower)
        self.assertNotIn("you may add a reaction", lower)
        self.assertIn("never add a fact", lower)
        self.assertNotIn("fiction is exempt", lower)

    def test_used_on_its_own_it_reads_the_voice_profile(self):  # #98: item 4 named notes it never loaded
        body = " ".join(self.text.split())
        self.assertIn("Used on its own, first run `python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py profile --voice --type "
                      "<type> --plugin-profile '${user_config.profile}' --plugin-locale '${user_config.locale}'`", body)
        self.assertIn("If the call fails, carry on without it.", body)
        self.assertIn("the profile's voice notes for replacements", body)
        self.assertNotIn("calibration notes", body)
        self.assertNotIn("First, before any other step", body)  # standalone only: check has already loaded it

    def test_all_26_patterns_kept_in_reference(self):
        for n in range(1, 27):
            self.assertRegex(self.patterns, rf"(?m)^### {n}\. ")
        self.assertNotRegex(self.patterns, r"(?m)^### 27\. ")

    def test_attribution(self):
        notice = (REPO / "NOTICE.md").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2025 Siqi Chen", notice)
        self.assertIn("v3.1.0", notice)


PROFILE_SUBCOMMANDS = {"check", "profile", "anchors", "register-checklist", "merge", "justify", "judge-input",
                       "status", "doctor"}
LOCALE_SUBCOMMANDS = {"profile", "register-checklist", "doctor"}  # #121: the commands that print the locale
CLI_SPAN = re.compile(r"`([^`\n]*\b(?:RUN|run\.py) ([a-z-]+)\b[^`\n]*)`")


def cli_spans(path: Path):
    """(line, span, subcommand) for each CLI call in a file, paragraph by paragraph, so a call wrapped onto a second
    line (to keep a skill inside its line width) is still seen whole."""
    line = 1
    for para in path.read_text(encoding="utf-8").split("\n\n"):
        for span, sub in CLI_SPAN.findall(" ".join(para.split())):
            yield line, span, sub
        line += para.count("\n") + 2


class ProfileFlagEverywhere(unittest.TestCase):  # without the flag, a settings-only profile is lost
    def test_subcommand_set_matches_the_cli(self):
        src = (REPO / "lib" / "plainspoken" / "__main__.py").read_text(encoding="utf-8")
        parsers = dict(re.findall(r'(\w+) = sub\.add_parser\("([a-z-]+)"', src))
        flagged = {parsers[v] for v in re.findall(r'(\w+)\.add_argument\("--plugin-profile"', src)}
        self.assertEqual(flagged, PROFILE_SUBCOMMANDS)

    def test_every_profile_loading_call_passes_the_plugin_profile(self):
        missing = []
        for path in sorted((REPO / "skills").glob("*/SKILL.md")):
            for n, span, sub in cli_spans(path):
                explicit = re.search(r"--profile\b", span)  # an explicit file (voice Build) needs no fallback
                if sub in PROFILE_SUBCOMMANDS and "--plugin-profile '${user_config.profile}'" not in span \
                        and not explicit:
                    missing.append(f"{path.parent.name}/SKILL.md:{n}: {span}")
        self.assertEqual(missing, [])


class LocaleFlagEverywhere(unittest.TestCase):  # #121: skills' Bash calls never see CLAUDE_PLUGIN_OPTION_LOCALE
    def test_subcommand_set_matches_the_cli(self):
        src = (REPO / "lib" / "plainspoken" / "__main__.py").read_text(encoding="utf-8")
        parsers = dict(re.findall(r'(\w+) = sub\.add_parser\("([a-z-]+)"', src))
        flagged = {parsers[v] for v in re.findall(r'(\w+)\.add_argument\("--plugin-locale"', src)}
        self.assertEqual(flagged, LOCALE_SUBCOMMANDS)

    def test_every_locale_printing_call_passes_the_plugin_locale(self):
        missing, seen = [], 0
        for path in sorted((REPO / "skills").glob("*/SKILL.md")):
            for n, span, sub in cli_spans(path):
                if sub in LOCALE_SUBCOMMANDS:
                    seen += 1
                    if "--plugin-locale '${user_config.locale}'" not in span:
                        missing.append(f"{path.parent.name}/SKILL.md:{n}: {span}")
        self.assertEqual(missing, [])
        self.assertGreater(seen, 20)


class PerFileProfile(unittest.TestCase):
    def test_file_less_calls_get_the_files_profile(self):
        for name in ("write", "plain-language"):
            with self.subTest(skill=name):
                text = " ".join(skill(name)[1].split())
                self.assertIn("RUN config profile-for", text)
                self.assertIn("add `--profile '<the printed value>'` to every `RUN` call below that takes "
                              "`--plugin-profile`", text)
                self.assertIn("Exit 3", text.replace("exit 3", "Exit 3"))

    def test_file_calls_resolve_it_themselves(self):
        for name in ("check", "humanize"):
            with self.subTest(skill=name):
                self.assertIn("[engine] profiles", skill(name)[1])

    def test_the_cli_has_profile_for(self):
        src = (REPO / "lib" / "plainspoken" / "__main__.py").read_text(encoding="utf-8")
        self.assertIn('add_parser("profile-for"', src)


class NoLoadTimeCommands(unittest.TestCase):  # #12: Hermes rates any load-time command under skills/ high
    def test_no_skill_file_has_a_load_time_command(self):
        found = []
        for f in sorted((REPO / "skills").rglob("*")):
            if f.is_file():
                for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if LOAD_LINE.search(line):
                        found.append(f"{f.relative_to(REPO)}:{n}")
        self.assertEqual(found, [])

    def test_every_skill_with_a_profile_call_runs_it_first(self):
        for f in sorted((REPO / "skills").glob("*/SKILL.md")):
            text = f.read_text(encoding="utf-8")
            if "First, before any other step" in text and f.parent.name != "kaizen":
                assert_first_step(self, text, PROFILE_CALL)


class MeaningDiff(unittest.TestCase):  # #147: check and humanize list what an edit changed in the meaning
    CHECK_DESCRIPTION = ("Checks a draft for AI writing tells with a fixed lint and four isolated judges, then fixes, "
                         "never adding. Use before an article, page, email, post or script goes out, and whenever "
                         "asked if any text, even one line, sounds like AI.")
    HUMANIZE_DESCRIPTION = ("Removes AI writing patterns without adding facts, in the writer's voice. Use when asked to "
                            "humanise or de-AI text, make it sound like a person wrote it, less like ChatGPT or a bot, "
                            "or less stiff.")

    @staticmethod
    def step(text: str, label: str) -> str:
        """The numbered step whose bold label starts with `label`, found by its content rather than its number."""
        m = re.search(rf"(?ms)^\d+\. \*\*{re.escape(label)}[^*]*\*\*(.*?)(?=^\d+\. \*\*|^## |\Z)", text)
        assert m, f"no **{label}** step"
        return " ".join(m.group(1).split())

    def test_check_starts_and_compares(self):
        _, text = skill("check")
        self.assertIn("`RUN meaning-diff FILE --start`", self.step(text, "Lint"))
        self.assertIn("(not a rerun)", self.step(text, "Lint"))
        report = self.step(text, "Report")
        self.assertIn("`RUN meaning-diff FILE`", report)
        self.assertLess(report.index("meaning-diff FILE"), report.index("RUN status FILE"))
        self.assertIn("`needs the owner` lines", report)
        self.assertIn("never call one of them a failure", report)
        route = re.search(r"(?ms)^## Report only\n(.*?)(?=^## )", text).group(1)
        self.assertIn("Skip `meaning-diff`: nothing is edited.", " ".join(route.split()))
        self.assertIn("run.py meaning-diff", text)  # the subcommands-used line

    def test_humanize_file_mode_runs_it(self):
        _, text = skill("humanize")
        flat = " ".join(text.split())
        self.assertIn("lib/run.py meaning-diff <file> --start", flat)
        self.assertIn("meaning-diff <file>` and put each line it lists in your summary", flat)
        self.assertIn("Not in text-only or embedded mode", flat)
        self.assertLess(flat.index("meaning-diff <file> --start"), flat.index("## Why AI text"))  # before rewriting

    def test_descriptions_unchanged(self):  # the always-on budget doesn't move
        self.assertEqual(skill("check")[0]["description"], self.CHECK_DESCRIPTION)
        self.assertEqual(skill("humanize")[0]["description"], self.HUMANIZE_DESCRIPTION)


class JoinRemedy(unittest.TestCase):  # #73: a 7d join padded a sentence or added a reason ("because …")
    def test_every_fix_step_says_a_join_adds_nothing(self):
        texts = {name: " ".join(skill(name)[1].split()) for name in ("check", "humanize", "write")}
        texts["rhythm"] = " ".join((REPO / "skills" / "plain-language" / "references" / "rhythm.md")
                                   .read_text(encoding="utf-8").split())
        for name in ("check", "humanize"):
            self.assertIn('A join uses "and" or "but", or merges two sentences; it never adds a clause, detail or '
                          'reason (such as "because …")', texts[name], name)
        self.assertIn("at most twice (a join adds no clause, detail or reason)", texts["write"])
        self.assertIn("A join adds no clause, detail or reason", texts["rhythm"])

    def test_a_rhythm_fix_never_pads_and_keeps_what_it_cannot_clear(self):  # #73 round 8: pads to cross 25 words
        def flat(path: Path) -> str:
            return " ".join(path.read_text(encoding="utf-8").split())
        check, humanize = (" ".join(skill(n)[1].split()) for n in ("check", "humanize"))
        rhythm = flat(REPO / "skills" / "plain-language" / "references" / "rhythm.md")
        guide = flat(REPO / "guides" / "checking.md")
        self.assertIn('A rhythm fix (7, 7d) joins two neighbouring sentences with "and", "but", a comma or a semicolon, '
                      "keeping their own words, or splits one. It never pads or restates to reach a length", check)
        self.assertIn('no "so" or "because"', check)
        self.assertIn("keep the WARN (`--keep`, then step 7)", check)
        self.assertIn("a 7d line the rhythm rule can't clear", check)  # step 1: kept, not lengthened
        self.assertIn("a 7 or 7d WARN the rhythm rule can't clear goes to step 7 instead, never lengthened", check)
        self.assertIn('A rhythm finding (7, 7d) is fixed only by joining two neighbouring sentences with "and", "but", '
                      "a comma or a semicolon in their own words, or by splitting one. Never pad a sentence", humanize)
        self.assertIn("never by padding", humanize)
        self.assertIn("in their own words, or leave the flag", rhythm)
        self.assertIn("never pad a sentence to reach a length", guide)
