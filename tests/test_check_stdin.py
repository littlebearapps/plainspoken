import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.test_cli import cli

DRAFT = ("Moreover, the committee underscored the pivotal role of volunteers. Additionally, it highlighted the need "
         "to foster a robust sense of community across the suburb.\n")


class CheckStdin(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)

    def test_stdin_matches_file_lint_and_saves_nothing(self):
        (self.cwd / "d.md").write_text(DRAFT, encoding="utf-8")
        from_file = cli("check", "d.md", "--profile", "default", "--content-type", "social", "--json", "--no-save",
                        cwd=self.cwd)
        clean = Path(tempfile.mkdtemp())  # the file run records kaizen events; stdin runs in a folder of its own
        self.addCleanup(shutil.rmtree, clean, ignore_errors=True)
        from_stdin = cli("check", "-", "--profile", "default", "--json", cwd=clean, input=DRAFT)
        self.assertEqual(from_stdin.returncode, from_file.returncode, from_stdin.stderr)
        a, b = json.loads(from_file.stdout), json.loads(from_stdin.stdout)
        strip = lambda fs: [(f["rule"], f["severity"], f.get("line")) for f in fs]  # noqa: E731
        self.assertEqual(strip(b["findings"]), strip(a["findings"]))
        self.assertEqual(b["article"], "<stdin>")
        self.assertEqual(b["content_type"], "social")
        self.assertEqual(list(clean.iterdir()), [], "stdin lint must not write reports or kaizen events")

    def test_stdin_takes_no_record(self):  # #1: stdin records nothing anyway, so the flag changes nothing
        r = cli("check", "-", "--profile", "default", "--json", "--no-record", cwd=self.cwd, input=DRAFT)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(json.loads(r.stdout)["article"], "<stdin>")
        self.assertEqual(list(self.cwd.iterdir()), [])

    def test_stdin_long_text_defaults_to_article(self):
        long = " ".join(["Plain words here, said once and then said again."] * 40) + "\n"
        r = cli("check", "-", "--profile", "default", "--json", cwd=self.cwd, input=long)
        self.assertEqual(json.loads(r.stdout)["content_type"], "article", r.stderr)

    def test_stdin_content_type_flag_wins(self):
        r = cli("check", "-", "--profile", "default", "--json", "--content-type", "article", cwd=self.cwd,
                input=DRAFT)
        self.assertEqual(json.loads(r.stdout)["content_type"], "article", r.stderr)

    def _profile(self, body: str) -> str:
        path = self.cwd / "voice.toml"
        path.write_text(f'[profile]\nname = "voice"\n[thresholds]\n{body}\n', encoding="utf-8")
        return str(path)

    def _rule1(self, r) -> list[dict]:
        return [f for f in json.loads(r.stdout)["findings"] if f["rule"] == "1"]

    def test_stdin_social_keeps_a_stricter_profile_em_dash_cap(self):  # #104
        prof = self._profile("em_dash_max = 0")
        r = cli("check", "-", "--profile", prof, "--json", cwd=self.cwd, input="Thanks for checking — good catch.\n")
        self.assertEqual(json.loads(r.stdout)["content_type"], "social", r.stderr)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual([f["severity"] for f in self._rule1(r)], ["BLOCK"])
        self.assertIn("limit 0", self._rule1(r)[0]["message"])

    def test_stdin_social_cap_holds_against_a_looser_profile(self):  # #104
        prof = self._profile("em_dash_max = 5")
        r = cli("check", "-", "--profile", prof, "--json", cwd=self.cwd, input="I tried it — and it worked — mostly.\n")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("limit 1", self._rule1(r)[0]["message"])

    def test_stdin_en_dash_cap_from_profile(self):  # #104
        text = "We're open 9am–6pm, so call any time.\n"
        self.assertEqual(self._rule1(cli("check", "-", "--profile", "default", "--json", cwd=self.cwd, input=text)), [])
        prof = self._profile("en_dash_max = 0")
        r = cli("check", "-", "--profile", prof, "--json", cwd=self.cwd, input=text)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("en dash", self._rule1(r)[0]["message"])

    def test_stdin_with_out_is_refused(self):
        r = cli("check", "-", "--profile", "default", "--out", "x.json", cwd=self.cwd, input=DRAFT)
        self.assertEqual(r.returncode, 2)
        self.assertIn("stdin", r.stderr)

    def test_empty_stdin_is_an_input_error(self):
        r = cli("check", "-", "--profile", "default", cwd=self.cwd, input="")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
