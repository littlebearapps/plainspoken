"""The `eval` command group: Phase 6 evals. `__main__` only registers it (`add_parser`) and dispatches (`run`).

`eval golden validate [--dir DIR] [--require-counts]`: load and check the golden set, prove no case text is quoted
in a held-out root, and print the per-group counts. Exit 0 valid · 1 problems (one `problem:` line each) · 2 a
missing folder, a file that isn't the format, or a ruleset that won't load.

`eval panel check [--panel FILE]`: compare the panel's billed models with the gateway's free catalogue (one GET, no
key). Exit 0 all listed at their configured prices · 1 problems (an unknown slug, a price more than 25% off, or an
unreachable catalogue) · 2 a panel file that won't load.

`eval panel estimate [--panel FILE] [--models a,b] PROMPT_FILE...`: a per-model table of prompts, estimated input
tokens and estimated cost, and the billed total. Free: nothing is sent. Exit 0 · 2 a bad panel, model name or prompt
file.

`eval judges --models a,b [--golden DIR] [--panel FILE] [--out DIR] [--group G] [--status S] [--dry-run] [--yes]
[--max-cost-usd N] [--concurrency N]`: put every golden case to every named judge model and measure them. Prints the
estimate first; `--dry-run` stops there (nothing sent, nothing written). OpenRouter models are billed: they need
`--yes` and run under `--max-cost-usd` (default 5), one budget per batch: a budget stop also holds back the unbilled
claude-cli calls until the resume. Run files go to `--out`, default `.plainspoken/evals/judges-<UTC time>/` in the
project: `run.json`, `replies.jsonl` (resumable: re-run with the same `--out`), `summary.json` and `report.md` (each
records every transport's sampling: OpenRouter at temperature 0, the CLI at its default); the run folder is made only
once the run is allowed, so a dry or refused run writes nothing. Exit 0 the run finished and every model meets the
accept bar · 1 refused without `--yes`, stopped early, or the bar is missed · 2 bad input.

`eval claims [--model M] [--golden DIR] [--out DIR] [--status S] [--dry-run] [--max-cost-usd N] [--concurrency N]
[--price-in X --price-out Y]`: put every CL golden case to the claims checker on one Claude model (`claude -p` on the
subscription; no other vendor) and score its verdict on each labelled claim. Prints the plan and the notional
estimate first; `--dry-run` stops there (nothing sent, nothing written). Nothing is billed, but the run stops before
the notional spend the CLI reports would pass `--max-cost-usd` (default 1). Run files go to `--out`, default
`.plainspoken/evals/claims-<UTC time>/`: `run.json`, `replies.jsonl` (resumable), `summary.json` and `report.md`.
Exit 0 every case scored · 1 stopped early, or a call failed or a reply couldn't be scored (re-run to retry) · 2 bad
input.

`eval rewrite DRAFT [--source FILE] [--profile P] [--content-type T] [--json]`: grade one rewrite with the engine
(`rewrite.grade`): any lint BLOCK, em dashes over the content type's cap, or a number the source doesn't have fails
it. Without `--source` the number check is skipped and says so. Free: no model is called. Exit 0 PASS · 1 FAIL · 2 a
missing or unreadable file, or a bad profile.

`eval first-call RESULT [--expect CALL] [--json]`: the first engine call (`run.py <subcommand>`) in each run of a
`claude plugin eval` run made with `--keep-temp` (RESULT: its `aggregate-result.json` or `--json` file), or in one
`trace.jsonl`, against the call the skill runs first (`evaltrace.FIRST_CALL`; `--expect` for a lone trace, default
`profile`). It says what each run called first, which the smoke cases' `*-first` graders can't. Free. Exit 0 every
run starts with its call · 1 one doesn't, or its trace is gone · 2 an unreadable file.

`eval blind build --spec FILE --out DIR [--words 350] --seed N`: turn a spec of matched texts (JSON list, or TOML
`[[pair]]`, of `{id, human, generated, model[, brief]}`; paths relative to the spec) into unlabelled pairs: normalised,
cut to whole sentences, A/B by a seeded, balanced shuffle. Writes `pairs.jsonl`, `key.json`, `build.json` (with each
side's spelling-marker counts) and `.heldout` to `--out`. Exit 0 · 1 an item's excerpts differ by more than 15%, or one
spells AU/GB and the other US (named; nothing written) · 2 bad input, or `--out` already holds a build.

`eval blind form --out DIR`: write `form.md` and `answers.csv` for human raters (the author sends them; the plugin
never contacts anyone). An `answers.csv` that already exists is kept. Exit 0 · 2 no build.

`eval blind run --out DIR --models a,b [--panel FILE] [--dry-run] [--yes] [--max-cost-usd N] [--concurrency N]`: ask
every pair, in both orders, of every named panel model. Same rules as `eval judges`: estimate first, `--dry-run` writes
nothing, OpenRouter models need `--yes` and stop at `--max-cost-usd` (default 5), re-run to resume. Replies go to
`DIR/replies.jsonl`. Exit 0 every call made and answered · 1 refused without `--yes`, stopped early, or a call failed
(re-run to retry it) · 2 bad input.

`eval blind score --out DIR [--answers CSV]`: score the panel's replies (tier 2, a proxy) and the raters' answers
(tier 1), print the report and write `score.json` and `score.md`. A pair and order with no reply or answer is missing,
kept apart from the errors; a reply whose key isn't a pair of the build is named in a warning. Exit 0 · 2 no build (or
an `--out` that isn't a folder), nothing to score, or a bad answers file.

`eval judges-report --run DIR [--min 0.8]`: print a run's report and apply the accept bar (TPR and TNR at least
`--min` on the all-cases split, errors at most 10%, every case run) to the run's models. Exit 0 every model meets it
· 1 one misses it (stderr names the group and model) · 2 a missing or unreadable run.

`eval lint-rate --drafts DIR [--profile P]`: the share of the `.md`/`.txt` drafts in DIR and its subfolders (hidden ones
skipped; a blind build's drafts folder is often one subfolder per model) with no lint BLOCK (the `rewrite.grade_many`
BLOCK result), with its 95% Wilson interval. Free. Exit 0 · 2 a missing folder, no drafts, a bad profile or a draft the
lint can't read.

`eval goodhart [--history FILE]`: the anti-Goodhart report over the eval history (`evalhistory`): a flag when, between
two consecutive blind runs of one tier, the lint pass rate on their drafts rose by 0.10 or more while readers didn't
improve (the `plainspoken_judged_human` intervals overlap, or the later one is entirely below). Each blind run takes the
latest lint-rate entry on its drafts at or before it in the file (else the first after it, before the next blind run); a
pair with no distinct measurement is a note, not compared, as is a blind entry with no value. Exit 0 no flag, or not
enough history · 1 a flag · 2 a `--history` file that doesn't exist.

History: `eval judges` and `eval judges-report` (unless the run stopped early, and never twice for one scoring of a
run at one `--min`), `eval blind score` (tier 2 from the non-Anthropic models only; nothing for a tier with no valid
judgement) and `eval lint-rate` each append to `<project>/.plainspoken/evals/history.jsonl` once their own result is
written. A history failure prints one `plainspoken: eval history skipped: …` line on stderr and never changes the
command's output or exit code. Never a traceback."""
import argparse
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from plainspoken import (blind, blind_score, config, evalclaims, evalhistory, evaljudges, evaltrace, golden, kaizen,
                         rewrite)
from plainspoken import evalmetrics as em
from plainspoken.adapters import llm_panel
from plainspoken.doc import CONTENT_TYPES
from plainspoken.registry import load_config


def _first_line(e: BaseException) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


def _fail(cmd: str, msg: str, code: int = 2) -> int:
    print(f"plainspoken: eval {cmd}: {msg}", file=sys.stderr)
    return code


def add_parser(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    ev = sub.add_parser("eval", help="evals: the golden set and the judge, rewrite and blind-reader measurements")
    es = ev.add_subparsers(dest="eval_cmd", required=True)
    gd = es.add_parser("golden", help="the held-out golden set the judges are measured against")
    gs = gd.add_subparsers(dest="golden_cmd", required=True)
    gv = gs.add_parser("validate", help="check the golden set's format, labels and held-out rule; print counts")
    gv.add_argument("--dir", type=Path, default=golden.DEFAULT_DIR,
                    help="the golden-set folder (default: the plugin's evals/golden/)")
    gv.add_argument("--require-counts", action="store_true",
                    help=f"also require at least {golden.MIN_CASES} cases per group and "
                         f"{golden.MIN_PER_LABEL} of each label")
    pn = es.add_parser("panel", help="the model panel the judges and blind readers run on")
    ps = pn.add_subparsers(dest="panel_cmd", required=True)
    pc = ps.add_parser("check", help="check the panel's models and prices against the gateway's free catalogue")
    pc.add_argument("--panel", type=Path, default=llm_panel.DEFAULT_PANEL,
                    help="the panel file (default: the plugin's evals/panel.toml)")
    pe = ps.add_parser("estimate", help="estimate what sending these prompts to the panel would cost (free)")
    pe.add_argument("--panel", type=Path, default=llm_panel.DEFAULT_PANEL,
                    help="the panel file (default: the plugin's evals/panel.toml)")
    pe.add_argument("--models", help="comma-separated panel model names (default: every model)")
    pe.add_argument("prompts", nargs="+", type=Path, metavar="PROMPT_FILE")
    jd = es.add_parser("judges", help="put the golden set to panel judges and measure them (OpenRouter models are "
                                      "paid: --yes)")
    jd.add_argument("--models", required=True, help="comma-separated panel model names")
    jd.add_argument("--golden", type=Path, default=golden.DEFAULT_DIR,
                    help="the golden-set folder (default: the plugin's evals/golden/)")
    jd.add_argument("--panel", type=Path, default=llm_panel.DEFAULT_PANEL,
                    help="the panel file (default: the plugin's evals/panel.toml)")
    jd.add_argument("--out", type=Path, help="the run folder (default: .plainspoken/evals/judges-<UTC time>/); "
                                             "re-run with the same folder to resume")
    jd.add_argument("--group", help=f"comma-separated judge groups ({', '.join(golden.JUDGE_GROUPS)}; default: all)")
    jd.add_argument("--status", help=f"comma-separated label statuses ({', '.join(golden.STATUSES)}; default: all)")
    jd.add_argument("--dry-run", action="store_true", help="print the estimate only: nothing sent, nothing written")
    jd.add_argument("--yes", action="store_true", help="allow the billed (OpenRouter) calls")
    jd.add_argument("--max-cost-usd", type=float, default=5.0,
                    help="stop before billed spend in the run folder would pass this (default 5); one budget per "
                         "batch, so the stop also holds back the unbilled claude-cli calls until you resume")
    jd.add_argument("--concurrency", type=int, default=4, help="calls in flight at once (default 4)")
    _claims_parser(es)
    rd = es.add_parser("rewrite-delta", help="lint-count both arms of a `claude plugin eval` rewrite run (needs "
                                             "--keep-temp; free)")
    rd.add_argument("result", type=Path, metavar="RESULT", help="the run's aggregate-result.json (or its --json file)")
    rd.add_argument("--profile", help="the voice profile (default: the project's, else the plugin default)")
    rd.add_argument("--json", action="store_true", help="print the rows and summary as JSON")
    rd.add_argument("--save", type=Path, help="write each graded piece to DIR/<case>/<arm>-<run>.md")
    fc = es.add_parser("first-call", help="the first engine call in each run of a `claude plugin eval` run (needs "
                                          "--keep-temp; free)")
    fc.add_argument("result", type=Path, metavar="RESULT",
                    help="the run's aggregate-result.json (or its --json file), or one trace.jsonl")
    fc.add_argument("--expect", default="profile", metavar="CALL",
                    help="for one trace.jsonl: the run.py call it should start with (default: profile)")
    fc.add_argument("--json", action="store_true", help="print the rows as JSON")
    rw = es.add_parser("rewrite", help="grade one rewrite: lint BLOCKs, the em-dash cap and new numbers (free)")
    rw.add_argument("draft", type=Path, metavar="DRAFT")
    rw.add_argument("--source", type=Path, help="the text it rewrites: a number not in it fails the draft")
    rw.add_argument("--profile", help="the voice profile (default: the project's, else the plugin default)")
    rw.add_argument("--content-type", choices=CONTENT_TYPES, default="article",
                    help="sets the caps, e.g. one em dash for social (default: article)")
    rw.add_argument("--json", action="store_true", help="print the grade as JSON")
    _blind_parser(es)
    jr = es.add_parser("judges-report", help="print a judge-validation run's report and apply the accept bar")
    jr.add_argument("--run", type=Path, required=True, help="the run folder `eval judges` wrote")
    jr.add_argument("--min", type=float, default=evaljudges.MIN_RATE,
                    help=f"the TPR and TNR each model needs on every group (default {evaljudges.MIN_RATE})")
    lr = es.add_parser("lint-rate", help="the share of a folder's drafts with no lint BLOCK (free; recorded in the "
                                         "eval history)")
    lr.add_argument("--drafts", type=Path, required=True, metavar="DIR",
                    help="the folder of .md/.txt drafts (subfolders included)")
    lr.add_argument("--profile", help="the voice profile (default: the project's, else the plugin default)")
    gh = es.add_parser("goodhart", help="the anti-Goodhart report: the lint improving while blind readers don't "
                                        "notice")
    gh.add_argument("--history", type=Path, metavar="FILE",
                    help="the history file (default: .plainspoken/evals/history.jsonl in the project)")


def _claims_parser(es: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    cl = es.add_parser("claims", help="put the CL golden cases to the claims checker on one Claude model and score "
                                      "its verdicts (claude -p; nothing billed)")
    cl.add_argument("--model", default="claude-opus-5-5",
                    help="the Claude model `claude -p --model` runs (default claude-opus-5-5, the agent's model)")
    cl.add_argument("--golden", type=Path, default=golden.DEFAULT_DIR,
                    help="the golden-set folder (default: the plugin's evals/golden/)")
    cl.add_argument("--out", type=Path, help="the run folder (default: .plainspoken/evals/claims-<UTC time>/); "
                                             "re-run with the same folder to resume")
    cl.add_argument("--status", help=f"comma-separated label statuses ({', '.join(golden.STATUSES)}; default: all)")
    cl.add_argument("--dry-run", action="store_true", help="print the plan and the estimate only: nothing sent, "
                                                           "nothing written")
    cl.add_argument("--max-cost-usd", type=float, default=1.0,
                    help="stop before the notional spend recorded in the run folder, plus the next calls' estimate, "
                         "would pass this (default 1)")
    cl.add_argument("--concurrency", type=int, default=4, help="calls in flight at once (default 4)")
    cl.add_argument("--price-in", type=float, help="list price, US$ per million input tokens, for the estimate "
                                                    "(default: the model's, when it's known)")
    cl.add_argument("--price-out", type=float, help="list price, US$ per million output tokens, for the estimate")


def _blind_parser(es: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    bl = es.add_parser("blind", help="the blind reader test: unlabelled pairs of a person's writing and plainspoken "
                                     "output, for people (tier 1) and the model panel (tier 2, a proxy)")
    bs = bl.add_subparsers(dest="blind_cmd", required=True)
    bb = bs.add_parser("build", help="build the unlabelled, length-matched pairs from a spec")
    bb.add_argument("--spec", type=Path, required=True, metavar="FILE",
                    help="JSON list (or TOML [[pair]]) of {id, human, generated, model[, brief]}")
    bb.add_argument("--out", type=Path, required=True, metavar="DIR", help="a new folder for the pairs and the key")
    bb.add_argument("--words", type=int, default=350,
                    help="each excerpt's minimum words, whole sentences (default 350)")
    bb.add_argument("--seed", type=int, required=True, help="the A/B shuffle's seed (required: pick one on purpose)")
    bf = bs.add_parser("form", help="write form.md and answers.csv for human raters (you send them)")
    bf.add_argument("--out", type=Path, required=True, metavar="DIR", help="the folder `eval blind build` wrote")
    br = bs.add_parser("run", help="ask the panel models every pair in both orders (OpenRouter models are paid: "
                                   "--yes); exits 1 when a call failed (re-run to retry it)")
    br.add_argument("--out", type=Path, required=True, metavar="DIR", help="the folder `eval blind build` wrote; "
                                                                           "re-run with it to resume")
    br.add_argument("--models", required=True, help="comma-separated panel model names")
    br.add_argument("--panel", type=Path, default=llm_panel.DEFAULT_PANEL,
                    help="the panel file (default: the plugin's evals/panel.toml)")
    br.add_argument("--dry-run", action="store_true", help="print the estimate only: nothing sent, nothing written")
    br.add_argument("--yes", action="store_true", help="allow the billed (OpenRouter) calls")
    br.add_argument("--max-cost-usd", type=float, default=5.0,
                    help="stop before billed spend in the folder would pass this (default 5); one budget per "
                         "batch, so the stop also holds back the unbilled claude-cli calls until you resume")
    br.add_argument("--concurrency", type=int, default=4, help="calls in flight at once (default 4)")
    bc = bs.add_parser("score", help="score the panel's replies and the raters' answers; write score.md/score.json")
    bc.add_argument("--out", type=Path, required=True, metavar="DIR", help="the folder `eval blind build` wrote")
    bc.add_argument("--answers", type=Path, metavar="CSV", help="the raters' answers (rater,pair,human,better)")


def run(args: argparse.Namespace) -> int:
    if args.eval_cmd == "golden" and args.golden_cmd == "validate":
        return _golden_validate(args)
    if args.eval_cmd == "panel" and args.panel_cmd == "check":
        return _panel_check(args)
    if args.eval_cmd == "panel" and args.panel_cmd == "estimate":
        return _panel_estimate(args)
    if args.eval_cmd == "judges":
        return _judges(args)
    if args.eval_cmd == "claims":
        return _claims(args)
    if args.eval_cmd == "judges-report":
        return _judges_report(args)
    if args.eval_cmd == "rewrite":
        return _rewrite(args)
    if args.eval_cmd == "first-call":
        return _first_call(args)
    if args.eval_cmd == "rewrite-delta":
        return _rewrite_delta(args)
    if args.eval_cmd == "lint-rate":
        return _lint_rate(args)
    if args.eval_cmd == "goodhart":
        return _goodhart(args)
    if args.eval_cmd == "blind":
        return {"build": _blind_build, "form": _blind_form, "run": _blind_run,
                "score": _blind_score}[args.blind_cmd](args)
    return _fail(args.eval_cmd, "unknown command")


def _golden_validate(args: argparse.Namespace) -> int:
    cmd = "golden validate"
    try:
        cases = golden.load(args.dir)
        problems = golden.validate(cases, require_counts=args.require_counts)
    except (ValueError, OSError) as e:  # GoldenError, or a ruleset that won't load
        return _fail(cmd, _first_line(e))
    problems += golden.heldout_leaks(cases, golden.heldout_roots())
    for group, row in golden.counts(cases).items():
        print(golden.count_line(group, row))
    for p in problems:
        print(f"problem: {p}")
    if problems:
        return _fail(cmd, f"{len(problems)} problem{'' if len(problems) == 1 else 's'}", 1)
    print(f"golden set valid: {len(cases)} case{'' if len(cases) == 1 else 's'}")
    return 0


def _panel_check(args: argparse.Namespace) -> int:
    cmd = "panel check"
    try:
        panel = llm_panel.load_panel(args.panel)
    except llm_panel.PanelError as e:
        return _fail(cmd, _first_line(e))
    billed = [m for m in panel.models if m.billed]
    problems = llm_panel.check_models(panel)
    for p in problems:
        print(f"problem: {p}")
    if problems:
        return _fail(cmd, f"{len(problems)} problem{'' if len(problems) == 1 else 's'}", 1)
    print(f"panel ok: {len(billed)} billed model{'' if len(billed) == 1 else 's'} listed at the configured prices "
          f"({len(panel.models) - len(billed)} on the Claude subscription, not checked)")
    return 0


def _panel_estimate(args: argparse.Namespace) -> int:
    cmd = "panel estimate"
    try:
        panel = llm_panel.load_panel(args.panel)
        names = None if args.models is None else [n.strip() for n in args.models.split(",") if n.strip()]
        models = list(panel.models) if names is None else [panel.get(n) for n in names]
    except llm_panel.PanelError as e:
        return _fail(cmd, _first_line(e))
    if not models:
        return _fail(cmd, "--models names no model")
    prompts = []
    for p in args.prompts:
        try:
            prompts.append(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            return _fail(cmd, f"{p}: can't read the prompt file ({getattr(e, 'strerror', None) or type(e).__name__})")
    _estimate_table([(m, prompts) for m in models], panel)
    return 0


# ---------------------------------------------------------------- judges

class _Usage(ValueError):
    pass


def _csv(value: str | None, allowed: tuple[str, ...], flag: str) -> list[str]:
    if value is None:
        return []
    items = list(dict.fromkeys(v.strip() for v in value.split(",") if v.strip()))
    bad = [v for v in items if v not in allowed]
    if bad or not items:
        raise _Usage(f"{flag} {', '.join(bad) or repr(value)}: must be one or more of {', '.join(allowed)}")
    return items


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _estimate_table(per_model: list[tuple[llm_panel.PanelModel, list[str]]], panel: llm_panel.Panel) -> float:
    """Print the estimate table (one row per model: its calls, estimated input tokens and cost) and the billed
    total; return that total. `panel estimate`, `judges` and `blind run` all print this one table."""
    rows = [("model", "transport", "calls", "est. input tokens", "est. cost US$")]
    total = 0.0
    for m, prompts in per_model:
        cost = llm_panel.estimate_cost(prompts, m, panel.max_out_tokens)
        total += cost
        rows.append((m.name, m.transport, str(len(prompts)), str(sum(llm_panel.estimate_tokens(p) for p in prompts)),
                     f"{cost:.4f}" if m.billed else "0 (subscription)"))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(c.ljust(w) if i < 2 else c.rjust(w) for i, (c, w) in enumerate(zip(r, widths))).rstrip())
    print(f"total billed estimate: US${total:.4f} (input estimated at 4 characters a token, output at "
          f"{panel.max_out_tokens} tokens a call; claude-cli models bill nothing)")
    return total


def _print_estimate(jobs: list[tuple[str, llm_panel.PanelModel, str]], models: list[llm_panel.PanelModel],
                    panel: llm_panel.Panel) -> float:
    return _estimate_table([(m, [p for _, jm, p in jobs if jm is m]) for m in models], panel)


def _run_limits(args: argparse.Namespace) -> str | None:
    """Why --max-cost-usd or --concurrency can't be used, or None. `judges` and `blind run` share it."""
    if not math.isfinite(args.max_cost_usd) or args.max_cost_usd < 0:
        return "--max-cost-usd must be a number, 0 or more"
    if args.concurrency < 1:
        return "--concurrency must be 1 or more"
    return None


def _panel_models(args: argparse.Namespace) -> tuple[llm_panel.Panel, list[str], list[llm_panel.PanelModel]]:
    """The panel and the --models it names, in order and once each. PanelError for a bad panel, an unknown name or
    no name at all."""
    panel = llm_panel.load_panel(args.panel)
    names = list(dict.fromkeys(n.strip() for n in args.models.split(",") if n.strip()))
    if not names:
        raise llm_panel.PanelError("--models names no model")
    return panel, names, [panel.get(n) for n in names]


def _paid_gate(cmd: str, todo: list[tuple[str, llm_panel.PanelModel, str]], models: list[llm_panel.PanelModel],
               panel: llm_panel.Panel, args: argparse.Namespace) -> int | None:
    """Print the estimate for the calls still to make, then stop for `--dry-run` (exit 0), billed calls without
    `--yes` (exit 1) or a missing API key (exit 2). None: go ahead. `judges` and `blind run` share this gate."""
    est = _print_estimate(todo, models, panel)
    if args.dry_run:
        print("dry run: nothing sent, nothing written")
        return 0
    billed = [j for j in todo if j[1].billed]
    if billed and not args.yes:
        return _fail(cmd, f"paid run: {len(billed)} OpenRouter call{'' if len(billed) == 1 else 's'} estimated at "
                          f"US${est:.4f}; add --yes to run them (spend stops at --max-cost-usd, "
                          f"US${args.max_cost_usd:.2f})", 1)
    if billed and not (os.environ.get(panel.key_env) or "").strip():
        return _fail(cmd, f"{panel.key_env} isn't set: the OpenRouter models need an API key in that environment "
                          "variable, so nothing was sent")
    return None


def _not_a_folder(out: Path, what: str) -> str | None:
    return f"{out}: not a folder: --out names {what}" if out.exists() and not out.is_dir() else None


def _accept_lines(results: list[dict]) -> list[str]:
    return [f"{r['group']} {r['model']}: {r['why'] if r['ok'] else 'misses: ' + r['why']}" for r in results]


def _history(build) -> None:
    """Append `build(ruleset_version, plugin_version)`'s entries to the project's eval history. Never raises and
    never prints to stdout: a failure is one `plainspoken: eval history skipped: …` line on stderr."""
    try:
        root = config.project_root(Path.cwd())
        for entry in build(load_config().version, kaizen.plugin_version()):
            evalhistory.append(root, entry)
    except Exception as e:  # deliberate: the history must never change the command's own result
        try:
            print(f"plainspoken: eval history skipped: {type(e).__name__}: {_first_line(e)}", file=sys.stderr)
        except Exception:
            pass


def _judges_history(results: list[dict], run: Path, min_rate: float, scored: str | None) -> None:
    """The run's `judges` history lines, less any the history already holds for the same scoring and bar: so
    `judges-report` after `judges` (or twice) adds nothing, while a new `--min` or a re-score adds lines."""
    def build(rv: str, pv: str) -> list[dict]:
        entries = evalhistory.judges_entries(results, str(Path(run).resolve()), min_rate=min_rate, scored=scored,
                                             ruleset_version=rv, plugin_version=pv)
        return evalhistory.unrecorded(config.project_root(Path.cwd()), entries)
    _history(build)


def _judges(args: argparse.Namespace) -> int:
    cmd = "judges"
    try:
        groups = _csv(args.group, golden.GROUPS, "--group")
        statuses = _csv(args.status, golden.STATUSES, "--status")
        bad = _run_limits(args)
        if bad:
            raise _Usage(bad)
    except _Usage as e:
        return _fail(cmd, str(e))
    try:
        cases = golden.load(args.golden)
        problems = golden.validate(cases, require_counts=False)
    except (ValueError, OSError) as e:  # GoldenError, or a ruleset that won't load
        return _fail(cmd, _first_line(e))
    if problems:
        for p in problems:
            print(f"problem: {p}")
        return _fail(cmd, f"the golden set has {len(problems)} problem{'' if len(problems) == 1 else 's'}: "
                          "fix them first (eval golden validate)")
    picked = [c for c in cases if c.group in golden.JUDGE_GROUPS and (not groups or c.group in groups)
              and (not statuses or c.status in statuses)]
    if not picked:
        return _fail(cmd, "no golden case matches --group/--status")
    try:
        panel, names, models = _panel_models(args)
    except llm_panel.PanelError as e:
        return _fail(cmd, _first_line(e))
    root = config.project_root(Path.cwd())
    out = args.out or root / ".plainspoken" / "evals" / f"judges-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    bad = _not_a_folder(out, "the run folder (a new one, or a run to resume)")
    if bad:
        return _fail(cmd, bad)
    gsha = evaljudges.golden_sha256(args.golden)
    filters = {"group": groups or None, "status": statuses or None}
    meta_path = out / "run.json"
    meta = _read_json(meta_path) if meta_path.exists() else None
    if meta_path.exists():
        if not isinstance(meta, dict):
            return _fail(cmd, f"{meta_path}: can't read it: use a new --out")
        for k, want, what in (("golden_sha256", gsha, "the golden set changed"), ("models", names, "the models differ"),
                              ("filters", filters, "--group/--status differ")):
            if meta.get(k) != want:
                return _fail(cmd, f"{out}: {what} since this run started: use a new --out to start a new run")
    latest, _ = llm_panel.read_replies(out / llm_panel.REPLIES)
    done = {k for k, r in latest.items() if r.error is None}
    try:  # the lint's temp files go to a temp folder, so a dry or refused run writes nothing
        with tempfile.TemporaryDirectory(prefix="plainspoken-judges-") as work:
            all_jobs = evaljudges.jobs(picked, models, Path(work))
    except (KeyError, ValueError, OSError) as e:
        return _fail(cmd, f"can't build the prompts: {_first_line(e)}")
    todo = [j for j in all_jobs if j[0] not in done]
    print(f"{len(picked)} golden case{'' if len(picked) == 1 else 's'} × {len(models)} "
          f"model{'' if len(models) == 1 else 's'}: {len(all_jobs)} calls, {len(all_jobs) - len(todo)} already done "
          f"in {out}")
    stop = _paid_gate(cmd, todo, models, panel, args)
    if stop is not None:
        return stop
    if meta is None:
        meta = {"schema": 1, "golden_dir": str(Path(args.golden).resolve()), "golden_sha256": gsha,
                "golden_cases": len(picked), "panel": str(Path(args.panel).resolve()), "models": names,
                "model_ids": {m.name: m.model for m in models}, "filters": filters, "started": _now()}
        try:
            out.mkdir(parents=True, exist_ok=True)
            _write_atomic(meta_path, json.dumps(meta, indent=2) + "\n")
        except OSError as e:
            return _fail(cmd, f"{meta_path}: can't write it ({e.strerror or type(e).__name__})")
    try:
        result = llm_panel.run_batch(all_jobs, panel, out, max_cost_usd=args.max_cost_usd, yes=args.yes,
                                     concurrency=args.concurrency)
    except llm_panel.PanelError as e:
        return _fail(cmd, _first_line(e))
    except OSError as e:
        return _fail(cmd, f"{out}: can't write the replies ({e.strerror or type(e).__name__})")
    keys = {k for k, _, _ in all_jobs}
    latest, _ = llm_panel.read_replies(out / llm_panel.REPLIES)
    summary = evaljudges.score(picked, {k: r for k, r in latest.items() if k in keys}, models=models,
                               calls=llm_panel.reply_lines(out / llm_panel.REPLIES))  # every call, retries too
    summary["run"] = {"id": out.name, "dir": str(out), "started": meta.get("started"), "scored": _now(),
                      "golden_sha256": gsha, "golden_cases": len(picked), "filters": filters,
                      "stopped": result.stopped, "max_cost_usd": args.max_cost_usd}
    try:
        _write_atomic(out / "summary.json", json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        _write_atomic(out / "report.md", evaljudges.render(summary, models=names))
    except OSError as e:
        return _fail(cmd, f"{out}: can't write the summary ({e.strerror or type(e).__name__})")
    results = evaljudges.accept(summary, models=names)
    if not result.stopped:  # a stopped run's figures are partial: they'd read as complete in the history
        _judges_history(results, out, evaljudges.MIN_RATE, summary["run"]["scored"])
    print(f"wrote {out / 'report.md'} (billed US${llm_panel.usd(summary['cost']['billed_usd'])}, notional "
          f"US${llm_panel.usd(summary['cost']['notional_usd'])})")
    for line in _accept_lines(results):
        print(line)
    if result.stopped:
        return _fail(cmd, f"stopped early: {result.stopped}; re-run with --out {out} to resume", 1)
    misses = [r for r in results if not r["ok"]]
    if misses:
        return _fail(cmd, "accept bar missed: " + "; ".join(f"{r['group']} {r['model']}" for r in misses), 1)
    return 0


# ---------------------------------------------------------------- claims checker

def _claims_prices(args: argparse.Namespace) -> tuple[float, float]:
    known = evalclaims.list_price(args.model)
    price_in = args.price_in if args.price_in is not None else (known[0] if known else None)
    price_out = args.price_out if args.price_out is not None else (known[1] if known else None)
    if price_in is None or price_out is None:
        raise _Usage(f"no list price for {args.model}: pass --price-in and --price-out (US$ per million tokens)")
    if not all(math.isfinite(x) and x >= 0 for x in (price_in, price_out)):
        raise _Usage("--price-in and --price-out must be numbers, 0 or more")
    return price_in, price_out


def _claims_budgeted(todo: list[tuple[str, llm_panel.PanelModel, str]], model: llm_panel.PanelModel, out: Path,
                     args: argparse.Namespace) -> str | None:
    """Run `todo` in batches of --concurrency. Before each batch, the notional US$ recorded in the folder plus the
    batch's estimate must stay within --max-cost-usd, else stop: why it stopped, or None when every job ran."""
    panel = llm_panel.Panel(models=(model,), base_url="https://claude-cli.invalid", key_env="OPENROUTER_API_KEY",
                            max_out_tokens=evalclaims.EST_OUT_TOKENS)
    path = out / llm_panel.REPLIES
    for i in range(0, len(todo), args.concurrency):
        batch = todo[i:i + args.concurrency]
        spent = sum(r.cost_usd for r in llm_panel.reply_lines(path))
        need = sum(evalclaims.estimate(p, model) for _, _, p in batch)
        if spent + need > args.max_cost_usd + 1e-12:
            return (f"budget reached: US${llm_panel.usd(spent)} notional spent of the US${args.max_cost_usd:.2f} "
                    f"limit (--max-cost-usd), and the next {len(batch)} call{'' if len(batch) == 1 else 's'} are "
                    f"estimated at US${llm_panel.usd(need)}")
        result = llm_panel.run_batch(batch, panel, out, max_cost_usd=args.max_cost_usd, concurrency=args.concurrency)
        if result.stopped:
            return result.stopped
    return None


def _claims(args: argparse.Namespace) -> int:
    cmd = "claims"
    try:
        if not evalclaims.claude_model(args.model):
            raise _Usage(f"--model {args.model!r}: eval claims runs on Claude only, through `claude -p`; give a "
                         "Claude model id (claude-opus-5-5) or alias (opus, sonnet, haiku)")
        statuses = _csv(args.status, golden.STATUSES, "--status")
        bad = _run_limits(args)
        if bad:
            raise _Usage(bad)
        model = evalclaims.make_model(args.model.strip(), *_claims_prices(args))
    except _Usage as e:
        return _fail(cmd, str(e))
    try:
        cases = golden.load(args.golden)
        problems = golden.validate(cases, require_counts=False)
    except (ValueError, OSError) as e:  # GoldenError, or a ruleset that won't load
        return _fail(cmd, _first_line(e))
    if problems:
        for p in problems:
            print(f"problem: {p}")
        return _fail(cmd, f"the golden set has {len(problems)} problem{'' if len(problems) == 1 else 's'}: "
                          "fix them first (eval golden validate)")
    picked = [c for c in cases if c.group == golden.CLAIMS and (not statuses or c.status in statuses)]
    if not picked:
        return _fail(cmd, f"no {golden.CLAIMS} golden case matches --status")
    root = config.project_root(Path.cwd())
    out = args.out or root / ".plainspoken" / "evals" / f"claims-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    bad = _not_a_folder(out, "the run folder (a new one, or a run to resume)")
    if bad:
        return _fail(cmd, bad)
    try:
        all_jobs = evalclaims.jobs(picked, model)
    except (KeyError, ValueError, OSError) as e:
        return _fail(cmd, f"can't build the prompts: {_first_line(e)}")
    psha = evalclaims.prompts_sha256(all_jobs)
    meta_path = out / "run.json"
    meta = _read_json(meta_path) if meta_path.exists() else None
    if meta_path.exists():
        if not isinstance(meta, dict):
            return _fail(cmd, f"{meta_path}: can't read it: use a new --out")
        for k, want, what in (("prompts_sha256", psha, "the cases, rubric or --status differ"),
                              ("model", model.model, "the model differs")):
            if meta.get(k) != want:
                return _fail(cmd, f"{out}: {what} since this run started: use a new --out to start a new run")
    latest, _ = llm_panel.read_replies(out / llm_panel.REPLIES)
    done = {k for k, r in latest.items() if r.error is None}
    todo = [j for j in all_jobs if j[0] not in done]
    claims_n = sum(len(c.claims) for c in picked)
    print(f"{len(picked)} {golden.CLAIMS} case{'' if len(picked) == 1 else 's'} ({claims_n} labelled claims) × "
          f"{model.model} via claude -p: {len(all_jobs)} calls, {len(all_jobs) - len(todo)} already done in {out}")
    by_key = {c.id: c for c in picked}
    total = 0.0
    for key, _, prompt in todo:
        case = by_key[key.split("|", 1)[0]]
        est = evalclaims.estimate(prompt, model)
        total += est
        print(f"  {case.id}: {len(case.claims)} claims, ~{llm_panel.estimate_tokens(prompt)} prompt tokens, "
              f"est. US${est:.4f}")
    print(f"total notional estimate: US${total:.4f} at US${model.price_in:g}/US${model.price_out:g} per million "
          f"tokens (each call: the prompt plus {evalclaims.CLI_OVERHEAD_TOKENS} tokens of CLI overhead in, "
          f"{evalclaims.EST_OUT_TOKENS} out); nothing is billed, and the run stops before the notional spend would "
          f"pass US${args.max_cost_usd:.2f} (--max-cost-usd)")
    if args.dry_run:
        print("dry run: nothing sent, nothing written")
        return 0
    if meta is None:
        meta = {"schema": 1, "golden_dir": str(Path(args.golden).resolve()), "golden_cases": len(picked),
                "prompts_sha256": psha, "model": model.model, "filters": {"status": statuses or None},
                "started": _now()}
        try:
            out.mkdir(parents=True, exist_ok=True)
            _write_atomic(meta_path, json.dumps(meta, indent=2) + "\n")
        except OSError as e:
            return _fail(cmd, f"{meta_path}: can't write it ({e.strerror or type(e).__name__})")
    try:
        stopped = _claims_budgeted(todo, model, out, args)
    except llm_panel.PanelError as e:
        return _fail(cmd, _first_line(e))
    except OSError as e:
        return _fail(cmd, f"{out}: can't write the replies ({e.strerror or type(e).__name__})")
    keys = {k for k, _, _ in all_jobs}
    latest, _ = llm_panel.read_replies(out / llm_panel.REPLIES)
    summary = evalclaims.score(picked, {k: r for k, r in latest.items() if k in keys}, model.name,
                               calls=llm_panel.reply_lines(out / llm_panel.REPLIES))
    summary["run"] = {"id": out.name, "dir": str(out), "started": meta.get("started"), "scored": _now(),
                      "stopped": stopped, "max_cost_usd": args.max_cost_usd}
    text = evalclaims.render(summary)
    try:
        _write_atomic(out / "summary.json", json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        _write_atomic(out / "report.md", text)
    except OSError as e:
        return _fail(cmd, f"{out}: can't write the summary ({e.strerror or type(e).__name__})")
    print(text, end="")
    print(f"wrote {out / 'report.md'} (notional US${llm_panel.usd(summary['notional_usd'])})")
    if stopped:
        return _fail(cmd, f"stopped early: {stopped}; re-run with --out {out} to resume", 1)
    errors = summary["cases"]["errors"]
    if errors:
        return _fail(cmd, f"{errors} case{'' if errors == 1 else 's'} had a failed call or an unscorable reply: re-run "
                          f"with --out {out} to retry a failed call", 1)
    return 0


def _rewrite(args: argparse.Namespace) -> int:
    cmd = "rewrite"
    for path in (args.draft, args.source):
        if path is not None and not path.is_file():
            return _fail(cmd, f"{path}: no such file")
    try:  # grade reads each file once: a non-UTF-8 file is a ValueError naming it
        prof, _ = config.resolve_profile_ex(args.profile, config.project_root(Path.cwd()), os.environ, "")
        g = rewrite.grade(args.draft, args.source, prof, args.content_type)
    except OSError as e:
        return _fail(cmd, f"{e.filename or args.draft}: can't read it ({e.strerror or type(e).__name__})")
    except ValueError as e:  # a bad profile, malformed frontmatter, or a file that isn't UTF-8
        return _fail(cmd, _first_line(e))
    print(json.dumps(g, indent=2, ensure_ascii=False) if args.json else rewrite.summarise(g))
    return 0 if g["verdict"] == "PASS" else 1


def _rewrite_delta(args: argparse.Namespace) -> int:
    cmd = "rewrite-delta"
    try:
        result = json.loads(args.result.read_text(encoding="utf-8"))
        root = Path(result["suite"]["root"])
        prof, _ = config.resolve_profile_ex(args.profile, config.project_root(Path.cwd()), os.environ, "")
        d = rewrite.delta(result, root, prof, save=args.save)
    except (OSError, ValueError, KeyError, TypeError) as e:
        return _fail(cmd, f"{args.result}: {_first_line(e)}")
    print(json.dumps(d, indent=2, ensure_ascii=False) if args.json else rewrite.summarise_delta(d))
    return 0 if d["rows"] else 1


def _first_call(args: argparse.Namespace) -> int:
    cmd = "first-call"
    try:
        if args.result.suffix == ".jsonl":
            r = evaltrace.first_call(args.result, args.expect)
            d = {"rows": [{"case": str(args.result), "arm": "", "run": 1, "expected": f"run.py {args.expect}", **r}],
                 "missing": [], "exempt": [], "skipped": []}
        else:
            d = evaltrace.audit(json.loads(args.result.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        return _fail(cmd, f"{args.result}: {_first_line(e)}")
    print(json.dumps(d, indent=2, ensure_ascii=False) if args.json else evaltrace.summarise(d))
    return 0 if d["rows"] and all(r["passed"] for r in d["rows"]) and not d["missing"] else 1


def _judges_report(args: argparse.Namespace) -> int:
    cmd = "judges-report"
    if not math.isfinite(args.min) or not 0 < args.min <= 1:
        return _fail(cmd, "--min must be more than 0 and at most 1")
    path = args.run / "summary.json"
    summary = _read_json(path)
    if not isinstance(summary, dict):
        return _fail(cmd, f"{path}: no readable summary (run `eval judges` first)")
    meta = _read_json(args.run / "run.json")
    names = meta.get("models") if isinstance(meta, dict) else None
    try:
        if not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
            names = [m["name"] for m in summary["models"]]
        text = evaljudges.render(summary, min_rate=args.min, models=names)
        results = evaljudges.accept(summary, models=names, min_rate=args.min)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return _fail(cmd, f"{path}: not a judge-validation summary")
    print(text, end="")
    run_info = summary.get("run")
    stopped = run_info.get("stopped") if isinstance(run_info, dict) else None
    if stopped:  # a stopped run's figures are partial: they'd read as complete in the history
        print(f"plainspoken: eval judges-report: the run stopped early ({stopped}), so nothing was added to the eval "
              "history; resume it with `eval judges --out` first", file=sys.stderr)
    else:
        scored = run_info.get("scored") if isinstance(run_info, dict) else None
        _judges_history(results, args.run, args.min, scored if isinstance(scored, str) else None)
    misses = [r for r in results if not r["ok"]]
    if misses:
        return _fail(cmd, "accept bar missed: " + "; ".join(f"{r['group']} {r['model']} ({r['why']})"
                                                             for r in misses), 1)
    return 0


# ---------------------------------------------------------------- blind reader test

BUILT = "the folder `eval blind build` wrote"

def _blind_build(args: argparse.Namespace) -> int:
    cmd = "blind build"
    if args.words < 1:
        return _fail(cmd, "--words must be 1 or more")
    bad = _not_a_folder(args.out, "a new folder for the pairs and the key")
    if bad:
        return _fail(cmd, bad)
    try:
        spec = blind.load_spec(args.spec)
        meta = blind.build(spec, args.out, words=args.words, seed=args.seed)
    except blind.BlindRefusal as e:
        return _fail(cmd, f"refused {len(e.ids)} item{'' if len(e.ids) == 1 else 's'} ({e}): match the texts' "
                          "lengths and spelling, or drop the item; nothing was written", 1)
    except blind.BlindError as e:
        return _fail(cmd, _first_line(e))
    except OSError as e:
        return _fail(cmd, f"{args.out}: can't write the build ({e.strerror or type(e).__name__})")
    print(f"built {meta['pairs']} pair{'' if meta['pairs'] == 1 else 's'} in {args.out} (seed {meta['seed']}, "
          f"at least {meta['words']} words a text, whole sentences)")
    print(f"{blind.KEY} and {blind.BUILD} hold the answers and the sources: keep them away from raters. "
          f"{blind.HELDOUT} keeps kaizen from mining the folder.")
    return 0


def _blind_form(args: argparse.Namespace) -> int:
    cmd = "blind form"
    bad = _not_a_folder(args.out, BUILT)
    if bad:
        return _fail(cmd, bad)
    try:
        path = blind.form(args.out)
    except blind.BlindError as e:
        return _fail(cmd, _first_line(e))
    except OSError as e:
        return _fail(cmd, f"{args.out}: can't write the form ({e.strerror or type(e).__name__})")
    print(f"wrote {path} and {args.out / blind.ANSWERS}: send both to the raters yourself (plainspoken never "
          "contacts anyone), then score their answers with `eval blind score --answers`")
    return 0


def _blind_run(args: argparse.Namespace) -> int:
    cmd = "blind run"
    bad = _run_limits(args) or _not_a_folder(args.out, BUILT)
    if bad:
        return _fail(cmd, bad)
    try:
        prompts = blind.prompts(args.out)
        blind.read_key(args.out)
    except blind.BlindError as e:
        return _fail(cmd, _first_line(e))
    try:
        panel, _, models = _panel_models(args)
    except llm_panel.PanelError as e:
        return _fail(cmd, _first_line(e))
    out = args.out
    jobs = [(f"{k}|{m.name}", m, p) for k, p in prompts for m in models]
    latest, _ = llm_panel.read_replies(out / llm_panel.REPLIES)
    done = {k for k, r in latest.items() if r.error is None}
    todo = [j for j in jobs if j[0] not in done]
    pairs = len(prompts) // 2
    print(f"{pairs} pair{'' if pairs == 1 else 's'} × 2 orders × {len(models)} model{'' if len(models) == 1 else 's'}: "
          f"{len(jobs)} calls, {len(jobs) - len(todo)} already done in {out}")
    stop = _paid_gate(cmd, todo, models, panel, args)
    if stop is not None:
        return stop
    try:
        result = llm_panel.run_batch(jobs, panel, out, max_cost_usd=args.max_cost_usd, yes=args.yes,
                                     concurrency=args.concurrency)
    except llm_panel.PanelError as e:
        return _fail(cmd, _first_line(e))
    except OSError as e:
        return _fail(cmd, f"{out}: can't write the replies ({e.strerror or type(e).__name__})")
    cost = evaljudges.costs(llm_panel.reply_lines(out / llm_panel.REPLIES))
    failed = sum(r.error is not None for r in result.replies)
    print(f"{len(result.replies)} of {len(jobs)} calls have a reply ({failed} failed: re-run to retry them); "
          f"billed US${llm_panel.usd(cost['billed_usd'])}, notional US${llm_panel.usd(cost['notional_usd'])}")
    if result.stopped:
        return _fail(cmd, f"stopped early: {result.stopped}; re-run with --out {out} to resume", 1)
    if failed:
        return _fail(cmd, f"{failed} call{'' if failed == 1 else 's'} failed: re-run with --out {out} to retry "
                          f"{'it' if failed == 1 else 'them'} (the score counts a failed call as an error)", 1)
    print(f"next: plainspoken eval blind score --out {out}")
    return 0


def _blind_score(args: argparse.Namespace) -> int:
    cmd = "blind score"
    out = args.out
    bad = _not_a_folder(out, BUILT)
    if bad:
        return _fail(cmd, bad)
    path = out / llm_panel.REPLIES
    latest, _ = llm_panel.read_replies(path)
    replies = list(latest.values())
    try:
        blind.read_pairs(out)
        if not replies and args.answers is None:
            return _fail(cmd, f"nothing to score in {out}: run `eval blind run` or pass --answers")
        summary = blind_score.score(out, replies or None, args.answers)
    except blind.BlindError as e:
        return _fail(cmd, _first_line(e))
    if replies:
        summary["cost"] = evaljudges.costs(llm_panel.reply_lines(path))  # every call, retries too
    summary["run"] = {"id": out.name, "dir": str(out), "scored": _now(),
                      "answers": None if args.answers is None else str(args.answers)}
    text = blind_score.render(summary)
    try:
        _write_atomic(out / "score.json", json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        _write_atomic(out / "score.md", text)
    except OSError as e:
        return _fail(cmd, f"{out}: can't write the score ({e.strerror or type(e).__name__})")
    print(text, end="")
    print(f"wrote {out / 'score.md'} and {out / 'score.json'}")
    drafts = blind.generated_folder(out)
    _history(lambda rv, pv: evalhistory.blind_entries(summary, str(Path(out).resolve()), drafts,
                                                      ruleset_version=rv, plugin_version=pv))
    return 0


# ---------------------------------------------------------------- history: the lint rate and the anti-Goodhart report

def _lint_rate(args: argparse.Namespace) -> int:
    cmd = "lint-rate"
    drafts = args.drafts
    if not drafts.is_dir():
        return _fail(cmd, f"{drafts}: no such folder")
    try:
        cfg = load_config()
        prof, _ = config.resolve_profile_ex(args.profile, config.project_root(Path.cwd()), os.environ, "")
        rows = rewrite.grade_many(drafts, None, prof, cfg=cfg, recursive=True)
    except (ValueError, OSError) as e:  # a bad profile, an unreadable or non-UTF-8 draft, malformed frontmatter
        return _fail(cmd, _first_line(e))
    if not rows:
        return _fail(cmd, f"{drafts}: no .md or .txt drafts")
    passed = sum(not r["blocks"] for r in rows)
    lo, hi = em.wilson(passed, len(rows))
    for r in rows:
        if r["blocks"]:
            print(f"  {Path(r['draft']).relative_to(drafts).as_posix()}: BLOCK "
                  f"{', '.join('r' + b for b in r['blocks'])}")
    print(f"lint pass rate: {passed / len(rows):.2f} [{lo:.2f}–{hi:.2f}] ({passed} of {len(rows)} draft"
          f"{'' if len(rows) == 1 else 's'} with no BLOCK; profile {prof.name}, ruleset {cfg.version})")
    _history(lambda rv, pv: [evalhistory.lint_entry(passed, len(rows), (lo, hi), str(drafts.resolve()),
                                                    profile=prof.name, ruleset_version=rv, plugin_version=pv)])
    return 0


def _goodhart(args: argparse.Namespace) -> int:
    cmd = "goodhart"
    if args.history is not None:
        if not args.history.is_file():
            return _fail(cmd, f"{args.history}: no such file")
        file = args.history
    else:
        file = evalhistory.path(config.project_root(Path.cwd()))
    try:
        entries = evalhistory.read_file(file)
    except OSError as e:
        return _fail(cmd, f"{file}: can't read it ({e.strerror or type(e).__name__})")
    if not evalhistory.enough(entries):
        print(f"not enough history in {file}: the report compares two blind runs of one tier, each with a "
              "lint-rate entry on its drafts (`eval blind score`, `eval lint-rate --drafts DIR`)")
        return 0
    flags, notes = evalhistory.report(entries)
    for n in notes:
        print(f"note: {n}")
    for f in flags:
        print(f)
    if flags:
        return _fail(cmd, f"{len(flags)} flag{'' if len(flags) == 1 else 's'}: investigate; never tune against the "
                          "held-out set", 1)
    total = evalhistory.pair_count(entries)
    compared = total - len(notes)
    if not notes:
        print(f"no flag: across {total} pair{'' if total == 1 else 's'} of blind runs, the lint pass rate never rose "
              f"by {evalhistory.LINT_JUMP:.2f} or more while readers failed to improve")
    elif compared:
        print(f"no flag in the {compared} pair{'' if compared == 1 else 's'} of blind runs compared; {len(notes)} "
              f"of {total} not compared (the notes above say why)")
    else:
        print(f"no flag, but none of the {total} pair{'' if total == 1 else 's'} of blind runs could be compared "
              "(the notes above say why)")
    return 0
