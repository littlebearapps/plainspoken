import unittest

from plainspoken.frontmatter import FrontmatterError, load

try:
    import yaml  # dev-only differential check; CI has no PyYAML and skips it
except ImportError:  # pragma: no cover
    yaml = None


class Supported(unittest.TestCase):
    def test_scalars_like_pyyaml(self):
        got = load('title: No\ndraft: yes\nn: 3\nf: 1.5\nd: 2026-10-01\nempty:\nnull_v: ~')
        self.assertEqual(got, {"title": False, "draft": True, "n": 3, "f": 1.5, "d": "2026-10-01",
                               "empty": None, "null_v": None})

    def test_quotes_and_escapes(self):
        got = load("title: 'It''s fine'\nsub: \"Say \\\"hi\\\" \\u00e9\"")
        self.assertEqual(got, {"title": "It's fine", "sub": 'Say "hi" é'})

    def test_block_scalars(self):
        self.assertEqual(load("d: |\n  one\n  two\n\n  para\nn: x"), {"d": "one\ntwo\n\npara\n", "n": "x"})
        self.assertEqual(load("d: >-\n  one\n  two\n\n  para\nn: x"), {"d": "one two\npara", "n": "x"})

    def test_sequence_of_mappings_both_indents(self):
        a = load('faqs:\n- question: "Q1?"\n  answer: "A1"\n- question: Q2\n  answer: A2\n')
        b = load('faqs:\n  - question: "Q1?"\n    answer: "A1"\n  - question: Q2\n    answer: A2\n')
        want = {"faqs": [{"question": "Q1?", "answer": "A1"}, {"question": "Q2", "answer": "A2"}]}
        self.assertEqual(a, want)
        self.assertEqual(b, want)

    def test_flow_list_comments_and_wrapping(self):
        got = load('tags: [a, "b, c", \'d\']\nx: 1 # c\n# full line\ny: "q" # c\nt: "wrapped\n  line"\n'
                   'z: plain\n  continued\nurl: https://e.com/a#frag')
        self.assertEqual(got, {"tags": ["a", "b, c", "d"], "x": 1, "y": "q", "t": "wrapped line",
                               "z": "plain continued", "url": "https://e.com/a#frag"})

    def test_flow_list_with_quotes_then_comment(self):
        self.assertEqual(load('tags: ["a", \'b\'] # c\nx: 1'), {"tags": ["a", "b"], "x": 1})
        self.assertEqual(load('tags: ["a]"] # c'), {"tags": ["a]"]})
        self.assertEqual(load("tags: [a, b] # it's"), {"tags": ["a", "b"]})
        with self.assertRaises(FrontmatterError):
            load('tags: ["a"] x')

    def test_nested(self):
        got = load("n:\n  a: 1\n  b:\n    c: [x]\n    d:\n      - e\n      - f: g\n        h: i")
        self.assertEqual(got, {"n": {"a": 1, "b": {"c": ["x"], "d": ["e", {"f": "g", "h": "i"}]}}})

    def test_empty_and_bom_and_crlf(self):
        self.assertEqual(load(""), {})
        self.assertEqual(load("\ufefftitle: T\r\nx: 1\r\n"), {"title": "T", "x": 1})


class Refused(unittest.TestCase):
    def test_unsupported_constructs_raise_with_line(self):
        cases = {
            "a: &x 1": "anchors",
            "a: {b: 1}": "flow mappings",
            "a:\n\t- x": "tab",
            "a: [1,\n 2]": "same line",
            "- x": "mapping",
            'a: "open': "unclosed",
            "a: 1\na: 2": "duplicate",
        }
        for text, needle in cases.items():
            with self.subTest(text=text):
                with self.assertRaises(FrontmatterError) as cm:
                    load(text)
                self.assertIn(needle, str(cm.exception))

    def test_nested_inline_sequence_refused(self):  # "- - a" was read as the string "- a"
        for text in ("a:\n  - - x\n", "a:\n  - -\n"):
            with self.subTest(text=text), self.assertRaisesRegex(FrontmatterError, "nested"):
                load(text)

    def test_deep_nesting_is_a_frontmatter_error(self):  # RecursionError escaped
        text = "".join(" " * i + "a:\n" for i in range(1500)) + " " * 1500 + "a: 1\n"
        with self.assertRaisesRegex(FrontmatterError, "nest"):
            load(text)

    def test_is_a_value_error(self):
        self.assertTrue(issubclass(FrontmatterError, ValueError))


@unittest.skipIf(yaml is None, "PyYAML not installed (dev-only differential check)")
class MatchesPyYAML(unittest.TestCase):
    def test_fixtures_match(self):
        import datetime
        from pathlib import Path

        def norm(v):
            if isinstance(v, (datetime.date, datetime.datetime)):
                return v.isoformat()
            if isinstance(v, dict):
                return {k: norm(x) for k, x in v.items()}
            if isinstance(v, list):
                return [norm(x) for x in v]
            return v

        for f in sorted((Path(__file__).parent / "fixtures" / "frontmatter").glob("*.md")):
            text = f.read_text(encoding="utf-8").replace("\r\n", "\n")
            fm = text[4:text.find("\n---", 3)]
            try:
                want = norm(yaml.safe_load(fm) or {})
            except yaml.YAMLError:
                continue
            with self.subTest(f=f.name):
                try:
                    self.assertEqual(load(fm), want)
                except FrontmatterError:
                    pass  # refusing is allowed; disagreeing isn't
