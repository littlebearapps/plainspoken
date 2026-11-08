"""Keep the host-facing short-draft route and reporting language in step (#149)."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DraftingRouteDocs(unittest.TestCase):
    def test_write_description_is_for_long_or_full_check_requests(self):
        skill = (ROOT / "skills/write/SKILL.md").read_text(encoding="utf-8")
        description = next(line.removeprefix("description: ") for line in skill.splitlines()
                           if line.startswith("description:"))
        self.assertLessEqual(len(description), 240)
        self.assertIn("writing people will read (an article, page, email, post, text message, caption or script)",
                      description)
        self.assertIn("250+ words or research", description)
        self.assertIn("full check on a short one", description)
        self.assertNotIn("short or long", description)

    def test_all_route_notes_name_the_lighter_route_and_its_limit(self):
        for name in ("data/drafting-rule.md", "hosts/hermes.md", "hosts/codex.md"):
            with self.subTest(file=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("write not followed; route: short-piece lint", text)
                self.assertIn("lint only, judges not run", text)
                self.assertIn("full check", text)
