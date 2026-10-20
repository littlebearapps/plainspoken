"""Drafting and ablation harness (Phase 6): draft the same briefs under five arms with `claude -p`.

    python3 scripts/dev/draft_runs.py --models opus,sonnet --out DIR [--briefs evals/briefs] [--arms a,b]
                                      [--runner claude] [--concurrency 1] [--timeout 900] [--dry-run]

Arms (every run starts from a new, empty temp folder, removed afterwards, with the brief on stdin):

- `none`: `--safe-mode --tools ""`, the brief as is (the baseline the mining uses);
- `plugin`: `--plugin-dir <repo>`, the prompt `/plainspoken:write ` + the brief, `--allowedTools "Bash(python3 *)"
  Read Write Edit`;
- `plugin+style`: `plugin` + `--settings <file>` holding `{"outputStyle": "plainspoken"}`;
- `plugin+brief`: `plugin` + `.plainspoken/config.toml` with `[brief] enabled = true` in the folder;
- `plugin+banlist`: `plugin` + one line appended to the prompt listing rule 2's hard-ban words, read from
  `data/rules.toml` when the prompt is built. Nothing under `skills/` changes.

Every command also carries `--model M --strict-mcp-config --no-session-persistence --output-format json`. Every
`plugin*` arm also carries `--setting-sources project,local`: without it the run loads the user's whole setup (their
CLAUDE.md, installed plugins and their SessionStart hooks, their output style), so `none` against `plugin` would
measure that setup as much as the plugin. With it the `--plugin-dir` skills still load, and nothing of the user's
does. (`--safe-mode`, which `none` uses, can't be used here: it hides the `--plugin-dir` skills too.) The `--settings`
file of `plugin+style` is a command-line source, so it still applies.

A good reply is saved as `<out>/<arm>/<model id>/<brief stem>.md`, the model id being the one `modelUsage` reports.
For `none` the draft is the reply text, byte for byte. For the `plugin*` arms the draft is the file the `write`
skill saves in `.plainspoken/drafts/` (its reply is only a note about that file); a plugin run that leaves no `.md`
there, or more than one, is an error and nothing is saved: grading its pointer note as a short, clean draft would
flatter the arm. Every run
appends one line to `<out>/runs.jsonl` (arm, model asked for, brief, saved path, model reported, notional cost,
error), so a re-run with the same `--out` skips each run whose draft is already saved, before the model id is known.
An error (an error reply, a draft that can't be found or saved) is logged there and not saved; the run goes on.
Two forms of one model (`opus` and `claude-opus-5-5`) answer as one model id, so they'd share a path: the first run
to claim it saves there, and the other is an error row, never an overwrite. Errors and reported models are scrubbed
of the panel's API key before they're logged.

The runs are on the Claude subscription: the CLI reports a notional cost and nothing is billed. Exit codes: 0 every
run has a draft · 1 a run errored · 2 bad usage or input. Tests inject a fake runner; nothing here is a test seam
for the network.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import tomllib
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "lib") not in sys.path:
    sys.path.insert(0, str(REPO / "lib"))

from plainspoken.adapters.llm_panel import (  # noqa: E402
    DEFAULT_PANEL, ERROR_MAX, PanelError, child_env, default_runner_for, load_panel, parse_cli, scrubber)
from plainspoken.report import write_atomic  # noqa: E402

RULES = REPO / "data" / "rules.toml"
BRIEFS = REPO / "evals" / "briefs"
INDEX = "runs.jsonl"
SETTINGS = "plainspoken-settings.json"
DRAFTS = Path(".plainspoken") / "drafts"
WRITE = "/plainspoken:write "
ARM_ORDER = ("none", "plugin", "plugin+style", "plugin+brief", "plugin+banlist")
SHORT_MODELS = ("opus", "sonnet", "haiku")
_MODEL = re.compile(r"(opus|sonnet|haiku|claude-[a-z0-9][a-z0-9.-]*)")
_PATH_UNSAFE = re.compile(r"[^A-Za-z0-9._+\[\]-]")
BASE_ARGS = ("--strict-mcp-config", "--no-session-persistence", "--output-format", "json")
NONE_ARGS = ("--safe-mode", "--tools", "")
PLUGIN_SOURCES = ("--setting-sources", "project,local")
PLUGIN_TOOLS = ("--allowedTools", "Bash(python3 *)", "Read", "Write", "Edit")
MAX_CONCURRENCY = 4


@dataclass(frozen=True)
class Arm:
    name: str
    plugin: bool = False
    style: bool = False
    brief: bool = False
    banlist: bool = False


@dataclass(frozen=True)
class Run:
    arm: str
    model: str  # the name asked for (`opus`, `sonnet`, `haiku` or a full id), passed to --model as given
    brief: Path

    @property
    def key(self) -> str:
        return f"{self.arm}|{self.model}|{self.brief.stem}"


def arms() -> dict[str, Arm]:
    """The five arms, in the fixed order."""
    return {
        "none": Arm("none"),
        "plugin": Arm("plugin", plugin=True),
        "plugin+style": Arm("plugin+style", plugin=True, style=True),
        "plugin+brief": Arm("plugin+brief", plugin=True, brief=True),
        "plugin+banlist": Arm("plugin+banlist", plugin=True, banlist=True),
    }


def briefs(folder: Path) -> list[Path]:
    return sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix == ".md")


def plan(briefs_dir: Path, arm_names: Iterable[str], models: Iterable[str], out: Path) -> list[Run]:
    """Every (arm, model, brief) run, arm by arm, then model, then brief. `out` is where they'll be saved (the plan
    doesn't depend on it). Raises ValueError for an unknown arm, a bad model name or a folder with no briefs."""
    known = arms()
    names, models = list(arm_names), list(models)
    if not names:
        raise ValueError("no arms given")
    for a in names:
        if a not in known:
            raise ValueError(f"unknown arm {a!r} (the arms are {', '.join(ARM_ORDER)})")
    if not models:
        raise ValueError("no models given")
    for m in models:
        if not _MODEL.fullmatch(m):
            raise ValueError(f"unknown model {m!r} (use {', '.join(SHORT_MODELS)} or a full claude-… id)")
    if not Path(briefs_dir).is_dir():
        raise ValueError(f"{briefs_dir}: no such folder")
    found = briefs(briefs_dir)
    if not found:
        raise ValueError(f"{briefs_dir}: no .md briefs")
    names = list(dict.fromkeys(names))
    models = list(dict.fromkeys(models))
    return [Run(a, m, b) for a in names for m in models for b in found]


def banlist() -> list[str]:
    """Rule 2's hard-ban words, as `data/rules.toml` holds them now (the BLOCK list, then the metaphorical-use list)."""
    lists = tomllib.loads(Path(RULES).read_text(encoding="utf-8")).get("lists", {})
    words = [w for k in ("ban_literal", "ban_qualified") for w in lists.get(k, []) if isinstance(w, str)]
    return list(dict.fromkeys(words))


def prompt(run: Run) -> str:
    """The text sent on stdin."""
    arm = arms()[run.arm]
    text = run.brief.read_text(encoding="utf-8")
    if not arm.plugin:
        return text
    p = WRITE + text
    if arm.banlist:
        p += ("" if p.endswith("\n") else "\n") + "Don't use any of these words: " + ", ".join(banlist()) + ".\n"
    return p


def command(run: Run, repo: Path, workdir: Path, *, exe: str = "claude") -> list[str]:
    """The `claude -p` argument list for one run from `workdir`."""
    arm = arms()[run.arm]
    args = [exe, "-p", "--model", run.model, *BASE_ARGS]
    if not arm.plugin:
        return args + list(NONE_ARGS)
    args += ["--plugin-dir", str(repo), *PLUGIN_SOURCES]
    if arm.style:
        args += ["--settings", str(Path(workdir) / SETTINGS)]
    return args + list(PLUGIN_TOOLS)


def prepare(run: Run, workdir: Path) -> None:
    """Write the arm's files into the (empty) run folder."""
    arm = arms()[run.arm]
    workdir = Path(workdir)
    if arm.style:
        (workdir / SETTINGS).write_text(json.dumps({"outputStyle": "plainspoken"}) + "\n", encoding="utf-8")
    if arm.brief:
        (workdir / ".plainspoken").mkdir(exist_ok=True)
        (workdir / ".plainspoken" / "config.toml").write_text("[brief]\nenabled = true\n", encoding="utf-8")


# ---------------------------------------------------------------- the index

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_index(out: Path) -> dict[str, dict]:
    """The newest good line for each run key; lines that don't parse (a torn last line) are ignored. A missing
    index is empty; any other OSError (`out` is a file, say) propagates for the caller to report."""
    latest: dict[str, dict] = {}
    try:
        raw = (Path(out) / INDEX).read_bytes()
    except FileNotFoundError:
        return latest
    for line in raw.split(b"\n"):
        try:
            d = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(d, dict) and isinstance(d.get("key"), str):
            latest[d["key"]] = d
    return latest


def done(entry: dict | None, out: Path) -> bool:
    """A run is done when its newest line saved a draft that's still there."""
    if not entry or entry.get("error") is not None or not isinstance(entry.get("path"), str):
        return False
    return (Path(out) / entry["path"]).is_file()


class _Index:
    """Appends one JSON line per run with a single `os.write` on an O_APPEND descriptor (whole lines under threads)."""

    def __init__(self, out: Path):
        path = Path(out) / INDEX
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        self.fd = os.open(path, flags, 0o644)
        if path.stat().st_size:  # a torn last line from an interrupted run must not swallow the next one
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    os.write(self.fd, b"\n")

    def append(self, row: dict) -> None:
        data = (json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n").encode("ascii")
        if os.write(self.fd, data) != len(data):
            raise OSError("short write to the run index")

    def close(self) -> None:
        os.close(self.fd)


# ---------------------------------------------------------------- one run

def model_dir(models: tuple[str, ...], asked: str) -> str:
    """The folder name for a reply: the one model `modelUsage` reports; with several (a helper model ran too), the one
    whose id holds the name asked for; else all of them joined with `+`. Made safe for a path."""
    pick = list(models)
    if len(pick) > 1:
        match = [m for m in pick if asked.lower() in m.lower()]
        pick = match if len(match) == 1 else pick
    name = "+".join(pick) or "unknown-model"
    return _PATH_UNSAFE.sub("_", name)


def _written_drafts(workdir: Path) -> list[Path]:
    folder = Path(workdir) / DRAFTS
    return sorted(p for p in folder.glob("*.md") if p.is_file()) if folder.is_dir() else []


class Claims:
    """Which run saved (or is saving) each draft path. Two forms of one model (`opus` and `claude-opus-5-5`) answer
    as the same model id, so they'd save to one path: the first run to claim it keeps it, and the other is an error
    row instead of a silent overwrite. Seeded from the index, so a resume keeps the earlier owner."""

    def __init__(self, latest: dict[str, dict]):
        self.lock = threading.Lock()
        self.owner = {e["path"]: k for k, e in latest.items()
                      if e.get("error") is None and isinstance(e.get("path"), str)}

    def claim(self, rel: str, key: str) -> str | None:
        """None when `key` may save to `rel` (now claimed for it), else the key that holds it."""
        with self.lock:
            other = self.owner.setdefault(rel, key)
        return None if other == key else other


def _save(path: Path, data: bytes) -> None:
    write_atomic(path, data)  # a unique temp file in the folder, so two writers never share one


def _line(text: str) -> str:
    return (text.strip().splitlines() or [""])[0]


def execute(run: Run, repo: Path, out: Path, runner: Callable, *, exe: str = "claude",
            scrub: Callable[[str], str] = lambda s: s, claims: Claims | None = None) -> dict:
    """Run one draft and save it; returns the index row. Never raises: a failed call, a missing draft file, a path
    another run claimed or a draft that can't be saved is an error row. The row's error and reported model pass
    through `scrub` (the panel key never reaches the index), then the error is cut to one line of ERROR_MAX."""
    row = {"key": run.key, "arm": run.arm, "model": run.model, "brief": run.brief.stem, "path": None,
           "model_reported": "", "cost_usd": 0.0, "error": None, "from": None, "at": ""}
    workdir = Path(tempfile.mkdtemp(prefix="plainspoken-draft-"))
    try:
        try:
            prepare(run, workdir)
            done_ = runner(command(run, repo, workdir, exe=exe), input=prompt(run), cwd=str(workdir))
        except FileNotFoundError:
            row["error"] = f"{exe}: the claude command isn't installed or on PATH"
        except subprocess.TimeoutExpired:
            row["error"] = "claude-cli: timed out"
        except Exception as e:  # noqa: BLE001 (a process boundary: whatever it raises becomes one line)
            row["error"] = f"{type(e).__name__}: {(str(e).strip().splitlines() or [''])[0]}"
        else:
            parsed = parse_cli(done_.returncode, done_.stdout, done_.stderr)
            row["model_reported"] = "+".join(parsed.models)
            row["cost_usd"] = round(parsed.cost_usd, 6)
            row["error"] = parsed.error
            if parsed.error is None:
                _keep(run, parsed, workdir, Path(out), row, claims or Claims({}))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    row["model_reported"] = scrub(row["model_reported"])
    if row["error"] is not None:
        row["error"] = _line(scrub(row["error"]))[:ERROR_MAX] or "error"
    row["at"] = _now()
    return row


def _keep(run: Run, parsed, workdir: Path, out: Path, row: dict, claims: Claims) -> None:
    """Save a good reply's draft into `out` and fill in the row; any failure becomes the row's error."""
    try:
        if arms()[run.arm].plugin:
            written = _written_drafts(workdir)
            if len(written) != 1:
                row["error"] = (f"the write skill left {len(written)} draft files in {DRAFTS.as_posix()}/ "
                                "(expected exactly 1); nothing saved")
                return
            data, source = written[0].read_bytes(), written[0].relative_to(workdir).as_posix()
        else:
            data, source = parsed.text.encode("utf-8"), "reply"
        rel = Path(run.arm) / model_dir(parsed.models, run.model) / f"{run.brief.stem}.md"
        other = claims.claim(rel.as_posix(), run.key)
        if other is not None:
            row["error"] = (f"{rel.as_posix()} is already saved by run {other} (two forms of one model?); nothing "
                            "saved")
            return
        _save(out / rel, data)
    except Exception as e:  # noqa: BLE001 (an unreadable draft, a lone surrogate, a full disk: one error line)
        row["error"] = f"can't save the draft ({type(e).__name__}: {(str(e).strip().splitlines() or [''])[0]})"
        return
    row["path"], row["from"] = rel.as_posix(), source


def run_all(runs: list[Run], repo: Path, out: Path, runner: Callable, *, concurrency: int = 1,
            exe: str = "claude", log: Callable[[str], None] = lambda s: None,
            scrub: Callable[[str], str] = lambda s: s) -> tuple[list[dict], int]:
    """Run every run not already done in `out`; returns (rows written this time, runs skipped)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    latest = read_index(out)
    todo = [r for r in runs if not done(latest.get(r.key), out)]
    skipped = len(runs) - len(todo)
    if not todo:
        return [], skipped
    claims = Claims({k: e for k, e in latest.items() if done(e, out)})
    index = _Index(out)
    lock = threading.Lock()

    def work(run: Run) -> dict:
        row = execute(run, repo, out, runner, exe=exe, scrub=scrub, claims=claims)
        with lock:
            index.append(row)
            log(f"{run.key}: " + (f"error: {row['error']}" if row["error"] else f"saved {row['path']}"))
        return row

    try:
        with ThreadPoolExecutor(max_workers=min(concurrency, len(todo))) as pool:
            rows = list(pool.map(work, todo))
    finally:
        index.close()
    return rows, skipped


# ---------------------------------------------------------------- CLI

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="draft_runs.py", description="Draft the eval briefs under the ablation arms.")
    p.add_argument("--briefs", type=Path, default=BRIEFS, help="folder of .md briefs (default: evals/briefs)")
    p.add_argument("--arms", default=",".join(ARM_ORDER), help="comma-separated arms (default: all five)")
    p.add_argument("--models", required=True, help="comma-separated models: opus, sonnet, haiku")
    p.add_argument("--out", type=Path, required=True, help="folder for the drafts and runs.jsonl")
    p.add_argument("--runner", default="claude", help="the claude command to run (default: claude)")
    p.add_argument("--concurrency", type=int, default=1, help=f"runs at once, 1 to {MAX_CONCURRENCY} (default 1)")
    p.add_argument("--timeout", type=float, default=900, help="seconds a run may take (default 900)")
    p.add_argument("--dry-run", action="store_true", help="list the runs and their commands; call nothing")
    return p


def _fail(reason: str, code: int = 2) -> int:
    print(f"draft_runs: {reason}", file=sys.stderr)
    return code


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def main(argv: list[str] | None = None, *, runner: Callable | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:  # argparse has printed the usage line
        return 0 if e.code == 0 else 2
    if not 1 <= args.concurrency <= MAX_CONCURRENCY:
        return _fail(f"--concurrency must be 1 to {MAX_CONCURRENCY}")
    if not args.timeout > 0:
        return _fail("--timeout must be more than 0")
    try:
        runs = plan(args.briefs, _split(args.arms), _split(args.models), args.out)
    except (ValueError, OSError) as e:
        return _fail(str(e))
    if args.out.exists() and not args.out.is_dir():
        return _fail(f"--out {args.out}: not a folder")
    if args.dry_run:
        try:
            latest = read_index(args.out)
        except OSError as e:
            return _fail(f"can't read {args.out / INDEX} ({e.strerror or type(e).__name__})")
        placeholder = Path("<new temp folder>")
        for run in runs:
            note = "  (skip: draft saved)" if done(latest.get(run.key), args.out) else ""
            cmd = shlex.join(command(run, REPO, placeholder, exe=args.runner))
            print(f"{run.arm}  {run.model}  {run.brief.name}{note}: {cmd} < {prompt_note(run)}")
        print(f"{len(runs)} runs; nothing called, nothing written")
        return 0
    try:
        key_env = load_panel(DEFAULT_PANEL).key_env
    except (PanelError, OSError):
        key_env = "OPENROUTER_API_KEY"
    if runner is None:  # the claude child never gets the panel's API key
        runner = default_runner_for(args.timeout, child_env(os.environ, key_env))
    try:
        rows, skipped = run_all(runs, REPO, args.out, runner, concurrency=args.concurrency, exe=args.runner,
                                log=lambda s: print(s, file=sys.stderr),
                                scrub=scrubber((os.environ.get(key_env) or "").strip()))
    except OSError as e:
        return _fail(f"can't write to {args.out} ({e.strerror or e})")
    errors = sum(1 for r in rows if r["error"])
    cost = sum(r["cost_usd"] for r in rows)
    print(f"ran {len(rows)}, skipped {skipped}, errors {errors}; notional cost US${cost:.2f} (subscription, "
          "nothing billed)")
    return 1 if errors else 0


def prompt_note(run: Run) -> str:
    arm = arms()[run.arm]
    what = str(run.brief)
    if arm.plugin:
        what = f"'{WRITE.strip()}' + {what}" + (" + the rule 2 ban line" if arm.banlist else "")
    return what


if __name__ == "__main__":
    sys.exit(main())
