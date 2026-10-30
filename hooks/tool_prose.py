"""PreToolUse tool-call check (#124): lint the writing in a tool call's arguments before the call runs.

Off by default. `[tool_call] mode` (project config, else the user-wide file, else the Claude Code option `tool_call`)
turns it on: `warn` tells the person in one line and gives the model the findings; `block-once` denies the first
call whose text has a BLOCK or WARN finding and lets the same text through when it's sent again; `ask` (Claude Code)
puts the finding in front of the person, who decides. A tool whose own name holds `draft` is only ever warned. It
never rewrites a call: no `updatedInput`, no `allow`.

Which calls: MCP tools on Claude Code and Codex (the matcher), every tool but a core list on Hermes; the shipped
skip list (`data/tool-call.toml`) and `[tool_call] skip` leave tools out, `include` puts them back. Which text: a
string argument with at least `min_words` (25) prose words once markup, quoted threads, signatures, code, tables and
links are stripped (`plainspoken.prose`); the stripped text is what's linted.

Cheapest first: everything up to the walk imports only `plainspoken.toolcall` and `plainspoken.prose`, so a skipped
call or one with no long prose exits in tens of milliseconds; the lint engine loads only when there's text to lint.
Any error: no output, exit 0 (Claude Code and Codex let the call go ahead). Kaizen events and the decision log
(`tool-calls.jsonl`) are written only under a project that already has a `.plainspoken` folder, and hold no text.

`--host codex`: never `ask` (it's block-once there), skills named `$plainspoken:…`. `--host hermes`: run by the
Hermes plugin in a subprocess; `ask` is block-once."""
import json
import os
import sys

_HOOKS = os.path.dirname(os.path.realpath(__file__))
_LIB = os.path.join(os.path.dirname(_HOOKS), "lib")
for _p in (_LIB, _HOOKS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

STATE = "tool-call-state.json"
SOURCE = "tool-call"


def _root(event: dict, env) -> str:
    """The project root, as `_common.kaizen_root` finds it, without importing config or pathlib."""
    from plainspoken import toolcall
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) and event.get("cwd") else None
    given = env.get("CLAUDE_PROJECT_DIR")
    root = toolcall.project_root(cwd or given or ".", {})
    if given and not os.path.isdir(os.path.join(root, ".plainspoken")):
        return toolcall.project_root(given, {})
    return root


def _first_line(e: BaseException) -> str:
    return f"{type(e).__name__}: {(str(e).strip().splitlines() or [''])[0]}"[:200]


def _kaizen(root):
    """The kaizen settings when this project keeps a `.plainspoken` folder and they can be read, else None."""
    if not os.path.isdir(os.path.join(str(root), ".plainspoken")):
        return None
    try:
        from pathlib import Path
        from plainspoken import capture, config
        root = Path(root)
        settings = config.kaizen_settings(root, os.environ)
        return settings if capture.source_on(settings, SOURCE) else None
    except Exception:
        return None


def _log(settings, rows: list[dict]) -> None:
    if settings is None:
        return
    from plainspoken import ledger
    for row in rows:
        ledger.append_row(settings, "tool-calls.jsonl", row)


def _row(host: str, name: str, field, outcome: str, mode: str) -> dict:
    from plainspoken import ledger, toolcall
    return {"host": host, "tool_server_hash": toolcall.server_hash(name),
            "tool_name": toolcall.split_name(toolcall.normalise_name(name))[1] or "-", "field": field.path or "-",
            "words": field.words, "bucket": ledger.word_bucket(field.words), "prose": not outcome.startswith("not-"),
            "outcome": outcome, "mode": mode}


def main(argv: list[str], stdin=None, env=None) -> int:
    argv = list(argv)
    host = argv[argv.index("--host") + 1] if "--host" in argv[:-1] else "claude-code"
    env = os.environ if env is None else env
    try:
        event = json.load(stdin or sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0
    name, tool_input = event.get("tool_name"), event.get("tool_input")
    if not isinstance(name, str) or not isinstance(tool_input, dict):
        return 0
    from plainspoken import toolcall
    if host not in toolcall.HOSTS:
        host = "claude-code"
    root = _root(event, env)
    settings = toolcall.settings(root, env)  # a config it can't read means off; doctor names the problem
    if settings["mode"] == "off" or toolcall.name_decision(name, host, settings) is not None:
        return 0
    fields = toolcall.walk(tool_input, settings["skip_fields"], settings["min_words"])
    candidates = [f for f in fields if f.outcome == "candidate"]
    half = settings["min_words"] / 2
    others = [f for f in fields if f.outcome != "candidate" and f.words >= half]
    if not candidates:
        if others:
            _log(_kaizen(root), [_row(host, name, f, f.outcome, settings["mode"]) for f in others])
        return 0
    return _check(event, host, name, root, settings, candidates, others, env)


def _friction(root, e: BaseException) -> None:
    """One `tool_call` friction line: the engine's message with its free-text slots taken out."""
    settings = _kaizen(root)
    if settings is not None:
        from plainspoken import capture, ledger
        ledger.friction("tool_call", SOURCE, capture.engine_detail(f"{type(e).__name__}: {e}"), settings)


def _emit(out: dict | None) -> int:
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


def _check(event: dict, host: str, name: str, root: str, settings: dict, candidates: list, others: list,
           env) -> int:
    import hashlib
    from pathlib import Path
    import _common
    from plainspoken import capture, config, hostreply, textlint, toolcall
    from plainspoken.registry import load_config
    mode = settings["mode"]
    root = Path(root)
    try:
        profile = config.profile_for_text(root, env, "tool_call")
        cfg = load_config()
    except Exception as e:  # a bad profile or ruleset: say so, never deny
        _friction(root, e)
        return _emit(hostreply.pre_tool(host, model=f"plainspoken tool-call check skipped: {_first_line(e)}"))
    norm = toolcall.normalise_name(name)
    lints = [(f, textlint.lint_text(f.text, profile, cfg=cfg, label=f.path or "-")) for f in candidates]
    data = Path(env.get("CLAUDE_PLUGIN_DATA") or env.get("PLUGIN_DATA") or root / ".plainspoken")
    session = str(event.get("session_id") or "-")
    turn = str(event.get("prompt_id") or event.get("turn_id") or session)
    _common.remember_linted(data, session, [f.text for f, _ in lints])
    kaizen = _kaizen(root)
    if kaizen is not None:
        for f, lint in lints:
            capture.for_text(lint, f.text, f"{SOURCE}:{norm}|{f.path}", profile, cfg, root, SOURCE)
    noisy = [(f, lint) for f, lint in lints if textlint.noisy(lint)]
    rows = [_row(host, name, f, f.outcome, mode) for f in others]
    clean = [_row(host, name, f, "clean", mode) for f, lint in lints if not textlint.noisy(lint)]
    if not noisy:
        _log(kaizen, rows + clean)
        return 0
    effective = mode
    if effective == "ask" and host != "claude-code":
        effective = "block-once"  # Codex has no ask; Hermes' approve fails closed and may ask a model, not a person
    if effective in ("block-once", "ask") and toolcall.is_draft(name):
        effective = "warn"  # a draft already waits for a person to read it
    outcome = {"warn": "warned", "block-once": "blocked", "ask": "asked"}[effective]
    if effective in ("block-once", "ask"):
        key = hashlib.sha256("\0".join([norm, *(f.text for f, _ in lints)]).encode("utf-8")).hexdigest()
        # block-once: the same text sent again goes through. ask: the person is asked again (they decide).
        if effective == "block-once" and _common.record_state(data, STATE, f"sent|{session}|{key}", "1") is not None:
            _log(kaizen, rows + clean + [_row(host, name, f, "resent-unchanged", mode) for f, _ in noisy])
            return 0
        held = _common.record_state(data, STATE, f"turn|{session}|{turn}|{norm}", key)
        if held is not None and held != key:  # one hold per tool per turn: a changed text is warned, never looped
            effective, outcome = "warn", "resent-changed"
    _log(kaizen, rows + clean + [_row(host, name, f, outcome, mode) for f, _ in noisy])
    total = {"BLOCK": 0, "WARN": 0}
    found: list[str] = []
    for _, lint in noisy:
        for sev, n in textlint.counts(lint).items():
            total[sev] += n
        found += [r for r in textlint.rules(lint) if r not in found]
    tally = f"{textlint.count_text(total)} ({', '.join(found[:6])}{', …' if len(found) > 6 else ''})"
    detail = textlint.summary([(f"field {f.path or '-'}", lint) for f, lint in noisy])
    check = hostreply.skill_ref(host, "check")
    if effective == "block-once":
        reason = (f"plainspoken checked the text of this {name} call before it ran: {tally}. It hasn't run. "
                  f"Removing what's flagged (never adding facts) and calling again is the fix; the same text sent "
                  f"again goes through unchanged.\n{detail}")
        return _emit(hostreply.pre_tool(host, decision="deny", reason=reason))
    if effective == "ask":
        reason = (f"plainspoken: the text of this {name} call has {tally}. Approve to send it as written, or say no "
                  f"so it can be fixed first.\n{detail}")
        return _emit(hostreply.pre_tool(host, decision="ask", reason=reason))
    person = f"plainspoken checked the text of this {name} call: {tally}. Warn mode, so the call went ahead."
    model = (f"plainspoken checked the text of this {name} call: {tally}. Warn mode doesn't hold a call back, so "
             f"it ran as written; these findings are for what's written next (remove what's flagged, never add "
             f"facts; {check} runs the full check):\n{detail}")
    return _emit(hostreply.pre_tool(host, person=person, model=model))


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:  # never block a tool call on an error of ours
        sys.exit(0)
