import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "integrity.py"
sys.path.insert(0, str(REPO / "lib"))
from plainspoken import _util  # noqa: E402
LIMIT = 2000
SUBPROCESS_SECONDS = 5.0  # wall clock incl. interpreter start; the tight timings are in-process (tests/test_integrity.py)


def run_hook(payload, project: Path, **env_over):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
    env.update({"CLAUDE_PROJECT_DIR": str(project), "CLAUDE_PLUGIN_DATA": str(project / ".data")})
    env.update(env_over)
    env = {k: v for k, v in env.items() if v is not None}
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env,
                          cwd=project)


class Base(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.art = self.project / "post.md"
        self.session = "s1"

    def event(self, path=None):
        return {"hook_event_name": "PostToolUse", "tool_name": "Write", "session_id": self.session,
                "cwd": str(self.project), "tool_input": {"file_path": str(path or self.art)}}

    def config(self, text: str):
        (self.project / ".plainspoken").mkdir(exist_ok=True)
        (self.project / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def run_on(self, text: str, path: Path | None = None, **env):
        target = path or self.art
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        r = run_hook(self.event(target), self.project, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        return r

    def context(self, r) -> str:
        out = json.loads(r.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertLessEqual(len(ctx), LIMIT)
        return ctx

    def assert_warns(self, text: str, *needles: str) -> str:
        r = self.run_on(text)
        self.assertTrue(r.stdout.strip(), "expected a warning, got silence")
        ctx = self.context(r)
        for n in needles:
            self.assertIn(n, ctx)
        return ctx

    def assert_silent(self, text: str, path: Path | None = None, **env):
        r = self.run_on(text, path, **env)
        self.assertEqual(r.stdout.strip(), "")


class NoLedger(Base):
    """The original content-integrity hook's cases, ported (a warning here was a block there)."""

    def test_unsourced_chart_warns(self):  # A1
        ctx = self.assert_warns('<figure><svg xmlns="http://www.w3.org/2000/svg" aria-label="Map Pack 42%">'
                                "<title>Where clicks go</title><text>42%</text></svg></figure>\n\nNo citation follows.\n",
                                "42%")
        self.assertIn("integrity:allow", ctx)
        self.assertIn("first_hand", ctx)

    def test_unsourced_chart_with_dollar_and_multiplier(self):  # A4
        self.assert_warns("<figure><svg><text>$4.99</text><text>3x</text></svg></figure>\n", "$4.99", "3x")

    def test_non_dollar_chart_warns(self):
        self.assert_warns("<figure><svg><text>€1.2m</text></svg></figure>\n", "€1.2")

    def test_chart_cited_after_figure_passes(self):  # B1
        self.assert_silent('<figure><svg xmlns="http://www.w3.org/2000/svg" style="max-width: 100%"><text>48%</text>'
                           "</svg></figure>\n\nOnly 48% pass ([Acme Survey](https://example.com/survey)).\n")

    def test_chart_cited_before_figure_passes(self):  # B12
        self.assert_silent("An [Acme study](https://example.com/study) found jobs ran 19% slower.\n\n"
                           "<figure><svg><text>-19%</text><text>Source: Acme 2025</text></svg></figure>\n\n"
                           "That is the gap.\n")

    def test_second_chart_does_not_inherit_first_citation(self):  # B14
        ctx = self.assert_warns("<figure><svg><text>10%</text></svg></figure>\n\nCited ([src](https://example.com/x)). "
                                "Then a longer stretch of prose, with no link in it at all.\n\n"
                                "<figure><svg><text>77%</text></svg></figure>\n\nNothing here.\n", "77%")
        self.assertNotIn("10%", ctx)

    def test_xmlns_and_schema_org_are_not_citations(self):  # B7 trap, inverted
        self.assert_warns('<figure><svg xmlns="http://www.w3.org/2000/svg"><text>42%</text></svg>'
                          "<figcaption>Source: https://schema.org/Dataset</figcaption></figure>\n", "42%")

    def test_attribute_percent_is_not_a_statistic(self):  # B7
        self.assert_silent('<figure><svg xmlns="http://www.w3.org/2000/svg" style="max-width: 100%; height: auto" '
                           'viewBox="0 0 560 380"><text>Melbourne</text></svg></figure>\n')

    def test_schema_org_jsonld_without_stat_is_silent(self):  # B11
        self.assert_silent('<script type="application/ld+json">{"@context":"https://schema.org"}</script>\n')

    def test_chart_allow_marker_clears(self):  # B3
        self.assert_silent("<figure><!-- integrity:allow — own job-board count --><svg><text>41%</text></svg></figure>\n")

    def test_scoped_marker_does_not_clear_distant_chart(self):  # B4e
        self.assert_warns("<!-- integrity:allow -->\n\n> **TL;DR:** my own 41% measurement.\n\n"
                          "Long prose separates the regions. [A cited chart](https://example.com/a) sits here.\n\n"
                          "<figure><svg><text>77%</text></svg></figure>\n\nNothing cites the second chart.\n\n"
                          "<figure><svg><text>88%</text></svg></figure>\n", "88%")

    def test_legacy_token_does_not_bypass(self):  # B4 / B4c
        self.assert_warns("[PERSONAL EXPERIENCE]\n<figure><svg><text>41%</text></svg></figure>\n", "41%")

    def test_unsourced_tldr_warns(self):  # A2
        self.assert_warns("---\ntitle: x\n---\n\n> **TL;DR:** roughly 65% of plumbers in Ballarat never answer.\n\n"
                          "Body text.\n", "TL;DR", "65%")

    def test_cited_tldr_passes(self):  # B2
        self.assert_silent("---\ntitle: x\n---\n\n> **TL;DR:** Only 48% pass ([src](https://example.org/a)).\n")

    def test_marker_on_line_above_tldr_clears(self):  # B13
        self.assert_silent("---\ntitle: x\n---\n\n<!-- integrity:allow -->\n"
                           "> **TL;DR:** a ~$4,868 overage on a $5/month account. The host waived it.\n")

    def test_chart_marker_does_not_clear_tldr(self):  # B13b
        self.assert_warns("---\ntitle: x\n---\n\n> **TL;DR:** local intent covers 46% of searches.\n\n"
                          "<figure><!-- integrity:allow --><svg><text>41%</text></svg></figure>\n", "46%")

    def test_chart_marker_above_a_tldr_does_not_clear_it(self):  # a chart's marker is the chart's
        self.assert_warns("<figure><!-- integrity:allow --><svg><text>41%</text></svg></figure>\n\n"
                          "> **TL;DR:** local intent covers 46% of searches.\n", "46%")

    def test_a_prose_marker_still_clears_a_tldr_after_a_marked_chart(self):  # only the chart's own marker is scoped
        self.assert_silent("<figure><!-- integrity:allow --><svg><text>41%</text></svg></figure>\n\n"
                           "<!-- integrity:allow -->\n> **TL;DR:** my own 46% measurement.\n")

    def test_tldr_marker_still_clears_the_chart_below(self):  # host window kept (the host's 002 shape)
        self.assert_silent("<!-- integrity:allow -->\n> **TL;DR:** my own 41% measurement.\n\n"
                           "<figure><svg><text>$3,000</text></svg></figure>\n")

    def test_marker_a_paragraph_above_the_tldr_still_clears_it(self):  # host's 300-character window kept
        self.assert_silent("<!-- integrity:allow -->\n\nA short opening paragraph.\n\n"
                           "> **TL;DR:** my own 41% measurement.\n")

    def test_marker_directly_above_a_chart_clears_it(self):
        self.assert_silent("Prose first.\n\n<!-- integrity:allow — own count -->\n\n"
                           "<figure><svg><text>41%</text></svg></figure>\n")

    def test_marker_in_the_prose_beside_a_chart_still_clears_it(self):  # host's chart window kept
        self.assert_silent("<figure><svg><text>41%</text></svg></figure>\n\n"
                           "I counted these myself. <!-- integrity:allow -->\n")

    def test_unsourced_description_warns(self):  # A3
        self.assert_warns('---\ndescription: "Cuts costs 50%."\n---\n\nBody prose with no citation at all.\n',
                          "description", "50%")

    def test_unsourced_og_description_warns(self):  # A5
        self.assert_warns('---\nogDescription: "Acme Plumbing grew 40% last quarter."\n---\n\nBody with no link.\n',
                          "ogDescription", "40%")

    def test_meta_stat_sourced_in_body_passes(self):  # B9
        self.assert_silent('---\ndescription: "Only 48% of websites pass."\n---\n\n'
                           "> **TL;DR:** Only 48% pass ([Acme Survey](https://example.com/survey)).\n")

    def test_meta_number_must_match_whole(self):  # "4" must not be "sourced" by a linked line saying 2024
        self.assert_warns('---\ndescription: "Fees rose 4%."\n---\n\nSee the [2024 report](https://example.com/r).\n',
                          "4%")

    def test_frontmatter_escape_clears(self):  # B4d
        self.assert_silent('---\ndescription: "The bill hit $4,868 on a $5/month account."\n# integrity: first-hand\n---\n\n'
                           "<!-- integrity:first-hand -->\n\n> **TL;DR:** a ~$4,868 overage on a $5/month account.\n\n"
                           "<figure><svg><text>$3,000</text></svg></figure>\n")

    def test_body_marker_does_not_clear_frontmatter(self):  # B4b
        self.assert_warns('---\ndescription: "The bill hit $4,868 on a $5/month account."\n---\n\n'
                          "<!-- integrity:first-hand -->\n\n> **TL;DR:** a ~$4,868 overage on a $5/month account.\n\n"
                          "<figure><svg><text>$3,000</text></svg></figure>\n", "description")

    def test_every_unsourced_chart_is_listed_up_to_five(self):
        charts = "".join(f"<figure><svg><text>{n}%</text></svg></figure>\n\nNo link.\n\n" for n in range(11, 18))
        ctx = self.assert_warns(charts, "11%", "15%", "+2 more charts")
        self.assertNotIn("16%", ctx)
        self.assertEqual(sum(1 for ln in ctx.splitlines() if ln.startswith("- Chart (line ")), 5)

    def test_every_unsourced_frontmatter_key_is_listed(self):
        ctx = self.assert_warns('---\ndescription: "Cuts costs 50%."\ntldr: "Saves $300."\n'
                                'ogDescription: "Up 3x."\n---\n\nBody with no link.\n',
                                "`description`: 50%", "`tldr`: $300", "`ogDescription`: 3x")
        self.assertEqual(ctx.count("# integrity: allow"), 1)

    def test_all_three_checks_in_one_message(self):
        self.assert_warns('---\ndescription: "Cuts costs 50%."\n---\n\n> **TL;DR:** up 65%.\n\n'
                          "<figure><svg><text>42%</text></svg></figure>\n", "Chart (line", "TL;DR: 65%",
                          "`description`: 50%")

    def test_clean_file_is_silent(self):
        self.assert_silent("# Notes\n\nI fixed the login bug on Friday.\n")

    def test_message_points_at_claims_skill(self):
        self.assertIn("/plainspoken:claims", self.assert_warns("<figure><svg><text>42%</text></svg></figure>\n"))


class WithLedger(Base):
    def ledger(self, data: dict, name: str | None = None):
        d = self.project / ".plainspoken" / "claims"
        d.mkdir(parents=True, exist_ok=True)
        name = name or f"{_util.path_key(self.art, self.project)}.claims.json"  # the path-keyed name
        (d / name).write_text(json.dumps(data), encoding="utf-8")

    def test_one_gap_warns_with_value(self):
        self.ledger({"claims": [{"id": "c1", "text": "Acme Plumbing charges $120 an hour"}]})
        ctx = self.assert_warns("# Prices\n\nAcme Plumbing charges $120 an hour and grew 40% in 2025.\n", "40%")
        self.assertIn("3 40%", ctx)  # line value
        self.assertNotIn(" $120:", ctx)  # no row for the recorded value

    def test_no_gaps_is_silent(self):
        self.ledger({"claims": [{"id": "c1", "text": "Acme Plumbing grew 40% in 2025"}]})
        self.assert_silent("# Prices\n\nAcme Plumbing grew 40% in 2025.\n")

    def test_ledger_replaces_the_no_ledger_checks(self):
        self.ledger({"claims": [{"id": "c1", "text": "42% of calls", "notes": "first_hand"}]})
        self.assert_silent("<figure><svg><text>42%</text></svg></figure>\n")

    def test_many_gaps_list_ten_then_more(self):
        self.ledger({"claims": []})
        body = "".join(f"Line {i} says {i + 10}% of jobs.\n\n" for i in range(15))
        ctx = self.assert_warns("# Many\n\n" + body, "+5 more")
        self.assertEqual(sum(1 for ln in ctx.splitlines() if "% of jobs" in ln), 10)

    def test_old_stem_only_ledger_still_used_when_it_names_the_file(self):
        self.art.write_text("placeholder\n", encoding="utf-8")
        self.ledger({"source_file": "post.md", "claims": [{"text": "Acme Plumbing charges $120 an hour"}]},
                    name="post.claims.json")
        self.assert_warns("# Prices\n\nAcme Plumbing charges $120 an hour and grew 40% in 2025.\n", "40%")

    def test_old_stem_only_ledger_of_another_file_is_not_used(self):  # a/post.md's ledger
        (self.project / "a").mkdir()
        (self.project / "a" / "post.md").write_text("Acme grew 40%.\n", encoding="utf-8")
        self.ledger({"source_file": "a/post.md", "claims": [{"text": "Acme grew 40%"}]}, name="post.claims.json")
        ctx = self.context(self.run_on("<figure><svg><text>42%</text></svg></figure>\n"))
        self.assertIn("no source", ctx)  # this post.md has no ledger: the no-ledger checks run

    def test_malformed_ledger_is_one_line(self):
        d = self.project / ".plainspoken" / "claims"
        d.mkdir(parents=True)
        (d / f"{_util.path_key(self.art, self.project)}.claims.toml").write_text("claims = [\n", encoding="utf-8")
        ctx = self.context(self.run_on("Acme grew 40%.\n"))
        self.assertTrue(ctx.startswith("plainspoken integrity skipped:"), ctx)
        self.assertEqual(len(ctx.splitlines()), 1)


class Modes(Base):
    UNSOURCED = "<figure><svg><text>42%</text></svg></figure>\n"

    def test_block_mode_prints_decision(self):
        self.config('[integrity]\nmode = "block"\n')
        r = self.run_on(self.UNSOURCED)
        out = json.loads(r.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("42%", out["reason"])
        self.assertLessEqual(len(out["reason"]), LIMIT)
        self.assertNotIn("hookSpecificOutput", out)

    def test_block_mode_repeats_on_an_identical_edit(self):
        self.config('[integrity]\nmode = "block"\n')
        first = json.loads(self.run_on(self.UNSOURCED).stdout)
        second = json.loads(self.run_on(self.UNSOURCED).stdout)
        self.assertEqual((first["decision"], second["decision"]), ("block", "block"))
        self.assertEqual(first["reason"], second["reason"])

    def test_block_then_fixed_says_so_once(self):
        self.config('[integrity]\nmode = "block"\n')
        self.run_on(self.UNSOURCED)
        ctx = self.context(self.run_on("Nothing to see.\n"))
        self.assertIn("no unsourced", ctx)
        self.assert_silent("Nothing to see.\n")

    def test_off_mode_is_silent(self):
        self.config('[integrity]\nmode = "off"\n')
        self.assert_silent(self.UNSOURCED)

    def test_malformed_config_is_one_line(self):
        self.config('[integrity]\nmode = "loud"\n')
        ctx = self.context(self.run_on(self.UNSOURCED))
        self.assertTrue(ctx.startswith("plainspoken integrity skipped:"), ctx)
        self.assertEqual(len(ctx.splitlines()), 1)

    def test_malformed_config_non_target_is_silent(self):
        self.config('[integrity]\nmode = "loud"\n')
        self.assert_silent("42%\n", self.project / "notes.txt")


class Scope(Base):
    UNSOURCED = "<figure><svg><text>42%</text></svg></figure>\n"

    def test_non_target_path_is_silent(self):
        self.assert_silent(self.UNSOURCED, self.project / "notes.txt")

    def test_integrity_paths_respected(self):
        self.config('[integrity]\npaths = ["docs/**/*.md"]\n')
        self.assert_silent(self.UNSOURCED)
        r = self.run_on(self.UNSOURCED, self.project / "docs" / "post.md")
        self.assertIn("42%", self.context(r))

    def test_falls_back_to_targets_option(self):
        self.assert_silent(self.UNSOURCED, CLAUDE_PLUGIN_OPTION_TARGETS='["docs/**/*.md"]')

    def test_integrity_paths_win_over_targets_option(self):
        self.config('[integrity]\npaths = ["**/*.md"]\n')
        r = self.run_on(self.UNSOURCED, CLAUDE_PLUGIN_OPTION_TARGETS='["docs/**/*.md"]')
        self.assertIn("42%", self.context(r))

    def test_plainspoken_folder_and_ledgers_are_skipped(self):
        self.assert_silent(self.UNSOURCED, self.project / ".plainspoken" / "reports" / "post.md")
        for name in ("post.claims.toml", "post.claims.json", "post.reader-value.toml"):
            self.assert_silent(self.UNSOURCED, self.project / name,
                               CLAUDE_PLUGIN_OPTION_TARGETS='["**/*"]')

    def test_outside_project_is_silent(self):
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.assert_silent(self.UNSOURCED, other / "post.md")


class Dedupe(Base):
    UNSOURCED = "<figure><svg><text>42%</text></svg></figure>\n"

    def test_second_identical_edit_is_silent(self):
        self.assertTrue(self.run_on(self.UNSOURCED).stdout.strip())
        self.assert_silent(self.UNSOURCED)

    def test_new_session_reports_again(self):
        self.run_on(self.UNSOURCED)
        self.session = "s2"
        self.assertTrue(self.run_on(self.UNSOURCED).stdout.strip())

    def test_back_to_clean_says_so_once(self):
        self.run_on(self.UNSOURCED)
        ctx = self.context(self.run_on("Nothing to see.\n"))
        self.assertIn("no unsourced", ctx)
        self.assert_silent("Nothing to see.\n")

    def test_state_file_is_separate(self):
        self.run_on(self.UNSOURCED)
        self.assertTrue((self.project / ".data" / "integrity-state.json").is_file())
        self.assertFalse((self.project / ".data" / "lint-watch-state.json").exists())


class StateSafety(Base):
    """A repository can commit .plainspoken/, so state writes must never follow a planted symlink."""
    UNSOURCED = "<figure><svg><text>42%</text></svg></figure>\n"

    def setUp(self):
        super().setUp()
        self.outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.outside, ignore_errors=True)
        self.victim = self.outside / "victim.txt"
        self.victim.write_text("precious\n", encoding="utf-8")
        (self.project / ".plainspoken").mkdir()

    def run_default_data(self):  # CLAUDE_PLUGIN_DATA unset: state goes to <project>/.plainspoken/
        return self.run_on(self.UNSOURCED, CLAUDE_PLUGIN_DATA=None)

    def assert_victim_untouched(self):
        self.assertEqual(self.victim.read_text(encoding="utf-8"), "precious\n")

    def test_planted_tmp_symlink(self):
        (self.project / ".plainspoken" / "integrity-state.tmp").symlink_to(self.victim)
        self.assertIn("42%", self.context(self.run_default_data()))
        self.assert_victim_untouched()

    def test_planted_state_symlink(self):
        (self.project / ".plainspoken" / "integrity-state.json").symlink_to(self.victim)
        for _ in range(2):  # the symlinked state is ignored, so each run reports
            self.assertIn("42%", self.context(self.run_default_data()))
        self.assert_victim_untouched()
        self.assertTrue((self.project / ".plainspoken" / "integrity-state.json").is_symlink())

    def test_symlinked_data_folder(self):
        shutil.rmtree(self.project / ".plainspoken")
        (self.project / ".plainspoken").symlink_to(self.outside, target_is_directory=True)
        self.assertIn("42%", self.context(self.run_default_data()))
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["victim.txt"])

    def test_no_temp_files_left(self):
        self.run_default_data()
        self.assertEqual(list((self.project / ".plainspoken").glob("*.tmp")), [])
        self.assertTrue((self.project / ".plainspoken" / "integrity-state.json").is_file())


class FailOpen(Base):
    def test_malformed_event(self):
        r = run_hook("{not json", self.project)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_event_without_tool_input(self):
        r = run_hook({"hook_event_name": "PostToolUse", "tool_name": "Write"}, self.project)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_missing_file_is_one_line(self):
        r = run_hook(self.event(self.project / "gone.md"), self.project)
        self.assertEqual(r.returncode, 0)
        ctx = self.context(r)
        self.assertTrue(ctx.startswith("plainspoken integrity skipped:"), ctx)
        self.assertEqual(len(ctx.splitlines()), 1)

    def test_big_file_is_fast_and_short(self):
        para = ("Acme Plumbing answered 12% more calls after the change, and [the log](https://example.com/log) "
                "shows it.\n\n<figure><svg><text>{n}%</text></svg></figure>\n\n")
        text = "---\ndescription: \"Calls up 99%.\"\n---\n\n> **TL;DR:** up 99%.\n\n"
        text += "".join(para.replace("{n}", str(i % 100)) for i in range(2500))
        text += "<figure><svg><text>7%</text></svg></figure>\n" * 50
        self.assertGreater(len(text.encode("utf-8")), 300_000)
        start = time.monotonic()
        r = self.run_on(text)
        self.assertLess(time.monotonic() - start, SUBPROCESS_SECONDS)
        self.context(r)

    def test_big_file_with_ledger_is_fast_and_short(self):
        d = self.project / ".plainspoken" / "claims"
        d.mkdir(parents=True)
        (d / "post.claims.json").write_text('{"claims": []}', encoding="utf-8")
        text = "".join(f"Acme Plumbing quoted ${i},000 and {i}% of jobs ran \"late by more than a day\".\n\n"
                       for i in range(6000))
        self.assertGreater(len(text.encode("utf-8")), 300_000)
        start = time.monotonic()
        r = self.run_on(text)
        self.assertLess(time.monotonic() - start, SUBPROCESS_SECONDS)
        self.context(r)

    def test_unclosed_figures_are_fast(self):
        text = "<figure><svg><text>1%</text>\n" * 12000
        self.assertGreater(len(text.encode("utf-8")), 300_000)
        start = time.monotonic()
        self.run_on(text)
        self.assertLess(time.monotonic() - start, SUBPROCESS_SECONDS)


BLOCK_TOMLLIB = """
import runpy, sys
class Blocker:  # what a python3 older than 3.11 looks like: no tomllib
    def find_spec(self, name, path=None, target=None):
        if name == "tomllib":
            raise ImportError("No module named 'tomllib'")
        return None
sys.meta_path.insert(0, Blocker())
sys.argv = [sys.argv[1]]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


class ImportFailure(Base):
    def test_fails_open(self):
        self.art.write_text("<figure><svg><text>42%</text></svg></figure>\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env.update({"CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_PLUGIN_DATA": str(self.project / ".data")})
        r = subprocess.run([sys.executable, "-c", BLOCK_TOMLLIB, str(HOOK)], input=json.dumps(self.event()),
                           capture_output=True, text=True, env=env, cwd=self.project)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        ctx = self.context(r)
        self.assertTrue(ctx.startswith("plainspoken integrity skipped:"), ctx)
        self.assertEqual(len(ctx.splitlines()), 1)


class Registration(unittest.TestCase):
    def test_second_command_on_post_tool_use(self):
        cfg = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        # The second PostToolUse group is the kaizen backstop on SubagentHandback (Phase 5).
        self.assertEqual([g["matcher"] for g in cfg["PostToolUse"]], ["Write|Edit", "SubagentHandback"])
        post = cfg["PostToolUse"][0]
        self.assertEqual(post["matcher"], "Write|Edit")
        self.assertEqual(len(post["hooks"]), 2)
        h = post["hooks"][1]
        self.assertEqual((h["type"], h["command"], h["args"]),
                         ("command", "python3", ["${CLAUDE_PLUGIN_ROOT}/hooks/integrity.py"]))
        self.assertEqual(h["timeout"], 15)
        self.assertNotIn("onFailure", h)


if __name__ == "__main__":
    unittest.main()
