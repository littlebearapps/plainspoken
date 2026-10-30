"""Per-component description caps, so the always-on budget is controlled offline.

Auto-trigger skills and agents are listed in every session; manual-only skills aren't (Claude Code skills docs,
checked 2026-10-12), but stay short anyway. Each task that adds a component adds its row."""
import unittest
from pathlib import Path

from scripts.dev.lint_frontmatter import parse_frontmatter

REPO = Path(__file__).resolve().parents[1]
CAPS = {
    "skills/check/SKILL.md": 280,
    "skills/humanize/SKILL.md": 200,
    "skills/voice/SKILL.md": 300,
    "skills/plain-language/SKILL.md": 240,
    "skills/copy-audit/SKILL.md": 300,
    "skills/register-check/SKILL.md": 300,
    "skills/adapt/SKILL.md": 300,
    "skills/write/SKILL.md": 240,
    "skills/claims/SKILL.md": 250,
    "skills/reader-value/SKILL.md": 250,
    "skills/kaizen/SKILL.md": 250,
    "skills/setup/SKILL.md": 250,
    "skills/doctor/SKILL.md": 250,
    "agents/tells-judge.md": 160,
    "agents/cold-reader.md": 140,
    "agents/claims-checker.md": 140,
    "agents/delivery-checker.md": 80,  # the always-on budget had ~35 tokens left when it was added
    "agents/mining-drafter.md": 30,  # ~10 tokens were left; it's only ever started by name, from kaizen mine
}


class Descriptions(unittest.TestCase):
    def test_caps(self):
        for rel, cap in CAPS.items():
            with self.subTest(rel=rel):
                desc = parse_frontmatter((REPO / rel).read_text(encoding="utf-8"))["description"]
                self.assertLessEqual(len(desc), cap)

    def test_every_skill_and_agent_has_a_cap(self):
        found = {p.relative_to(REPO).as_posix() for p in (*REPO.glob("skills/*/SKILL.md"), *REPO.glob("agents/*.md"))}
        self.assertEqual(found - set(CAPS), set())
