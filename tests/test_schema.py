import datetime as dt
import unittest

from plainspoken import schema as S


def errs(instance, sch):
    return S.validate(instance, sch)


class Type(unittest.TestCase):
    def test_wrong_type_names_root(self):
        out = errs("x", {"type": "integer"})
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("<root>: "), out)

    def test_bool_is_never_an_integer(self):
        self.assertEqual(len(errs(True, {"type": "integer"})), 1)
        self.assertEqual(len(errs(False, {"type": "number"})), 1)

    def test_type_list(self):
        self.assertEqual(errs(3, {"type": ["integer", "null"]}), [])
        self.assertEqual(errs(None, {"type": ["integer", "null"]}), [])
        self.assertEqual(len(errs("3", {"type": ["integer", "null"]})), 1)

    def test_each_type(self):
        cases = [({}, "object"), ([], "array"), ("", "string"), (1, "integer"), (1.5, "number"), (2, "number"),
                 (True, "boolean"), (None, "null")]
        for value, name in cases:
            self.assertEqual(errs(value, {"type": name}), [], name)

    def test_unknown_type_name_is_a_schema_error(self):
        with self.assertRaises(S.SchemaError):
            errs(1, {"type": "int"})

    def test_a_type_that_isnt_a_name_is_a_schema_error(self):  # was a TypeError
        for bad in ({}, [{}], [["string"]], 3, None, []):
            with self.subTest(type=bad), self.assertRaises(S.SchemaError):
                errs(1, {"type": bad})


class RequiredAndAdditional(unittest.TestCase):
    SCH = {"type": "object", "additionalProperties": False, "required": ["a"],
           "properties": {"a": {"type": "string"}}}

    def test_missing_key_named(self):
        out = errs({}, self.SCH)
        self.assertEqual(len(out), 1)
        self.assertIn("'a'", out[0])

    def test_extra_key_named(self):
        out = errs({"a": "x", "zz": 1}, self.SCH)
        self.assertEqual(len(out), 1)
        self.assertIn("'zz'", out[0])

    def test_additional_properties_true_is_unsupported(self):
        with self.assertRaises(S.SchemaError):
            errs({}, {"type": "object", "additionalProperties": True})

    def test_additional_properties_schema_checks_every_unlisted_key(self):  # the report's rules map
        sch = {"type": "object", "properties": {"a": {"type": "string"}},
               "additionalProperties": {"type": "object", "required": ["v"]}}
        self.assertEqual(errs({"a": "x", "r1": {"v": 1}, "r2": {"v": 2}}, sch), [])
        out = errs({"a": "x", "r1": {"v": 1}, "r2": {}, "r3": 5}, sch)
        self.assertEqual(out, ["r2: missing required key 'v'", "r3: expected object, got integer"])

    def test_additional_properties_schema_is_walked(self):
        with self.assertRaises(S.SchemaError):
            errs({}, {"type": "object", "additionalProperties": {"type": "int"}})


class Scalars(unittest.TestCase):
    def wrap(self, claim_schema):
        return {"type": "object", "properties": {"claims": {"type": "array", "items": {
            "type": "object", "properties": {"claim_id": claim_schema}}}}}

    def one(self, value, claim_schema):
        out = errs({"claims": [{"claim_id": value}]}, self.wrap(claim_schema))
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith("claims.0.claim_id: "), out)

    def test_enum(self):
        self.one("c", {"enum": ["a", "b"]})

    def test_const(self):
        self.one(2, {"const": 1})

    def test_const_true_rejects_one(self):
        self.one(1, {"const": True})

    def test_pattern(self):
        self.one("abc", {"type": "string", "pattern": "^[0-9]+$"})

    def test_min_length(self):
        self.one("", {"type": "string", "minLength": 1})

    def test_min_items(self):
        self.one([], {"type": "array", "minItems": 1})

    def test_valid_values_pass(self):
        sch = self.wrap({"type": "string", "enum": ["ab"], "pattern": "^a", "minLength": 2})
        self.assertEqual(errs({"claims": [{"claim_id": "ab"}]}, sch), [])

    def test_errors_sorted_by_path(self):
        sch = {"type": "array", "items": {"type": "string"}}
        out = errs([1, "ok", 2] + ["x"] * 8 + [3], sch)
        self.assertEqual([e.split(":")[0] for e in out], ["0", "2", "11"])


class Ref(unittest.TestCase):
    def test_local_ref_resolves(self):
        sch = {"type": "array", "items": {"$ref": "#/$defs/claim"},
               "$defs": {"claim": {"type": "object", "required": ["claim_id"]}}}
        self.assertEqual(errs([{"claim_id": "A"}], sch), [])
        out = errs([{}], sch)
        self.assertEqual(len(out), 1)
        self.assertIn("claim_id", out[0])

    def test_cyclic_ref_is_a_schema_error(self):  # was a RecursionError
        cyclic = ({"$ref": "#/$defs/a", "$defs": {"a": {"$ref": "#/$defs/a"}}},
                  {"$ref": "#/$defs/a", "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"allOf": [{"$ref": "#/$defs/a"}]}}},
                  {"$defs": {"a": {"if": {"$ref": "#/$defs/a"}, "then": {}}}},  # even in a branch never reached
                  {"$defs": {"a": {"then": {"$ref": "#/$defs/a"}}}})
        for sch in cyclic:
            with self.subTest(schema=sch), self.assertRaisesRegex(S.SchemaError, "cyclic"):
                errs({}, sch)
        tree = {"$ref": "#/$defs/node", "$defs": {"node": {"type": "object", "properties": {
            "kids": {"type": "array", "items": {"$ref": "#/$defs/node"}}}}}}
        self.assertEqual(errs({"kids": [{"kids": []}, {}]}, tree), [])  # recursion into the instance is fine
        self.assertEqual(len(errs({"kids": [{"kids": 3}]}, tree)), 1)

    def test_remote_ref_raises(self):
        with self.assertRaises(S.SchemaError):
            errs({}, {"$ref": "other.json#/x"})

    def test_missing_def_raises(self):
        with self.assertRaises(S.SchemaError):
            errs({}, {"$ref": "#/$defs/nope", "$defs": {}})


class Conditionals(unittest.TestCase):
    def test_claim_ledger_status_conditionals(self):
        sch = S.load("claim-ledger")
        claim = sch["$defs"]["claim"]
        base = {"claim_id": "A-001-C001", "text": "x", "locations": [{"kind": "body"}],
                "claim_type": "statistic", "prominence": "high"}
        out = errs(dict(base, status="verified"), {**claim, "$defs": sch["$defs"]})
        self.assertTrue(any("'source'" in e for e in out), out)
        self.assertEqual(errs(dict(base, status="opinion_or_inference"), {**claim, "$defs": sch["$defs"]}), [])

    def test_if_without_match_skips_then(self):
        sch = {"allOf": [{"if": {"properties": {"k": {"const": "a"}}}, "then": {"required": ["z"]}}]}
        self.assertEqual(errs({"k": "b"}, sch), [])
        self.assertEqual(len(errs({"k": "a"}, sch)), 1)


class DependentRequired(unittest.TestCase):
    def test_additional_passages_needs_passage(self):
        sch = {"type": "object", "dependentRequired": {"additional_passages": ["passage"]}}
        out = errs({"additional_passages": []}, sch)
        self.assertEqual(len(out), 1)
        self.assertIn("passage", out[0])
        self.assertEqual(errs({"additional_passages": [], "passage": "p"}, sch), [])


class Format(unittest.TestCase):
    def test_date(self):
        self.assertEqual(errs("2026-10-14", {"format": "date"}), [])
        self.assertEqual(len(errs("2026-13-45", {"format": "date"})), 1)
        self.assertEqual(len(errs("14/10/2026", {"format": "date"})), 1)

    def test_date_time_needs_an_offset(self):  # RFC 3339 date-time carries its offset
        for naive in ("2026-10-14T09:00:00", "2026-10-14 09:00", "2026-10-14T09:00:00.5"):
            with self.subTest(naive=naive):
                self.assertEqual(len(errs(naive, {"format": "date-time"})), 1)
        self.assertEqual(len(errs(dt.datetime(2026, 10, 14, 9, 0), {"format": "date-time"})), 1)  # TOML local

    def test_date_time(self):
        self.assertEqual(len(errs("2026-10-14", {"format": "date-time"})), 1)
        self.assertEqual(errs("2026-10-14T09:00:00Z", {"format": "date-time"}), [])
        self.assertEqual(errs("2026-10-14T09:00:00+10:00", {"format": "date-time"}), [])
        self.assertEqual(len(errs("not a date", {"format": "date-time"})), 1)

    def test_datetime_objects_are_converted_first(self):
        when = dt.datetime(2026, 10, 14, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=10)))
        self.assertEqual(errs(when, {"type": "string", "format": "date-time"}), [])
        self.assertEqual(errs({"d": dt.date(2026, 10, 14)},
                              {"properties": {"d": {"type": "string", "format": "date"}}}), [])

    def test_toml_local_time_in_enum_field_never_crashes(self):
        import tomllib
        doc = tomllib.loads("status = 09:00:00")
        self.assertIsInstance(doc["status"], dt.time)
        out = errs(doc, {"properties": {"status": {"enum": ["verified", "removed"]}}})
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("status: "), out)
        self.assertIn("09:00:00", out[0])

    def test_unserialisable_value_in_message_never_crashes(self):
        out = errs({"k": object()}, {"properties": {"k": {"const": 1}}})
        self.assertEqual(len(out), 1)
        self.assertEqual(len(errs(object(), {"enum": [1]})), 1)

    def test_show_never_raises(self):  # the docstring's promise holds
        circular: list = []
        circular.append(circular)
        for value in ({(1, 2): "tuple key"}, circular, float("nan"), object()):
            with self.subTest(value=type(value).__name__):
                self.assertIsInstance(S._show(value), str)
        out = errs({(1, 2): 1}, {"enum": [1]})
        self.assertEqual(len(out), 1)

    def test_unknown_format_raises(self):
        with self.assertRaises(S.SchemaError):
            errs("x", {"format": "email"})


class Unsupported(unittest.TestCase):
    def test_unknown_keyword_named(self):
        with self.assertRaises(S.SchemaError) as cm:
            errs({}, {"oneOf": []})
        self.assertIn("oneOf", str(cm.exception))

    def test_unknown_keyword_in_unreached_branch_still_raises(self):
        sch = {"allOf": [{"if": {"const": "never"}, "then": {"anyOf": []}}]}
        with self.assertRaises(S.SchemaError):
            errs("x", sch)

    def test_annotations_ignored(self):
        sch = {"$schema": "x", "$id": "y", "title": "t", "description": "d", "type": "null"}
        self.assertEqual(errs(None, sch), [])


class ShippedSchemas(unittest.TestCase):
    def test_both_load_and_are_fully_supported(self):
        for name in ("claim-ledger", "reader-value"):
            sch = S.load(name)
            self.assertIsInstance(sch, dict)
            S.check_schema(sch)

    def test_load_rejects_odd_names(self):
        for bad in ("../x", "nope", ""):
            with self.assertRaises(S.SchemaError):
                S.load(bad)

    def test_claim_ledger_generalised(self):
        sch = S.load("claim-ledger")
        claim = sch["$defs"]["claim"]["properties"]
        self.assertIn("human_signoff", claim)
        self.assertIn("signed_by", claim["human_signoff"]["required"])
        self.assertIn("approved_by_owner", claim["first_hand_scope"]["properties"])
        self.assertIn("source_snapshot", claim["binding"]["properties"])
        self.assertIn("regulated_class", claim)
        self.assertTrue(sch["$id"].startswith("https://github.com/littlebearapps/plainspoken/"))

    def test_source_file_pattern(self):
        sch = S.load("claim-ledger")
        pat = {"type": "string", "pattern": sch["properties"]["source_file"]["pattern"]}
        for ok in ("posts/a.md", "a.mdx", "x/y.txt", "page.html", "n.markdown"):
            self.assertEqual(errs(ok, pat), [], ok)
        for bad in ("/abs/a.md", "x/../a.md", "a.pdf", "../a.md"):
            self.assertEqual(len(errs(bad, pat)), 1, bad)

    def test_claim_id_pattern(self):
        pat = {"pattern": S.load("claim-ledger")["$defs"]["claim"]["properties"]["claim_id"]["pattern"]}
        for ok in ("C1", "GEO-007-C014", "post_3-a"):
            self.assertEqual(errs(ok, pat), [], ok)
        for bad in ("-a", "a-", "a--b", "a b", ""):
            self.assertEqual(len(errs(bad, pat)), 1, bad)

    def test_minimal_ledger_valid(self):
        ledger = {"schema_version": 1, "article_id": "a1", "article_slug": "a", "source_file": "posts/a.md",
                  "source_content_hash": "sha256:" + "0" * 64,
                  "checked_at": dt.datetime(2026, 10, 14, 9, 0, tzinfo=dt.timezone.utc),
                  "checked_by": "checker", "coverage_status": "complete", "claims": []}
        self.assertEqual(errs(ledger, S.load("claim-ledger")), [])

    def test_reader_value_decision_needs_decision(self):
        rv = {"schema_version": 1, "type": "decision", "primary_reader": "a small charity",
              "problem": "which tool to pick", "promised_outcome": "a clear choice",
              "original_value": "a worked comparison", "cta_excluded_confirmed": True}
        out = errs(rv, S.load("reader-value"))
        self.assertEqual(len(out), 1)
        self.assertIn("'decision'", out[0])
        self.assertEqual(errs(dict(rv, decision="tool A or B"), S.load("reader-value")), [])


if __name__ == "__main__":
    unittest.main()
