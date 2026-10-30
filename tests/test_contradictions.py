"""The shipped defaults don't contradict each other (two known contradictions in the source rules)."""
import ast
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GLOBS = ("skills/**/*.md", "agents/*.md", "data/rubrics/*.md", "data/brief.md", "templates/*", "guides/*.md",
         "output-styles/*.md", "README.md")
CAP = re.compile(
    r"\b\d{1,2}\s*(?:-|–|to)\s*\d{1,2}[- ]words?\b[^.\n]*\b(?:cap|limit|max(?:imum)?|or (?:fewer|less))\b"
    r"|\b(?:no|never a|keep (?:every|each|all)) sentences? (?:over|longer than|above|under|below) \d+ words\b"
    r"|\b\d{1,2}-word average sentences?\b", re.I)


HEADING = re.compile(r"(#{1,6})\s")


def drafting_text(text: str) -> str:
    """The text minus every "How it's checked" section: those describe the checker, they aren't drafting caps. A
    section runs to the next heading of the same or a higher level, so its own subsections are skipped with it; a
    `#` line inside a code fence isn't a heading."""
    out, skip_level, fenced = [], 0, False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        m = None if fenced else HEADING.match(line)
        if m:
            level = len(m.group(1))
            if skip_level and level <= skip_level:
                skip_level = 0
            if not skip_level and "how it's checked" in line.lower():
                skip_level = level
        if not skip_level:
            out.append(line)
    return "\n".join(out)


FOURTH = re.compile(r"([^.\n]{0,60})\badd (?:a|one more) fourth\b", re.I)
CODE = ("lib/**/*.py", "hooks/*.py")  # the engine's and the hooks' messages reach the writer too


def message_strings(source: str) -> list[str]:
    """Every string literal in a module. An f-string's fields read as 25, so a cap built from a threshold
    (f"no sentence over {n} words") still reads as one."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.JoinedStr):
            out.append("".join(v.value if isinstance(v, ast.Constant) else "25" for v in node.values))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
    return out


def asks_for_a_long_sentence(message: str) -> bool:
    """The staccato finding ("No sentence over 25 words in this section — join two neighbours with "and" or "but" …")
    names the check and asks for a longer sentence: the opposite of a cap, like a docs "How it's checked" section."""
    return "in this section — join two " in message


def code_messages() -> list[tuple[str, str]]:
    out = []
    for g in CODE:
        for p in sorted(REPO.glob(g)):
            out += [(str(p.relative_to(REPO)), m) for m in message_strings(p.read_text(encoding="utf-8"))]
    return out


def shipped() -> list[Path]:
    out = []
    for g in GLOBS:
        out += [p for p in REPO.glob(g) if p.is_file()]
    return sorted(set(out))


class Contradictions(unittest.TestCase):
    def test_never_add_a_fourth(self):
        texts = [(str(p.relative_to(REPO)), p.read_text(encoding="utf-8")) for p in shipped()] + code_messages()
        for where, text in texts:
            for m in FOURTH.finditer(text):
                self.assertRegex(m.group(1).lower(), r"\b(?:never|don't|do not|not)\b", f"{where}: {m.group(0)}")

    def test_no_cap_in_engine_or_hook_messages(self):
        hits = [f"{where}: {m.group(0)}" for where, msg in code_messages() if not asks_for_a_long_sentence(msg)
                for m in CAP.finditer(msg)]
        self.assertEqual(hits, [])
        self.assertGreater(len(code_messages()), 1000)  # the scan reaches lib/ and hooks/

    def test_message_strings_catch_a_cap_built_from_a_threshold(self):
        src = 'n = 20\nMSG = f"Keep every sentence under {n} words."\nOTHER = "add a fourth item"\n'
        msgs = message_strings(src)
        self.assertTrue(any(CAP.search(m) for m in msgs))
        self.assertTrue(any(FOURTH.search(m) for m in msgs))
        staccato = 'MSG = f"No sentence over {n} words in this section — join two {_JOIN}"\n'
        self.assertTrue(all(asks_for_a_long_sentence(m) for m in message_strings(staccato) if CAP.search(m)))

    def test_no_blanket_sentence_cap(self):
        hits = [f"{p.relative_to(REPO)}: {m.group(0)}" for p in shipped()
                for m in CAP.finditer(drafting_text(p.read_text(encoding="utf-8")))]
        self.assertEqual(hits, [])

    def test_write_lists_the_real_number_of_items(self):
        self.assertIn("List as many items as there really are",
                      (REPO / "skills" / "write" / "SKILL.md").read_text(encoding="utf-8"))

    def test_rhythm_guidance_has_over_correction_guardrails(self):
        text = (REPO / "skills" / "plain-language" / "references" / "rhythm.md").read_text(encoding="utf-8")
        self.assertIn("## Over-correction guardrails", text)
        self.assertIn("no length cap", text.lower())

    def test_rubric_rule_6_uses_the_delete_test(self):
        rubric = (REPO / "data" / "rubrics" / "judges.md").read_text(encoding="utf-8")
        section = rubric.split("### 6 Rule of three", 1)[1].split("\n### ", 1)[0]
        self.assertIn("delete test", section)

    def test_cap_phrase_in_how_its_checked_is_ignored(self):
        described = "## How it's checked\n\nA section with no sentence over 25 words is flagged.\n"
        self.assertIsNone(CAP.search(drafting_text(described)))

    def test_same_cap_phrase_elsewhere_still_fails(self):
        drafted = "## Drafting\n\nKeep no sentence over 25 words.\n\n## How it's checked\n\nFine.\n"
        self.assertIsNotNone(CAP.search(drafting_text(drafted)))

    def test_subsections_of_how_its_checked_are_skipped(self):
        described = ("## How it's checked\n\nFine.\n\n### Detail\n\nA section with no sentence over 25 words is "
                     "flagged.\n\n## Drafting\n\nWrite.\n")
        self.assertIsNone(CAP.search(drafting_text(described)))
        self.assertIn("Write.", drafting_text(described))

    def test_skipping_ends_at_the_same_or_a_higher_level(self):
        for heading in ("### Next", "## Next", "# Next"):
            drafted = f"### How it's checked\n\nFine.\n\n{heading}\n\nKeep no sentence over 25 words.\n"
            self.assertIsNotNone(CAP.search(drafting_text(drafted)), heading)
        deeper = "## How it's checked\n\n#### Deeper\n\nKeep no sentence over 25 words.\n"
        self.assertIsNone(CAP.search(drafting_text(deeper)))

    def test_a_hash_line_in_a_fence_is_not_a_heading(self):
        described = ("## How it's checked\n\n```toml\n# a comment\nx = 1\n```\n\nA section with no sentence "
                     "over 25 words is flagged.\n")
        self.assertIsNone(CAP.search(drafting_text(described)))
