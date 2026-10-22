"""Engine-side rewrite graders: `rewrite.grade`, `rewrite.grade_many` and `eval rewrite` (Phase 6)."""
import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from plainspoken import __main__ as cli_main
from plainspoken import rewrite
from plainspoken.profile import default as default_profile

# Plain, varied sentences: no lint BLOCK on the default profile, two em dashes, the source's numbers only.
CLEAN = ("The hall on Albert Road opens at 6 on Thursday, and the first talk starts half an hour later. "
         "Bring a chair if you can — we never have quite enough. "
         "Last year about 2500 people came through over the weekend, which was more than we planned for, so this "
         "time there are extra volunteers on the door and a second urn for tea. "
         "Parking is tight. The station is a short walk away — turn left out of the gate and follow the river.\n")
SOURCE = ("Doors open at 6 on Thursday at the Albert Road hall. Around 2,500 visitors came last year.\n")


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestGrade(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.profile = default_profile()

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        p = self.d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_grade_pass(self):
        g = rewrite.grade(self.write("draft.md", CLEAN), self.write("source.md", SOURCE), self.profile, "article")
        self.assertEqual(g["blocks"], [])
        self.assertEqual(g["em_dashes"], 2)
        self.assertEqual(g["em_dash_cap"], 3)
        self.assertEqual(g["new_numbers"], [])
        self.assertGreater(g["words"], 60)
        self.assertEqual(g["verdict"], "PASS")

    def test_grade_block_word(self):
        draft = self.write("draft.md", CLEAN.replace("Parking is tight.", "Parking is a pivotal concern."))
        g = rewrite.grade(draft, self.write("source.md", SOURCE), self.profile, "article")
        self.assertIn("2", g["blocks"])
        self.assertEqual(g["verdict"], "FAIL")

    def test_grade_em_dash_over_cap(self):
        text = CLEAN.replace("Parking is tight.", "Parking is tight — very tight — on the day.")
        g = rewrite.grade(self.write("draft.md", text), self.write("source.md", SOURCE), self.profile, "article")
        self.assertEqual((g["em_dashes"], g["em_dash_cap"]), (4, 3))
        self.assertEqual(g["verdict"], "FAIL")
        social = rewrite.grade(self.write("post.md", CLEAN), self.write("source.md", SOURCE), self.profile, "social")
        self.assertEqual((social["em_dashes"], social["em_dash_cap"]), (2, 1))  # the social cap, from the ruleset
        self.assertEqual(social["verdict"], "FAIL")

    def test_grade_em_dash_cap_holds_with_rule_1_off(self):
        """The cap is the grader's own check, so a profile that disables lint rule 1 still fails on it."""
        text = CLEAN.replace("Parking is tight.", "Parking is tight — very tight — on the day.")
        off = replace(self.profile, rules_disabled=frozenset({"1"}))
        g = rewrite.grade(self.write("draft.md", text), self.write("source.md", SOURCE), off, "article")
        self.assertNotIn("1", g["blocks"])
        self.assertEqual(g["verdict"], "FAIL")

    def test_grade_new_number(self):
        source = self.write("source.md", "We sold 2,500 tickets across 4 nights.\n")
        draft = self.write("draft.md", CLEAN.replace("about 2500 people", "about 2500 people (40% of them locals)"))
        g = rewrite.grade(draft, source, self.profile, "article")
        # 2500 is the source's 2,500; 40 is new even though the source has a 4; 6 isn't in this source either.
        self.assertEqual(g["new_numbers"], ["6", "40"])
        self.assertEqual(g["verdict"], "FAIL")

    def test_numbers_normalise_commas_only(self):
        self.assertEqual(rewrite.numbers("2,500 and 2500, 3.2, v1.4.0, 40% and 4."), ["2,500", "2500", "3.2",
                                                                                      "1.4.0", "40", "4"])
        self.assertEqual(rewrite.number_key("12,000"), rewrite.number_key("12000"))
        self.assertNotEqual(rewrite.number_key("3.2"), rewrite.number_key("32"))

    def test_reformatted_number_is_the_same_number(self):
        """Thousands separators are formatting: 3,200 and 3200 are one number either way round. A comma that isn't
        a thousands separator (4,7 or 1,0) is a list, not a reformatted 47 or 10."""
        self.assertEqual(rewrite.numbers("1,0 and 4,7, then 12,500.5 and 1,000,000"),
                         ["1", "0", "4", "7", "12,500.5", "1,000,000"])
        self.assertEqual(rewrite.number_key("12,500.5"), "12500.5")
        self.assertEqual(rewrite.number_key("1,000,000"), rewrite.number_key("1000000"))
        for src, draft in (("We ran 3,200 km.", "We ran 3200 km."), ("We ran 3200 km.", "We ran 3,200 km."),
                           ("It cost 12000 dollars.", "It cost 12,000 dollars.")):
            g = rewrite.grade(self.write("draft.md", draft + "\n"), self.write("source.md", src + "\n"),
                              self.profile, "article")
            self.assertEqual(g["new_numbers"], [], (src, draft))
        g = rewrite.grade(self.write("draft.md", "Room 1,0 is shut.\n"), self.write("source.md", "Room 10 is shut.\n"),
                          self.profile, "article")
        self.assertEqual(g["new_numbers"], ["1", "0"])

    def test_grade_reads_each_file_once(self):
        draft, source = self.write("draft.md", CLEAN), self.write("source.md", SOURCE)
        reads: list[str] = []
        real_text, real_bytes = Path.read_text, Path.read_bytes

        def read_text(p, *a, **kw):
            reads.append(Path(p).name)
            return real_text(p, *a, **kw)

        def read_bytes(p, *a, **kw):
            reads.append(Path(p).name)
            return real_bytes(p, *a, **kw)

        with mock.patch.object(Path, "read_text", read_text), mock.patch.object(Path, "read_bytes", read_bytes):
            code, _, err = run_cli("eval", "rewrite", str(draft), "--source", str(source), "--profile", "default")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(n for n in reads if n in ("draft.md", "source.md")), ["draft.md", "source.md"])

    def test_grade_without_source_skips_numbers(self):
        g = rewrite.grade(self.write("draft.md", CLEAN), None, self.profile, "article")
        self.assertEqual(g["new_numbers"], [])
        self.assertIsNone(g["source"])
        self.assertEqual(g["verdict"], "PASS")

    def test_grade_many_pairs_by_stem(self):
        drafts, sources = self.d / "drafts", self.d / "sources"
        self.write("drafts/a.md", CLEAN)
        self.write("drafts/b.md", CLEAN.replace("Parking is tight.", "Parking is a pivotal concern."))
        self.write("sources/a.md", SOURCE)
        self.write("sources/b.txt", SOURCE)
        rows = rewrite.grade_many(drafts, sources, self.profile, "article")
        self.assertEqual([(Path(r["draft"]).name, r["verdict"]) for r in rows], [("a.md", "PASS"), ("b.md", "FAIL")])
        self.assertEqual(Path(rows[1]["source"]).name, "b.txt")
        self.write("drafts/c.md", CLEAN)
        with self.assertRaisesRegex(ValueError, "c.md"):
            rewrite.grade_many(drafts, sources, self.profile, "article")
        self.assertEqual(len(rewrite.grade_many(drafts, None, self.profile, "article")), 3)

    def test_grade_many_recursive(self):
        drafts = self.d / "drafts"
        self.write("drafts/model-a/one.md", CLEAN)
        self.write("drafts/model-b/two.md", CLEAN)
        self.write("drafts/.hidden/three.md", CLEAN)
        self.assertEqual(rewrite.grade_many(drafts, None, self.profile, "article"), [])  # not recursive by default
        rows = rewrite.grade_many(drafts, None, self.profile, "article", recursive=True)
        self.assertEqual([Path(r["draft"]).relative_to(drafts).as_posix() for r in rows],
                         ["model-a/one.md", "model-b/two.md"])

    def test_cli_json(self):
        draft, source = self.write("draft.md", CLEAN), self.write("source.md", SOURCE)
        code, out, err = run_cli("eval", "rewrite", str(draft), "--source", str(source), "--profile", "default",
                                 "--json")
        self.assertEqual(code, 0, err)
        g = json.loads(out)
        self.assertEqual(g["verdict"], "PASS")
        for key in ("blocks", "em_dashes", "em_dash_cap", "new_numbers", "words", "verdict"):
            self.assertIn(key, g)
        bad = self.write("bad.md", CLEAN.replace("about 2500 people", "about 2600 people"))
        code, out, _ = run_cli("eval", "rewrite", str(bad), "--source", str(source), "--profile", "default",
                               "--content-type", "social")
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)
        self.assertIn("2600", out)

    def test_cli_bad_input(self):
        source = self.write("source.md", SOURCE)
        code, _, err = run_cli("eval", "rewrite", str(self.d / "missing.md"), "--profile", "default")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("plainspoken: eval rewrite: "), err)
        code, _, err = run_cli("eval", "rewrite", str(source), "--source", str(self.d / "nope.md"),
                               "--profile", "default")
        self.assertEqual(code, 2)
        self.assertIn("nope.md", err)
        code, _, err = run_cli("eval", "rewrite", str(source), "--profile", "no-such-profile")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)
        self.write("binary.md", "")
        (self.d / "binary.md").write_bytes(b"\xff\xfe\x00bad")
        code, _, err = run_cli("eval", "rewrite", str(self.d / "binary.md"), "--profile", "default")
        self.assertEqual(code, 2)
        self.assertIn("binary.md: not UTF-8 text", err)
        code, _, err = run_cli("eval", "rewrite", str(source), "--source", str(self.d / "binary.md"),
                               "--profile", "default")
        self.assertEqual(code, 2)
        self.assertIn("binary.md: not UTF-8 text", err)



class NumbersInWords(unittest.TestCase):
    """Numbers written as words count on both sides of the number check (#33)."""

    def words(self, text: str) -> list[tuple[str, int]]:
        return rewrite.word_numbers(text)

    def test_the_documented_set(self):
        self.assertEqual(self.words("seven in every ten"), [("seven", 7), ("ten", 10)])
        self.assertEqual(self.words("Two hundred and twelve came in; twenty-one were left"),
                         [("Two hundred and twelve", 212), ("twenty-one", 21)])
        self.assertEqual(self.words("a hundred, an eleven-year-old, a dozen eggs, two dozen, zero, nineteen"),
                         [("a hundred", 100), ("eleven", 11), ("a dozen", 12), ("two dozen", 24), ("zero", 0),
                          ("nineteen", 19)])
        self.assertEqual(self.words("twelve thousand five hundred, then one hundred and five"),
                         [("twelve thousand five hundred", 12500), ("one hundred and five", 105)])
        self.assertEqual(self.words("seven and ten, twenty twenty, fifty-five"),
                         [("seven", 7), ("ten", 10), ("twenty", 20), ("twenty", 20), ("fifty-five", 55)])

    def test_not_numbers_here(self):
        """Ordinals, fractions, plurals, a scale word with no count of its own, bare "one" and words that only
        contain a number word."""
        self.assertEqual(self.words("the second Saturday, half the toasters, hundreds of them, dozens, tens of "
                                    "thousands, 2 million, a few thousand, no one, the one I like, one of them, "
                                    "someone, often, money, nineteenth, tension, bone"), [])

    def test_figures_merge_digits_and_words_in_order(self):
        self.assertEqual(rewrite.figures("seven in every ten, 3 out of 4, then 71% and 4,7 and 2,500 per cent"),
                         [("seven", "7", "10"), ("ten", "10", None), ("3", "3", "4"), ("4", "4", None),
                          ("71", "71", "100"), ("4", "4", None), ("7", "7", None), ("2,500", "2500", "100")])
        self.assertEqual(rewrite.number_key("twenty-one"), "21")
        self.assertEqual(rewrite.numbers("seven and 7"), ["7"], "numbers() stays digits-only")

    def test_words_and_digits_are_one_number_either_way_round(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [f.unlink() for f in d.iterdir()] and d.rmdir())
        for src, draft, new in (("Seven of the 10 came back.", "Seven in every ten came back.", []),
                                ("7 of the ten came back.", "seven of the 10 came back.", []),
                                ("Two hundred and twelve came in.", "212 came in.", []),
                                ("212 came in.", "Two hundred and twelve came in, and nine left.", ["nine"])):
            (d / "s.md").write_text(src + "\n", encoding="utf-8")
            (d / "d.md").write_text(draft + "\n", encoding="utf-8")
            g = rewrite.grade(d / "d.md", d / "s.md", default_profile(), "article")
            self.assertEqual(g["new_numbers"], new, (src, draft))


class DerivedNumbers(unittest.TestCase):
    """A number worked out from the source's own numbers is derived, listed, and not new (#33)."""
    SOURCE = ("So far 212 items have come in and 151 were fixed. Ray worked 31 years for the railways. Each fixed item "
              "keeps roughly a kilo out of landfill.\n")

    def test_derivation_rules(self):
        known = ["212", "151", "31"]
        cases = {("150", None): "≈ 151",                       # a rounding, under 1% off
                 ("30", None): "≈ 31",                         # 3% off
                 ("200", None): "≈ 212",                       # 5.7% off: still a rounding
                 ("363", None): "= 212 + 151",
                 ("61", None): "= 212 − 151",
                 ("4681", None): "= 151 × 31",
                 ("1.4", None): "≈ 212 / 151",                 # a ratio, rounded to the piece's own decimals
                 ("71", "100"): "≈ 100 × 151 / 212",           # 71%
                 ("7", "10"): "≈ 10 × 151 / 212",              # seven in every ten
                 ("60", None): None,                           # 61 rounded: a combination isn't rounded
                 ("7", None): None,                            # a whole-number ratio has to be exact
                 ("71", None): None,                           # 71 without a % isn't a percentage
                 ("913", None): None,
                 ("1.4.0", None): None}                        # a version isn't a value
        for (n, base), how in cases.items():
            self.assertEqual(rewrite.derivation(n, known, base), how, (n, base))
        self.assertEqual(rewrite.derivation("20", ["19"]), "≈ 19")
        self.assertIsNone(rewrite.derivation("3000", ["2500"]), "20% off is not a rounding")
        self.assertEqual(rewrite.derivation("12.5", ["12.45"]), "≈ 12.45")
        self.assertIsNone(rewrite.derivation("302", ["151"]), "a number isn't combined with itself")
        self.assertEqual(rewrite.derivation("1.40", ["1.4"]), "= 1.4", "the same value, written another way")

    def test_grade_lists_derived_apart_from_new(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [f.unlink() for f in d.iterdir()] and d.rmdir())
        (d / "s.md").write_text(self.SOURCE, encoding="utf-8")
        piece = ("The 151 fixes have kept something like 150 kilos out of the tip, about seven in every ten of the "
                 "items people brought in.\n")
        (d / "d.md").write_text(piece, encoding="utf-8")
        g = rewrite.grade(d / "d.md", d / "s.md", default_profile(), "article")
        self.assertEqual(g["new_numbers"], [])
        self.assertEqual(g["derived_numbers"], [{"number": "150", "from": "≈ 151"},
                                                {"number": "seven", "from": "≈ 10 × 151 / 212"},
                                                {"number": "ten", "from": "base of the rate seven in ten"}])
        self.assertEqual(g["verdict"], "PASS", "derived numbers don't fail a rewrite")
        text = rewrite.summarise(g)
        self.assertIn("  new numbers: none\n", text)
        self.assertIn("derived numbers (from the source's own, not counted as new): 150 ≈ 151, seven ≈ 10 × 151 / 212",
                      text)
        (d / "d.md").write_text(piece.replace("about seven", "about 913, or seven"), encoding="utf-8")
        g = rewrite.grade(d / "d.md", d / "s.md", default_profile(), "article")
        self.assertEqual(g["new_numbers"], ["913"])
        self.assertEqual(g["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
