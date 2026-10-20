import unittest
from pathlib import Path

from plainspoken import profile, report

REPO = Path(__file__).resolve().parents[1]
MARK = "<!-- plainspoken: quotes tells on purpose -->"
GLOBS = ("skills/*/SKILL.md", "skills/*/references/*.md", "agents/*.md", "templates/*.md", "guides/*.md",
         "output-styles/*.md", "data/brief.md")
# Files that quote tells on purpose. Adding one needs a reason in the commit message.
EXEMPT = {"skills/humanize/references/patterns.md", "skills/copy-audit/references/tells.md"}


def marked(path: Path) -> bool:
    return MARK in "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])


def own_files() -> list[Path]:
    files = [REPO / "README.md", REPO / "docs" / "report-contract.md"]
    for pattern in GLOBS:
        files += sorted(REPO.glob(pattern))
    return files


class SelfLint(unittest.TestCase):
    """The plugin's own reader-facing text passes its own lint: default profile, content type article."""

    def test_no_blocks_in_own_text(self):
        for path in own_files():
            rel = path.relative_to(REPO).as_posix()
            if rel in EXEMPT:
                continue
            with self.subTest(file=rel):
                lint = report.run_lint(path, profile.default())
                blocks = [(f["rule"], f["line"], f["excerpt"]) for f in lint["findings"] if f["severity"] == "BLOCK"]
                self.assertEqual(blocks, [], rel)

    def test_exemptions_are_marked_and_listed(self):
        found = {p.relative_to(REPO).as_posix() for p in own_files() if marked(p)}
        self.assertEqual(found, EXEMPT)
