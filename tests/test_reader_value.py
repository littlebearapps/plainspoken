"""The reader-value contract: loading (TOML, JSON, or a fenced block in markdown), validation (schema + CTA-shaped
value + vague original value), the shipped + project CTA phrases, the template, and the `reader-value` CLI group.

Ported from a blog workspace's nine contract tests, with invented examples."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plainspoken import reader_value
from plainspoken.reader_value import ContractError

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / "lib" / "run.py"
FIX = REPO / "tests" / "fixtures" / "reader_value"
TEMPLATE = REPO / "templates" / "reader-value.toml"
PROJECT_CTA = "Book a Free Strategy Call"  # shipped `book a` also catches it; PROJECT_ONLY proves the merge
PROJECT_ONLY = "Claim the Acme Strategy Pass"


def shipped() -> tuple[str, ...]:
    return reader_value.shipped_cta_phrases()


def with_project() -> tuple[str, ...]:
    return reader_value.merge_phrases(shipped(), [PROJECT_CTA, PROJECT_ONLY])


def vague() -> tuple[str, ...]:
    return reader_value.shipped_vague_phrases()


def check(contract: dict, cta: tuple[str, ...] | None = None) -> list[dict]:
    return reader_value.validate(contract, with_project() if cta is None else cta, vague())


def task() -> dict:
    """A valid task contract (an invented plumbing how-to)."""
    return {
        "schema_version": 1,
        "type": "task",
        "primary_reader": "A homeowner with a slow-draining kitchen sink",
        "problem": "Can't tell whether a slow drain is a do-it-yourself job or needs a plumber",
        "promised_outcome": "A cleared drain, or a clear sign that it's a job for a licensed plumber",
        "first_action": {"verb": "remove", "object": "the sink strainer and trap cap",
                         "location": "under the kitchen sink"},
        "effort": "about 30 minutes",
        "prerequisites": ["a bucket", "a sink plunger"],
        "success_signal": "A full sink empties in under a minute",
        "stop_condition": "Stop and call a licensed plumber if water backs up into another fixture",
        "original_value": "A three-check triage drawn from the call-outs Acme Plumbing attended last winter",
        "cta_excluded_confirmed": True,
    }


def messages(findings: list[dict]) -> str:
    return "\n".join(f["message"] for f in findings)


class ValidContracts(unittest.TestCase):
    def test_task_contract_valid(self):
        self.assertEqual(check(task()), [])

    def test_evidence_trail_without_checklist_is_valid(self):
        """History is never forced into steps."""
        contract = {
            "schema_version": 1,
            "type": "evidence_trail",
            "primary_reader": "A resident curious about the old Example Street tram depot",
            "problem": "The depot's 1920s history is scattered across council minutes and newspapers",
            "promised_outcome": "Knows what the depot was, what survives of it, and where the records are",
            "original_value": "A source trail assembled from the council's building files and two local papers",
            "evidence_trail": ["council building permit file, 1924", "The Example Gazette, 3 May 1925, p. 4",
                               "walk: the surviving tram tracks in the depot yard"],
            "cta_excluded_confirmed": True,
        }
        self.assertEqual(check(contract), [])

    def test_historical_interpretation_needs_evidence_trail_not_first_action(self):
        contract = {
            "schema_version": 1,
            "type": "historical_interpretation",
            "primary_reader": "A local historian",
            "problem": "Why the tram depot closed in 1956 is disputed",
            "promised_outcome": "Can weigh the two accounts of the depot's closure",
            "original_value": "A side-by-side reading of the council minutes and the union's newsletter",
            "cta_excluded_confirmed": True,
        }
        findings = check(contract)
        self.assertIn("evidence_trail", messages(findings))
        self.assertNotIn("first_action", messages(findings))
        contract["evidence_trail"] = ["council minutes, March 1956"]
        self.assertEqual(check(contract), [])

    def test_cta_phrase_with_enough_real_outcome_is_not_cta_shaped(self):
        c = task()
        c["promised_outcome"] = "Knows which three drain checks to run before deciding whether to book a call"
        self.assertEqual(check(c), [])


class InvalidContracts(unittest.TestCase):
    def test_cta_only_outcome_fails(self):
        c = task()
        c["promised_outcome"] = PROJECT_CTA
        self.assertIn("CTA", messages(check(c)))

    def test_project_phrase_only_fires_when_configured(self):
        c = task()
        c["promised_outcome"] = PROJECT_ONLY  # no shipped phrase in it
        self.assertEqual(check(c, shipped()), [])
        self.assertIn("CTA", messages(check(c)))

    def test_shipped_defaults_alone_catch_get_in_touch(self):
        c = task()
        c["promised_outcome"] = "Get in touch for a quote"
        self.assertIn("CTA", messages(check(c, shipped())))

    def test_shipped_defaults_alone_flag_common_sales_ctas(self):
        for outcome in ("Book a strategy session", "Send an enquiry", "Make an enquiry today", "Enquiries welcome",
                        "Book an appointment", "Book a demo", "Subscribe to the newsletter", "Schedule a call",
                        "Contact me today", "Email me", "Call us", "Inquire now", "Join the waitlist"):
            with self.subTest(outcome=outcome):
                c = task()
                c["promised_outcome"] = outcome
                self.assertIn("promised_outcome is CTA-shaped", messages(check(c, shipped())))

    def test_shipped_defaults_alone_flag_an_enquiry_first_action(self):
        c = task()
        c["first_action"] = {"verb": "send", "object": "an enquiry", "location": "the contact form"}
        self.assertIn("first_action is CTA-shaped", messages(check(c, shipped())))

    def test_common_diy_first_actions_are_not_ctas(self):
        for verb, obj, where in (("open", "the booking settings", "your booking platform"),
                                 ("sign up", "for Search Console", "search.google.com"),
                                 ("request a quote", "from three suppliers", "their websites"),
                                 ("reach out", "to your web host", "its support page")):
            with self.subTest(verb=verb):
                c = task()
                c["first_action"] = {"verb": verb, "object": obj, "location": where}
                self.assertEqual(check(c, shipped()), [])

    def test_bare_book_and_hire_are_not_ctas(self):
        c = task()
        c["promised_outcome"] = "Read the book"
        c["first_action"] = {"verb": "hire", "object": "a skip bin", "location": "the driveway"}
        self.assertEqual(check(c, shipped()), [])

    def test_longest_phrase_is_removed_first(self):
        """8 words: removing "book a call" leaves 5 (CTA-shaped); removing only "book a" would leave 6."""
        c = task()
        c["promised_outcome"] = "Know exactly when to book a call today"
        self.assertIn("promised_outcome is CTA-shaped", messages(check(c, shipped())))

    def test_cta_first_action_fails(self):
        c = task()
        c["first_action"] = {"verb": "book", "object": "a Free Strategy Call", "location": "example.com"}
        findings = check(c)
        self.assertIn("first_action", messages(findings))
        self.assertIn("CTA", messages(findings))

    def test_task_without_success_signal_fails(self):
        c = task()
        del c["success_signal"]
        self.assertIn("success_signal", messages(check(c)))

    def test_vague_original_value_fails(self):
        c = task()
        c["original_value"] = "Unique insights"
        self.assertIn("vague", messages(check(c)))

    def test_cta_not_confirmed_excluded_fails(self):
        c = task()
        c["cta_excluded_confirmed"] = False
        self.assertIn("cta_excluded_confirmed", messages(check(c)))

    def test_decision_without_decision_fails(self):
        c = task()
        c["type"] = "decision"
        findings = check(c)
        self.assertTrue(any(f["message"].startswith("schema: ") and "decision" in f["message"] for f in findings),
                        findings)

    def test_findings_are_errors(self):
        c = task()
        c["original_value"] = "expert advice."
        for f in check(c):
            self.assertEqual(set(f), {"severity", "message"})
            self.assertEqual(f["severity"], "error")


class LoadContract(unittest.TestCase):
    def test_toml_json_and_markdown_fences_load_the_same_dict(self):
        want = reader_value.load_contract(FIX / "contract.toml")
        self.assertEqual(want, task())
        for name in ("contract.json", "contract-toml.md", "contract-yaml.md"):
            with self.subTest(name=name):
                self.assertEqual(reader_value.load_contract(FIX / name), want)

    def test_parses_fenced_yaml_block(self):
        c = reader_value.load_contract(FIX / "decision-yaml.md")
        self.assertEqual(c["type"], "decision")
        self.assertEqual(check(c), [])

    def test_absent_block_is_a_contract_error(self):
        for name in ("no-block.md", "heading-no-fence.md"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ContractError, "no Reader Value Contract block in"):
                    reader_value.load_contract(FIX / name)

    def test_yaml_flow_mapping_is_a_contract_error_naming_the_line(self):
        with self.assertRaisesRegex(ContractError, r"line 8\b"):
            reader_value.load_contract(FIX / "flow-mapping.md")

    def test_contract_errors_are_value_errors(self):
        self.assertTrue(issubclass(ContractError, ValueError))

    def test_malformed_files_are_contract_errors(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        cases = {
            "bad.toml": "type = \n",
            "bad.json": "{\"type\": ",
            "list.json": "[1, 2]",
            "unclosed.md": "## Reader Value Contract\n\n```toml\nschema_version = 1\n",
            "two.md": "## Reader Value Contract\n\n```toml\nschema_version = 1\n```\n\n```json\n{}\n```\n",
            "bad-fence.md": "## Reader Value Contract\n\n```toml\ntype = \n```\n",
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                (d / name).write_text(text, encoding="utf-8")
                with self.assertRaises(ContractError):
                    reader_value.load_contract(d / name)

    def test_heading_inside_a_code_fence_is_not_the_contract(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = d / "doc.md"
        p.write_text("# Notes\n\n````markdown\n## Reader Value Contract\n\n```toml\nschema_version = 1\n```\n````\n",
                     encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "no Reader Value Contract block"):
            reader_value.load_contract(p)


class Phrases(unittest.TestCase):
    def test_validate_parameter_does_not_shadow_the_module_function(self):
        import inspect
        params = inspect.signature(reader_value.validate).parameters
        self.assertNotIn("cta_phrases", params)
        self.assertTrue(callable(reader_value.cta_phrases))

    def test_shipped_cta_phrases(self):
        got = shipped()
        for phrase in ("book a call", "get in touch", "free audit", "start a free trial", "enquire", "subscribe"):
            self.assertIn(phrase, got)
        for phrase in ("book a", "book an", "enquiry", "contact me", "email us", "call me", "join the waitlist"):
            self.assertIn(phrase, got)
        for phrase in ("book", "hire", "booking", "request a quote", "get a quote", "reach out", "sign up", "signup",
                       "sign-up"):  # common DIY first actions; a project adds its own
            self.assertNotIn(phrase, got)
        self.assertEqual(len(got), 28)
        self.assertEqual(len({p.casefold() for p in got}), 28)

    def test_shipped_vague_phrases(self):
        for phrase in ("unique insights", "expert perspective", "valuable content", "great tips"):
            self.assertIn(phrase, vague())

    def test_merge_adds_project_phrases_and_dedupes_case_insensitively(self):
        merged = reader_value.merge_phrases(shipped(), [PROJECT_CTA, "Get In Touch", "  hire me  ", "Book A",
                                                        "BOOK  A  CALL"])
        self.assertIn(PROJECT_CTA, merged)
        self.assertEqual(len(merged), len(shipped()) + 1)

    def test_cta_phrases_for_a_project(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.assertEqual(reader_value.cta_phrases(d), shipped())
        (d / ".plainspoken").mkdir()
        (d / ".plainspoken" / "config.toml").write_text(f'[reader_value]\ncta_phrases = ["{PROJECT_ONLY}"]\n',
                                                        encoding="utf-8")
        got = reader_value.cta_phrases(d)
        self.assertIn(PROJECT_ONLY, got)
        self.assertIn("get in touch", got)


class Template(unittest.TestCase):
    def test_template_validates_clean(self):
        c = reader_value.load_contract(TEMPLATE)
        self.assertEqual(check(c), [])

    def test_template_names_every_field(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        for field in ("schema_version", "type", "primary_reader", "problem", "decision", "promised_outcome",
                      "first_action", "effort", "prerequisites", "success_signal", "stop_condition",
                      "original_value", "evidence_trail", "cta_excluded_confirmed"):
            self.assertIn(field, text)


def run(*args, cwd):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_", "CLAUDE_PROJECT_DIR"))}
    env.pop("PYTHONPATH", None)
    return subprocess.run([sys.executable, str(RUN), "reader-value", *args], cwd=cwd, capture_output=True, text=True,
                          env=env)


class Cli(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()

    def write(self, name: str, text: str) -> Path:
        p = self.root / name
        p.write_text(text, encoding="utf-8")
        return p

    def configure(self, *phrases: str):
        (self.root / ".plainspoken").mkdir(exist_ok=True)
        body = ", ".join(f'"{p}"' for p in phrases)
        self.write(".plainspoken/config.toml", f"[reader_value]\ncta_phrases = [{body}]\n")

    def outcome(self, text: str) -> str:
        raw = (FIX / "contract.toml").read_text(encoding="utf-8")
        old = 'promised_outcome = "A cleared drain, or a clear sign that it\'s a job for a licensed plumber"'
        self.assertIn(old, raw)
        return raw.replace(old, f'promised_outcome = "{text}"')

    def test_validate_clean(self):
        r = run("validate", str(FIX / "contract-toml.md"), cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no findings", r.stdout)

    def test_validate_findings_exit_1(self):
        self.write("c.toml", self.outcome("Get in touch for a quote"))
        r = run("validate", "c.toml", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("CTA", r.stdout)

    def test_project_phrase_added_and_shipped_default_still_fires(self):
        self.configure(PROJECT_ONLY)
        self.write("project.toml", self.outcome(PROJECT_ONLY))
        self.write("shipped.toml", self.outcome("Get in touch for a quote"))
        for name in ("project.toml", "shipped.toml"):
            with self.subTest(name=name):
                r = run("validate", name, cwd=self.root)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("CTA", r.stdout)

    def test_project_phrase_ignored_without_config(self):
        self.write("project.toml", self.outcome(PROJECT_ONLY))
        r = run("validate", "project.toml", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_validate_contract_error_exit_2(self):
        for target in (str(FIX / "no-block.md"), str(FIX / "flow-mapping.md"), "missing.toml"):
            with self.subTest(target=target):
                r = run("validate", target, cwd=self.root)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
                self.assertNotIn("Traceback", r.stderr)

    def test_contract_error_names_the_path_once(self):  # ContractError printed the path twice
        for name in ("no-block.md", "flow-mapping.md"):
            with self.subTest(name=name):
                target = FIX / name
                r = run("validate", str(target), cwd=self.root)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(r.stderr.count(name), 1, r.stderr)
                self.assertIn("ContractError", r.stderr)

    def test_bad_project_config_exit_2(self):
        (self.root / ".plainspoken").mkdir()
        self.write(".plainspoken/config.toml", '[reader_value]\ncta_phrases = "buy"\n')
        r = run("validate", str(FIX / "contract.toml"), cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("cta_phrases", r.stderr)

    def test_modules(self):
        r = run("modules", str(FIX / "modules-clean.md"), cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = run("modules", str(FIX / "modules-broken-anchor.md"), cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("#three-checks", r.stdout)
        r = run("modules", "missing.md", cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_template_prints_the_template(self):
        r = run("template", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, TEMPLATE.read_text(encoding="utf-8"))



# --- the isolated delivery reviewer ------------------------------------------------------------------
DRAFT = """# Clearing a slow kitchen sink

Most slow sinks clear in about 30 minutes with a bucket and a plunger.

## Three checks first

Run the tap and watch the plughole: water that pools in one sink only means the blockage is close.

## Clear the trap

Put a bucket under the trap, then remove the sink strainer and trap cap under the kitchen sink. The trap holds
dirty water, so wear gloves.

The drain is clear when a full sink empties in under a minute.

Stop and call a licensed plumber if water backs up into another fixture.
"""

START_HERE = """# Clearing a slow kitchen sink

<!-- module:start-here -->
Jump to [the trap](#clear-the-trap).
<!-- /module:start-here -->

## Clear the trap

Remove the sink strainer and trap cap under the kitchen sink.
"""


def item(name: str, verdict: str = "pass", evidence: str | None = "remove the sink strainer and trap cap",
         why: str = "the draft says so") -> dict:
    return {"item": name, "verdict": verdict, "location": "Clear the trap", "evidence": evidence, "why": why,
            "fix": None}


def passing_items() -> list[dict]:
    items = [item(name) for name in reader_value.DELIVERY_ITEMS if name != "start_here"]
    return items + [item("start_here", "n/a", None, "the draft has no start-here module")]


class DeliveryBase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / ".git").mkdir()
        self.draft = self.root / "drafts" / "kitchen sink.md"
        self.draft.parent.mkdir()
        self.draft.write_text(DRAFT, encoding="utf-8")
        self.contract = self.root / ".plainspoken" / "reader-value" / "kitchen sink.reader-value.toml"
        self.contract.parent.mkdir(parents=True)
        self.contract.write_text((FIX / "contract.toml").read_text(encoding="utf-8"), encoding="utf-8")
        self.reports = self.root / ".plainspoken" / "reports"
        self.reports.mkdir()
        self.record_path = self.reports / "kitchen.delivery.json"

    def hashes(self) -> dict:
        block = reader_value.delivery_input(self.draft, self.contract, self.root)
        return {"article_sha256": block["article_sha256"], "contract_sha256": block["contract_sha256"]}

    def reply(self, items: list[dict] | None = None, result: str = "PASS", **extra) -> str:
        import json
        body = {"article": self.draft.name, **self.hashes(), "result": result,
                "items": passing_items() if items is None else items, **extra}
        return json.dumps(body)

    def record(self, text: str, reviewer: str = "delivery-checker") -> dict:
        return reader_value.record_delivery(self.draft, self.contract, text, self.record_path,
                                            {"article": "drafts/kitchen sink.md", "contract": "c.toml"}, self.root,
                                            reviewer)

    def write_reply(self, text: str) -> Path:
        p = self.reports / "reply.json"
        p.write_text(text, encoding="utf-8")
        return p

    def saved(self) -> dict:
        import json
        return json.loads(self.record_path.read_text(encoding="utf-8"))


class DeliveryInput(DeliveryBase):
    def test_input_names_the_files_and_hashes(self):
        block = reader_value.delivery_input(self.draft, self.contract, self.root)
        self.assertEqual(set(block), {"article", "contract", "rubric", "article_sha256", "contract_sha256"})
        self.assertEqual(block["article"], str(self.draft.resolve()))
        self.assertEqual(block["contract"], str(self.contract.resolve()))
        self.assertEqual(Path(block["rubric"]), REPO / "data" / "rubrics" / "delivery.md")
        self.assertTrue(Path(block["rubric"]).is_file())
        self.assertTrue(block["article_sha256"].startswith("sha256:"))
        self.assertNotEqual(block["article_sha256"], block["contract_sha256"])

    def test_default_contract_is_named_after_the_draft(self):
        self.assertEqual(reader_value.default_contract(self.draft, self.root),
                         self.root / ".plainspoken" / "reader-value" / "kitchen sink.reader-value.toml")

    def test_an_invalid_contract_never_starts_the_reviewer(self):
        self.contract.write_text(self.contract.read_text(encoding="utf-8").replace(
            "A cleared drain, or a clear sign that it's a job for a licensed plumber", "Get in touch"),
            encoding="utf-8")
        with self.assertRaises(reader_value.ContractNotReady) as cm:
            reader_value.delivery_input(self.draft, self.contract, self.root)
        self.assertIn("CTA", str(cm.exception))

    def test_the_draft_is_never_its_own_contract(self):
        with self.assertRaises(ValueError):
            reader_value.delivery_input(self.draft, self.draft, self.root)


class DeliveryRecord(DeliveryBase):
    def test_isolated_pass_is_bound_to_article_contract_and_rubric(self):
        rec = self.record(self.reply())
        self.assertEqual(rec["result"], "PASS")
        self.assertEqual(rec["reviewer"], "delivery-checker")
        saved = self.saved()
        self.assertEqual(saved, rec)
        h = self.hashes()
        self.assertEqual(saved["article_sha256"], h["article_sha256"])
        self.assertEqual(saved["contract_sha256"], h["contract_sha256"])
        self.assertEqual(saved["rubric_sha256"], reader_value.delivery_rubric_hash())
        self.assertTrue(all(i["evidence_verified"] for i in saved["items"] if i["verdict"] == "pass"))

    def test_self_check_never_passes(self):
        rec = self.record(self.reply(), reviewer="self-check")
        self.assertEqual(rec["reviewer"], "self-check")
        self.assertEqual(rec["reading"], "PASS")
        self.assertNotEqual(rec["result"], "PASS")
        self.assertEqual(rec["result"], "INCOMPLETE")

    def test_self_check_fail_stays_fail(self):
        items = passing_items()
        items[3] = item("success_and_stop", "fail", None, "no stop boundary anywhere")
        rec = self.record(self.reply(items, "FAIL"), reviewer="self-check")
        self.assertEqual(rec["result"], "FAIL")

    def test_unknown_reviewer_is_refused(self):
        with self.assertRaises(ValueError):
            self.record(self.reply(), reviewer="writer")

    def test_a_failed_item_fails(self):
        items = passing_items()
        items[2] = item("disclosure", "fail", "The trap holds dirty water", "no cost named")
        rec = self.record(self.reply(items, "FAIL"))
        self.assertEqual(rec["result"], "FAIL")
        self.assertEqual(rec["failed"], 1)

    def test_a_failed_item_fails_even_when_the_reply_says_pass(self):
        items = passing_items()
        items[0] = item("outcome", "fail", None, "never gets there")
        self.assertEqual(self.record(self.reply(items, "PASS"))["result"], "FAIL")

    def test_pass_evidence_not_in_the_draft_is_incomplete(self):
        items = passing_items()
        items[1] = item("standalone_action", evidence="pour boiling water down the drain")
        rec = self.record(self.reply(items))
        self.assertEqual(rec["result"], "INCOMPLETE")
        self.assertEqual(rec["unverified_evidence"], 1)
        self.assertFalse(rec["items"][1]["evidence_verified"])

    def test_pass_without_evidence_is_incomplete(self):
        items = passing_items()
        items[5] = item("original_value", evidence=None)
        self.assertEqual(self.record(self.reply(items))["result"], "INCOMPLETE")

    def test_reply_fail_with_no_failed_item_is_incomplete(self):
        self.assertEqual(self.record(self.reply(result="FAIL"))["result"], "INCOMPLETE")

    def test_module_findings_fail_the_gate(self):
        self.draft.write_text(DRAFT + "\n<!-- module:decision -->\n| a |\n", encoding="utf-8")
        rec = self.record(self.reply())
        self.assertEqual(rec["result"], "FAIL")
        self.assertEqual(len(rec["module_findings"]), 1)
        self.assertIn("never closed", rec["module_findings"][0]["message"])

    def test_start_here_item_must_match_the_draft(self):
        # no start-here module: the item is n/a, and a verdict on it is a malformed reply
        items = passing_items()
        items[6] = item("start_here")
        with self.assertRaises(reader_value.DeliveryReplyError):
            self.record(self.reply(items))
        self.assertEqual(self.saved()["result"], "INCOMPLETE")
        # a start-here module: the item needs a verdict, never n/a
        self.draft.write_text(START_HERE, encoding="utf-8")
        with self.assertRaises(reader_value.DeliveryReplyError):
            self.record(self.reply(passing_items()))
        items = passing_items()
        items[6] = item("start_here", evidence="Remove the sink strainer and trap cap")
        for i in (0, 1, 2, 3, 4, 5):
            items[i] = item(items[i]["item"], evidence="Remove the sink strainer and trap cap")
        self.assertEqual(self.record(self.reply(items))["result"], "PASS")

    def test_na_is_only_for_disclosure_and_start_here_and_needs_a_why(self):
        items = passing_items()
        items[2] = item("disclosure", "n/a", None, "the piece asks the reader to do nothing")
        self.assertEqual(self.record(self.reply(items))["result"], "PASS")
        items[2] = item("disclosure", "n/a", None, "")
        with self.assertRaises(reader_value.DeliveryReplyError):
            self.record(self.reply(items))
        items = passing_items()
        items[0] = item("outcome", "n/a", None, "not needed")
        with self.assertRaises(reader_value.DeliveryReplyError):
            self.record(self.reply(items))

    def test_every_item_exactly_once(self):
        malformed = {
            "missing": passing_items()[:-1],
            "repeated": passing_items() + [item("outcome")],
            "unknown": passing_items()[:-1] + [item("vibes")],
            "bad verdict": [item("outcome", "maybe")] + passing_items()[1:],
            "not an object": ["outcome"] + passing_items()[1:],
        }
        for name, items in malformed.items():
            with self.subTest(name=name):
                with self.assertRaises(reader_value.DeliveryReplyError):
                    self.record(self.reply(items))
                self.assertEqual(self.saved()["result"], "INCOMPLETE")
                self.assertIsNotNone(self.saved()["reply_error"])

    def test_malformed_reply_overwrites_an_earlier_pass_with_incomplete(self):
        self.record(self.reply())
        with self.assertRaises(reader_value.DeliveryReplyError):
            self.record("not json at all")
        self.assertEqual(self.saved()["result"], "INCOMPLETE")

    def test_stale_reply_writes_nothing(self):
        self.record(self.reply())
        stale = self.reply(article_sha256="sha256:" + "0" * 64)
        with self.assertRaises(reader_value.StaleDeliveryReply):
            self.record(stale)
        self.assertEqual(self.saved()["result"], "PASS")
        for missing in ("article_sha256", "contract_sha256"):
            with self.subTest(missing=missing):
                import json
                body = json.loads(self.reply())
                del body[missing]
                with self.assertRaises(reader_value.StaleDeliveryReply):
                    self.record(json.dumps(body))

    def test_malformed_reply_naming_other_hashes_writes_nothing(self):
        self.record(self.reply())
        text = '{"article_sha256": "sha256:' + "1" * 64 + '", "result": "PASS", "items": [}'
        with self.assertRaises(reader_value.StaleDeliveryReply):
            self.record(text)
        self.assertEqual(self.saved()["result"], "PASS")

    def test_an_edited_contract_makes_the_reply_stale(self):
        text = self.reply()
        self.contract.write_text(self.contract.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
        with self.assertRaises(reader_value.StaleDeliveryReply):
            self.record(text)

    def test_a_contract_that_no_longer_validates_records_incomplete(self):
        text = self.reply()
        self.record(text)
        # same contract bytes, but the project now lists a CTA phrase its first_action holds
        (self.root / ".plainspoken" / "config.toml").write_text('[reader_value]\ncta_phrases = ["kitchen sink"]\n',
                                                                 encoding="utf-8")
        with self.assertRaises(reader_value.ContractNotReady):
            self.record(text)
        self.assertEqual(self.saved()["result"], "INCOMPLETE")
        self.assertIn("doesn't validate", self.saved()["reply_error"])

    def test_reply_in_one_fenced_block_with_prose(self):
        rec = self.record("Here it is.\n```json\n" + self.reply() + "\n```\n")
        self.assertEqual(rec["result"], "PASS")
        self.assertTrue(rec["reply_had_prose"])


class DeliveryCli(DeliveryBase):

    def test_deliver_input_uses_the_default_contract(self):
        import json
        r = run("deliver-input", "drafts/kitchen sink.md", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["contract"], str(self.contract.resolve()))

    def test_deliver_input_without_a_contract_exits_2(self):
        self.contract.unlink()
        r = run("deliver-input", "drafts/kitchen sink.md", cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)

    def test_deliver_input_refuses_an_invalid_contract(self):
        self.contract.write_text(self.contract.read_text(encoding="utf-8").replace(
            "A cleared drain, or a clear sign that it's a job for a licensed plumber", "Get in touch"),
            encoding="utf-8")
        r = run("deliver-input", "drafts/kitchen sink.md", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not started", r.stderr)

    def test_deliver_records_a_pass_under_the_report_key(self):
        import json
        reply = self.write_reply(self.reply())
        r = run("deliver", "drafts/kitchen sink.md", "--from", str(reply), "--reviewer", "delivery-checker",
                cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("delivery: PASS"), r.stdout)
        paths = json.loads(subprocess.run([sys.executable, str(RUN), "paths", "drafts/kitchen sink.md"],
                                          cwd=self.root, capture_output=True, text=True).stdout)
        self.assertTrue(paths["delivery"].endswith(f"{paths['key']}.delivery.json"))
        self.assertTrue(paths["delivery-reply"].endswith(f"{paths['key']}.delivery-reply.json"))
        saved = json.loads(Path(paths["delivery"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["result"], "PASS")
        self.assertEqual(saved["article"], "drafts/kitchen sink.md")
        self.assertEqual(saved["contract"], ".plainspoken/reader-value/kitchen sink.reader-value.toml")

    def test_self_check_exits_1_and_says_so(self):
        reply = self.write_reply(self.reply())
        r = run("deliver", "drafts/kitchen sink.md", "--from", str(reply), "--reviewer", "self-check", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("delivery: INCOMPLETE"), r.stdout)
        self.assertIn("self-check", r.stdout.splitlines()[0])

    def test_fail_exits_1_and_malformed_exits_2(self):
        items = passing_items()
        items[3] = item("success_and_stop", "fail", None, "no stop boundary")
        r = run("deliver", "drafts/kitchen sink.md", "--from", str(self.write_reply(self.reply(items, "FAIL"))),
                "--reviewer", "delivery-checker", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("delivery: FAIL"), r.stdout)
        r = run("deliver", "drafts/kitchen sink.md", "--from", str(self.write_reply("{")), "--reviewer",
                "delivery-checker", cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("INCOMPLETE", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_stale_reply_exits_1_and_writes_nothing(self):
        reply = self.write_reply(self.reply(contract_sha256="sha256:" + "0" * 64))
        r = run("deliver", "drafts/kitchen sink.md", "--from", str(reply), "--reviewer", "delivery-checker",
                cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not recorded", r.stderr)
        self.assertEqual(list(self.reports.glob("*.delivery.json")), [])

    def test_contract_error_names_the_path_once(self):
        self.contract.write_text("not = [valid", encoding="utf-8")
        for cmd in (("deliver-input",), ("deliver", "--from", str(self.write_reply("{}")), "--reviewer",
                                           "delivery-checker")):
            with self.subTest(cmd=cmd[0]):
                r = run(cmd[0], "drafts/kitchen sink.md", *cmd[1:], cwd=self.root)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(r.stderr.count("kitchen sink.reader-value.toml"), 1, r.stderr)


class DeliveryReviewerLabel(DeliveryBase):  # no default label, so leaving out a flag can't pass
    def test_reviewer_is_required(self):
        reply = self.write_reply(self.reply())
        r = run("deliver", "drafts/kitchen sink.md", "--from", str(reply), cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--reviewer", r.stderr)
        self.assertEqual(list(self.reports.glob("*.delivery.json")), [])

    def test_unknown_reviewer_is_a_usage_error(self):
        reply = self.write_reply(self.reply())
        r = run("deliver", "drafts/kitchen sink.md", "--from", str(reply), "--reviewer", "writer", cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_the_old_self_check_flag_is_gone(self):
        reply = self.write_reply(self.reply())
        r = run("deliver", "drafts/kitchen sink.md", "--from", str(reply), "--self-check", cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


class DeliveryStatus(DeliveryBase):  # a reader that recomputes the three hashes
    def deliver(self, reviewer: str = "delivery-checker", items: list[dict] | None = None,
                result: str = "PASS") -> None:
        self.record(self.reply(items, result), reviewer=reviewer)

    def status(self) -> dict:
        return reader_value.delivery_status(self.draft, self.contract, self.record_path, self.root)

    def test_no_record_is_incomplete(self):
        st = self.status()
        self.assertEqual(st["status"], "INCOMPLETE")
        self.assertIn("no delivery record", " ".join(st["reasons"]))

    def test_current_pass(self):
        self.deliver()
        st = self.status()
        self.assertEqual(st["status"], "PASS", st)
        self.assertEqual(st["reasons"], [])

    def test_current_fail(self):
        items = passing_items()
        items[0] = item("outcome", "fail", None, "never gets there")
        self.deliver(items=items, result="FAIL")
        self.assertEqual(self.status()["status"], "FAIL")

    def test_an_edited_draft_makes_a_pass_stale(self):
        self.deliver()
        self.draft.write_text(DRAFT + "\nOne more line.\n", encoding="utf-8")
        st = self.status()
        self.assertEqual(st["status"], "STALE")
        self.assertIn("draft changed", " ".join(st["reasons"]))
        self.assertEqual(self.saved()["result"], "PASS")  # the record itself still says PASS: only status knows

    def test_an_edited_contract_makes_it_stale(self):
        self.deliver()
        self.contract.write_text(self.contract.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
        st = self.status()
        self.assertEqual(st["status"], "STALE")
        self.assertIn("contract changed", " ".join(st["reasons"]))

    def test_a_changed_rubric_makes_it_stale(self):
        self.deliver()
        import json
        rec = self.saved()
        rec["rubric_sha256"] = "sha256:" + "0" * 64
        self.record_path.write_text(json.dumps(rec), encoding="utf-8")
        st = self.status()
        self.assertEqual(st["status"], "STALE")
        self.assertIn("rubric changed", " ".join(st["reasons"]))

    def test_a_self_check_record_is_never_pass_even_if_edited_to_say_so(self):
        self.deliver(reviewer="self-check")
        self.assertEqual(self.status()["status"], "INCOMPLETE")
        import json
        rec = self.saved()
        rec["result"] = "PASS"
        self.record_path.write_text(json.dumps(rec), encoding="utf-8")
        st = self.status()
        self.assertEqual(st["status"], "INCOMPLETE")
        self.assertIn("self-check", " ".join(st["reasons"]))

    def test_unreadable_record_is_incomplete(self):
        for text in ("{", "[]", '{"result": "PASS"}'):
            with self.subTest(text=text):
                self.record_path.write_text(text, encoding="utf-8")
                st = self.status()
                self.assertEqual(st["status"], "INCOMPLETE")
                self.assertIn("unreadable", " ".join(st["reasons"]))

    def test_a_contract_that_no_longer_validates_is_incomplete(self):
        self.deliver()
        (self.root / ".plainspoken" / "config.toml").write_text('[reader_value]\ncta_phrases = ["kitchen sink"]\n',
                                                                 encoding="utf-8")
        st = self.status()
        self.assertEqual(st["status"], "INCOMPLETE")
        self.assertIn("doesn't validate", " ".join(st["reasons"]))


class DeliveryStatusCli(DeliveryBase):
    def test_status_exit_codes(self):
        r = run("status", "drafts/kitchen sink.md", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("delivery: INCOMPLETE"), r.stdout)
        reply = self.write_reply(self.reply())
        run("deliver", "drafts/kitchen sink.md", "--from", str(reply), "--reviewer", "delivery-checker",
            cwd=self.root)
        r = run("status", "drafts/kitchen sink.md", cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], "delivery: PASS")
        self.draft.write_text(DRAFT + "\nEdited.\n", encoding="utf-8")
        r = run("status", "drafts/kitchen sink.md", cwd=self.root)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("delivery: STALE"), r.stdout)

    def test_status_json_and_bad_input(self):
        import json
        r = run("status", "drafts/kitchen sink.md", "--json", cwd=self.root)
        self.assertEqual(json.loads(r.stdout)["status"], "INCOMPLETE")
        r = run("status", "drafts/missing.md", cwd=self.root)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
