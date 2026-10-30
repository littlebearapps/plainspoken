"""Stop (Claude Code, Codex) and Hermes' post_llm_call: lint a draft written into the final chat reply (#125).

Off by default: `[chat_reply] mode = "warn"` (project config, else the user-wide file, else the Claude Code option
`chat_reply`) turns it on. It speaks only when the turn's prompt asked for writing (`nudge.intent`: nudge.py records
the kind on UserPromptSubmit, Hermes passes the prompt in) and the reply holds a draft (`plainspoken.reply.drafts`).
Each draft, at most three, is linted as `check -` would (social under 300 words); when any has a BLOCK or WARN
finding, one short message goes to the person.

Warn-only, person-only: the output is only ever `{"systemMessage": …}` or nothing. It never sends a decision, a
reason, `additionalContext`, `continue` or exit 2, so nothing reaches the model and nothing can loop, and it never
changes the reply. It doesn't skip on `stop_hook_active`, since it never causes a continuation; a draft it already
reported in this session isn't reported again, a changed one is.

It stays quiet on a write report (the write skill's status block: that file was checked already, and #75's report
guard reads that reply), and on a draft that lint after edits or the tool-call check already linted this session
(`_common.linted_before`). Kaizen events (no excerpts, ever) and one decision row per draft
(`chat-replies.jsonl`, no text) go only into a project that already has a `.plainspoken` folder. Any error: no
output, exit 0.

`--host codex` names skills `$plainspoken:…`; `--host hermes` is run by the Hermes plugin, which posts the message.
"""
import json
import os
import sys

_HOOKS = os.path.dirname(os.path.realpath(__file__))
if _HOOKS not in sys.path:
    sys.path.insert(0, _HOOKS)

SOURCE = "chat-reply"
STATE = "chat-reply-state.json"
LOG = "chat-replies.jsonl"
ASKS = ("draft", "draft-long", "rewrite")
MAX_WORDS = 10_000  # past this, a draft isn't linted (`too-long`)


def _may_be_on(event: dict) -> bool:
    """False when nothing could turn the check on: no plugin option and no config file that names `chat_reply`. Off
    is the default, so most turns end here without loading the config reader (stdlib and `toolcall` only)."""
    if str(os.environ.get("CLAUDE_PLUGIN_OPTION_CHAT_REPLY", "")).strip().lower() == "true":
        return True
    from plainspoken import toolcall
    project = os.environ.get("CLAUDE_PROJECT_DIR") or toolcall.project_root(event.get("cwd") or ".", {})
    for path in (toolcall.user_config_path(os.environ), os.path.join(project, ".plainspoken", "config.toml")):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                if "chat_reply" in f.read():
                    return True
        except OSError:
            continue
    return False


def _kaizen(root):
    """The kaizen settings when this project keeps a `.plainspoken` folder and capture from this source is on."""
    if not (root / ".plainspoken").is_dir():
        return None
    try:
        from plainspoken import capture, config
        settings = config.kaizen_settings(root, os.environ)
        return settings if capture.source_on(settings, SOURCE) else None
    except Exception:
        return None


class _Log:
    """The decision rows for this turn, written together at the end; nothing without kaizen settings."""

    def __init__(self, settings, host: str, ask: str):
        self.settings, self.host, self.ask, self.rows = settings, host, ask, []

    def add(self, outcome: str, shape: str = "-", words: int = 0, label: str | None = None) -> None:
        """One row; `label` is the draft's, whose hash (`ledger.label_id`) its finding events carry as doc_id."""
        if self.settings is not None:
            from plainspoken import ledger
            self.rows.append({"host": self.host, "ask": self.ask, "shape": shape, "words": words,
                              "bucket": ledger.word_bucket(words), "outcome": outcome,
                              "doc": ledger.label_id(label) if label else "-"})

    def write(self) -> None:
        if self.settings is not None:
            from plainspoken import ledger
            for row in self.rows:
                ledger.append_row(self.settings, LOG, row)


def main(argv: list[str], stdin=None) -> int:
    host = argv[argv.index("--host") + 1] if "--host" in argv[:-1] else "claude-code"
    try:
        event = json.load(stdin or sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0
    text = event.get("last_assistant_message")
    if not isinstance(text, str) or not text.strip():
        return 0
    import _common  # puts lib/ on sys.path
    if not _may_be_on(event):
        return 0
    from pathlib import Path
    from plainspoken import config
    project = (Path(os.environ["CLAUDE_PROJECT_DIR"]) if os.environ.get("CLAUDE_PROJECT_DIR")
               else config.project_root(Path(event.get("cwd") or ".")))
    try:
        settings = config.chat_reply_settings(project, os.environ)
    except (ValueError, OSError):
        return 0  # a config it can't read means off; doctor names the problem
    if settings["mode"] == "off":
        return 0
    data = _common.state_dir(project)
    if host == "hermes":
        from nudge import intent
        ask = intent(event.get("prompt"))
    else:
        ask = _common.read_state(data, _common.ASK_STATE).get(_common.turn_slot(event))
    if ask not in ASKS:
        return 0
    if host not in ("claude-code", "codex", "hermes"):
        host = "claude-code"
    root = _common.kaizen_root(event)
    log = _Log(_kaizen(root), host, ask)
    try:
        return _check(event, host, text, project, root, data, settings, log)
    finally:
        log.write()


def _check(event: dict, host: str, text: str, project, root, data, settings: dict, log: _Log) -> int:
    import _common
    from plainspoken import prose, reply
    if reply.is_write_report(text):
        log.add("write-report", words=prose.word_count(text))
        return 0
    found = reply.drafts(text, writing_ask=True, min_words=settings["min_words"])
    if not found:
        log.add("no-draft", words=prose.word_count(text))
        return 0
    session = str(event.get("session_id") or "-")
    shown = _common.read_state(data, STATE)
    todo = []
    for d in found:
        label = f"{SOURCE}:{prose.text_hash(d.text)}"
        if d.words > MAX_WORDS:
            log.add("too-long", d.shape, d.words, label)
        elif _common.linted_before(data, session, d.text):
            log.add("seen", d.shape, d.words, label)
        elif shown.get(f"{session}|{label}") == "warned":
            log.add("repeat", d.shape, d.words, label)
        else:
            todo.append((d, label))
    if not todo:
        return 0
    from plainspoken import capture, config, textlint
    from plainspoken.registry import load_config
    try:
        profile = config.profile_for_text(project, os.environ, "chat_reply")  # no [chat_reply] profile key (yet)
        cfg = load_config()
        lints = [(d, label, textlint.lint_text(d.text, profile, cfg=cfg, label=label)) for d, label in todo]
    except Exception as e:  # a bad profile or ruleset: say nothing, note it as friction
        if log.settings is not None:
            from plainspoken import ledger
            ledger.friction("capture_error", SOURCE, capture.engine_detail(f"{type(e).__name__}: {e}"),
                            log.settings)
        return 0
    noisy = []
    for d, label, lint in lints:
        if log.settings is not None:
            capture.for_text(lint, d.text, label, profile, cfg, root, SOURCE)
        if textlint.noisy(lint):
            noisy.append((d, lint))
            _common.record_state(data, STATE, f"{session}|{label}", "warned")
        log.add("warned" if textlint.noisy(lint) else "clean", d.shape, d.words, label)
    if noisy:
        print(json.dumps({"systemMessage": reply.message(noisy, host)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:  # warn-only: never break the end of a turn
        sys.exit(0)
