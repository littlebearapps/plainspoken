"""Eval case files are well formed (claude plugin eval 2.1.296 format): the trigger cases and the
rewrite cases. Running them is a paid, owner-approved step; this test only checks structure, offline.
The rewrite cases' regex graders are run here through Python `re` on each case's hand-written `reference.md`."""
import re
import tempfile
import unittest
from pathlib import Path

from plainspoken import rewrite
from plainspoken.checks_lexical import _pattern as ban_pattern
from plainspoken.profile import default as default_profile
from plainspoken.registry import load_config, spelling_variants
from scripts.dev.lint_frontmatter import parse_frontmatter

REPO = Path(__file__).resolve().parents[1]
EVALS = REPO / "evals"
CASES = EVALS / "triggers"
REWRITE = EVALS / "rewrite"
REWRITE_SLASH = EVALS / "rewrite-slash"
SMOKE = EVALS / "smoke"
DRAFTING = (EVALS / "drafting", EVALS / "drafting-hooks")
EXTRA = (EVALS / "longform", EVALS / "fix")
CASE_KEYS = {"schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome", "model",
             "max_turns", "timeout_seconds", "allowed_tools", "append_system_prompt", "env"}
GRADER_TYPES = {"regex", "tool_used", "tool_order", "file_exists", "llm", "baseline"}
AUTO = {"check", "humanize", "write", "plain-language"}
MANUAL = {"voice", "copy-audit", "register-check", "adapt", "claims", "reader-value", "kaizen", "setup", "doctor"}
READ_ONLY = {"Read", "Glob", "Grep", "Skill"}
CLI_GRANT = "Bash(python3 *)"  # the run grants it with --allow-tools; covers `python3 <plugin>/lib/run.py …`


def flow_list(value: str) -> list[str]:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return []
    return [x.strip().strip("\"'") for x in value[1:-1].split(",") if x.strip()]


def body(text: str) -> str:
    parts = text.split("\n---", 1)
    return parts[1].split("\n", 1)[1].strip() if len(parts) == 2 and "\n" in parts[1] else ""


def _case(d: Path):
    text = (d / "prompt.md").read_text(encoding="utf-8")
    graders = [(g.name, parse_frontmatter(g.read_text(encoding="utf-8")), body(g.read_text(encoding="utf-8")))
               for g in sorted((d / "graders").glob("*.md"))]
    return d, parse_frontmatter(text), body(text), graders


def cases():
    for d in sorted(p for p in CASES.iterdir() if p.is_dir()):
        yield _case(d)


def loadable_cases() -> list[Path]:
    """Every folder `claude plugin eval` loads as a case: one holding a prompt.md or a case.yaml, at any depth
    (evals/results/ is git-ignored run output, so it's left out)."""
    found = {p.parent for name in ("prompt.md", "case.yaml") for p in EVALS.rglob(name)}
    return sorted(d for d in found if d.relative_to(EVALS).parts[0] != "results")


def grader_skill(g: dict) -> str:
    """The skill a tool_used grader matches: the name before the closing quote of its input_match."""
    return re.search(r"\)\?([a-z-]+)\"$", g["input_match"]).group(1)


def is_slash(fm: dict, prompt: str) -> bool:
    skill = skill_of(fm)
    return skill in MANUAL and prompt.startswith(f"/plainspoken:{skill}")


def skill_of(fm: dict) -> str:
    tags = flow_list(fm.get("tags", ""))
    names = [t for t in tags if t in AUTO | MANUAL]
    assert "trigger" in tags and len(names) == 1, tags
    return names[0]


REWRITE_GRADERS = {"no-flagged-words.md", "em-dash-cap.md", "no-new-numbers.md", "kept-the-facts.md"}
NOT_CONTAINS = {"no-flagged-words.md", "em-dash-cap.md", "no-new-numbers.md"}
SOCIAL = {"rewrite--linkedin-post"}  # graded with the social content type's caps; the rest are articles
# Python-only or JS-only regex syntax. `claude plugin eval` runs the patterns as JavaScript and this test runs them
# through Python `re`, so a pattern must mean the same in both.
# `\d`, `\w` and `\b` (and their negations) are Unicode-aware in Python `re` but ASCII-only in JavaScript, so a
# grader spells its classes out (`[0-9]`, `[A-Za-z0-9_]`) and both runners read the same characters.
NOT_PORTABLE = ("(?i", "(?m", "(?s", "(?x", "(?a", "(?u", "(?L", "(?P", "(?#", "(?>", "\\A", "\\Z", "\\z",
                "[^]", "*+", "++", "?+", "}+", "\\p{", "\\h", "\\d", "\\D", "\\w", "\\W", "\\b", "\\B")
WORD = "A-Za-z0-9_"  # JavaScript's \w, spelled out
PY_FLAGS = {"i": re.I, "m": re.M, "s": re.S}
# Every rewrite prompt ends with this, in both arms: without it, a skill's documented extras (a numbered list of
# remaining patterns, the draft as well as the final) land in the plugin arm's reply only and trip the regex graders.
CLOSING = "Just send back the rewritten version, nothing else."


def rewrite_cases():
    for d in sorted(p for p in REWRITE.iterdir() if p.is_dir()):
        yield _case(d)


def passage(prompt: str) -> str:
    """The pasted text: the prompt's blockquote lines, without the `> ` marker."""
    return "\n".join(ln[2:] if ln.startswith("> ") else ln[1:] for ln in prompt.splitlines() if ln.startswith(">"))


def marked(text: str) -> str:
    """`text` as the drafting, longform and fix cases ask for it: between a line `<<<PIECE` and a line `PIECE>>>`."""
    return f"<<<PIECE\n{text}\nPIECE>>>"


def facts_source(d: Path, prompt: str) -> str:
    """What carries a marker case's facts: the draft its scaffold saves (evals/fix), else the brief without its line
    about the markers."""
    script = (d / "scaffold.sh").read_text(encoding="utf-8")
    m = re.search(r"<<'DRAFT'\n(.*?)\nDRAFT\n", script, re.S)
    return m.group(1) if m else "\n".join(ln for ln in prompt.splitlines() if "<<<PIECE" not in ln)


def compiled(g: dict) -> re.Pattern:
    flags = 0
    for f in g.get("flags", ""):
        flags |= PY_FLAGS[f]
    return re.compile(g["pattern"], flags)


def content_type(case: str) -> str:
    return rewrite.content_type_for(case)


_LINT_EDGE = (r"(?<![\w-])", r"(?![\w-])")


def flagged_pattern(text: str) -> str:
    """The no-flagged-words pattern for a passage, built from the lint itself: every rule-2 hard-ban word the lint
    finds in `text`, each spelling of it the lint loads, and the lint's own inflection tails, grouped by
    tail. Only the word-edge class is spelled out for JavaScript."""
    bans = load_config().lists["ban_literal"]
    hits = {w for w in bans if ban_pattern(w, True).search(text)}
    words = sorted({v for w in hits for v in spelling_variants(w)} & set(bans))
    groups: dict[str, list[str]] = {}
    for w in words:
        core = ban_pattern(w, True).pattern
        assert core.startswith(_LINT_EDGE[0]) and core.endswith(_LINT_EDGE[1]), core
        core = core[len(_LINT_EDGE[0]):-len(_LINT_EDGE[1])].replace("\\-", "-")
        stem = re.escape(w).replace("\\-", "-").replace("\\ ", "\\s+")
        stem = stem if core.startswith(stem) else stem[:-1]  # an -e word's tail includes the e
        groups.setdefault(core[len(stem):], []).append(stem)
    alts = [f"(?:{'|'.join(stems)}){tail}" if tail else "|".join(stems)
            for tail, stems in sorted(groups.items(), key=lambda kv: (not kv[0], kv[0]))]
    return f"(?<![{WORD}-])(?:{'|'.join(alts)})(?![{WORD}-])"


NOT_NAMES = {"I", "Parents", "Guardians"}  # capitalised in a passage without being a name


def proper_nouns(text: str) -> list[str]:
    """The capitalised words in a passage that don't start a sentence, a heading or a line after a salutation:
    its names, places, days and months."""
    out = []
    for m in re.finditer(r"[A-Z][A-Za-z]*", text):
        before = text[:m.start()]
        last = re.search(r"([A-Za-z0-9.!?#,])[^A-Za-z0-9.!?#,]*$", before)
        gap = before[last.end(1):] if last else ""
        initial = (last is None or last.group(1) in ".!?#" or "\n\n" in gap
                   or (last.group(1) == "," and "\n" in gap))
        if not initial and m.group(0) not in NOT_NAMES and m.group(0) not in out:
            out.append(m.group(0))
    return out


class RewriteCases(unittest.TestCase):
    def test_rewrite_cases_shape(self):
        found = list(rewrite_cases())
        self.assertEqual(len(found), 12)
        for d, fm, prompt, graders in found:
            with self.subTest(case=d.name):
                self.assertEqual(set(fm) - CASE_KEYS, set())
                self.assertEqual(fm["name"], d.name)
                self.assertTrue(d.name.startswith("rewrite--"))
                self.assertTrue(fm.get("description"))
                self.assertEqual(flow_list(fm["tags"]), ["rewrite"])
                self.assertEqual(fm["max_turns"], "8")
                self.assertEqual(flow_list(fm["allowed_tools"]), ["Read", "Glob", "Grep", "Skill"])
                self.assertEqual((d / flow_list(fm["plugins"])[0]).resolve(), REPO)
                self.assertNotIn("env", fm)
                self.assertFalse((d / "case.yaml").exists())
                self.assertTrue((d / "reference.md").is_file())
                text = passage(prompt)
                self.assertGreater(len(text.split()), 40)
                ask = "\n".join(ln for ln in prompt.splitlines() if not ln.startswith(">"))
                self.assertTrue(ask.strip())
                self.assertIsNone(re.search(r"\d", ask), "a number in the request would count as the passage's")
                self.assertEqual({name for name, _, _ in graders}, REWRITE_GRADERS)
                for name, g, _ in graders:
                    self.assertEqual(g.get("type"), "regex", name)
                    self.assertIn(g.get("target", "last_message"), {"last_message"}, name)
                    self.assertLessEqual(set(g.get("flags", "")), set(PY_FLAGS), name)
                    for token in NOT_PORTABLE:
                        self.assertNotIn(token, g["pattern"], f"{name}: {token} isn't portable JS/Python regex")
                    compiled(g)
                    if name in NOT_CONTAINS:
                        self.assertEqual(g.get("match"), "not_contains", name)
                    else:
                        self.assertNotIn("match", g, name)
                    if name == "no-flagged-words.md":
                        self.assertIn("i", g.get("flags", ""))

    def test_slash_arm_mirrors_each_rewrite_case(self):
        """evals/rewrite-slash: the same six passages and graders, asked through /plainspoken:humanize, so the arm
        measures the skill itself rather than whether a plain request starts it."""
        plain = {d.name: (fm, prompt, graders) for d, fm, prompt, graders in rewrite_cases()}
        slash = [_case(d) for d in sorted(p for p in REWRITE_SLASH.iterdir() if p.is_dir())]
        self.assertEqual(sorted(d.name for d, *_ in slash), sorted(f"{n}--slash" for n in plain))
        for d, fm, prompt, graders in slash:
            with self.subTest(case=d.name):
                pfm, pprompt, pgraders = plain[d.name.removesuffix("--slash")]
                self.assertEqual(fm["name"], d.name)
                self.assertEqual(flow_list(fm["tags"]), ["rewrite-slash"])
                self.assertEqual(prompt, f"/plainspoken:humanize {pprompt}")
                self.assertEqual(graders, pgraders)
                self.assertEqual({k: v for k, v in fm.items() if k not in {"name", "description", "tags"}},
                                 {k: v for k, v in pfm.items() if k not in {"name", "description", "tags"}})

    def test_rewrite_prompts_ask_for_the_rewrite_only(self):
        self.assertIsNone(re.search(r"\d", CLOSING))
        for d, fm, prompt, graders in rewrite_cases():
            with self.subTest(case=d.name):
                self.assertEqual(prompt.splitlines()[-1], CLOSING)
                self.assertEqual(prompt.count(CLOSING), 1)

    def test_rewrite_graders_pass_on_reference(self):
        for d, fm, prompt, graders in rewrite_cases():
            reference = (d / "reference.md").read_text(encoding="utf-8")
            text = passage(prompt)
            for name, g, _ in graders:
                with self.subTest(case=d.name, grader=name):
                    hit = compiled(g).search(reference)
                    if name in NOT_CONTAINS:
                        self.assertIsNone(hit, f"reference.md trips {name}: {hit and hit.group(0)!r}")
                    else:
                        self.assertIsNotNone(hit)
                        self.assertIsNotNone(compiled(g).search(text), "the fact must come from the passage")
                    if name in ("no-flagged-words.md", "em-dash-cap.md"):
                        self.assertIsNotNone(compiled(g).search(text), "the passage itself must fail it")

    def test_flagged_words_are_the_passage_bans(self):
        """The list is exactly the hard-ban words in the passage: it catches each one the lint finds, and nothing
        else in the passage."""
        bans = load_config().lists["ban_literal"]
        for d, fm, prompt, graders in rewrite_cases():
            text = passage(prompt)
            rx = compiled(next(g for name, g, _ in graders if name == "no-flagged-words.md"))
            hits = [m for w in bans for m in ban_pattern(w, True).finditer(text)]
            with self.subTest(case=d.name):
                self.assertGreaterEqual(len(hits), 3)
                for m in hits:
                    self.assertIsNotNone(rx.search(m.group(0)), m.group(0))
                rest = text
                for m in sorted(hits, key=lambda m: -m.start()):
                    rest = rest[:m.start()] + "x" + rest[m.end():]
                self.assertIsNone(rx.search(rest), "the grader names a word the passage doesn't hold")

    def test_flagged_words_pattern_is_built_from_the_lint(self):
        """The tails are the lint's own (no broader), and every spelling the lint loads is caught (no narrower)."""
        for d, fm, prompt, graders in rewrite_cases():
            g = next(g for name, g, _ in graders if name == "no-flagged-words.md")
            with self.subTest(case=d.name):
                self.assertEqual(g["pattern"], flagged_pattern(passage(prompt)))

    def test_graders_discriminate(self):
        """Each grader passes the reference and fails a reply that keeps the passage's fault: the flagged words and
        the em dashes are the passage's own, and dropping any one name, place, day or month fails kept-the-facts."""
        for d, fm, prompt, graders in rewrite_cases():
            reference = (d / "reference.md").read_text(encoding="utf-8")
            text = passage(prompt)
            by_name = {name: compiled(g) for name, g, _ in graders}
            with self.subTest(case=d.name):
                for name in ("no-flagged-words.md", "em-dash-cap.md"):  # not_contains: a hit fails the reply
                    self.assertIsNotNone(by_name[name].search(text), f"the passage passes {name}")
                    self.assertIsNone(by_name[name].search(reference), f"the reference fails {name}")
                kept = by_name["kept-the-facts.md"]
                names = proper_nouns(text)
                self.assertTrue(names)
                self.assertIsNotNone(kept.search(text))
                self.assertIsNotNone(kept.search(reference))
                for noun in names:
                    dropped = re.sub(re.escape(noun), "Zz", reference, flags=re.I)
                    self.assertIsNone(kept.search(dropped), f"kept-the-facts passes without {noun}")

    def test_graders_read_ascii_classes_only(self):
        """Every class a grader uses means the same in JavaScript and Python: compiled with re.ASCII (JavaScript's
        reading of \\d, \\w and \\b), each grader finds what it finds without it, on text with Unicode digits and
        letters."""
        probe = "٣ ٤٥ ½ — é Ölçü naïve Zürich 2,500 14% café—bar Riverbend\u00a0Park"
        for d, fm, prompt, graders in rewrite_cases():
            reference = (d / "reference.md").read_text(encoding="utf-8")
            for name, g, _ in graders:
                rx = compiled(g)
                ascii_rx = re.compile(g["pattern"], (rx.flags & ~re.UNICODE) | re.ASCII)
                for sample in (reference, passage(prompt), probe, reference + " ٣ " + probe):
                    with self.subTest(case=d.name, grader=name):
                        self.assertEqual([m.span() for m in rx.finditer(sample)],
                                         [m.span() for m in ascii_rx.finditer(sample)])

    def test_em_dash_pattern_is_the_cap(self):
        cfg = load_config()
        for d, fm, prompt, graders in rewrite_cases():
            cap = cfg.thresholds(default_profile(), content_type(d.name))["em_dash_max"]
            rx = compiled(next(g for name, g, _ in graders if name == "em-dash-cap.md"))
            with self.subTest(case=d.name, cap=cap):
                self.assertIsNotNone(rx.search("a — b\n" * (cap + 1)))
                self.assertIsNone(rx.search("a — b\n" * cap))

    def test_new_numbers_pattern_allows_the_passage_only(self):
        for d, fm, prompt, graders in rewrite_cases():
            text = passage(prompt)
            rx = compiled(next(g for name, g, _ in graders if name == "no-new-numbers.md"))
            nums = rewrite.numbers(text)
            with self.subTest(case=d.name):
                self.assertTrue(nums)
                self.assertIsNone(rx.search(text))
                for n in nums:  # 2,500 and 2500 are the same number, either way round
                    key = rewrite.number_key(n)
                    self.assertIsNone(rx.search(f"about {key} of them"), key)
                    if "." not in key and len(key) > 3:
                        self.assertIsNone(rx.search(f"about {int(key):,} of them"), key)
                    self.assertIsNotNone(rx.search(f"about {key}7 of them"), key)
                self.assertIsNotNone(rx.search("there were 913 of them"))

    def test_references_pass_engine_grade(self):
        """The engine grader (`eval rewrite`) agrees with the regex graders on each reference."""
        with tempfile.TemporaryDirectory() as tmp:
            for d, fm, prompt, graders in rewrite_cases():
                src = Path(tmp) / f"{d.name}.source.md"
                src.write_text(passage(prompt) + "\n", encoding="utf-8")
                g = rewrite.grade(d / "reference.md", src, default_profile(), content_type(d.name))
                own = rewrite.grade(src, src, default_profile(), content_type(d.name))
                with self.subTest(case=d.name):
                    self.assertEqual(g["verdict"], "PASS", g)
                    self.assertIn("2", own["blocks"], "the passage itself fails on its hard-ban words")


class EvalCases(unittest.TestCase):
    def test_case_files(self):
        found = list(cases())
        # Counted from the tree: every trigger folder is a case, and every case the runner would load
        # is a trigger or a rewrite case, so each one is checked by a test below.
        self.assertTrue(found)
        self.assertEqual(len(found), len([p for p in CASES.iterdir() if p.is_dir()]))
        rewrite_dirs = [p for p in (*REWRITE.iterdir(), *REWRITE_SLASH.iterdir(), *SMOKE.iterdir(),
                                    *DRAFTING[0].iterdir(), *DRAFTING[1].iterdir(), *EXTRA[0].iterdir(),
                                    *EXTRA[1].iterdir()) if p.is_dir()]
        self.assertEqual(sorted([d for d, *_ in found] + rewrite_dirs), loadable_cases())
        for d, fm, prompt, graders in found:
            with self.subTest(case=d.name):
                self.assertEqual(set(fm) - CASE_KEYS, set())
                self.assertEqual(fm["name"], d.name)
                self.assertTrue(d.name.startswith(skill_of(fm) + "--"))
                self.assertTrue(prompt)
                self.assertEqual((d / flow_list(fm["plugins"])[0]).resolve(), REPO)
                self.assertFalse((d / "case.yaml").exists())
                self.assertTrue(graders)
                for name, g, _ in graders:
                    self.assertIn(g.get("type"), GRADER_TYPES, name)

    def test_drafting_cases_pair_up_and_mark_the_piece(self):
        """evals/drafting and evals/drafting-hooks: the same briefs, the second with the nudge and the rule switched on
        by its scaffold. Each asks for the piece between markers, so `eval rewrite-delta` lints the writing, not a
        skill's report around it."""
        plain = sorted(p.name.removeprefix("drafting--") for p in DRAFTING[0].iterdir() if p.is_dir())
        hooks = sorted(p.name.removeprefix("drafting-hooks--") for p in DRAFTING[1].iterdir() if p.is_dir())
        self.assertEqual(plain, hooks)
        self.assertGreaterEqual(len(plain), 12)
        for folder, tag in ((DRAFTING[0], "drafting"), (DRAFTING[1], "drafting-hooks")):
            for d in sorted(p for p in folder.iterdir() if p.is_dir()):
                _, fm, prompt, graders = _case(d)
                with self.subTest(case=d.name):
                    self.assertEqual(fm["name"], d.name)
                    self.assertEqual(flow_list(fm["tags"]), [tag])
                    self.assertIn("<<<PIECE", prompt)
                    self.assertIn("scaffold_script: scaffold.sh", (d / "case.yaml").read_text(encoding="utf-8"))
                    script = (d / "scaffold.sh").read_text(encoding="utf-8")
                    self.assertIn("git init", script)
                    self.assertEqual("[nudge]" in script, tag == "drafting-hooks")
                    self.assertEqual({n for n, _, _ in graders}, {"kept-the-facts.md"})  # new numbers: eval rewrite-delta
                    for name, g, _ in graders:
                        rx = compiled(g)
                        if name == "kept-the-facts.md":
                            self.assertTrue(rx.search(marked(facts_source(d, prompt))),
                                            "the brief itself carries every kept fact")
                        else:
                            self.assertIsNone(rx.search(passage(prompt).replace("> - ", "")),
                                              "the brief's own numbers are allowed")

    def test_drafting_fact_graders_take_numbers_in_words(self):
        """A piece that spells a kept number out ("Forty stalls") keeps the fact, so the grader passes it (#47)."""
        words = {"10": "ten", "15": "fifteen", "22": "twenty-two", "40": "forty"}
        checked = 0
        for folder in DRAFTING:
            for d in sorted(p for p in folder.iterdir() if p.is_dir()):
                _, _, prompt, graders = _case(d)
                kept = compiled(next(g for n, g, _ in graders if n == "kept-the-facts.md"))
                source = facts_source(d, prompt)
                for digits, word in words.items():
                    if re.search(rf"\b{digits}\b", source) and rf"\b(?:{digits}|" in kept.pattern:
                        with self.subTest(case=d.name, number=digits):
                            spelt = re.sub(rf"\b{digits}\b", word.capitalize(), source)
                            self.assertTrue(kept.search(marked(spelt)))
                        checked += 1
        self.assertEqual(checked, 8)

    def test_longform_and_fix_cases(self):
        """evals/longform (long pieces from notes) and evals/fix (a stiff draft saved by the scaffold, fixed in place):
        both with the nudge and the rule on, both asking for the piece between markers."""
        for folder, tag in ((EXTRA[0], "longform"), (EXTRA[1], "fix")):
            found = sorted(p for p in folder.iterdir() if p.is_dir())
            self.assertGreaterEqual(len(found), 3)
            for d in found:
                _, fm, prompt, graders = _case(d)
                with self.subTest(case=d.name):
                    self.assertEqual(fm["name"], d.name)
                    self.assertTrue(d.name.startswith(tag + "--"))
                    self.assertEqual(flow_list(fm["tags"]), [tag])
                    self.assertIn("<<<PIECE", prompt)
                    script = (d / "scaffold.sh").read_text(encoding="utf-8")
                    self.assertIn("[nudge]", script)
                    self.assertEqual("<<'DRAFT'" in script, tag == "fix")
                    kept = compiled(next(g for n, g, _ in graders if n == "kept-the-facts.md"))
                    self.assertTrue(kept.search(marked(facts_source(d, prompt))))

    def test_marker_graders_read_the_piece_only(self):
        """Every case that asks for the piece between markers grades only that piece: a report around it that
        repeats the facts doesn't pass a piece that left them out, and neither does the prompt's own mention of the
        markers."""
        for folder in (*DRAFTING, *EXTRA):
            for d in sorted(p for p in folder.iterdir() if p.is_dir()):
                _, fm, prompt, graders = _case(d)
                facts = facts_source(d, prompt)
                for name, g, _ in graders:
                    if g.get("type") != "regex" or g.get("match", "contains") != "contains":
                        continue
                    rx = compiled(g)
                    with self.subTest(case=d.name, grader=name):
                        self.assertEqual(g.get("target", "last_message"), "last_message")
                        self.assertTrue(g["pattern"].startswith(r"(?:^|\n)<<<PIECE"), "anchor to the opening marker")
                        self.assertTrue(rx.search(f"Report: done.\n\n{marked(facts)}\n\nmerge: PASS"))
                        self.assertTrue(rx.search(marked(facts).replace("\n", "\r\n")))
                        self.assertIsNone(rx.search(f"{facts}\n{marked('A short piece.')}\n{facts}"),
                                          "the report around the piece counts")
                        self.assertIsNone(rx.search(f"{prompt}\n{facts}"), "the prompt's marker mention counts")
                        self.assertIsNone(rx.search(f"<<<PIECE\n{facts}"), "a piece with no closing marker counts")

    def test_smoke_cases_run_every_skill_once_by_slash(self):
        """evals/smoke: one case per skill that does real work on a saved draft (paid; `--tag smoke`)."""
        skills = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md"))
        found = [_case(d) for d in sorted(p for p in SMOKE.iterdir() if p.is_dir())]
        self.assertEqual([d.name for d, *_ in found], [f"{s}--smoke" for s in skills])
        for d, fm, prompt, graders in found:
            skill = d.name.removesuffix("--smoke")
            with self.subTest(case=d.name):
                self.assertEqual(set(fm) - CASE_KEYS, set())
                self.assertEqual(fm["name"], d.name)
                self.assertEqual(flow_list(fm["tags"]), ["smoke", skill])
                self.assertTrue(prompt.startswith(f"/plainspoken:{skill}"))
                self.assertEqual((d / flow_list(fm["plugins"])[0]).resolve(), REPO)
                self.assertTrue(graders)
                for name, g, _ in graders:
                    if g.get("type") == "tool_used":  # only "never used": a skill that changes nothing (doctor)
                        self.assertIn(g.get("tool"), ("Write", "Edit"), name)
                        self.assertEqual((g.get("min"), g.get("max")), ("0", "0"), name)
                        continue
                    self.assertEqual(g.get("type"), "regex", name)
                    rx = compiled(g)
                    # A kept-the-facts grader is meant to match the passage; its not_contains partner fails an echo.
                    if g.get("match") != "not_contains" and not name.startswith("kept-"):
                        self.assertIsNone(rx.search(prompt), f"{name}: the request itself satisfies it")

    def test_skill_graders_match_only_their_skill(self):
        for d, fm, _, graders in cases():
            for name, g, _ in graders:
                if g.get("type") != "tool_used":
                    continue
                with self.subTest(case=d.name, grader=name):
                    self.assertEqual(g["tool"], "Skill")
                    rx = re.compile(g["input_match"])
                    skill = grader_skill(g)
                    self.assertTrue(rx.search(f'{{"skill": "plainspoken:{skill}"}}'))
                    self.assertTrue(rx.search(f'{{"skill":"{skill}"}}'))
                    for other in (AUTO | MANUAL) - {skill}:
                        self.assertIsNone(rx.search(f'{{"skill": "plainspoken:{other}"}}'), other)

    def test_polarity_counts(self):
        pos, neg, slash = {}, {}, {}
        for d, fm, prompt, graders in cases():
            skill = skill_of(fm)
            for _, g, _ in graders:
                if g.get("type") == "tool_used" and grader_skill(g) == skill:
                    never = g.get("min") == "0" and g.get("max") == "0"
                    (neg if never else pos)[skill] = (neg if never else pos).get(skill, 0) + 1
            if prompt.startswith(f"/plainspoken:{skill}"):
                slash[skill] = slash.get(skill, 0) + 1
        for skill in AUTO:
            self.assertGreaterEqual(pos.get(skill, 0), 2 if skill in {"check", "humanize"} else 3, skill)
            self.assertGreaterEqual(neg.get(skill, 0), 1 if skill in {"check", "humanize"} else 2, skill)
        for skill in MANUAL:
            self.assertGreaterEqual(neg.get(skill, 0), 1, skill)
            self.assertGreaterEqual(slash.get(skill, 0), 1, skill)
            self.assertEqual(pos.get(skill, 0), 0, f"{skill} is manual-only: no fires grader")

    def test_manual_natural_negatives_assert_no_invocation(self):
        """A manual skill can't start on its own (its `disable-model-invocation` flag), so a
        natural-language case for it would pass on the flag alone. Each one must assert the outcome: exactly one
        `tool_used` grader on Skill, min 0 and max 0, that matches that skill whether or not it's namespaced."""
        found: dict[str, list[str]] = {}
        for d, fm, prompt, graders in cases():
            skill = skill_of(fm)
            if skill not in MANUAL or is_slash(fm, prompt):
                continue
            found.setdefault(skill, []).append(d.name)
            with self.subTest(case=d.name):
                self.assertFalse(prompt.lstrip().startswith("/"), "a natural-language case, not a slash command")
                self.assertNotIn(f"plainspoken:{skill}", prompt)
                never = [g for _, g, _ in graders if g.get("type") == "tool_used" and g.get("tool") == "Skill"
                         and grader_skill(g) == skill and g.get("min") == "0" and g.get("max") == "0"]
                self.assertEqual(len(never), 1, "one grader asserting the skill was never invoked")
                rx = re.compile(never[0]["input_match"])
                self.assertTrue(rx.search(f'{{"skill": "plainspoken:{skill}"}}'))
                self.assertTrue(rx.search(f'{{"skill":"{skill}"}}'))
        self.assertEqual(set(found), MANUAL, "every manual skill has a natural-language negative")

    def test_no_case_needs_write_access_or_scaffolding(self):
        for d, fm, prompt, _ in cases():
            tools = set(flow_list(fm.get("allowed_tools", "[]")))
            # Only a manual skill's slash case may ask for the scoped CLI grant; no case asks for Write or Edit.
            allowed = READ_ONLY | ({CLI_GRANT} if is_slash(fm, prompt) else set())
            self.assertLessEqual(tools, allowed, d.name)
            self.assertNotIn("env", fm, d.name)

    def test_slash_cases_ask_for_the_cli(self):  # every manual skill runs the CLI at load
        for d, fm, prompt, _ in cases():
            if is_slash(fm, prompt):
                self.assertIn(CLI_GRANT, flow_list(fm.get("allowed_tools", "[]")), d.name)

    def test_slash_regexes_match_a_reply_line_not_an_echo(self):
        for d, fm, prompt, graders in cases():
            if not is_slash(fm, prompt):
                continue
            for name, g, _ in graders:
                if g.get("type") != "regex":
                    continue
                with self.subTest(case=d.name, grader=name):
                    self.assertTrue(g["pattern"].startswith(r"(?:^|\n)"), "anchor the pattern to a line start")
                    rx = re.compile(g["pattern"], re.I if "i" in g.get("flags", "") else 0)  # JS and Python agree here
                    self.assertIsNone(rx.search(prompt), "the request itself satisfies the pattern")

    def test_slash_regexes_still_match_the_reply_they_grade(self):
        replies = {
            "setup--slash": ["plainspoken is set up like this now:\n\n- writing nudge: off\n- drafting rule: off\n"
                             "- lint after edits: on",
                             "| Writing nudge | off |\n| Drafting rule | off |"],
            "copy-audit--slash": ["Copy audit: shown in reply — PARTIAL\n\n1. ...",
                                  "**Copy audit:** .plainspoken/drafts/harbour-row.md — **FAIL**"],
            "register-check--slash": ["Register check: pasted text (follow-up)\n...\n\n"
                                      "Flags only. You decide what to send."],
            "voice--slash": ["Three modes:\n\n- **build** <samples...>: make a profile.\n- **apply** <file>: rewrite."
                             "\n- **check** <file>: compare.",
                             "1. `/plainspoken:voice build` makes one\n2. `apply` rewrites\n3. `check` compares"],
            "claims--slash": ["claims: INCOMPLETE\nStopped at step 1: ...\n\n"
                              "Checked against saved sources only. You decide what to publish.",
                              "> *Checked against saved sources only. You decide what to publish.*"],
            "reader-value--slash": ["Which mode do you want?\n\n- `outline` <brief>: set the contract before "
                                    "drafting.\n- `deliver` <draft>: check the draft against it.",
                                    "Two modes:\n\n- **outline** <brief>: set the contract.\n- **deliver** <draft>: "
                                    "check the draft.",
                                    "1. `/plainspoken:reader-value outline` sets it\n2. `deliver` checks it"],
            "kaizen--slash": ["Which mode?\n\n- `review`: the proposals waiting.\n- `calibrate`: propose changes.\n"
                              "- `dismiss` <file>: a wrong finding.",
                              "1. **review** shows the queue\n2. **calibrate** proposes",
                              "- `/plainspoken:kaizen review`\n- `/plainspoken:kaizen calibrate`"],
            "doctor--slash": ["- python3: ok (3.12.1)\n- WARN git: no git on PATH\n\nUnverified: Bash permission",
                              "| python3 | ok |\n| Bash permission | not checked |"],
        }
        echoes = {"copy-audit--slash": "Here's the copy audit: it fails on proof.",
                  "doctor--slash": "All checks are fine.\n- python3: ok\n- Bash permission: unverified",
                  "voice--slash": "Which mode do you want: build, apply or check?",
                  "reader-value--slash": "Which mode do you want: outline or deliver?",  # one line: not the menu
                  "claims--slash": "I checked the claims against the saved sources.",
                  "kaizen--slash": "Do you want to review the proposals or calibrate?"}
        self.assertLessEqual(set(replies) | set(echoes), {c[0].name for c in cases()})
        for d, fm, prompt, graders in cases():
            for name, g, _ in graders:
                if g.get("type") != "regex" or d.name not in replies:
                    continue
                rx = re.compile(g["pattern"], re.I if "i" in g.get("flags", "") else 0)
                for reply in replies[d.name]:
                    self.assertIsNotNone(rx.search(reply), f"{d.name}: {reply!r}")
                if d.name in echoes:
                    self.assertIsNone(rx.search(echoes[d.name]), d.name)

    def test_adapt_slash_follows_the_argument_hint(self):  # <file or pasted text> <platform...>
        _, fm, prompt, _ = next(c for c in cases() if c[0].name == "adapt--slash")
        args = prompt.removeprefix("/plainspoken:adapt").strip()
        self.assertTrue(args.startswith('"'), "the source comes first")
        self.assertRegex(args, r'"\s+linkedin bluesky$')
