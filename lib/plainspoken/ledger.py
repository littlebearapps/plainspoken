"""The kaizen ledger: an append-only record of what the engine flagged and what people did about it (Phase 5).

One JSON object per line, UTF-8, `\\n`-terminated, at most 4,096 bytes, in `<ledger_dir>/<YYYY-MM>.jsonl` (the month
of the event's own `ts`, UTC). `friction.jsonl` in the same folder, not month-split, records engine friction, and
`tool-calls.jsonl` and `chat-replies.jsonl` record the tool-call and chat-reply checks' decisions (`append_row`), with
no text.

Schema v1, defined by the code below: `make_event` builds and validates an event,
`validate` lists what's wrong with one. Every event carries an `id`, the first 16 hex of the sha256 of the canonical
JSON of every field except `ts`, `id` and `excerpt`, so the same span recorded twice has one id and metrics count
`distinct` ids, never raw lines. A hand edit that changes an identity field no longer matches its id, so it reads as
a bad line.

No text by default. A span is a hash (`span_hash`). `append` drops `excerpt` unless the settings turn excerpts on.
The only free text is `reason` (≤200 characters), and only on `override`, `diff` and `decision` events.

Concurrency: `append` opens the month file with O_APPEND and writes the whole line with one `os.write`, so two
sessions appending at once never interleave inside a line (on a local file system: NFS doesn't promise it). It
refuses a symlinked ledger folder (or any symlinked folder between the project root and it), a symlinked month file,
a file that resolves outside the folder, and a file with another hard link. The folders are checked, then opened one
at a time with O_NOFOLLOW, so one swapped for a link between the check and the write is refused too.

`read` skips and counts bad lines (unparseable, failing `validate`, or a future schema `v`), and reads nothing
through a symlinked folder. `friction` never raises.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from plainspoken import config, justify, pinning, prose, reply, toolcall

SCHEMA_VERSION = 1
MAX_LINE = 4096
MAX_REASON = 200
MAX_EXCERPT = 120
MAX_FACET = 80
MAX_DETAIL = 200

EVENTS = ("lint", "judge", "fix", "justify", "jr", "override", "diff", "publish", "decision", "apply", "calibrate",
          "mine", "backfill")
ACTORS = ("lint", "judge:J1", "judge:J2", "judge:J3", "judge:J4", "jr", "human", "publish", "engine")
OUTCOMES = ("fired", "passed", "fixed", *(f"justified:{k}" for k in justify.KINDS), "jr_accept", "jr_reject",
            "dismissed", "upheld", "missed", "survived_publish", "approved", "rejected", "applied", "proposed",
            "superseded")  # superseded: an approved proposal apply refused as stale; a v1 addition
SEVERITIES = ("BLOCK", "WARN", "CANDIDATE", "INFO")
RULELESS_EVENTS = ("decision", "apply", "calibrate", "mine")  # the only events whose `rule` may be null
REASON_EVENTS = ("override", "diff", "decision")  # the only events that may carry a `reason`
FACET_KEYS = ("term", "section", "metric", "form", "agree", "kind", "pattern", "model", "by")
FACET_SECTIONS = ("faq", "question", "intro", "other")
FACET_METRICS = ("mattr", "burstiness", "ttr", "slop")
FACET_FORMS = ("no-long", "short-run")
FRICTION_KINDS = ("merge_incomplete", "judge_reply_rejected", "agent_handback", "capture_error", "skill", "tool_call")
# Per-check decision logs, one row per field a check looked at: counts and outcomes, never text. A local server's
# name can name a client, so the server is an 8-hex hash; the tool's own name (`send_message`) is kept for tuning.
BUCKETS = ((20, "0-20"), (40, "20-40"), (60, "40-60"), (80, "60-80"), (120, "80-120"), (200, "120-200"),
           (400, "200-400"), (None, "400+"))
TOOL_CALL_OUTCOMES = ("below-cutoff", "clean", "warned", "blocked", "asked", "resent-unchanged", "resent-changed",
                      "too-long")
_TOOL_CALL_ROW = frozenset(("v", "ts", "host", "tool_server_hash", "tool_name", "field", "words", "bucket", "prose",
                            "outcome", "mode"))
_HEX8 = re.compile(r"[0-9a-f]{8}")
# The chat-reply check (#125): one row per draft it looked at after a writing ask (or one per turn with no draft to
# look at), with the draft's shape and size and a hash `doc` that joins its finding events (`ledger.label_id`).
CHAT_REPLY_OUTCOMES = ("no-draft", "write-report", "seen", "repeat", "clean", "warned", "too-long")
CHAT_REPLY_ASKS = ("draft", "draft-long", "rewrite")
_CHAT_REPLY_ROW = frozenset(("v", "ts", "host", "ask", "shape", "words", "bucket", "outcome", "doc"))
_HEX16 = re.compile(r"[0-9a-f]{16}")

_REQUIRED = ("v", "id", "ts", "ruleset_version", "profile", "event", "actor", "outcome", "rule", "severity",
             "doc_id", "doc_sha", "span_hash", "facets")
_OPTIONAL = ("proposal", "reason", "excerpt")
_FIELDS = frozenset(_REQUIRED + _OPTIONAL)
_NOT_IDENTITY = ("ts", "id", "excerpt")
_HEX16 = re.compile(r"[0-9a-f]{16}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00")
_PATTERN = re.compile(r"[a-z0-9-]{1,40}")
_MONTH_FILE = re.compile(r"(\d{4}-\d{2})\.jsonl")


class LedgerError(ValueError):
    """An event that isn't valid, or a ledger that can't be written safely."""


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def normalise(text: str) -> str:
    """Straighten typographic quotes, collapse whitespace, strip, lower-case."""
    return pinning.normalise_text(text).lower()


def span_hash(rule: str, text: str) -> str:
    """16 hex: sha256 of `rule + "\\0" + normalise(text)`. `text` is the excerpt, or for a whole-document finding the
    metric name."""
    return _sha16(f"{rule}\0{normalise(text)}")


def label_id(label: str) -> str:
    """16 hex: sha256 of `label`. A synthetic doc id for a document that has no project path (history backfill)."""
    return _sha16(label)


def doc_id(path: Path, root: Path) -> str:
    """16 hex: sha256 of `path` relative to `root`, POSIX form; of the resolved absolute POSIX path when `path` is
    outside `root`. Both are resolved first (symlinks followed), a relative `path` against the current directory."""
    p, r = config.resolve_path(Path(path)), config.resolve_path(Path(root))
    try:
        key = p.relative_to(r).as_posix()
    except ValueError:
        key = p.as_posix()
    return label_id(key)


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_id(event: Mapping) -> str:
    """The `id` an event should carry: over every field except `ts`, `id` and `excerpt`."""
    return _sha16(_canonical({k: v for k, v in event.items() if k not in _NOT_IDENTITY}))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def valid_ts(ts: object) -> bool:
    """`ts` is the ledger's UTC time to the second, `YYYY-MM-DDTHH:MM:SS+00:00`, and a real date."""
    if not isinstance(ts, str) or not _TS.fullmatch(ts):
        return False
    try:
        datetime.fromisoformat(ts)
    except ValueError:
        return False
    return True


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _short(value: object) -> bool:
    return _text(value) and len(value) <= MAX_FACET


def _facet_errors(facets: object) -> list[str]:
    if not isinstance(facets, dict):
        return ["facets must be an object"]
    errors = []
    for key, value in facets.items():
        if key not in FACET_KEYS:
            errors.append(f"unknown facet {key!r}")
        elif key == "agree":
            if not isinstance(value, bool):
                errors.append("facet agree must be true or false")
        elif key == "section" and value not in FACET_SECTIONS:
            errors.append(f"facet section must be one of {', '.join(FACET_SECTIONS)}")
        elif key == "metric" and value not in FACET_METRICS:
            errors.append(f"facet metric must be one of {', '.join(FACET_METRICS)}")
        elif key == "form" and value not in FACET_FORMS:
            errors.append(f"facet form must be one of {', '.join(FACET_FORMS)}")
        elif key == "pattern" and not (isinstance(value, str) and _PATTERN.fullmatch(value)):
            errors.append("facet pattern must match [a-z0-9-]{1,40}")
        elif key == "term" and not (_short(value) and value == value.lower()):
            errors.append(f"facet term must be a lower-case string of at most {MAX_FACET} characters")
        elif key in ("kind", "model", "by") and not _short(value):
            errors.append(f"facet {key} must be a string of at most {MAX_FACET} characters")
    return errors


def _field_errors(event: object) -> list[str]:
    """Every check in `validate` except the `id` ones. Never raises: each value is type-checked before use."""
    if not isinstance(event, dict):
        return ["an event must be an object"]
    errors = [f"unknown field {k!r}" for k in sorted(set(event) - _FIELDS, key=str)]
    errors += [f"missing field {k!r}" for k in _REQUIRED if k not in event]
    if errors:
        return errors
    v = event["v"]
    if isinstance(v, bool) or v != SCHEMA_VERSION:
        return [f"v must be {SCHEMA_VERSION}, got {v!r}"]
    if not valid_ts(event["ts"]):
        errors.append("ts must be UTC ISO 8601 to the second (YYYY-MM-DDTHH:MM:SS+00:00)")
    for key in ("ruleset_version", "profile"):
        if not _text(event[key]):
            errors.append(f"{key} must be a non-empty string")
    for key, allowed in (("event", EVENTS), ("actor", ACTORS), ("outcome", OUTCOMES)):
        if event[key] not in allowed:
            errors.append(f"{key} {event[key]!r} is not one of {', '.join(allowed)}")
    rule = event["rule"]
    if rule is None:
        if event["event"] not in RULELESS_EVENTS:
            errors.append(f"rule may be null only on {', '.join(RULELESS_EVENTS)} events")
    elif not _text(rule):
        errors.append("rule must be a non-empty string or null")
    if event["severity"] is not None and event["severity"] not in SEVERITIES:
        errors.append(f"severity must be one of {', '.join(SEVERITIES)} or null")
    for key, pattern, what in (("doc_id", _HEX16, "16"), ("span_hash", _HEX16, "16"), ("doc_sha", _HEX64, "64")):
        value = event[key]
        if value is not None and not (isinstance(value, str) and pattern.fullmatch(value)):
            errors.append(f"{key} must be {what} lower-case hex or null")
    errors += _facet_errors(event["facets"])
    if "proposal" in event and not _text(event["proposal"]):
        errors.append("proposal must be a non-empty string")
    if "reason" in event:
        if event["event"] not in REASON_EVENTS:
            errors.append(f"reason is allowed only on {', '.join(REASON_EVENTS)} events")
        elif not (_text(event["reason"]) and len(event["reason"]) <= MAX_REASON):
            errors.append(f"reason must be a non-empty string of at most {MAX_REASON} characters")
    if "excerpt" in event and not (isinstance(event["excerpt"], str) and len(event["excerpt"]) <= MAX_EXCERPT):
        errors.append(f"excerpt must be a string of at most {MAX_EXCERPT} characters")
    return errors


def validate(event: object) -> list[str]:
    """What's wrong with `event` against schema v1 (empty list = valid)."""
    errors = _field_errors(event)
    if errors:
        return errors
    if not (isinstance(event["id"], str) and _HEX16.fullmatch(event["id"])):
        return ["id must be 16 lower-case hex"]
    if event["id"] != event_id(event):  # safe: every field passed its type check above
        return ["id doesn't match the event's fields (edited after it was written?)"]
    return []


def _ts(ts: str | datetime | None) -> str:
    if ts is None:
        return _now()
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            raise LedgerError("ts: a datetime needs a time zone")
        return ts.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return ts


def make_event(*, event: str, actor: str, outcome: str, ruleset_version: str, profile: str, rule: str | None = None,
               severity: str | None = None, doc_id: str | None = None, doc_sha: str | None = None,
               span_hash: str | None = None, facets: Mapping | None = None, proposal: str | None = None,
               reason: str | None = None, excerpt: str | None = None, ts: str | datetime | None = None) -> dict:
    """A valid v1 event with its `id` set and `ts` now (UTC, seconds) when None. `reason` is cut to 200 characters
    and `excerpt` to 120. Raises LedgerError when the result isn't valid."""
    out: dict = {"v": SCHEMA_VERSION, "id": "", "ts": _ts(ts), "ruleset_version": ruleset_version,
                 "profile": profile, "event": event, "actor": actor, "outcome": outcome, "rule": rule,
                 "severity": severity, "doc_id": doc_id, "doc_sha": doc_sha, "span_hash": span_hash,
                 "facets": dict(facets or {})}
    if proposal is not None:
        out["proposal"] = proposal
    if reason is not None:
        out["reason"] = reason[:MAX_REASON].strip() if isinstance(reason, str) else reason
    if excerpt is not None:
        out["excerpt"] = excerpt[:MAX_EXCERPT] if isinstance(excerpt, str) else excerpt
    errors = _field_errors(out)  # before hashing, so a value JSON can't encode is a LedgerError, not a TypeError
    if errors:
        raise LedgerError("bad ledger event: " + "; ".join(errors))
    out["id"] = event_id(out)
    return out


def distinct(events: Iterable[dict]) -> list[dict]:
    """The first event for each `id`, in order."""
    seen: set[str] = set()
    out = []
    for e in events:
        if e.get("id") not in seen:
            seen.add(e.get("id"))
            out.append(e)
    return out


def _encode(event: dict) -> bytes:
    return (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _fit(event: dict) -> bytes:
    """One encoded line of at most MAX_LINE bytes: `reason` is shortened first (the id follows it, since `reason` is
    an identity field), then `excerpt`. Raises LedgerError when even without them the line is too long."""
    line = _encode(event)
    for key in ("reason", "excerpt"):
        while len(line) > MAX_LINE and key in event:
            over = len(line) - MAX_LINE
            keep = event[key][: max(0, len(event[key]) - max(1, over // 4))].rstrip()
            if keep:
                event[key] = keep
            else:
                del event[key]
            if key == "reason":
                event["id"] = event_id(event)
            line = _encode(event)
    if len(line) > MAX_LINE:
        raise LedgerError(f"ledger line is {len(line)} bytes, over the {MAX_LINE}-byte limit")
    return line


def symlinked(folder: Path, root: Path | None) -> Path | None:
    """The first symlink among `folder` and its parents below `root` (just `folder` when it isn't under `root`)."""
    folder = Path(folder)
    chain = [folder]
    if root is not None:
        try:
            rel = folder.relative_to(root)
        except ValueError:
            rel = None
        if rel is not None:
            chain = [Path(root).joinpath(*rel.parts[: i + 1]) for i in range(len(rel.parts))]
    for p in chain:
        if p.is_symlink():
            return p
    return None


def _safe_target(settings: Mapping, name: str) -> Path:
    """`<ledger_dir>/<name>`, made safe to append to; raises LedgerError otherwise."""
    folder = Path(settings["ledger_dir"])
    root = settings.get("root")
    link = symlinked(folder, Path(root) if root is not None else None)
    if link is not None:
        raise LedgerError(f"{link}: the ledger folder is a symlink, so nothing was written")
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise LedgerError(f"{folder}: can't create the ledger folder ({e})") from None
    link = symlinked(folder, Path(root) if root is not None else None)
    if link is not None:
        raise LedgerError(f"{link}: the ledger folder is a symlink, so nothing was written")
    path = folder / name
    if path.is_symlink():
        raise LedgerError(f"{path}: the ledger file is a symlink, so nothing was written")
    try:
        if config.resolve_path(path).parent != config.resolve_path(folder):
            raise LedgerError(f"{path}: resolves outside the ledger folder, so nothing was written")
    except (OSError, RuntimeError) as e:
        raise LedgerError(f"{path}: can't resolve ({e})") from None
    return path


def _open_folder(folder: Path, root: Path | None) -> int | None:
    """A directory fd for `folder`, opened one component at a time below `root` with O_NOFOLLOW (just `folder`
    itself when it isn't under `root`), so a folder swapped for a symlink after `_safe_target` checked it is refused
    rather than followed. None where the platform can't open relative to a directory fd (the checks in
    `_safe_target` are then all there is)."""
    nofollow, directory = getattr(os, "O_NOFOLLOW", 0), getattr(os, "O_DIRECTORY", 0)
    if not (nofollow and directory and os.open in os.supports_dir_fd):
        return None
    flags = os.O_RDONLY | directory | nofollow | getattr(os, "O_CLOEXEC", 0)
    folder = Path(folder)
    parts: tuple[str, ...] = ()
    if root is not None:
        try:
            parts = folder.relative_to(root).parts
        except ValueError:
            parts = ()
    try:
        if parts:
            fd = os.open(root, os.O_RDONLY | directory | getattr(os, "O_CLOEXEC", 0))
        else:
            return os.open(folder, flags)
        for part in parts:
            try:
                nxt = os.open(part, flags, dir_fd=fd)
            finally:
                os.close(fd)
            fd = nxt
        return fd
    except OSError as e:
        raise LedgerError(f"{folder}: can't open the ledger folder without following a link ({e})") from None


def _write_line(path: Path, line: bytes, root: Path | None = None) -> None:
    """Append `line` to `path` with one write. The folder is opened link-free below `root` (`_open_folder`) and the
    file relative to it with O_NOFOLLOW; a file with another hard link is refused (it could be any file)."""
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    path = Path(path)
    dir_fd = _open_folder(path.parent, Path(root) if root is not None else None)
    try:
        fd = os.open(path.name if dir_fd is not None else path, flags, 0o666, dir_fd=dir_fd)
    except OSError as e:
        raise LedgerError(f"{path}: can't open the ledger ({e})") from None
    finally:
        if dir_fd is not None:
            os.close(dir_fd)
    try:
        if os.fstat(fd).st_nlink > 1:
            raise LedgerError(f"{path}: the ledger file has another hard link, so nothing was written")
        written = os.write(fd, line)
    except OSError as e:
        raise LedgerError(f"{path}: can't write the ledger ({e})") from None
    finally:
        os.close(fd)
    if written != len(line):
        raise LedgerError(f"{path}: short write ({written} of {len(line)} bytes)")


def append(event: dict, settings: Mapping) -> Path | None:
    """Append one event; the month file's path, or None when capture is off. `excerpt` is dropped unless
    `settings["excerpts"]`. Raises LedgerError on an invalid event, a line that can't fit in 4,096 bytes, or an
    unsafe ledger folder or file."""
    if not settings.get("capture", True):
        return None
    ev = dict(event)
    if not settings.get("excerpts", False):
        ev.pop("excerpt", None)
    errors = validate(ev)
    if errors:
        raise LedgerError("bad ledger event: " + "; ".join(errors))
    line = _fit(ev)
    path = _safe_target(settings, f"{ev['ts'][:7]}.jsonl")
    _write_line(path, line, settings.get("root"))
    return path


def _months(folder: Path, since: str | None, until: str | None) -> list[Path]:
    out = []
    for p in folder.iterdir():
        m = _MONTH_FILE.fullmatch(p.name)
        if not m or p.is_symlink() or not p.is_file():
            continue
        month = m.group(1)
        if since is not None and month < since[:7]:
            continue  # every ts in the month sorts before `since`
        if until is not None and f"{month}-01T00:00:00+00:00" >= until:
            continue  # the month's earliest ts is already at or after `until`
        out.append(p)
    return sorted(out, key=lambda p: p.name)


def _read_jsonl(path: Path, valid, since: str | None, until: str | None) -> tuple[list[dict], int]:
    """(the rows of one JSON-lines file for which `valid(row)` is true, with `since <= ts < until`; the number of bad
    lines). A bad line is unparseable or fails `valid`. An unreadable file gives ([], 0). Never raises."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return [], 0
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    rows, bad = [], 0
    for raw in lines:
        try:
            row = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):  # RecursionError: absurdly nested JSON
            bad += 1
            continue
        if not valid(row):
            bad += 1
            continue
        if (since is None or row["ts"] >= since) and (until is None or row["ts"] < until):
            rows.append(row)
    return rows, bad


def _readable_folder(settings: Mapping) -> Path | None:
    """The ledger folder, or None when it's missing, symlinked (itself or a folder between the root and it) or
    can't be checked."""
    folder = Path(settings["ledger_dir"])
    root = settings.get("root")
    try:
        if symlinked(folder, Path(root) if root is not None else None) is not None or not folder.is_dir():
            return None
    except OSError:
        return None
    return folder


def read(settings: Mapping, since: str | None = None, until: str | None = None) -> tuple[list[dict], int]:
    """(valid events with `since <= ts < until`, in file order, oldest month first; the number of bad lines). A bad
    line is unparseable, fails `validate`, or has a `v` other than 1. Only the month files the range needs are
    read. A missing or symlinked ledger folder gives ([], 0); a symlinked month file is skipped."""
    folder = _readable_folder(settings)
    if folder is None:
        return [], 0
    try:
        files = _months(folder, since, until)
    except OSError:
        return [], 0
    events, bad = [], 0
    for path in files:
        rows, n = _read_jsonl(path, lambda ev: not validate(ev), since, until)
        events += rows
        bad += n
    return events, bad


def friction(kind: str, source: str, detail: str, settings: Mapping) -> None:
    """Record one friction line `{v, ts, kind, source, detail}` in `<ledger_dir>/friction.jsonl`. `detail` is cut to
    200 characters of engine message (never article text). Never raises; does nothing when capture is off or
    `kind` isn't a known friction kind."""
    try:
        if not settings.get("capture", True) or kind not in FRICTION_KINDS:
            return
        row = {"v": SCHEMA_VERSION, "ts": _now(), "kind": kind, "source": str(source)[:MAX_FACET],
               "detail": str(detail)[:MAX_DETAIL]}
        line = _encode(row)
        if len(line) > MAX_LINE:
            return
        _write_line(_safe_target(settings, "friction.jsonl"), line, settings.get("root"))
    except Exception:  # deliberate: friction is the sink for capture errors, so nothing may escape it
        return


def word_bucket(words: int) -> str:
    """The word band a count falls in: 0-20, 20-40, 40-60, 60-80, 80-120, 120-200, 200-400 or 400+."""
    for top, name in BUCKETS:
        if top is None or words < top:
            return name
    return BUCKETS[-1][1]


def valid_tool_call_row(row: object) -> bool:
    """`row` is a `tool-calls.jsonl` line `append_row` could have written: exactly the schema's fields, a known host,
    mode, bucket and outcome, an 8-hex server hash and short strings."""
    if not (isinstance(row, dict) and set(row) == _TOOL_CALL_ROW):
        return False
    outcome = row["outcome"]
    known = outcome in TOOL_CALL_OUTCOMES or (isinstance(outcome, str) and outcome.startswith("not-prose:")
                                              and outcome.split(":", 1)[1] in prose.REASONS)
    words = row["words"]
    return (known and not isinstance(row["v"], bool) and row["v"] == SCHEMA_VERSION and valid_ts(row["ts"])
            and row["host"] in toolcall.HOSTS and row["mode"] in toolcall.MODES
            and isinstance(row["tool_server_hash"], str) and _HEX8.fullmatch(row["tool_server_hash"]) is not None
            and _short(row["tool_name"]) and isinstance(row["field"], str) and len(row["field"]) <= MAX_FACET
            and isinstance(words, int) and not isinstance(words, bool) and words >= 0
            and row["bucket"] in {name for _, name in BUCKETS} and isinstance(row["prose"], bool))


def valid_chat_reply_row(row: object) -> bool:
    """`row` is a `chat-replies.jsonl` line `append_row` could have written: exactly the schema's fields, a known host,
    ask, shape (or `-`), bucket and outcome, and a 16-hex `doc` (or `-`)."""
    if not (isinstance(row, dict) and set(row) == _CHAT_REPLY_ROW):
        return False
    words = row["words"]
    return (not isinstance(row["v"], bool) and row["v"] == SCHEMA_VERSION and valid_ts(row["ts"])
            and row["host"] in toolcall.HOSTS and row["ask"] in CHAT_REPLY_ASKS
            and row["shape"] in (*reply.SHAPES, "-") and row["outcome"] in CHAT_REPLY_OUTCOMES
            and isinstance(words, int) and not isinstance(words, bool) and words >= 0
            and row["bucket"] in {name for _, name in BUCKETS}
            and isinstance(row["doc"], str) and (row["doc"] == "-" or _HEX16.fullmatch(row["doc"]) is not None))


ROW_LOGS = {"tool-calls.jsonl": valid_tool_call_row, "chat-replies.jsonl": valid_chat_reply_row}


def append_row(settings: Mapping, name: str, row: Mapping) -> None:
    """Append one decision row (`v` and `ts` added) to `<ledger_dir>/<name>`, a known log in ROW_LOGS. A row that
    doesn't validate, capture off, or any error: nothing is written. Never raises."""
    try:
        valid = ROW_LOGS.get(name)
        if valid is None or not settings.get("capture", True):
            return
        out = {"v": SCHEMA_VERSION, "ts": _now(), **row}
        for key in ("tool_name", "field"):
            if isinstance(out.get(key), str):
                out[key] = out[key][:MAX_FACET]
        if not valid(out):
            return
        line = _encode(out)
        if len(line) <= MAX_LINE:
            _write_line(_safe_target(settings, name), line, settings.get("root"))
    except Exception:  # deliberate: a decision log never breaks the check that writes it
        return


def read_rows(settings: Mapping, name: str, since: str | None = None,
              until: str | None = None) -> tuple[list[dict], int]:
    """(the rows of decision log `name` with `since <= ts < until`; the number of bad lines). Never raises."""
    valid = ROW_LOGS.get(name)
    folder = _readable_folder(settings)
    if valid is None or folder is None:
        return [], 0
    path = folder / name
    try:
        if path.is_symlink() or not path.is_file():
            return [], 0
    except OSError:
        return [], 0
    return _read_jsonl(path, valid, since, until)


def valid_friction(row: object) -> bool:
    """`row` is a friction line `friction` could have written: `{v: 1, ts, kind, source, detail}`, a known kind,
    strings within their caps."""
    return (isinstance(row, dict) and set(row) == {"v", "ts", "kind", "source", "detail"}
            and not isinstance(row["v"], bool) and row["v"] == SCHEMA_VERSION and valid_ts(row["ts"])
            and row["kind"] in FRICTION_KINDS and isinstance(row["source"], str) and len(row["source"]) <= MAX_FACET
            and isinstance(row["detail"], str) and len(row["detail"]) <= MAX_DETAIL)


def read_friction(settings: Mapping, since: str | None = None, until: str | None = None) -> tuple[list[dict], int]:
    """(friction rows with `since <= ts < until`, in file order; the number of bad lines) from
    `<ledger_dir>/friction.jsonl`. A bad line is unparseable or fails `valid_friction`. A missing or symlinked folder
    or file gives ([], 0). Never raises."""
    folder = _readable_folder(settings)
    if folder is None:
        return [], 0
    path = folder / "friction.jsonl"
    try:
        if path.is_symlink() or not path.is_file():
            return [], 0
    except OSError:
        return [], 0
    return _read_jsonl(path, valid_friction, since, until)
