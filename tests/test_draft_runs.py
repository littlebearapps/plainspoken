"""Drafting and ablation harness: `scripts/dev/draft_runs.py` and `scripts/dev/ablation_table.py`.

Every test uses a fake runner: nothing here spawns `claude` or touches the network."""
import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import threading
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from plainspoken import config
from scripts.dev import ablation_table as at
from scripts.dev import draft_runs as dr

REPO = Path(__file__).resolve().parents[1]
BASE = ["--strict-mcp-config", "--no-session-persistence", "--output-format", "json"]
PLUGIN_TOOLS = ["--allowedTools", "Bash(python3 *)", "Read", "Write", "Edit"]
SOURCES = ["--setting-sources", "project,local"]


def cli_json(result="A draft.\n", models=("claude-opus-5-5",), cost=0.25, **over) -> str:
    body = {"type": "result", "is_error": False, "result": result, "total_cost_usd": cost,
            "usage": {"input_tokens": 10, "output_tokens": 20},
            "modelUsage": {m: {"inputTokens": 10, "outputTokens": 20} for m in models}}
    body.update(over)
    return json.dumps(body)


def skill_saves(args, cwd, text="# The draft the skill saved\n", name="draft.md"):
    """What the write skill does in a plugin run: save its draft under .plainspoken/drafts/."""
    if "--plugin-dir" in args:
        d = Path(cwd) / ".plainspoken" / "drafts"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")


class FakeRunner:
    """Answers every call with `stdout` (or `answer(args, input, cwd)` when given) and records what it was asked.
    Without `answer`, a plugin-arm call saves one draft file the way the write skill does (`saves=False` turns that
    off)."""

    def __init__(self, stdout=None, returncode=0, stderr="", error=None, answer=None, saves=True):
        self.stdout = stdout if stdout is not None else cli_json()
        self.returncode, self.stderr, self.error, self.answer = returncode, stderr, error, answer
        self.saves = saves
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, args, *, input, cwd):
        files = sorted(str(p.relative_to(cwd)) for p in Path(cwd).rglob("*") if p.is_file())
        with self.lock:
            self.calls.append({"args": list(args), "input": input, "cwd": cwd, "files": files})
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer(args, input, cwd)
        if self.saves:
            skill_saves(args, cwd)
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)


def _tree_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(folder)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.briefs = root / "briefs"
        self.briefs.mkdir()
        (self.briefs / "alpha.md").write_text("# Brief: alpha\n\nWrite 3 short paragraphs about kettles.\n",
                                              encoding="utf-8")
        (self.briefs / "beta.md").write_text("# Brief: beta\n\nAn email declining a meeting.\n", encoding="utf-8")
        (self.briefs / "notes.txt").write_text("not a brief\n", encoding="utf-8")
        self.out = root / "out"
        self.work = root / "work"
        self.work.mkdir()

    def run_main(self, argv, runner=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = dr.main(argv, runner=runner)
        return code, stdout.getvalue(), stderr.getvalue()

    def index(self) -> list[dict]:
        path = self.out / dr.INDEX
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ArmTests(Base):
    def test_arms_exact_set(self):
        self.assertEqual(list(dr.arms()), ["none", "plugin", "plugin+style", "plugin+brief", "plugin+banlist"])
        self.assertEqual(dr.ARM_ORDER, tuple(dr.arms()))
        self.assertEqual(at.ARM_ORDER, dr.ARM_ORDER)
        for name, arm in dr.arms().items():
            self.assertEqual(arm.name, name)

    def test_command_per_arm(self):
        brief = self.briefs / "alpha.md"
        text = brief.read_text(encoding="utf-8")
        for model in ("opus", "sonnet", "haiku"):
            head = ["claude", "-p", "--model", model, *BASE]
            want = {
                "none": head + ["--safe-mode", "--tools", ""],
                "plugin": head + ["--plugin-dir", str(REPO), *SOURCES, *PLUGIN_TOOLS],
                "plugin+style": head + ["--plugin-dir", str(REPO), *SOURCES, "--settings",
                                        str(self.work / dr.SETTINGS), *PLUGIN_TOOLS],
                "plugin+brief": head + ["--plugin-dir", str(REPO), *SOURCES, *PLUGIN_TOOLS],
                "plugin+banlist": head + ["--plugin-dir", str(REPO), *SOURCES, *PLUGIN_TOOLS],
            }
            for arm, args in want.items():
                with self.subTest(arm=arm, model=model):
                    run = dr.Run(arm, model, brief)
                    self.assertEqual(dr.command(run, REPO, self.work), args)
        self.assertEqual(dr.prompt(dr.Run("none", "opus", brief)), text)
        self.assertEqual(dr.prompt(dr.Run("plugin", "opus", brief)), "/plainspoken:write " + text)
        self.assertEqual(dr.prompt(dr.Run("plugin+style", "opus", brief)), "/plainspoken:write " + text)
        self.assertEqual(dr.prompt(dr.Run("plugin+brief", "opus", brief)), "/plainspoken:write " + text)
        self.assertEqual(dr.command(dr.Run("none", "opus", brief), REPO, self.work, exe="/opt/claude")[0],
                         "/opt/claude")

    def test_banlist_built_at_run_time(self):
        brief = self.briefs / "alpha.md"
        text = brief.read_text(encoding="utf-8")
        skills_before = _tree_hash(REPO / "skills")
        p = dr.prompt(dr.Run("plugin+banlist", "opus", brief))
        self.assertTrue(p.startswith("/plainspoken:write " + text))
        extra = p[len("/plainspoken:write " + text):]
        self.assertEqual(extra.strip().count("\n"), 0, "one line appended")
        rules = tomllib.loads((REPO / "data" / "rules.toml").read_text(encoding="utf-8"))
        for word in (rules["lists"]["ban_literal"][0], rules["lists"]["ban_literal"][-1], "delve"):
            self.assertIn(word, extra)
        # read at run time: a different rules file gives a different line
        fake = Path(self.tmp.name) / "rules.toml"
        fake.write_text('[lists]\nban_literal = ["zorbleflux"]\nban_qualified = ["quuxify"]\n', encoding="utf-8")
        with mock.patch.object(dr, "RULES", fake):
            p2 = dr.prompt(dr.Run("plugin+banlist", "opus", brief))
        self.assertIn("zorbleflux", p2)
        self.assertIn("quuxify", p2)
        self.assertNotIn("delve", p2)
        # a full run of the arm writes nothing under skills/ and nowhere but the out folder
        runner = FakeRunner()
        code, _, _ = self.run_main(["--briefs", str(self.briefs), "--arms", "plugin+banlist", "--models", "opus",
                                    "--out", str(self.out)], runner=runner)
        self.assertEqual(code, 0)
        self.assertIn("delve", runner.calls[0]["input"])
        self.assertEqual(_tree_hash(REPO / "skills"), skills_before)
        for arm in ("none", "plugin", "plugin+style", "plugin+brief"):
            self.assertNotIn("delve", dr.prompt(dr.Run(arm, "opus", brief)))

    def test_brief_arm_writes_config(self):
        brief = self.briefs / "alpha.md"
        for arm in dr.ARM_ORDER:
            with self.subTest(arm=arm):
                work = Path(tempfile.mkdtemp(dir=self.tmp.name))
                dr.prepare(dr.Run(arm, "opus", brief), work)
                files = sorted(str(p.relative_to(work)) for p in work.rglob("*") if p.is_file())
                if arm == "plugin+brief":
                    self.assertEqual(files, [".plainspoken/config.toml"])
                    cfg = tomllib.loads((work / ".plainspoken" / "config.toml").read_text(encoding="utf-8"))
                    self.assertEqual(cfg, {"brief": {"enabled": True}})
                    self.assertTrue(config.brief_enabled(work))
                elif arm == "plugin+style":
                    self.assertEqual(files, [dr.SETTINGS])
                    data = json.loads((work / dr.SETTINGS).read_text(encoding="utf-8"))
                    self.assertEqual(data, {"outputStyle": "plainspoken"})
                else:
                    self.assertEqual(files, [])


class RunTests(Base):
    def argv(self, *extra):
        return ["--briefs", str(self.briefs), "--out", str(self.out), *extra]

    def test_plan_order_and_briefs(self):
        runs = dr.plan(self.briefs, ["none", "plugin"], ["opus", "sonnet"], self.out)
        self.assertEqual([(r.arm, r.model, r.brief.name) for r in runs], [
            ("none", "opus", "alpha.md"), ("none", "opus", "beta.md"),
            ("none", "sonnet", "alpha.md"), ("none", "sonnet", "beta.md"),
            ("plugin", "opus", "alpha.md"), ("plugin", "opus", "beta.md"),
            ("plugin", "sonnet", "alpha.md"), ("plugin", "sonnet", "beta.md")])
        for bad in (["nope"], []):
            with self.subTest(arms=bad), self.assertRaises(ValueError):
                dr.plan(self.briefs, bad, ["opus"], self.out)
        with self.assertRaises(ValueError):
            dr.plan(self.briefs, ["none"], ["gpt-5"], self.out)

    def test_every_run_from_a_new_empty_folder(self):
        runner = FakeRunner()
        code, _, _ = self.run_main(self.argv("--arms", "none,plugin+brief", "--models", "opus"), runner=runner)
        self.assertEqual(code, 0)
        cwds = [c["cwd"] for c in runner.calls]
        self.assertEqual(len(set(cwds)), 4)
        for c in runner.calls:
            self.assertFalse(Path(c["cwd"]).exists(), "the temp folder is removed afterwards")
            want = [".plainspoken/config.toml"] if "--plugin-dir" in c["args"] else []
            self.assertEqual(c["files"], want)

    def test_saves_reply_by_reported_model(self):
        reply = "# Kettles\n\nA draft with  two spaces and a trailing newline.\n\n"
        runner = FakeRunner(cli_json(result=reply, models=("claude-haiku-4-5", "claude-opus-5-5")))
        code, out, _ = self.run_main(self.argv("--arms", "none", "--models", "opus"), runner=runner)
        self.assertEqual(code, 0, out)
        saved = self.out / "none" / "claude-opus-5-5" / "alpha.md"
        self.assertEqual(saved.read_bytes(), reply.encode("utf-8"))
        self.assertTrue((self.out / "none" / "claude-opus-5-5" / "beta.md").is_file())
        rows = self.index()
        self.assertEqual(len(rows), 2)
        row = rows[0]
        self.assertEqual((row["arm"], row["model"], row["brief"]), ("none", "opus", "alpha"))
        self.assertEqual(row["path"], "none/claude-opus-5-5/alpha.md")
        self.assertEqual(row["model_reported"], "claude-haiku-4-5+claude-opus-5-5", "every model reported is kept")
        self.assertEqual(row["cost_usd"], 0.25)
        self.assertIsNone(row["error"])
        self.assertEqual(row["from"], "reply")
        self.assertEqual(runner.calls[0]["input"], (self.briefs / "alpha.md").read_text(encoding="utf-8"))

    def test_error_reply_logged_not_saved(self):
        cases = [
            FakeRunner(cli_json(is_error=True, result="Not logged in")),
            FakeRunner(cli_json(result="")),
            FakeRunner("", returncode=1, stderr="boom"),
            FakeRunner(error=subprocess.TimeoutExpired(["claude"], 5)),
            FakeRunner(error=FileNotFoundError("claude")),
        ]
        for runner in cases:
            with self.subTest(runner=runner.stdout[:40] or repr(runner.error)):
                if self.out.exists():
                    for p in sorted(self.out.rglob("*"), reverse=True):
                        p.unlink() if p.is_file() else p.rmdir()
                code, _, err = self.run_main(self.argv("--arms", "none", "--models", "opus"), runner=runner)
                self.assertEqual(code, 1)
                self.assertEqual(len(runner.calls), 2, "the run carries on after an error")
                self.assertEqual([p for p in self.out.rglob("*.md")], [])
                rows = self.index()
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(r["error"] and r["path"] is None for r in rows))
                self.assertIn("error", err)

    def test_resume_skips_existing_drafts(self):
        def by_model(args, input, cwd):  # each short name answers as its own model id
            model = args[args.index("--model") + 1]
            skill_saves(args, cwd)
            return subprocess.CompletedProcess(args, 0, cli_json(models=(f"claude-{model}-9",)), "")
        argv = self.argv("--arms", "none,plugin", "--models", "opus,sonnet")
        runner = FakeRunner(answer=by_model)
        self.assertEqual(self.run_main(argv, runner=runner)[0], 0)
        self.assertEqual(len(runner.calls), 8)
        self.assertEqual(len(list(self.out.rglob("*.md"))), 8)
        again = FakeRunner(answer=by_model)
        code, out, _ = self.run_main(argv, runner=again)
        self.assertEqual(code, 0)
        self.assertEqual(again.calls, [])
        self.assertIn("skipped 8", out)
        # a draft deleted by hand is drafted again; an errored run is retried; a torn last line is ignored
        first = self.index()[0]
        (self.out / first["path"]).unlink()
        with open(self.out / dr.INDEX, "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": dr.Run("plugin", "sonnet", self.briefs / "beta.md").key, "arm": "plugin",
                                "model": "sonnet", "brief": "beta", "path": None, "model_reported": "",
                                "cost_usd": 0, "error": "claude-cli: timed out", "from": None, "at": "x"}) + "\n")
            f.write('{"key": "torn')
        third = FakeRunner(answer=by_model)
        code, out, _ = self.run_main(argv, runner=third)
        self.assertEqual(code, 0)
        self.assertEqual(len(third.calls), 2)
        self.assertTrue((self.out / first["path"]).is_file())
        fourth = FakeRunner(answer=by_model)
        self.assertEqual(self.run_main(argv, runner=fourth)[0], 0)
        self.assertEqual(fourth.calls, [])

    def test_default_runner_drops_the_panel_key(self):
        seen = {}

        def fake_runner_for(timeout, env=None):
            seen["env"] = env
            return FakeRunner()
        with mock.patch.object(dr, "default_runner_for", fake_runner_for), \
                mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-or-secret", "HOME_TEST_VAR": "kept"}):
            self.run_main(self.argv("--arms", "none", "--models", "opus"))
        self.assertIsNotNone(seen["env"])
        self.assertNotIn("OPENROUTER_API_KEY", seen["env"])
        self.assertEqual(seen["env"]["HOME_TEST_VAR"], "kept")

    def test_dry_run_lists_runs_no_calls(self):
        runner = FakeRunner()
        code, out, _ = self.run_main(self.argv("--arms", "none,plugin+style", "--models", "opus", "--dry-run"),
                                     runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(runner.calls, [])
        self.assertFalse(self.out.exists(), "a dry run writes nothing")
        lines = [ln for ln in out.splitlines() if ln.startswith(("none", "plugin"))]
        self.assertEqual(len(lines), 4)
        self.assertTrue(any("--safe-mode" in ln and "alpha.md" in ln for ln in lines))
        self.assertTrue(any("--settings" in ln and "--plugin-dir" in ln for ln in lines))

    def test_plugin_arm_saves_written_draft(self):
        def answer(args, input, cwd):
            d = Path(cwd) / ".plainspoken" / "drafts"
            d.mkdir(parents=True)
            (d / "kettles.md").write_text("# The draft the skill saved\n", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, cli_json(result="Saved to .plainspoken/drafts/kettles.md"),
                                               "")
        runner = FakeRunner(answer=answer)
        code, _, _ = self.run_main(self.argv("--arms", "plugin", "--models", "opus"), runner=runner)
        self.assertEqual(code, 0)
        saved = self.out / "plugin" / "claude-opus-5-5" / "alpha.md"
        self.assertEqual(saved.read_text(encoding="utf-8"), "# The draft the skill saved\n")
        self.assertEqual(self.index()[0]["from"], ".plainspoken/drafts/kettles.md")

    def test_plugin_arm_without_one_draft_file_is_an_error(self):
        def two(args, input, cwd):
            skill_saves(args, cwd, name="a.md")
            skill_saves(args, cwd, name="b.md")
            return subprocess.CompletedProcess(args, 0, cli_json(result="Saved two drafts"), "")
        for label, runner, count in [("none saved", FakeRunner(cli_json(result="Saved to x.md"), saves=False), 0),
                                     ("two saved", FakeRunner(answer=two), 2)]:
            with self.subTest(label):
                out = Path(self.tmp.name) / label.replace(" ", "-")
                code, _, err = self.run_main(["--briefs", str(self.briefs), "--out", str(out), "--arms", "plugin",
                                              "--models", "opus"], runner=runner)
                self.assertEqual(code, 1)
                self.assertEqual(list(out.rglob("*.md")), [], "the pointer reply is never saved as a draft")
                rows = [json.loads(x) for x in (out / dr.INDEX).read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(rows), 2)
                for row in rows:
                    self.assertIsNone(row["path"])
                    self.assertIn(f"left {count} draft files", row["error"])
                    self.assertEqual(row["model_reported"], "claude-opus-5-5")
        # the none arm still saves its reply text
        code, _, _ = self.run_main(self.argv("--arms", "none", "--models", "opus"),
                                   runner=FakeRunner(cli_json(result="Just the reply\n"), saves=False))
        self.assertEqual(code, 0)
        self.assertEqual((self.out / "none" / "claude-opus-5-5" / "alpha.md").read_text(encoding="utf-8"),
                         "Just the reply\n")

    def test_unsavable_reply_is_an_error_row(self):
        runner = FakeRunner(cli_json(result="A draft \ud800 with a lone surrogate"))
        self.assertIn("\\ud800", runner.stdout)
        code, _, err = self.run_main(self.argv("--arms", "none", "--models", "opus"), runner=runner)
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)
        self.assertEqual(list(self.out.rglob("*.md")), [])
        rows = self.index()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIsNone(row["path"])
            self.assertIn("can't save the draft (UnicodeEncodeError", row["error"])
        # an OSError while saving (the model folder's name is taken by a file) is an error row too
        (self.out / "plugin").mkdir()
        (self.out / "plugin" / "claude-opus-5-5").write_text("in the way", encoding="utf-8")
        code, _, err = self.run_main(self.argv("--arms", "plugin", "--models", "opus"), runner=FakeRunner())
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)
        bad = [r for r in self.index() if r["arm"] == "plugin"]
        self.assertEqual(len(bad), 2)
        self.assertTrue(all("can't save the draft" in r["error"] for r in bad))

    def test_two_forms_of_one_model_never_share_a_draft(self):
        """opus and claude-opus-5-5 both answer as claude-opus-5-5: the first run to claim a path saves there and the
        other is an error row, never a silent overwrite; no `.part` file is left behind."""
        for concurrency in ("1", "4"):
            with self.subTest(concurrency=concurrency):
                code, _, _ = self.run_main(self.argv("--arms", "none", "--models", "opus,claude-opus-5-5",
                                                     "--concurrency", concurrency), runner=FakeRunner())
                self.assertEqual(code, 1)
                saved = sorted(p.relative_to(self.out).as_posix() for p in self.out.rglob("*.md"))
                self.assertEqual(saved, ["none/claude-opus-5-5/alpha.md", "none/claude-opus-5-5/beta.md"])
                left = [p.name for p in self.out.rglob("*") if p.is_file() and p.suffix not in (".md", ".jsonl")]
                self.assertEqual(left, [], "no temp file is left behind")
                rows = self.index()[-4:]
                bad = [r for r in rows if r["error"]]
                self.assertEqual(len(bad), 2)
                for r in bad:
                    self.assertIn(f"none/claude-opus-5-5/{r['brief']}.md", r["error"])
                    self.assertIn("already", r["error"])
                    self.assertIsNone(r["path"])
                # a re-run skips the saved drafts and still refuses the other form
                again = FakeRunner()
                self.assertEqual(self.run_main(self.argv("--arms", "none", "--models", "opus,claude-opus-5-5"),
                                               runner=again)[0], 1)
                self.assertEqual(len(again.calls), 2)
                for p in sorted(self.out.rglob("*"), reverse=True):
                    p.unlink() if p.is_file() else p.rmdir()

    def test_errors_are_scrubbed(self):
        secret = "sk-or-v1-secret-value"
        runner = FakeRunner("", returncode=1, stderr=f"auth failed for {secret}")
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": secret}):
            code, _, err = self.run_main(self.argv("--arms", "none", "--models", "opus"), runner=runner)
        self.assertEqual(code, 1)
        raw = (self.out / dr.INDEX).read_text(encoding="utf-8")
        self.assertNotIn(secret, raw)
        self.assertNotIn(secret, err)
        self.assertIn("auth failed for ***", raw)

    def test_out_naming_a_file(self):
        target = Path(self.tmp.name) / "a-file"
        target.write_text("x", encoding="utf-8")
        for extra in (["--dry-run"], []):
            with self.subTest(extra=extra):
                runner = FakeRunner()
                code, out, err = self.run_main(["--briefs", str(self.briefs), "--out", str(target), "--models",
                                                "opus", *extra], runner=runner)
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith("draft_runs: "), err)
                self.assertNotIn("Traceback", err)
                self.assertEqual(runner.calls, [])
                self.assertEqual(target.read_text(encoding="utf-8"), "x")

    def test_usage_errors(self):
        for argv in (["--briefs", str(self.briefs), "--models", "opus"],
                     self.argv("--models", "opus", "--arms", "nope"),
                     self.argv("--models", "gpt"),
                     self.argv("--models", "opus", "--concurrency", "9"),
                     ["--briefs", str(self.briefs / "missing"), "--out", str(self.out), "--models", "opus"]):
            with self.subTest(argv=argv):
                runner = FakeRunner()
                code, _, err = self.run_main(argv, runner=runner)
                self.assertEqual(code, 2)
                self.assertEqual(runner.calls, [])
                self.assertNotIn("Traceback", err)

    def test_concurrency_runs_every_job_once(self):
        runner = FakeRunner()
        code, _, _ = self.run_main(self.argv("--arms", ",".join(dr.ARM_ORDER), "--models", "opus",
                                             "--concurrency", "4"), runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(len(runner.calls), 10)
        self.assertEqual(len(self.index()), 10)
        self.assertEqual(len({r["key"] for r in self.index()}), 10)


class TableTests(Base):
    def test_ablation_table_counts(self):
        drafts = Path(self.tmp.name) / "drafts"
        clean = "# Kettles\n\nI boil water in a kettle every morning, and it takes about 3 minutes.\n"
        banned = "# Kettles\n\nThis is a crucial kettle. It boils water fast enough for me.\n"
        dashes = "# Kettles\n\nOne — two — three — four — five. It boils water.\n"
        numbers = "# Kettles\n\nIt boils 1,700 millilitres in 4 minutes, and I like that.\n"
        files = {
            "none/claude-opus-5-5": {"alpha": clean, "beta": banned},
            "plugin/claude-opus-5-5": {"alpha": dashes, "beta": numbers},
            "plugin+banlist/claude-opus-5-5": {"alpha": clean},
        }
        for folder, items in files.items():
            d = drafts / folder
            d.mkdir(parents=True)
            for stem, text in items.items():
                (d / f"{stem}.md").write_text(text, encoding="utf-8")
        (drafts / dr.INDEX).write_text("", encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = at.main(["--drafts", str(drafts), "--briefs", str(self.briefs), "--profile", "default"])
        self.assertEqual(code, 0, stderr.getvalue())
        rows = {}
        for line in stdout.getvalue().splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 7 and cells[0] in dr.ARM_ORDER:
                rows[cells[0]] = cells[1:]
        self.assertEqual(list(rows), ["none", "plugin", "plugin+banlist"], "the fixed arm order")
        # model, drafts, mean words, BLOCK-bearing, em dash over cap, new numbers
        self.assertEqual(rows["none"][0], "claude-opus-5-5")
        self.assertEqual(rows["none"][1], "2")
        self.assertEqual(rows["none"][3:], ["1", "0", "0"])
        self.assertEqual(rows["plugin"][1], "2")
        self.assertEqual(rows["plugin"][4:], ["1", "1"])
        self.assertEqual(rows["plugin+banlist"][1:2] + rows["plugin+banlist"][3:], ["1", "0", "0", "0"])
        self.assertRegex(rows["none"][2], r"^\d+(\.\d)?$")

    def test_ablation_table_bad_input(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = at.main(["--drafts", str(Path(self.tmp.name) / "nope"), "--briefs", str(self.briefs),
                            "--profile", "default"])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_ablation_table_draft_with_no_brief_exit_2(self):
        drafts = Path(self.tmp.name) / "drafts"
        (drafts / "none" / "claude-opus-5-5").mkdir(parents=True)
        (drafts / "none" / "claude-opus-5-5" / "alpha.md").write_text("I boil water.\n", encoding="utf-8")
        (drafts / "none" / "claude-opus-5-5" / "gamma.md").write_text("I boil water.\n", encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = at.main(["--drafts", str(drafts), "--briefs", str(self.briefs), "--profile", "default"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(stderr.getvalue().startswith("ablation_table: gamma.md: no source named gamma.*"),
                        stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
