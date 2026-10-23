import re
import subprocess
import sys
import tomllib
import unittest

from plainspoken import modules, reader_value
from tests._skills import REPO, SkillBasics, files

SKILL = REPO / "skills" / "reader-value"
REFS = SKILL / "references"
RUN_SPAN = re.compile(r"`RUN ([^`\n]+)`")
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
CORE = ("defined benefit to its reader before drafting", "The sales CTA never counts as reader value",
        "park the piece and say why")
GROUPS = ("claims", "reader-value")  # subcommand groups: their --help lives one level down


def cli_help(*argv: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(REPO / "lib" / "run.py"), *argv, "--help"], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def flat(text: str) -> str:
    return " ".join(text.split())


class ReaderValueSkill(SkillBasics, unittest.TestCase):
    NAME = "reader-value"
    REQUIRED = ("Core rules", "Outline mode", "Deliver mode", "Report")
    DRAFTING = True
    REFERENCES = ("contract.md", "outline-gate.md", "delivery-gate.md", "action-modules.md", "claude-code.md")

    def test_manual_only_with_its_argument_hint(self):
        self.assertEqual(self.fm["disable-model-invocation"], "true")
        self.assertEqual(self.fm["argument-hint"], "outline|deliver <file>")
        self.assertLessEqual(len(self.fm["description"]), 250)
        self.assertIn("Manual only", self.fm["description"])

    def test_three_core_rules_in_the_first_40_lines(self):
        head = flat("\n".join(self.text.splitlines()[:40]))
        for rule in CORE:
            self.assertIn(rule, head, rule)
        for reason in ("search volume", "competitor", "keyword", "CTA"):
            self.assertIn(reason, head, reason)

    def test_every_run_call_names_a_real_subcommand_and_flag(self):
        seen = 0
        for f in files(self.NAME):
            for span in RUN_SPAN.findall(f.read_text(encoding="utf-8")):
                words = span.split()
                argv = words[:2] if words[0] in GROUPS else words[:1]
                code, out = cli_help(*argv)
                self.assertEqual(code, 0, f"{f.name}: RUN {span}: {out[-300:]}")
                for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", span):
                    self.assertIn(flag, out, f"{f.name}: RUN {span}: {flag} isn't a flag of {' '.join(argv)}")
                seen += 1
        self.assertGreaterEqual(seen, 4)
        for sub in ("reader-value template", "reader-value validate", "reader-value modules"):
            self.assertRegex(self.text, rf"`RUN {sub}\b", sub)

    def test_run_calls_never_carry_the_profile_flag_or_double_quotes(self):
        for f in files(self.NAME):
            for span in RUN_SPAN.findall(f.read_text(encoding="utf-8")):
                self.assertNotIn("--plugin-profile", span, f"{f.name}: {span}")  # argparse rejects it: exit 2
                self.assertNotIn('"', span, f"{f.name}: {span}")  # user text in single quotes ($ stays literal)

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

    def test_writes_only_its_own_dir_and_the_reviewer_reply(self):
        tools = self.fm["allowed-tools"]
        self.assertIn("Write(.plainspoken/reader-value/*)", tools)
        self.assertIn("Edit(.plainspoken/reader-value/*)", tools)
        self.assertIn("Write(.plainspoken/reports/*.delivery-reply.json)", tools)
        others = re.findall(r"(?:Write|Edit)\((?!\.plainspoken/reader-value/)[^)]*\)", tools)
        self.assertEqual(others, ["Write(.plainspoken/reports/*.delivery-reply.json)"])
        self.assertIn(".plainspoken/reader-value/", self.text)

    def test_both_modes_and_their_outcomes(self):
        outline = self.text.split("## Outline mode", 1)[1].split("\n## ", 1)[0]
        deliver = self.text.split("## Deliver mode", 1)[1].split("\n## ", 1)[0]
        self.assertRegex(outline, r"`RUN reader-value template`")
        self.assertRegex(outline, r"`RUN reader-value validate ")
        self.assertIn("PARKED", outline)
        self.assertRegex(deliver, r"`RUN reader-value validate ")  # a missing or broken contract never passes
        self.assertRegex(deliver, r"`RUN reader-value modules ")
        self.assertRegex(deliver, r"`RUN reader-value deliver-input ")
        self.assertRegex(deliver, r"`RUN reader-value deliver '[^`]*--from")
        self.assertIn("references/delivery-gate.md", deliver)
        self.assertIn("INCOMPLETE", deliver)
        self.assertIn("line", deliver)
        self.assertIn("never the gate", flat(deliver))

    def test_contract_named_after_the_draft_in_both_modes(self):  # brief stem vs draft stem
        outline = flat(self.text.split("## Outline mode", 1)[1].split("\n## ", 1)[0])
        deliver = flat(self.text.split("## Deliver mode", 1)[1].split("\n## ", 1)[0])
        self.assertIn("named from the draft's path, not from FILE", outline)
        self.assertIn("ask the user where the draft will live", outline)
        self.assertIn("`.plainspoken/reader-value/hot-water.reader-value.toml`", outline)
        self.assertIn("ask the user for the contract's path", deliver)
        self.assertIn("don't search the directory", deliver)
        self.assertIn("name the contract after the draft", flat(self.text))

    def test_failed_validation_is_incomplete_not_parked(self):
        outline = flat(self.text.split("## Outline mode", 1)[1].split("\n## ", 1)[0])
        rounds = outline.split("After three rounds that still fail,", 1)[1].split(" 5. ", 1)[0]
        self.assertIn("reader-value outline: INCOMPLETE", rounds)
        self.assertNotIn("park the piece", rounds)
        self.assertIn("`reader-value outline: INCOMPLETE`", flat(self.text.split("## Report", 1)[1]))

    def test_template_placeholders_are_not_ready(self):  # the template validates clean as printed
        self.assertIn("still holding the template's invented value", flat(self.text))

    def test_apostrophe_escape_shown(self):
        self.assertIn("'\\''", self.text)

    def test_no_offer_lookalike_names(self):  # examples never read like a real sales offer
        for f in files(self.NAME):
            text = f.read_text(encoding="utf-8").lower()
            for offer in ("book a call", "free audit", "discovery call"):
                self.assertNotIn(offer, text, f.name)

    def test_figures_go_to_the_claim_ledger(self):
        for f in (SKILL / "SKILL.md", REFS / "contract.md"):
            text = flat(f.read_text(encoding="utf-8"))
            self.assertIn("claim ledger", text, f.name)
            self.assertIn("/plainspoken:claims", text, f.name)

    def test_cta_phrases_stay_in_data(self):  # ban-list-style lists live in data/claims.toml and the checker
        shipped = reader_value.shipped_cta_phrases() + reader_value.shipped_vague_phrases()
        for f in files(self.NAME):
            text = f.read_text(encoding="utf-8")
            found = {p for p in shipped if re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text, re.I)}
            self.assertLessEqual(len(found), 3, f"{f.name} repeats the shipped list: {sorted(found)}")
        contract = flat((REFS / "contract.md").read_text(encoding="utf-8"))
        self.assertIn("[reader_value]", contract)
        self.assertIn("cta_phrases", contract)
        self.assertIn(".plainspoken/config.toml", contract)

    def test_no_real_domains(self):
        for f in files(self.NAME):
            for host in re.findall(r"\b[\w-]+\.(?:com|net|org|au|st|io|co)\b", f.read_text(encoding="utf-8")):
                self.assertIn(host, ("example.com", "example.org"), f"{f.name}: {host}")


class ReaderValueReferences(unittest.TestCase):
    def read(self, name: str) -> str:
        return (REFS / name).read_text(encoding="utf-8")

    def test_contract_examples_are_valid_contracts(self):
        blocks = re.findall(r"(?s)```toml\n(.*?)\n```", self.read("contract.md"))
        contracts = [b for b in blocks if "schema_version" in b]
        self.assertGreaterEqual(len(contracts), 2)
        types = set()
        for block in contracts:
            data = tomllib.loads(block)
            self.assertEqual(reader_value.validate(data, reader_value.shipped_cta_phrases(),
                                                   reader_value.shipped_vague_phrases()), [], block[:80])
            types.add(data["type"])
        self.assertTrue(types & {"evidence_trail", "historical_interpretation"}, types)
        self.assertTrue(types & {"task", "implementation", "debugging_path", "self_check"}, types)

    def test_contract_lists_every_field_and_type(self):
        schema = __import__("plainspoken.schema", fromlist=["load"]).load("reader-value")
        text = self.read("contract.md")
        for field in schema["properties"]:
            self.assertIn(f"`{field}`", text, field)
        for t in schema["properties"]["type"]["enum"]:
            self.assertIn(f"`{t}`", text, t)

    def test_outline_gate_names_the_park_reasons(self):
        text = flat(self.read("outline-gate.md"))
        for reason in ("search volume", "competitor", "keyword", "CTA", "PARKED"):
            self.assertIn(reason, text, reason)

    def test_delivery_gate_checklist(self):
        text = flat(self.read("delivery-gate.md"))
        for item in ("promised outcome", "without further research", "effort", "risk", "success signal",
                     "stop", "disguised pitch", "original value", "never the gate"):
            self.assertIn(item, text, item)

    def test_delivery_example_is_a_complete_report(self):  # matches SKILL.md's Report section
        text = self.read("delivery-gate.md")
        block = re.search(r"(?s)```text\n(reader-value: FAIL.*?)\n```", text).group(1)
        for part in ("Module findings", "Claims to ledger", "Record:", "Contract:"):
            self.assertIn(part, block, part)
        self.assertEqual(block.splitlines()[-1], "Checked against the contract only. You decide what to publish.")
        skill_last = re.search(r"The last line, exactly: `([^`]+)`", (SKILL / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(block.splitlines()[-1], skill_last.group(1))

    def test_action_module_examples_pass_the_checker(self):
        text = self.read("action-modules.md")
        blocks = re.findall(r"(?s)```markdown\n(.*?)\n```", text)
        self.assertGreaterEqual(len(blocks), 3)
        names = set()
        for block in blocks:
            self.assertEqual(modules.check(block), [], block[:80])
            names |= set(re.findall(r"<!-- module:([\w-]+) -->", block))
        self.assertEqual(names, set(modules.NAMES))
        self.assertIn("section number", text)
        self.assertRegex(text, r"`RUN reader-value modules ")

    def test_ready_example_is_not_the_templates_scenario(self):
        text = self.read("outline-gate.md")
        ready = [para for para in text.split("\n\n") if "READY" in para]
        self.assertEqual(len(ready), 1)
        template = tomllib.loads((REPO / "templates" / "reader-value.toml").read_text(encoding="utf-8"))
        for words in ("sink", "drain", "trap cap", template["success_signal"].lower()):
            self.assertNotIn(words, ready[0].lower(), words)

    def test_only_the_isolated_reviewer_passes(self):  # the producer never awards its own pass
        text = flat((SKILL / "SKILL.md").read_text(encoding="utf-8"))
        deliver = text.split("## Deliver mode", 1)[1].split("## Report", 1)[0]
        report = text.split("## Report", 1)[1]
        self.assertIn("`delivery-checker` agent in a fresh context", deliver)
        self.assertIn("no hint about who wrote it", deliver)
        self.assertIn("--reviewer delivery-checker", deliver)  # review fix 1: the label is explicit, no default
        self.assertIn("--reviewer self-check", deliver)
        self.assertNotIn("--self-check", text)
        self.assertRegex(deliver, r"`RUN reader-value status '")  # the reader that notices a stale record
        self.assertIn("never PASS", deliver)
        self.assertIn("You never award your own delivery pass", text)
        self.assertIn("`Reviewer: the isolated delivery-checker, in a fresh context.`", report)
        self.assertIn("`Self-check: the writer's reading of the draft against the contract, not an independent "
                      "review.`", report)
        block = re.search(r"(?s)```text\n(reader-value: FAIL.*?)\n```", self.read("delivery-gate.md")).group(1)
        self.assertTrue(block.splitlines()[1].startswith(("Reviewer:", "Self-check:")), block.splitlines()[1])
        readme = flat((REPO / "README.md").read_text(encoding="utf-8"))
        self.assertIn("delivery-checker", readme)
        self.assertIn("self-check", readme)
        self.assertIn("plainspoken:delivery-checker", self.read("claude-code.md"))
        contract = flat((REPO / "docs" / "report-contract.md").read_text(encoding="utf-8"))
        self.assertIn("`reviewer` is the caller's declaration, not a proof", contract)
        self.assertIn("reader-value status", contract)

    def test_delivery_example_is_one_scenario(self):  # no hot-water paths in a kitchen-sink example
        text = self.read("delivery-gate.md").split("## Example", 1)[1]
        self.assertNotIn("hot water", text)
        self.assertNotIn("hot-water", text)
        stems = {re.sub(r"-[0-9a-f]{8}$", "", s) for s in
                 re.findall(r"([\w-]+)\.(?:reader-value\.toml|claims\.toml|delivery\.json|md)\b", text)}
        self.assertEqual(stems, {"kitchen-sink"})
        self.assertIn("```toml", text)  # the contract and the report are separate blocks
        for name in reader_value.DELIVERY_ITEMS:
            self.assertIn(f"- {name}: ", text)

    def test_history_reading_is_labelled_as_plainspokens(self):  # an interpretation, not ported text
        text = flat(self.read("delivery-gate.md"))
        self.assertNotIn("A history piece meets this item with its evidence trail", text)
        self.assertIn("plainspoken's reading, not the ported text", text)

    def test_lines_keep_the_file_width(self):
        body = (SKILL / "SKILL.md").read_text(encoding="utf-8").split("\n---\n", 1)[1]
        for n, line in enumerate(body.splitlines(), start=1):
            self.assertLessEqual(len(line), 118, f"body line {n}: {line[:60]}…")

    def test_reference_lines_keep_the_file_width(self):
        for name in ReaderValueSkill.REFERENCES:
            for n, line in enumerate((REFS / name).read_text(encoding="utf-8").splitlines(), start=1):
                self.assertLessEqual(len(line), 118, f"{name}:{n}: {line[:60]}…")

    def test_claude_code_specifics(self):
        text = self.read("claude-code.md")
        self.assertIn("/plainspoken:reader-value outline", text)
        self.assertIn("/plainspoken:reader-value deliver", text)
        flat = " ".join(text.split())
        self.assertNotIn("one Bash call per command", text)  # #92: as #78 for claims, chains of run.py calls are fine
        self.assertIn("`paths` and `deliver-input` in one chain", flat)
        self.assertIn("stops at the first call that fails", flat)
        self.assertIn("No `;`, no pipes, no shell loops", flat)


if __name__ == "__main__":
    unittest.main()
