import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from plainspoken import claims, schema
from tests._skills import REPO, SkillBasics, files

SKILL = REPO / "skills" / "claims"
REFS = SKILL / "references"
RUN_SPAN = re.compile(r"`RUN ([^`\n]+)`")
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
CORE = ("Never verify from memory", "Never add a statistic or a source", "never award your own pass")


def cli_help(*argv: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(REPO / "lib" / "run.py"), *argv, "--help"], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


class ClaimsSkill(SkillBasics, unittest.TestCase):
    NAME = "claims"
    REQUIRED = ("Core rules", "Steps", "Report")
    DRAFTING = True
    REFERENCES = ("evidence-rules.md", "ledger-format.md", "pinning.md", "regulated-claims.md", "claude-code.md")

    def test_manual_only_with_its_argument_hint(self):
        self.assertEqual(self.fm["disable-model-invocation"], "true")
        self.assertEqual(self.fm["argument-hint"], "<article> [--ledger PATH]")
        self.assertLessEqual(len(self.fm["description"]), 250)
        self.assertTrue(self.fm["description"].startswith("Verifies every number, quote, name and date"))

    def test_three_core_rules_in_the_first_40_lines(self):
        head = "\n".join(self.text.splitlines()[:40])
        for rule in CORE:
            self.assertIn(rule, " ".join(head.split()), rule)

    def test_every_run_call_names_a_real_subcommand_and_flag(self):
        seen = 0
        for f in files(self.NAME):
            for span in RUN_SPAN.findall(f.read_text(encoding="utf-8")):
                words = span.split()
                argv = words[:2] if words[0] == "claims" else words[:1]
                code, out = cli_help(*argv)
                self.assertEqual(code, 0, f"{f.name}: RUN {span}: {out[-300:]}")
                for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", span):
                    self.assertIn(flag, out, f"{f.name}: RUN {span}: {flag} isn't a flag of {' '.join(argv)}")
                seen += 1
        self.assertGreaterEqual(seen, 8)
        for sub in ("paths", "claims scaffold", "claims pin", "claims gaps", "claims hash", "claims checker-input",
                    "claims record", "claims status"):
            self.assertRegex(self.text, rf"`RUN {sub}\b", sub)

    def test_claims_calls_never_carry_the_profile_flag(self):  # argparse rejects it there with exit 2
        for f in files(self.NAME):
            for span in RUN_SPAN.findall(f.read_text(encoding="utf-8")):
                if span.startswith(("claims", "paths")):
                    self.assertNotIn("--plugin-profile", span, f"{f.name}: {span}")

    def test_referenced_files_exist(self):
        for f in files(self.NAME):
            text = f.read_text(encoding="utf-8")
            targets = set(LINK.findall(text)) | set(re.findall(r"`(references/[\w.-]+\.md)`", text))
            for target in targets:
                if target.startswith(("http://", "https://")):
                    continue
                base = SKILL if target.startswith("references/") and f.name == "SKILL.md" else f.parent
                self.assertTrue((base / target).resolve().is_file(), f"{f.name}: {target}")
        for name in self.REFERENCES:
            self.assertIn(f"references/{name}", self.text, name)

    def test_writes_only_its_own_dirs(self):
        tools = self.fm["allowed-tools"]
        for grant in ("Write(.plainspoken/sources/*)", "Write(.plainspoken/claims/*)", "Edit(.plainspoken/claims/*)"):
            self.assertIn(grant, tools)
        self.assertIn(".plainspoken/sources/", self.text)
        self.assertIn("sources_dir", self.text)

    def test_the_isolated_checker_decides(self):
        self.assertIn("claims-checker", self.text)
        self.assertIn("plainspoken:claims-checker", (REFS / "claude-code.md").read_text(encoding="utf-8"))
        self.assertIn("fresh context", self.text)
        self.assertRegex(self.text, r"`RUN claims record \S+ --from ")

    def test_passage_templates_use_single_quotes(self):  # "$1,000" expands to ",000" in double quotes
        for f in files(self.NAME):
            self.assertNotRegex(f.read_text(encoding="utf-8"), r'--passage\s+"', f.name)
        self.assertIn("'\\''", (REFS / "pinning.md").read_text(encoding="utf-8"))

    def test_only_the_replys_json_object_is_saved(self):  # parse_reply reads a bare reply whole
        for f in (SKILL / "SKILL.md", REFS / "claude-code.md"):
            text = " ".join(f.read_text(encoding="utf-8").split())
            self.assertNotIn("reply unchanged", text, f.name)
        flat = " ".join(self.text.split())
        self.assertIn("first `{` to its last `}`", flat)

    def step(self, n: int) -> str:
        body = self.text.split(f"\n{n}. **", 1)[1].split(f"\n{n + 1}. ", 1)[0].split("\n## ", 1)[0]
        return " ".join(body.split())

    def test_stale_ledger_goes_back_to_the_claims_not_the_hash(self):
        step6 = self.step(6)
        self.assertNotIn("back to step 5", step6)
        self.assertIn("back to steps 2 to 5", step6)
        self.assertIn("re-pin", step6)

    def test_an_edit_after_the_checker_goes_back_to_step_2(self):
        self.assertIn("go back to steps 2 to 6 for the claims you edited", self.step(7))

    def test_checked_at_comes_from_the_cli(self):
        self.assertIn("`RUN claims hash ARTICLE --stamp`", self.step(5))

    def test_lines_keep_the_file_width(self):
        body = self.text.split("\n---\n", 1)[1]
        for n, line in enumerate(body.splitlines(), start=1):
            self.assertLessEqual(len(line), 118, f"body line {n}: {line[:60]}…")

    def test_reference_lines_keep_the_file_width(self):
        for name in self.REFERENCES:
            for n, line in enumerate((REFS / name).read_text(encoding="utf-8").splitlines(), start=1):
                self.assertLessEqual(len(line), 118, f"{name}:{n}: {line[:60]}…")

    def test_output_schema_not_copied_from_the_rubric(self):
        for f in files(self.NAME):
            text = f.read_text(encoding="utf-8")
            self.assertNotIn('"suggested_fix"', text, f.name)
            self.assertNotIn("Output schema", text, f.name)


class ClaimsReferences(unittest.TestCase):
    def read(self, name: str) -> str:
        return (REFS / name).read_text(encoding="utf-8")

    def test_evidence_rules_cover_the_rubrics_rules(self):
        rubric = (REPO / "data" / "rubrics" / "claims.md").read_text(encoding="utf-8")
        section = rubric.split("## Evidence rules", 1)[1].split("\n## ", 1)[0]
        leads = re.findall(r"(?m)^- \*\*(.+?)\*\*", section)
        self.assertGreaterEqual(len(leads), 7)
        ours = self.read("evidence-rules.md")
        for lead in leads:
            self.assertIn(lead.rstrip("."), ours, lead)

    def test_ledger_format_lists_the_closed_status_list(self):
        statuses = schema.load("claim-ledger")["$defs"]["claim"]["properties"]["status"]["enum"]
        text = self.read("ledger-format.md")
        for s in statuses:
            self.assertRegex(text, rf"(?m)^\| `{s}` \|", s)
        for field in ("exclusions", "human_signoff", "first_hand_scope", "approved_by_owner", "coverage_status",
                      "source_content_hash", "additional_passages", "derivation"):
            self.assertIn(f"`{field}`", text, field)

    def test_annotated_example_is_a_valid_ledger(self):
        text = self.read("ledger-format.md")
        block = re.search(r"(?s)```toml\n(.*?)\n```", text).group(1)
        data = tomllib.loads(block)
        self.assertEqual(schema.validate(data, schema.load("claim-ledger")), [])
        self.assertIn("example.com", block)
        statuses = {c["status"] for c in data["claims"]}
        self.assertGreaterEqual(len(statuses), 4)
        with tempfile.TemporaryDirectory() as tmp:  # parses as a file too, not just as a string
            p = Path(tmp) / "example.claims.toml"
            p.write_text(block, encoding="utf-8")
            self.assertEqual(claims.load_ledger(p), data)

    def test_pinning_names_the_80_word_cut_and_the_refusal(self):
        text = self.read("pinning.md")
        self.assertIn("80 words", text)
        self.assertIn("never hand-write a hash", text.lower())
        self.assertRegex(text, r"`RUN claims recheck ")

    def test_regulated_claims_is_an_empty_extension_point(self):
        text = self.read("regulated-claims.md")
        self.assertIn("[claims]", text)
        self.assertIn("regulated_matrix", text)
        self.assertIn(".plainspoken/config.toml", text)
        self.assertIn("no legal advice", text.lower())
        shipped = [p for p in (REPO / "data").rglob("*") if "regulated" in p.name.lower()]
        self.assertEqual(shipped, [])
        self.assertIn("reportage rule", text)
        self.assertIn("sign-off rule", text)

    def test_claude_code_specifics(self):
        text = self.read("claude-code.md")
        self.assertIn("/plainspoken:claims", text)
        self.assertIn("one Bash call per command", text)
        self.assertIn("no shell loops", text.lower())
        self.assertIn("claims hash ARTICLE --stamp", text)  # the clock comes from the CLI
        self.assertIn("never a heredoc", text)
        self.assertIn("`; echo`", text)


if __name__ == "__main__":
    unittest.main()
