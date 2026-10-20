"""tomlw.py: the small TOML writer behind `claims scaffold` and `claims pin`. Round-trips through tomllib."""
import math
import tomllib
import unittest

from plainspoken import tomlw


def _scaffold_shaped() -> dict:
    return {
        "schema_version": 1,
        "article_id": "ACME-PLUMBING",
        "article_slug": "acme-plumbing",
        "source_file": "posts/acme plumbing.md",
        "source_content_hash": "sha256:" + "0" * 64,
        "checked_at": "2026-10-14T09:00:00+11:00",
        "checked_by": "plainspoken claims scaffold",
        "coverage_status": "unstarted",
        "coverage_notes": "line one\nline two",
        "claims": [
            {
                "claim_id": "ACME-C001",
                "text": 'Acme Plumbing said "we fix 90% of leaks" — C:\\path\\to\\file, tab\there',
                "locations": [{"kind": "frontmatter", "field": "title", "anchor": "line 2"}],
                "claim_type": "quotation",
                "prominence": "high",
                "status": "blocking",
                "resolution": "unreviewed candidate from claims scaffold",
                "notes": "unicode: café “curly” ‘single’ £450 €1.2m \u00a0nbsp \x01ctrl \x7fdel",
            },
            {
                "claim_id": "ACME-C002",
                "text": "plain",
                "locations": [{"kind": "body"}],
                "claim_type": "statistic",
                "prominence": "medium",
                "status": "blocking",
                "resolution": "r",
                "binding": {"same_subject": True, "same_geography": False, "same_period": True,
                            "same_denominator": True, "supports_strength": False,
                            "additional_passages": [{"passage": "p1", "passage_sha256": "sha256:" + "a" * 64}]},
            },
        ],
        "exclusions": [],
        "numbers": {"ratio": 0.25, "big": 1e20, "small": 1e-05, "neg": -3, "list": [1, 2, 3], "words": ["a", "b"]},
        "weird keys": {"has space": "x", "dotted.key": "y", "": "empty key", "ünï": "z"},
        "empty_table": {},
    }


class RoundTrip(unittest.TestCase):
    def test_scaffold_shaped_dict_round_trips(self):
        data = _scaffold_shaped()
        self.assertEqual(tomllib.loads(tomlw.dumps(data)), data)

    def test_nested_tables_inside_array_of_tables(self):
        data = {"a": [{"b": {"c": {"d": 1}}, "e": [{"f": "g"}]}, {"h": True}]}
        self.assertEqual(tomllib.loads(tomlw.dumps(data)), data)

    def test_table_with_only_subtables_gets_no_header(self):
        out = tomlw.dumps({"claims": {"binding": {"passage": "x"}}})
        self.assertTrue(out.startswith("[claims.binding]\n"), out)
        self.assertNotIn("[claims]\n", out)

    def test_bool_is_not_written_as_int(self):
        self.assertIn("flag = true", tomlw.dumps({"flag": True}))

    def test_special_floats(self):
        out = tomllib.loads(tomlw.dumps({"a": math.inf, "b": -math.inf, "c": math.nan}))
        self.assertEqual((out["a"], out["b"]), (math.inf, -math.inf))
        self.assertTrue(math.isnan(out["c"]))


class Refusals(unittest.TestCase):
    def test_set_is_a_type_error(self):
        with self.assertRaises(TypeError):
            tomlw.dumps({"tags": {"a", "b"}})

    def test_other_unsupported_values(self):
        import datetime
        for bad in (None, datetime.date(2026, 10, 14), b"bytes", [[1, 2]], [1, {"a": 1}], ("tuple",)):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                tomlw.dumps({"x": bad})

    def test_non_dict_top_level_and_non_str_key(self):
        with self.assertRaises(TypeError):
            tomlw.dumps([1, 2])
        with self.assertRaises(TypeError):
            tomlw.dumps({1: "a"})


if __name__ == "__main__":
    unittest.main()
