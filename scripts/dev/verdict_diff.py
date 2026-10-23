"""Lint verdict diff: lint one fixed public corpus with two trees and show what changed (plan 8.2, spec §13).

    python3 scripts/dev/verdict_diff.py OLD NEW [--json] [--max-rows 40] [--fail-on-change]

OLD and NEW are each a git ref of this repo (exported with `git archive` into a temp folder, so nothing in the repo
changes) or the path of a checkout. Examples: `verdict_diff.py origin/main HEAD` for a pull request,
`verdict_diff.py v0.12.0 HEAD` for a release range, `verdict_diff.py ../plainspoken-old .` for two folders.

The corpus is read from NEW, so both trees lint the same texts and only the engine, the ruleset and the default
profile differ:

- every case text in `evals/golden/*.toml` (the judge and claims cases), linted as its own `content_type`;
- the plain prose fixtures: `evals/rewrite/*/reference.md` and `tests/fixtures/voice/*.md`, linted as `social`
  under 300 words and `article` from 300 (the rule `check -` uses for stdin).

Each tree's own engine lints each text the way `check - --plugin-profile default --content-type T --json
--no-record` does, in one Python process per tree (the two run side by side) with the tree's `lib/` first on the
path. Lint only: no judges, no model, no network. Nothing is written into either tree or the repo: texts go in on
stdin (which saves no report), `--no-record` records no kaizen event, and the process runs in an empty temp folder
with an empty HOME and no `PLAINSPOKEN_*` or `CLAUDE_*` variables, so no project or user config applies. A tree
that can't lint stdin yet (v0.6.0 can't) lints each text as a file in that temp folder instead.

For each text the diff compares the status (BLOCK when any finding is BLOCK, else WARN when any is WARN, else
CLEAN; the engine's own lint status calls the last two CLEAN) and the number of findings per rule and severity.
Output is markdown for a job summary or a release PR, or JSON with --json. The report names texts by path and case
id only, never by their words or labels: the golden set is held out (`guides/evals.md`).

Exit codes: 0 the report printed (changed or not) · 1 something changed and --fail-on-change was given · 2 bad usage,
a ref or folder that can't be read, or a tree whose lint can't be run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOCIAL_WORDS = 300  # the stdin rule of `check -`: under this many words lints as social
PROSE_GLOBS = ("evals/rewrite/*/reference.md", "tests/fixtures/voice/*.md")
STATUSES = ("BLOCK", "WARN", "CLEAN")
ERROR = "ERROR"

# Runs inside each tree's interpreter, from an empty temp folder: argv[1] is the tree's lib/ folder, stdin a JSON
# list of {id, text, content_type}; stdout one JSON object id → {"findings": [[rule, severity], ...], "ruleset": v}
# or {"error": msg}. A tree whose parser lacks an optional flag gets it dropped; one that can't lint stdin (before
# `check -`) gets each text as a file in that temp folder, with --no-save where it has it.
DRIVER = r'''
import contextlib, io, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from plainspoken.__main__ import main
items = json.load(sys.stdin)
real_out = sys.stdout
optional = ["--plugin-profile", "--content-type", "--no-record", "--no-save"]
use_stdin = True
out = {}
def argv_for(item, path):
    argv = ["check", "-" if path is None else path, "--json"]
    for flag in optional:
        if flag == "--plugin-profile":
            argv += [flag, "default"]
        elif flag == "--content-type":
            argv += [flag, item["content_type"]]
        elif flag != "--no-save" or path is not None:
            argv.append(flag)
    return argv
def call(argv, text):
    buf, err = io.StringIO(), io.StringIO()
    sys.stdin = io.StringIO(text)
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue(), err.getvalue()
def lint(n, item):
    global use_stdin
    for _ in range(len(optional) + 2):
        path = None
        if not use_stdin:
            path = "draft-%d.md" % n
            Path(path).write_text(item["text"] if item["text"].endswith("\n") else item["text"] + "\n", encoding="utf-8")
        code, text, err = call(argv_for(item, path), item["text"])
        if "unrecognized arguments:" in err:
            bad = err.split("unrecognized arguments:", 1)[1].split()
            if any(f in bad for f in optional):
                optional[:] = [f for f in optional if f not in bad]
                continue
        if use_stdin and not text.strip() and ("check -" in err or "'-'" in err):
            use_stdin = False
            continue
        return code, text, err
    return code, text, err
for n, item in enumerate(items):
    code, text, err = lint(n, item)
    try:
        rep = json.loads(text)
        out[item["id"]] = {"findings": [[f["rule"], f["severity"]] for f in rep["findings"]],
                           "ruleset": rep.get("ruleset_version", "")}
    except (ValueError, KeyError, TypeError):
        out[item["id"]] = {"error": (err.strip().splitlines() or ["exit %s" % code])[-1][:300]}
real_out.write(json.dumps(out))
'''


class DiffError(Exception):
    pass


# ------------------------------------------------------------------ corpus

def _content_type(text: str) -> str:
    return "social" if len(text.split()) < SOCIAL_WORDS else "article"


def corpus(tree: Path) -> list[dict]:
    """[{id, text, content_type}] in a fixed order: golden cases by file and position, then the prose fixtures."""
    items: list[dict] = []
    for path in sorted((tree / "evals" / "golden").glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
            raise DiffError(f"can't read {path.relative_to(tree)}: {e}") from e
        for n, case in enumerate(data.get("case", []), 1):
            text = case.get("text") if isinstance(case, dict) else None
            if not isinstance(text, str) or not text.strip():
                continue
            cid = case.get("id") or f"{path.stem}#{n}"
            ctype = case.get("content_type") if case.get("content_type") in ("article", "social") else "article"
            items.append({"id": f"golden/{cid}", "text": text, "content_type": ctype})
    for pattern in PROSE_GLOBS:
        for path in sorted(tree.glob(pattern)):
            text = path.read_text(encoding="utf-8")
            if text.strip():
                items.append({"id": path.relative_to(tree).as_posix(), "text": text,
                              "content_type": _content_type(text)})
    if not items:
        raise DiffError(f"no corpus texts found in {tree}")
    return items


# ------------------------------------------------------------------ diff logic (no git, no subprocess)

def status(result: dict) -> str:
    if "error" in result:
        return ERROR
    sevs = {sev for _, sev in result["findings"]}
    return "BLOCK" if "BLOCK" in sevs else "WARN" if "WARN" in sevs else "CLEAN"


def counts(result: dict) -> Counter:
    """(rule, severity) → number of findings; empty for an error."""
    return Counter((rule, sev) for rule, sev in result.get("findings", []))


def _key(rule: str, sev: str) -> str:
    return f"{rule} {sev}"


def diff(old: dict[str, dict], new: dict[str, dict]) -> dict:
    """Compare two lint result maps (text id → result, as DRIVER prints). Every text is in the corpus, so a text
    missing from one side counts as an error there."""
    missing = {"error": "not linted"}
    texts, transitions, statuses_old, statuses_new = [], Counter(), Counter(), Counter()
    totals_old, totals_new, touched = Counter(), Counter(), Counter()
    for tid in sorted(set(old) | set(new)):
        a, b = old.get(tid, missing), new.get(tid, missing)
        sa, sb = status(a), status(b)
        statuses_old[sa] += 1
        statuses_new[sb] += 1
        ca, cb = counts(a), counts(b)
        totals_old.update(ca)
        totals_new.update(cb)
        changes = {_key(*k): [ca.get(k, 0), cb.get(k, 0)] for k in sorted(set(ca) | set(cb)) if ca[k] != cb[k]}
        for k in set(ca) | set(cb):
            if ca[k] != cb[k]:
                touched[k] += 1
        if sa != sb or changes:
            row = {"id": tid, "old": sa, "new": sb, "changes": changes}
            for side, res in (("old_error", a), ("new_error", b)):
                if "error" in res:
                    row[side] = res["error"]
            texts.append(row)
            if sa != sb:
                transitions[f"{sa} → {sb}"] += 1
    rules = [{"rule": rule, "severity": sev, "old": totals_old.get((rule, sev), 0),
              "new": totals_new.get((rule, sev), 0), "texts": touched[(rule, sev)]}
             for rule, sev in sorted(touched, key=_rule_order)]
    return {
        "texts": len(set(old) | set(new)),
        "changed": len(texts),
        "status_old": {s: statuses_old[s] for s in (*STATUSES, ERROR) if statuses_old[s]},
        "status_new": {s: statuses_new[s] for s in (*STATUSES, ERROR) if statuses_new[s]},
        "transitions": dict(sorted(transitions.items())),
        "rules": rules,
        "changed_texts": texts,
    }


def _rule_order(k: tuple[str, str]) -> tuple:
    rule, sev = k
    digits = "".join(ch for ch in rule if ch.isdigit())
    return (int(digits) if digits else 10**6, rule, sev)


def _rulesets(results: dict[str, dict]) -> str:
    return ", ".join(sorted({r["ruleset"] for r in results.values() if r.get("ruleset")})) or "unknown"


def markdown(rep: dict, max_rows: int = 40) -> str:
    """The report as markdown for `$GITHUB_STEP_SUMMARY` or a release PR body."""
    o, n = rep["old"], rep["new"]
    lines = [f"### Lint verdict diff: `{o['label']}` → `{n['label']}`", "",
             f"{rep['texts']} corpus texts ({rep['corpus']['golden']} golden cases, {rep['corpus']['prose']} prose "
             f"fixtures), deterministic lint with the default profile. Ruleset {o['ruleset']} → {n['ruleset']}.", "",
             "| Status | Before | After |", "|---|---|---|"]
    for s in (*STATUSES, ERROR):
        a, b = rep["status_old"].get(s, 0), rep["status_new"].get(s, 0)
        if a or b:
            lines.append(f"| {s} | {a} | {b} |")
    lines.append("")
    if not rep["changed"]:
        lines.append("No status or finding count changed.")
        return "\n".join(lines) + "\n"
    moved = ", ".join(f"{k}: {v}" for k, v in rep["transitions"].items()) or "none"
    lines += [f"**{rep['changed']} of {rep['texts']} texts changed.** Status moves: {moved}.", "",
              "| Rule | Severity | Findings before | After | Texts changed |", "|---|---|---|---|---|"]
    lines += [f"| {r['rule']} | {r['severity']} | {r['old']} | {r['new']} | {r['texts']} |" for r in rep["rules"]]
    lines += ["", "| Text | Status | Findings (rule severity before→after) |", "|---|---|---|"]
    rows = rep["changed_texts"]
    for t in rows[:max_rows]:
        st = t["old"] if t["old"] == t["new"] else f"{t['old']} → {t['new']}"
        detail = ", ".join(f"r{k} {v[0]}→{v[1]}" for k, v in t["changes"].items())
        errs = "; ".join(f"{side.split('_')[0]}: {t[side]}" for side in ("old_error", "new_error") if side in t)
        detail = "; ".join(x for x in (detail, errs) if x) or "–"
        lines.append(f"| `{t['id']}` | {st} | {detail.replace('|', '/')} |")
    if len(rows) > max_rows:
        lines.append(f"\n{len(rows) - max_rows} more changed texts: run `scripts/dev/verdict_diff.py` with --json.")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ trees and linting

def _git(*args: str, binary: bool = False) -> str | bytes:
    p = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=False)
    if p.returncode:
        raise DiffError(f"git {' '.join(args)}: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout if binary else p.stdout.decode().strip()


def materialise(spec: str, tmp: Path) -> tuple[Path, str]:
    """A checkout path as is, else a git ref exported into a new folder under tmp. Returns (tree, label)."""
    path = Path(spec)
    if path.is_dir():
        if not (path / "lib" / "run.py").is_file():
            raise DiffError(f"{spec} is a folder without lib/run.py: not a plainspoken tree")
        return path.resolve(), spec
    try:
        sha = _git("rev-parse", "--verify", "--quiet", f"{spec}^{{commit}}")
    except DiffError:
        raise DiffError(f"{spec} is neither a folder nor a commit in {REPO}") from None
    dest = Path(tempfile.mkdtemp(prefix="tree-", dir=tmp))
    archive = dest.with_suffix(".tar")
    archive.write_bytes(_git("archive", "--format=tar", sha, binary=True))
    with tarfile.open(archive) as tar:
        tar.extractall(dest, filter="data")
    archive.unlink()
    return dest, f"{spec} ({sha[:7]})" if not sha.startswith(spec) else sha[:7]


def _clean_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PLAINSPOKEN_", "CLAUDE_", "PYTHON")) and k not in ("XDG_CONFIG_HOME",)}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"))
    return env


def lint_tree(tree: Path, items: list[dict], python: str, tmp: Path) -> dict[str, dict]:
    """Lint every item with the tree's own engine, in one process run from an empty folder."""
    work = Path(tempfile.mkdtemp(prefix="cwd-", dir=tmp))
    p = subprocess.run([python, "-I", "-c", DRIVER, str(tree / "lib")], input=json.dumps(items), cwd=work,
                       env=_clean_env(work), capture_output=True, text=True, check=False)
    if p.returncode:
        raise DiffError(f"lint in {tree} failed: {(p.stderr.strip().splitlines() or ['no output'])[-1]}")
    try:
        return json.loads(p.stdout)
    except ValueError as e:
        raise DiffError(f"lint in {tree} printed no JSON: {e}") from e


def run(old_spec: str, new_spec: str, python: str = sys.executable) -> dict:
    with tempfile.TemporaryDirectory(prefix="plainspoken-verdict-diff-") as t:
        tmp = Path(t)
        old_tree, old_label = materialise(old_spec, tmp)
        new_tree, new_label = materialise(new_spec, tmp)
        items = corpus(new_tree)
        with ThreadPoolExecutor(max_workers=2) as pool:  # the two trees lint side by side
            old_f, new_f = (pool.submit(lint_tree, tree, items, python, tmp) for tree in (old_tree, new_tree))
            old, new = old_f.result(), new_f.result()
    rep = diff(old, new)
    golden = sum(1 for i in items if i["id"].startswith("golden/"))
    rep["corpus"] = {"golden": golden, "prose": len(items) - golden}
    rep["old"] = {"label": old_label, "ruleset": _rulesets(old)}
    rep["new"] = {"label": new_label, "ruleset": _rulesets(new)}
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="verdict_diff.py", description=__doc__.split("\n")[0])
    ap.add_argument("old", help="git ref or checkout path: the tree before")
    ap.add_argument("new", help="git ref or checkout path: the tree after (the corpus is read from here)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON instead of markdown")
    ap.add_argument("--max-rows", type=int, default=40, help="changed texts listed in the markdown (default 40)")
    ap.add_argument("--fail-on-change", action="store_true", help="exit 1 when any status or count changed")
    ap.add_argument("--python", default=sys.executable, help="interpreter that runs each tree's lint")
    args = ap.parse_args(argv)
    try:
        rep = run(args.old, args.new, args.python)
    except DiffError as e:
        print(f"verdict_diff: {e}", file=sys.stderr)
        return 2
    print(json.dumps(rep, indent=2, ensure_ascii=False) if args.json else markdown(rep, args.max_rows), end="")
    return 1 if args.fail_on_change and rep["changed"] else 0


if __name__ == "__main__":
    sys.exit(main())
