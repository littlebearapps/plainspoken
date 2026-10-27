"""Explaining findings: shorthand that hides scope, assumed goals, exposure not ability, the order a finding is
explained in, and recommendations someone else carries out."""
import unittest

from tests._skills import REPO, flat, headings

WATCH = "skills/plain-language/references/watch-outs.md"
TERMS = "skills/plain-language/references/insider-terms.md"
FIELDS = "skills/voice/references/fields.md"
LABELS = "skills/write/references/confidence-labels.md"


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """The body under `## heading`, up to the next H2."""
    marker = f"\n## {heading}\n"
    if marker not in text:
        raise AssertionError(f"missing section: {heading}")
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


class FindingsGuidance(unittest.TestCase):
    def test_familiar_shorthand(self):
        body = flat(section(read(WATCH), "Familiar shorthand")).lower()
        for phrase in ("what exactly?", "capacity", "reporting", "shortest concrete phrase", "[writer:",
                       "precision", "before:", "after:"):
            self.assertIn(phrase, body, phrase)

    def test_assumed_goal(self):
        body = flat(section(read(WATCH), "Assumed goal")).lower()
        for phrase in ("as fact", "condition", "if the club wants"):
            self.assertIn(phrase, body, phrase)

    def test_naming_the_part_before_its_job(self):
        body = flat(section(read(WATCH), "Naming the part before its job")).lower()
        for phrase in ("what the reader would see", "what it's for", "what's there now", "why it matters",
                       "then name", "already has", "before:", "after:"):
            self.assertIn(phrase, body, phrase)

    def test_watch_outs_still_lists_every_pattern(self):
        h = headings(read(WATCH))
        for name in ("Familiar shorthand", "Assumed goal", "Naming the part before its job", "Soft abstractions"):
            self.assertIn(name, h)

    def test_a_reader_using_a_term_may_not_know_it(self):
        spotting = flat(section(read(TERMS), "Spotting them"))
        self.assertIn("in their own message", spotting)
        self.assertIn("keep their word and add its plain meaning", spotting)

    def test_persona_describes_exposure_not_ability(self):
        persona = flat(read(FIELDS).split("- `persona`:", 1)[1].split("\n- `", 1)[0])
        self.assertIn("hasn't been exposed to", persona)
        self.assertIn("never their age or ability", persona)

    def test_recommendations_someone_else_carries_out(self):
        body = flat(section(read(LABELS), "Recommendations someone else carries out")).lower()
        for phrase in ("reports, audits", "the item affected", "who usually does it", "a role",
                       "confirmation", "still unknown", "platform-specific steps"):
            self.assertIn(phrase, body, phrase)

    def test_touched_files_wrap_at_118(self):
        for rel in (WATCH, TERMS, FIELDS, LABELS):
            for n, line in enumerate(read(rel).splitlines(), start=1):
                self.assertLessEqual(len(line), 118, f"{rel}:{n}")


if __name__ == "__main__":
    unittest.main()
