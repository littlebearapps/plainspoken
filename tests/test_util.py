"""_util: the helpers more than one module shares (one helper each, so their rules can't drift)."""
import copy
import unittest
from unittest import mock

from plainspoken import _util, checker, claims, claims_tools, config, extraction, integrity, pinning, schema


class SafeRelative(unittest.TestCase):
    def test_one_rule_for_every_project_relative_path(self):
        good = ("a.md", "docs/a.md", ".plainspoken/sources/x.txt", "a..b/c.md", "./a.md")
        bad = ("", "  ", "/abs.md", "\\abs.md", "../up.md", "a/../b.md", "a\\..\\b.md", "C:x.md", "c:/x.md",
               "a\x00.md", None, 3)
        for value in good:
            with self.subTest(value=value):
                self.assertTrue(_util.safe_relative(value))
                self.assertTrue(pinning.safe_relative(value))
                self.assertTrue(config._relative_dir(value))
        for value in bad:
            with self.subTest(value=value):
                self.assertFalse(_util.safe_relative(value))
                self.assertFalse(pinning.safe_relative(value))
                self.assertFalse(config._relative_dir(value))


class Graphemes(unittest.TestCase):  # `length` counts what a reader sees as one character
    def check(self, cases):
        for text, want in cases:
            with self.subTest(text=text.encode("unicode_escape").decode()):
                self.assertEqual(_util.graphemes(text), want)

    def test_plain_text(self):
        self.check((("", 0), ("abc", 3), ("Two words.", 10), ("a\nb", 3), ("\r\n", 1), ("\n\n", 2)))

    def test_combining_marks(self):
        self.check((("e\u0301", 1), ("cafe\u0301", 4), ("e\u0301\u0302\u0323", 1), ("a\u20dd", 1),
                    ("\u0301", 1), ("\u0301a", 2), ("\n\u0301", 2)))

    def test_zwj_sequences(self):
        family = "\U0001F468\u200d\U0001F469\u200d\U0001F467\u200d\U0001F466"
        coder = "\U0001F469\U0001F3FD\u200d\U0001F4BB"  # with a skin-tone modifier
        rainbow_flag = "\U0001F3F3\ufe0f\u200d\U0001F308"
        self.check(((family, 1), (coder, 1), (rainbow_flag, 1), (family + family, 2), ("a" + family + "b", 3),
                    ("a\u200db", 2)))  # a ZWJ joins pictographs, not letters

    def test_variation_selectors(self):
        self.check((("\u2764\ufe0f", 1), ("\u263a\ufe0e", 1), ("1\ufe0f\u20e3", 1), ("\u845b\U000E0100", 1),
                    ("\u2764\ufe0f\u2764\ufe0f", 2)))

    def test_regional_indicator_pairs(self):
        au, nz = "\U0001F1E6\U0001F1FA", "\U0001F1F3\U0001F1FF"
        self.check(((au, 1), (au + nz, 2), (au + nz[0], 2), (au[0], 1), ("x" + au + "y", 3)))

    def test_tag_sequence_flag(self):
        england = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"
        self.check(((england, 1),))


class SharedHelpers(unittest.TestCase):
    def test_no_module_keeps_its_own_copy(self):
        for module, name in ((checker, "_sha"), (checker, "_now"), (checker, "_reject_constant"),
                             (claims_tools, "_hash_or_none"), (claims_tools, "now_iso"), (integrity, "_clip"),
                             (extraction, "_FRONTMATTER"), (extraction, "_TLDR"), (claims, "_hash_or_none")):
            with self.subTest(module=module.__name__, name=name):
                self.assertFalse(hasattr(module, name))
        self.assertIs(extraction.FRONTMATTER, integrity.FRONTMATTER)
        self.assertIs(extraction.TLDR, integrity.TLDR)

    def test_now_iso_has_an_offset(self):
        self.assertRegex(_util.now_iso(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")

    def test_clip(self):
        self.assertEqual(_util.clip("short", 10), "short")
        self.assertEqual(_util.clip("x" * 20, 10), "x" * 9 + "…")

    def test_strict_json_refuses_duplicates_and_constants(self):
        self.assertEqual(claims.strict_json('{"a": 1}'), {"a": 1})
        for bad in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                claims.strict_json(bad)


class SchemaDerived(unittest.TestCase):
    """claims_tools reads the enums and patterns it needs from the ledger schema instead of copying them."""

    def test_scaffold_rules_follow_the_schema(self):
        real = schema.load("claim-ledger")
        changed = copy.deepcopy(real)
        claim = changed["$defs"]["claim"]["properties"]
        claim["locations"]["items"]["properties"]["kind"]["enum"].append("sidebar")
        claim["claim_id"]["pattern"] = "^[A-Z]+$"
        changed["properties"]["source_file"]["pattern"] = r"^(?!/)(?!.*\.\./).+\.(md|rst)$"
        claims_tools._schema.cache_clear()
        self.addCleanup(claims_tools._schema.cache_clear)
        with mock.patch.object(claims_tools.schema, "load", return_value=changed):
            self.assertIn("sidebar", claims_tools.location_kinds())
            self.assertTrue(claims_tools.id_pattern().match("ABC"))
            self.assertFalse(claims_tools.id_pattern().match("A-1"))
            self.assertEqual(claims_tools.source_suffixes(), (".md", ".rst"))

    def test_scaffold_claim_types_are_schema_values(self):
        types = schema.load("claim-ledger")["$defs"]["claim"]["properties"]["claim_type"]["enum"]
        self.assertLessEqual(set(claims_tools._CLAIM_TYPES.values()) | {"premise"}, set(types))
        self.assertEqual(claims_tools.source_suffixes(), (".md", ".mdx", ".markdown", ".txt", ".html"))


if __name__ == "__main__":
    unittest.main()
