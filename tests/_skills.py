"""Shared checks for the Phase 3 skill tests. A skill's test class mixes in SkillBasics with unittest.TestCase."""
from __future__ import annotations

import re
from pathlib import Path

from plainspoken.registry import load_config
from scripts.dev.lint_frontmatter import parse_frontmatter

REPO = Path(__file__).resolve().parents[1]
AUTO = {"check", "humanize", "write", "plain-language"}
MARK = "<!-- plainspoken: quotes tells on purpose -->"
# #12: no load-time command; the skill's first step runs the profile call explicitly (same command, same flags).
FIRST_STEP = "**First, before any other step:** run"
PROFILE_CALL = "`python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py profile --plugin-profile '${user_config.profile}'`"
# The load-time form Hermes rates high (`inline_shell_exec`), written with \x60 so this file never matches it.
LOAD_LINE = re.compile("!\x60[^\x60\\s][^\x60\\n]*\x60")
TOOL_NAMES = re.compile(r"\b(Agent|Task|Bash|Read|Write|Edit|Grep|Glob) tool\b")


def load(name: str) -> tuple[dict, str]:
    text = (REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    return parse_frontmatter(text), text


def headings(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"(?m)^#{2,3} (.+?)\s*$", text)]


def files(name: str) -> list[Path]:
    d = REPO / "skills" / name
    return [d / "SKILL.md", *sorted((d / "references").glob("*.md"))]


def flat(text: str) -> str:
    return " ".join(text.split())


def assert_first_step(case, text: str, call: str) -> None:
    """`text` names `call` as its explicit first step, before the first heading after Core rules."""
    body = flat(text)
    start = body.find(f"{FIRST_STEP} {call} and read what it prints")
    case.assertNotEqual(start, -1, call)
    case.assertIn("If the call fails, carry on without it.", body[start:start + 400])
    later = [m.start() for m in re.finditer(r"## (?!Core rules)", body)]
    case.assertTrue(later and start < later[0], "the first step must come before the skill's steps")


class SkillBasics:
    NAME = ""
    REQUIRED: tuple[str, ...] = ()    # H2/H3 heading texts that must appear, in this order
    DRAFTING = False                  # True: no ban-list word anywhere in the skill's files
    REFERENCES: tuple[str, ...] = ()  # files that must exist under references/

    def setUp(self):
        self.fm, self.text = load(self.NAME)

    def test_frontmatter(self):
        self.assertEqual(self.fm["name"], self.NAME)
        self.assertLessEqual(len(self.fm["description"]), 1024)
        self.assertEqual(self.fm.get("disable-model-invocation") == "true", self.NAME not in AUTO)
        self.assertIn("Bash(python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py *)", self.fm.get("allowed-tools", ""))

    def test_size(self):
        self.assertLessEqual(len(self.text.splitlines()), 500)

    def test_core_rules_come_first(self):
        self.assertEqual(headings(self.text)[0], "Core rules")

    def test_required_sections_in_order(self):
        found = headings(self.text)
        self.assertEqual([h for h in self.REQUIRED if h not in found], [])
        self.assertEqual([h for h in found if h in self.REQUIRED], list(self.REQUIRED))

    def test_references_exist(self):
        for name in self.REFERENCES:
            self.assertTrue((REPO / "skills" / self.NAME / "references" / name).is_file(), name)

    def test_profile_read_first(self):
        assert_first_step(self, self.text, PROFILE_CALL)

    def test_no_load_time_command(self):
        for f in files(self.NAME):
            self.assertIsNone(LOAD_LINE.search(f.read_text(encoding="utf-8")), f.name)

    def test_placeholder_never_double_quoted(self):
        for f in files(self.NAME):
            self.assertNotIn('"${user_config', f.read_text(encoding="utf-8"), f.name)

    def test_tool_neutral_prose(self):  # Claude specifics live in references/claude-code.md
        self.assertIsNone(TOOL_NAMES.search(self.text))
        self.assertNotIn("## Claude Code notes", self.text)

    def test_claude_specifics_in_their_own_reference(self):
        self.assertTrue((REPO / "skills" / self.NAME / "references" / "claude-code.md").is_file())
        self.assertIn("references/claude-code.md", self.text)

    def test_no_ban_list_words(self):
        if not self.DRAFTING:
            self.skipTest("audit skill: may describe patterns")
        words = load_config().lists["ban_literal"]
        for f in files(self.NAME):
            text = f.read_text(encoding="utf-8")
            self.assertNotIn(MARK, text, f"{f.name}: a drafting skill can't carry quoted tells")
            for w in words:
                self.assertIsNone(re.search(rf"\b{re.escape(w)}\b", text, re.I), f"{f.name}: {w}")
