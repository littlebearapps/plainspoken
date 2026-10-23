"""The first engine call in a `claude plugin eval` run's kept trace (#58).

Since #12 each skill runs its profile call as an explicit first step, not at load time. Each `evals/smoke/*` case's
`*-first` grader checks that in the runner, as a regex over the trace (`grader_pattern`), but the runner only says
"pattern not found in trace" when it fails. `first_call` reads a kept trace (`--keep-temp`) the same way and says what
the first engine call was. An engine call is a Bash tool call whose command runs `run.py <subcommand>`; the first
`run.py` in that command is the one that counts, so `run.py profile …; run.py check …` in one call starts with
`profile`. Free: no model is called."""
import json
import re
from pathlib import Path

# The call each skill's smoke case expects first; None is exempt, with the reason. The exempt cases say why in their
# prompt.md too.
FIRST_CALL: dict[str, str | None] = {
    "adapt": "profile", "check": "profile", "claims": "profile", "copy-audit": "profile", "kaizen": "kaizen review",
    "plain-language": "profile", "reader-value": "profile", "register-check": "profile", "voice": "profile",
    "write": "profile", "humanize": "profile", "setup": None,
}
EXEMPT = {
    "setup": "it reads no profile: its first step is `setup --status`",
}

_ENGINE = re.compile(r"run\.py[\"']?[ ]+(?=[a-z-])")
_SEPARATOR = re.compile(r"\s*(?:;|&&|\|\||\||\n)")


def _want(first: str, quote: str) -> str:
    return r"run\.py" + quote + r"[ ]+" + r"[ ]+".join(map(re.escape, first.split())) + r"(?![A-Za-z0-9_-])"


def grader_pattern(first: str) -> str:
    """The smoke grader's regex (JavaScript and Python alike) over the runner's trace text (each row as compact JSON,
    one per line): the first Bash call that runs `run.py <subcommand>` runs `run.py <first>` first. A command's
    characters are JSON-escaped there, so a quote is `\\"`; other input keys may come before `command`. V8 copes
    with a first engine call up to about 5 MB into the trace; past that the runner reports "grader threw", still a
    fail."""
    string = r'"(?:[^"\\]|\\[\s\S])*"'
    call = r'"name":"Bash","input":\{(?:"[a-z_]+":(?:' + string + r'|[^,{}"]*),)*"command":"'
    quote = r'(?:\\"|\x27)?'
    engine = r"run\.py" + quote + r"[ ]+[a-z-]"
    before = r"(?:(?!" + engine + r')(?:[^"\\]|\\[\s\S]))*'
    return r"^(?:(?!" + call + before + engine + r")[\s\S])*" + call + before + _want(first, quote)


def tool_calls(trace: Path) -> list[dict]:
    """Every tool call in a kept `trace.jsonl`, in order (subagents' included, as the runner counts them)."""
    calls = []
    for line in Path(trace).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get("message") if isinstance(row, dict) and row.get("type") == "assistant" else None
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                calls.append({"name": item.get("name"), "input": item.get("input")})
    return calls


def engine_call(command: str) -> str | None:
    """The first `run.py <subcommand> …` a shell command runs, up to the next `;`, `&&`, `|` or line; None if none."""
    m = _ENGINE.search(command)
    if m is None:
        return None
    return "run.py " + _SEPARATOR.split(command[m.end():], 1)[0].strip()


def first_call(trace: Path, first: str = "profile") -> dict:
    """Whether the run's first engine call is `run.py <first>`, with what it saw: `passed`, `call` (the call as run,
    or None), `index` (1-based among all tool calls), `calls` (how many) and a one-line `message`."""
    calls = tool_calls(trace)
    want = re.compile(_want(first, "[\"']?"))
    for i, c in enumerate(calls, 1):
        command = c["input"].get("command") if c["name"] == "Bash" and isinstance(c["input"], dict) else None
        seen = engine_call(command) if isinstance(command, str) else None
        if seen is None:
            continue
        passed = want.match(command, _ENGINE.search(command).start()) is not None
        where = f"tool call {i} of {len(calls)}"
        message = (f"first engine call ({where}): {seen}" if passed
                   else f"first engine call ({where}) was {seen}, not run.py {first}")
        return {"passed": passed, "call": seen, "index": i, "calls": len(calls), "message": message}
    return {"passed": False, "call": None, "index": None, "calls": len(calls),
            "message": f"no run.py call in the trace ({len(calls)} tool calls)"}


def audit(result: dict) -> dict:
    """`first_call` on every run of a `claude plugin eval` result (`aggregate-result.json` or its `--json` file),
    with each case's expected call from `FIRST_CALL` (by the skill its name starts with). A run whose trace is gone
    (no `--keep-temp`) is missing, never a pass; a case for a skill not in `FIRST_CALL` is skipped."""
    rows, missing, exempt, skipped = [], [], [], []
    for case in result.get("cases", []):
        name = case["name"]
        skill = name.split("--", 1)[0]
        if skill not in FIRST_CALL:
            skipped.append(name)
            continue
        first = FIRST_CALL[skill]
        if first is None:
            exempt.append(f"{name}: {EXEMPT[skill]}")
            continue
        for arm, runs in case.get("arms", {}).items():
            for i, run in enumerate(runs, 1):
                trace = run.get("tracePath")
                if not (trace and Path(trace).is_file()):
                    missing.append(f"{name} {arm} #{i}")
                    continue
                rows.append({"case": name, "arm": arm, "run": i, "expected": f"run.py {first}",
                             **first_call(Path(trace), first)})
    return {"rows": rows, "missing": missing, "exempt": exempt, "skipped": skipped}


def summarise(d: dict) -> str:
    passed = sum(1 for r in d["rows"] if r["passed"])
    lines = [f"first engine call · {passed} of {len(d['rows'])} runs start with the expected call"]
    for r in d["rows"]:
        run = f"{r['arm']} #{r['run']}" if r["arm"] else "run"
        lines.append(f"  {r['case']} {run}: {'PASS' if r['passed'] else 'FAIL'} · {r['message']}")
    for e in d["exempt"]:
        lines.append(f"  exempt: {e}")
    if d["missing"]:
        lines.append(f"  missing traces (run with --keep-temp): {', '.join(d['missing'])}")
    return "\n".join(lines)
