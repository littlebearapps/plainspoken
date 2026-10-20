"""The model panel (Phase 6): the only place plainspoken calls a model, and only from `eval` commands.

One unlabelled prompt goes to one panel model over one of two transports:

- `claude-cli` runs `claude -p` on the Claude subscription from a new, empty temp folder (removed afterwards), with
  tools, MCP servers, slash commands and session saving off. The CLI reports a notional `total_cost_usd`; nothing is
  billed, so these calls never count against the budget and need no `--yes`.
- `openrouter` POSTs to `{base_url}/chat/completions` with one key, read from the environment variable the panel
  names. These calls are billed: a batch with any of them needs `yes=True` and runs under `max_cost_usd`. Every
  request carries the panel's privacy routing (`provider.data_collection`, "deny" unless the panel says "allow", and
  `provider.zdr` when the panel sets `zdr = true`; a model's own `zdr` overrides the panel's), so prompts holding
  private text only reach providers that don't store or train on them.

The panel is configuration (`evals/panel.toml`), checked against the gateway's free catalogue by `check_models`.
Every reply records the model asked for, the model that answered, the token counts, the cost and the UTC time.

A batch writes one JSON line per call to `<out>/replies.jsonl`, on an `O_APPEND` descriptor under the batch's lock
(a short write is finished before another thread writes), so a line is whole even with several threads writing.
Re-running with the same folder resumes: a job whose key already has a good line is skipped; a torn last line is
ignored; a job whose line recorded an error is called again (the newest line for a key is the one that counts). The
budget covers the whole folder, earlier runs included: before each billed call the runner checks the recorded spend,
plus what's reserved for calls in flight, plus this call's estimate, and stops cleanly when that would pass
`max_cost_usd`. There is one budget per batch: once it stops the batch, the unbilled `claude-cli` jobs not yet
started stop too, and wait for the resume with the rest (a stopped run is one partial state, finished by re-running
the same folder).

The key's value never reaches a reply, a run file, an error message or stderr: every text is scrubbed before it's
stored, and request headers are never recorded. Tests inject `opener` (HTTP) and `runner` (subprocess) fakes.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PANEL = PLUGIN_ROOT / "evals" / "panel.toml"
REPLIES = "replies.jsonl"
TRANSPORTS = ("openrouter", "claude-cli")
BILLED = frozenset({"openrouter"})
TEMPERATURE = 0  # every OpenRouter request; `claude -p` has no temperature flag, so the CLI samples at its default
SAMPLING = {"openrouter": f"temperature {TEMPERATURE}",
            "claude-cli": "the CLI's default sampling (claude -p has no temperature flag)"}
SAMPLING_NOTE = "Run-to-run variance isn't comparable across transports."
RETRY_DELAY = 5  # seconds before the one retry on 429, 5xx or a network failure
DEFAULT_MAX_OUT = 6000
_new_lock = threading.Lock  # the batch's spend lock (a test seam)
ERROR_MAX = 300  # characters of an error kept, cut only after the key is scrubbed
DRIFT = 0.25  # a catalogue price more than 25% from the configured one is a problem
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_ENV_VAR = re.compile(r"[A-Z_][A-Z0-9_]*")
_TOP_KEYS = {"max_out_tokens", "gateway", "model"}
_GATEWAY_KEYS = {"transport", "base_url", "key_env", "data_collection", "zdr"}
DATA_COLLECTION = ("deny", "allow")
_MODEL_KEYS = {"name", "vendor", "transport", "model", "price_in", "price_out", "zdr", "groups"}
JUDGE_GROUPS = ("J1", "J2", "J3", "J4", "JR")
CLI_ARGS = ("--safe-mode", "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
            "--no-session-persistence", "--output-format", "json")


class PanelError(ValueError):
    """A panel file, job list or environment that can't be used. The message names the key, never a value."""


@dataclass(frozen=True)
class PanelModel:
    name: str
    vendor: str
    transport: str
    model: str
    price_in: float  # US$ per million input tokens
    price_out: float  # US$ per million output tokens
    zdr: bool | None = None  # overrides the panel's zdr for this model; None = use the panel's
    groups: tuple[str, ...] | None = None  # the judge groups this model judges; None = every group

    @property
    def billed(self) -> bool:
        return self.transport in BILLED


@dataclass(frozen=True)
class Panel:
    models: tuple[PanelModel, ...]
    base_url: str
    key_env: str
    max_out_tokens: int
    data_collection: str = "deny"  # OpenRouter `provider.data_collection`: "deny" skips providers that may store prompts
    zdr: bool = False  # OpenRouter `provider.zdr`: only zero-data-retention endpoints

    def get(self, name: str) -> PanelModel:
        for m in self.models:
            if m.name == name:
                return m
        raise PanelError(f"no panel model named {name!r} (the panel has {', '.join(m.name for m in self.models)})")


@dataclass(frozen=True)
class Reply:
    key: str
    name: str
    model_requested: str
    model_reported: str
    text: str
    in_tokens: int
    out_tokens: int
    cost_usd: float
    billed: bool
    at: str
    error: str | None
    provider: str = ""  # the host OpenRouter routed the call to ("" for claude-cli, or when the reply doesn't say)


@dataclass
class BatchResult:
    replies: list[Reply] = field(default_factory=list)  # every job's latest reply after this run, in job order
    skipped: int = 0  # jobs that already had a good reply in the run folder
    spent: float = 0.0  # billed US$ recorded in the run folder, earlier runs included
    stopped: str | None = None  # why the run stopped before every job had a reply


# ---------------------------------------------------------------- config

def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_panel(path: Path) -> Panel:
    """Load and validate a panel file. Raises PanelError naming the key at fault."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise PanelError(f"{path}: can't read the panel file ({e.strerror or type(e).__name__})") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise PanelError(f"{path}: not a TOML file ({str(e).splitlines()[0]})") from None
    where = f"{path}"
    extra = sorted(set(data) - _TOP_KEYS)
    if extra:
        raise PanelError(f"{where}: unknown key {extra[0]!r} (allowed: {', '.join(sorted(_TOP_KEYS))})")
    max_out = data.get("max_out_tokens", DEFAULT_MAX_OUT)
    if not isinstance(max_out, int) or isinstance(max_out, bool) or not 0 < max_out <= 100_000:
        raise PanelError(f"{where}: max_out_tokens must be a whole number from 1 to 100000")
    gw = data.get("gateway", {})
    if not isinstance(gw, dict):
        raise PanelError(f"{where}: [gateway] must be a table")
    extra = sorted(set(gw) - _GATEWAY_KEYS)
    if extra:
        raise PanelError(f"{where}: [gateway] unknown key {extra[0]!r}")
    default_transport = gw.get("transport", "openrouter")
    if default_transport not in TRANSPORTS:
        raise PanelError(f"{where}: [gateway] transport must be one of {', '.join(TRANSPORTS)}")
    base_url = gw.get("base_url", "https://openrouter.ai/api/v1")
    if not isinstance(base_url, str) or not base_url.startswith("https://") or len(base_url) < 10:
        raise PanelError(f"{where}: [gateway] base_url must be an https:// URL")
    key_env = gw.get("key_env", "OPENROUTER_API_KEY")
    if not isinstance(key_env, str) or not _ENV_VAR.fullmatch(key_env):
        raise PanelError(f"{where}: [gateway] key_env must be an environment variable name (A-Z, 0-9, _)")
    data_collection = gw.get("data_collection", "deny")
    if data_collection not in DATA_COLLECTION:
        raise PanelError(f"{where}: [gateway] data_collection must be \"deny\" or \"allow\"")
    zdr = gw.get("zdr", False)
    if not isinstance(zdr, bool):
        raise PanelError(f"{where}: [gateway] zdr must be true or false")
    raw = data.get("model")
    if not isinstance(raw, list) or not raw:
        raise PanelError(f"{where}: no [[model]] entries: the panel needs at least one model")
    models, seen = [], set()
    for i, m in enumerate(raw, 1):
        at = f"{where}: [[model]] {i}"
        if not isinstance(m, dict):
            raise PanelError(f"{at}: must be a table")
        extra = sorted(set(m) - _MODEL_KEYS)
        if extra:
            raise PanelError(f"{at}: unknown key {extra[0]!r} (allowed: {', '.join(sorted(_MODEL_KEYS))})")
        for k in ("name", "vendor", "model"):
            if not isinstance(m.get(k), str) or not m[k].strip():
                raise PanelError(f"{at}: {k} is missing or empty")
        name = m["name"]
        at = f"{where}: [[model]] {name!r}"
        if not _NAME.fullmatch(name):
            raise PanelError(f"{at}: name must be lower-case letters, digits and hyphens")
        if name in seen:
            raise PanelError(f"{at}: name is used twice")
        seen.add(name)
        transport = m.get("transport", default_transport)
        if transport not in TRANSPORTS:
            raise PanelError(f"{at}: transport must be one of {', '.join(TRANSPORTS)}")
        for k in ("price_in", "price_out"):
            if not _number(m.get(k)) or m[k] < 0:
                raise PanelError(f"{at}: {k} must be a number of US$ per million tokens, 0 or more")
        zdr_m = m.get("zdr")
        if zdr_m is not None and not isinstance(zdr_m, bool):
            raise PanelError(f"{at}: zdr must be true or false")
        groups_m = m.get("groups")
        if groups_m is not None:
            if (not isinstance(groups_m, list) or not groups_m or len(set(groups_m)) != len(groups_m)
                    or any(g not in JUDGE_GROUPS for g in groups_m)):
                raise PanelError(f"{at}: groups must be a non-empty list of distinct judge groups from "
                                 f"{', '.join(JUDGE_GROUPS)}")
            groups_m = tuple(groups_m)
        models.append(PanelModel(name, m["vendor"].strip(), transport, m["model"].strip(), float(m["price_in"]),
                                 float(m["price_out"]), zdr_m, groups_m))
    return Panel(tuple(models), base_url.rstrip("/"), key_env, max_out, data_collection, zdr)


# ---------------------------------------------------------------- estimates

def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def estimate_cost(prompts: list[str], model: PanelModel, max_out_tokens: int = DEFAULT_MAX_OUT) -> float:
    """Estimated input tokens plus `max_out_tokens` a prompt, at the model's prices; 0 for an unbilled transport."""
    if not model.billed:
        return 0.0
    tokens_in = sum(estimate_tokens(p) for p in prompts)
    return (tokens_in * model.price_in + len(prompts) * max_out_tokens * model.price_out) / 1e6


def sampling(transports: Iterable[str]) -> dict[str, str]:
    """How each of these transports samples (`SAMPLING`), in `TRANSPORTS` order: a run records it because a model
    at temperature 0 and one at the CLI's default don't vary from run to run the same way."""
    used = set(transports)
    return {t: SAMPLING[t] for t in TRANSPORTS if t in used}


def transport_for(billed: bool) -> str:
    """The transport behind a reply or model known only by whether it's billed: OpenRouter bills, the CLI doesn't."""
    return "openrouter" if billed else "claude-cli"


def sampling_line(sampling_: dict[str, str]) -> str | None:
    """The report header line for a run's `sampling`, or None when nothing was sampled."""
    if not sampling_:
        return None
    parts = [f"{t} at {how}" for t, how in sampling_.items()]
    return f"- Sampling: {' · '.join(parts)}. {SAMPLING_NOTE}"


def usd(x: float) -> str:
    return f"{x:.2f}" if x >= 0.01 or x == 0 else f"{x:.4f}"


ANTHROPIC_ALIASES = ("opus", "sonnet", "haiku")  # the claude CLI's model aliases (`opus[1m]` counts too)


def is_anthropic(model: str, vendor: str | None = None) -> bool:
    """An Anthropic model: by the panel's vendor when it names one, else by the model id (`claude-…`,
    `anthropic/…`, or one of the CLI's aliases `opus`, `sonnet`, `haiku`). Judges favour their own family and
    plainspoken's drafts are Claude-written, so the cross-vendor figures leave these models out."""
    if vendor:
        return vendor.casefold() == "anthropic"
    m = (model or "").strip().casefold()
    return m.startswith(("claude-", "anthropic/")) or m.split("[", 1)[0] in ANTHROPIC_ALIASES


# ---------------------------------------------------------------- helpers

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_line(text: str, limit: int | None = None) -> str:
    """The first line, uncut unless `limit` is given. Never cut text that may hold the key before it's scrubbed:
    a key straddling the cut would leave its prefix behind. `_reply` scrubs, then cuts."""
    line = (text.strip().splitlines() or [""])[0]
    return line if limit is None else line[:limit]


def scrubber(secret: str) -> Callable[[str], str]:
    """A function that replaces `secret` (as is, and URL-quoted) with `***` in any text. Shared with the drafting
    harness, whose run index must never hold the key either."""
    forms = {secret, urllib.parse.quote(secret, safe=""), urllib.parse.quote_plus(secret)} if secret else set()

    def scrub(text: str) -> str:
        for form in forms:
            text = text.replace(form, "***")
        return text
    return scrub


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _reply(key: str, model: PanelModel, scrub: Callable[[str], str], *, text: str = "", reported: str = "",
           tin: int = 0, tout: int = 0, cost: float = 0.0, error: str | None = None, provider: str = "") -> Reply:
    return Reply(key=key, name=model.name, model_requested=model.model, model_reported=scrub(reported),
                 text=scrub(text), in_tokens=tin, out_tokens=tout, cost_usd=round(max(cost, 0.0), 6),
                 billed=model.billed, at=_now(),
                 error=None if error is None else (_first_line(scrub(error), ERROR_MAX) or "error"),
                 provider=_first_line(scrub(provider), ERROR_MAX) if provider else "")


def default_opener_for(timeout: float) -> Callable:
    def opener(request: urllib.request.Request) -> tuple[int, bytes]:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            return r.status, r.read()
    return opener


default_opener = None  # tests patch this to a fake; None means a real urllib opener


def default_runner_for(timeout: float, env: Mapping[str, str] | None = None) -> Callable:
    """Runs a child process (the `claude` CLI) with `timeout`; `env` None inherits ours."""
    child = None if env is None else dict(env)

    def runner(args: list[str], *, input: str, cwd: str) -> subprocess.CompletedProcess:
        return subprocess.run(args, input=input, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=child)
    return runner


def child_env(env: Mapping[str, str], key_env: str) -> dict[str, str]:
    """`env` without the panel's API key variable: a `claude` child never needs it, so it never gets it."""
    return {k: v for k, v in env.items() if k != key_env}


def _open(opener: Callable, request: urllib.request.Request) -> tuple[int, str]:
    """(status, body text); an HTTPError becomes its status and body. Other exceptions propagate."""
    try:
        status, body = opener(request)
    except urllib.error.HTTPError as e:
        try:
            body = e.read() or b""
        except Exception:  # noqa: BLE001 (an unreadable error body is just empty)
            body = b""
        status = e.code
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
    return (status if isinstance(status, int) else 0), text


# ---------------------------------------------------------------- transports

def call(model: PanelModel, prompt: str, panel: Panel, *, opener: Callable | None = None,
         runner: Callable | None = None, env: Mapping[str, str] = os.environ, timeout: float = 180,
         key: str = "") -> Reply:
    """One prompt to one model; `key` labels the Reply. Transport failures are an error Reply; a missing API key
    for a billed model is a PanelError, raised before anything is sent."""
    secret = (env.get(panel.key_env) or "").strip()
    if model.transport == "claude-cli":
        runner = runner or default_runner_for(timeout, child_env(env, panel.key_env))
        return _call_cli(model, prompt, runner, scrubber(secret), key)
    if not secret:
        raise PanelError(f"{panel.key_env} isn't set: the {model.transport} models need an API key in that "
                         "environment variable, so nothing was sent")
    return _call_openrouter(model, prompt, panel, opener or default_opener or default_opener_for(timeout),
                            secret, key)


def _call_openrouter(model: PanelModel, prompt: str, panel: Panel, opener: Callable, secret: str,
                     key: str) -> Reply:
    scrub = scrubber(secret)
    provider: dict = {"data_collection": panel.data_collection}
    if (panel.zdr if model.zdr is None else model.zdr):
        provider["zdr"] = True
    body = json.dumps({"model": model.model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": TEMPERATURE, "max_tokens": panel.max_out_tokens, "usage": {"include": True},
                       "provider": provider}).encode("utf-8")
    error = "no attempt"
    for attempt in (1, 2):
        if attempt == 2:
            time.sleep(RETRY_DELAY)
        request = urllib.request.Request(f"{panel.base_url}/chat/completions", data=body, method="POST",
                                         headers={"Authorization": f"Bearer {secret}",
                                                  "Content-Type": "application/json",
                                                  "X-Title": "plainspoken-evals"})
        try:
            status, text = _open(opener, request)
        except Exception as e:  # noqa: BLE001 (a network boundary: a timeout or refused connection is retried once)
            error = f"OpenRouter: can't reach the API ({_first_line(scrub(str(e) or type(e).__name__))})"
            continue
        if status == 429 or status >= 500 or status == 0:
            error = f"OpenRouter HTTP {status}: {_first_line(scrub(text)) or 'no message'}"
            continue
        if not 200 <= status < 300:
            return _reply(key, model, scrub, error=f"OpenRouter HTTP {status}: "
                                                    f"{_first_line(scrub(text)) or 'no message'}")
        return _parse_openrouter(model, text, scrub, key)
    return _reply(key, model, scrub, error=error)


def _parse_openrouter(model: PanelModel, text: str, scrub: Callable[[str], str], key: str) -> Reply:
    try:
        data = json.loads(text)
    except ValueError:
        return _reply(key, model, scrub, error="OpenRouter: the answer wasn't JSON")
    if not isinstance(data, dict):
        return _reply(key, model, scrub, error="OpenRouter: the answer wasn't a JSON object")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    tin, tout = _int(usage.get("prompt_tokens")), _int(usage.get("completion_tokens"))
    cost = usage.get("cost")
    if not _number(cost) or cost < 0:
        cost = (tin * model.price_in + tout * model.price_out) / 1e6
    reported = data.get("model") if isinstance(data.get("model"), str) else ""
    served = data.get("provider") if isinstance(data.get("provider"), str) else ""
    base = {"reported": reported, "tin": tin, "tout": tout, "cost": float(cost), "provider": served}
    if isinstance(data.get("error"), dict):
        msg = data["error"].get("message")
        return _reply(key, model, scrub, error=f"OpenRouter: {_first_line(str(msg or 'error'))}", **base)
    choices = data.get("choices")
    content = finish = None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        finish = choices[0].get("finish_reason")
        if isinstance(message, dict):
            content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        why = f" (finish_reason {_first_line(scrub(str(finish)))})" if isinstance(finish, str) and finish else ""
        return _reply(key, model, scrub, error=f"OpenRouter: the answer had no message content{why}", **base)
    return _reply(key, model, scrub, text=content, **base)


def _call_cli(model: PanelModel, prompt: str, runner: Callable, scrub: Callable[[str], str], key: str) -> Reply:
    args = ["claude", "-p", "--model", model.model, *CLI_ARGS]
    folder = tempfile.mkdtemp(prefix="plainspoken-panel-")
    try:
        try:
            done = runner(args, input=prompt, cwd=folder)
        except FileNotFoundError:
            return _reply(key, model, scrub, error="claude-cli: the claude command isn't installed or on PATH")
        except subprocess.TimeoutExpired:
            return _reply(key, model, scrub, error="claude-cli: timed out")
        except Exception as e:  # noqa: BLE001 (a process boundary: whatever it raises becomes one line)
            return _reply(key, model, scrub, error=f"claude-cli: {type(e).__name__}: {_first_line(str(e))}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    parsed = parse_cli(done.returncode, done.stdout, done.stderr)
    base = {"reported": "+".join(parsed.models), "tin": parsed.in_tokens, "tout": parsed.out_tokens,
            "cost": parsed.cost_usd}
    if parsed.error is not None:
        return _reply(key, model, scrub, error=parsed.error, **(base if parsed.json else {}))
    return _reply(key, model, scrub, text=parsed.text, **base)


@dataclass(frozen=True)
class CliResult:
    """What one `claude -p --output-format json` run gave back. `error` is None or one unscrubbed reason; `json` says
    whether the output was a JSON object (so the usage fields mean something)."""
    text: str
    models: tuple[str, ...]  # the `modelUsage` keys, sorted
    in_tokens: int
    out_tokens: int
    cost_usd: float  # the CLI's notional `total_cost_usd`
    error: str | None
    json: bool


def parse_cli(returncode: int, stdout: str | bytes | None, stderr: str | bytes | None) -> CliResult:
    """Parse a finished `claude -p --output-format json` run. A non-zero exit, `is_error`, output that isn't a JSON
    object or an empty `result` is an error with a reason. Shared with the drafting harness
    (`scripts/dev/draft_runs.py`)."""
    out = stdout if isinstance(stdout, str) else (stdout or b"").decode("utf-8", "replace")
    err = stderr if isinstance(stderr, str) else (stderr or b"").decode("utf-8", "replace")
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        if returncode != 0:
            why = _first_line(err) or _first_line(out) or "no message"
            return CliResult("", (), 0, 0, 0.0, f"claude-cli exited {returncode}: {why}", False)
        return CliResult("", (), 0, 0, 0.0, "claude-cli: the output wasn't JSON", False)
    usage = data.get("modelUsage") if isinstance(data.get("modelUsage"), dict) else {}
    models = tuple(sorted(str(k) for k in usage))
    u = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    tin = sum(_int(u.get(k)) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    tout = _int(u.get("output_tokens"))
    cost = data.get("total_cost_usd")
    cost = float(cost) if _number(cost) else 0.0
    result = data.get("result")
    error = None
    if data.get("is_error") is True or returncode != 0:
        why = _first_line(result) if isinstance(result, str) and result.strip() else (_first_line(err) or "is_error")
        error = f"claude-cli reported an error: {why}"
    elif not isinstance(result, str) or not result.strip():
        error = "claude-cli: the output had no result"
    return CliResult(result if error is None else "", models, tin, tout, cost, error, True)


# ---------------------------------------------------------------- run file

_FIELD_TYPES = {f.name: f.type for f in fields(Reply)}
_OPTIONAL = {"provider"}  # added after run folders existed: a line without it still reads


def _from_line(line: bytes) -> Reply | None:
    try:
        d = json.loads(line)
    except ValueError:
        return None
    if not isinstance(d, dict) or not set(_FIELD_TYPES) - _OPTIONAL <= set(d) <= set(_FIELD_TYPES):
        return None
    for k in ("key", "name", "model_requested", "model_reported", "text", "at", *(_OPTIONAL & set(d))):
        if not isinstance(d[k], str):
            return None
    if not d["key"] or not isinstance(d["billed"], bool) or not (d["error"] is None or isinstance(d["error"], str)):
        return None
    if not all(type(d[k]) is int and d[k] >= 0 for k in ("in_tokens", "out_tokens")) or not _number(d["cost_usd"]):
        return None  # token counts are whole numbers; a cost may be a whole one
    return Reply(**d)


def reply_lines(path: Path) -> list[Reply]:
    """Every good line of a replies file in file order, superseded and errored calls included (what each call
    cost). Lines that don't parse are skipped; a missing file gives []."""
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return []
    return [r for r in (_from_line(ln) for ln in raw.split(b"\n") if ln.strip()) if r is not None]


def read_replies(path: Path) -> tuple[dict[str, Reply], float]:
    """The newest good reply for each key in a replies file, and the billed US$ it records (every line counts).
    Lines that don't parse (a torn last line) are ignored."""
    latest: dict[str, Reply] = {}
    spent = 0.0
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return latest, spent
    for line in raw.split(b"\n"):
        r = _from_line(line) if line.strip() else None
        if r is None:
            continue
        latest[r.key] = r
        if r.billed:
            spent += r.cost_usd
    return latest, spent


def _open_append(path: Path) -> int:
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags, 0o600)


def _write(fd: int, data: bytes) -> None:
    """All of `data`: a short `os.write` (legal on a regular file) is followed by the rest, so a line is never left
    half-written. Callers hold the batch lock, so no other line lands between the parts."""
    view = memoryview(data)
    done = 0
    while done < len(data):
        n = os.write(fd, view[done:])
        if n <= 0:
            raise OSError(f"short write ({done} of {len(data)} bytes)")
        done += n


def _line(r: Reply) -> bytes:
    """One JSON line, ASCII only: a lone surrogate a model sent as a JSON escape (\\ud800) stays an escape, so the
    line always encodes and `read_replies` reads back the same text."""
    return (json.dumps(asdict(r), ensure_ascii=True, sort_keys=True) + "\n").encode("ascii")


# ---------------------------------------------------------------- batch

def run_batch(jobs: list[tuple[str, PanelModel, str]], panel: Panel, out: Path, *, max_cost_usd: float = 5.0,
              yes: bool = False, concurrency: int = 4, opener: Callable | None = None,
              runner: Callable | None = None, env: Mapping[str, str] = os.environ) -> BatchResult:
    """Run every job not already done in `out/replies.jsonl`. Billed jobs need `yes`; the recorded billed spend
    in the folder never passes `max_cost_usd` (bar the gap between an estimate and a reply's actual cost). A job
    whose call fails in any way gets an error Reply; the run carries on. A budget stop halts the whole batch,
    unbilled jobs included (one budget per batch). A reply that can't be written stops the run and is left out of
    `replies`, which only ever holds what the folder holds; its cost still counts in `spent`, as it was spent."""
    keys = [j[0] for j in jobs]
    if any(not isinstance(k, str) or not k for k in keys):
        raise PanelError("every job needs a non-empty key")
    if len(set(keys)) != len(keys):
        raise PanelError("job keys must be unique within a run")
    if any(not isinstance(m, PanelModel) or not isinstance(p, str) for _, m, p in jobs):
        raise PanelError("every job needs a panel model and a text prompt")
    if not _number(max_cost_usd) or max_cost_usd < 0:
        raise PanelError("max_cost_usd must be a number, 0 or more")
    if not isinstance(concurrency, int) or concurrency < 1:
        raise PanelError("concurrency must be 1 or more")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / REPLIES
    latest, spent = read_replies(path)
    done = {k for k, r in latest.items() if r.error is None}
    todo = [j for j in jobs if j[0] not in done]
    result = BatchResult(skipped=len(jobs) - len(todo), spent=round(spent, 6))

    def finish() -> BatchResult:
        result.replies = [latest[k] for k in keys if k in latest]
        return result

    billed = [j for j in todo if j[1].billed]
    if billed and not yes:
        est = sum(estimate_cost([p], m, panel.max_out_tokens) for _, m, p in billed)
        result.stopped = f"paid run needs --yes (estimate US${usd(est)})"
        return finish()
    if billed and not (env.get(panel.key_env) or "").strip():
        raise PanelError(f"{panel.key_env} isn't set: the paid models need an API key in that environment "
                         "variable, so nothing was sent")
    if not todo:
        return finish()

    lock = _new_lock()
    scrub = scrubber((env.get(panel.key_env) or "").strip())
    state = {"spent": spent, "reserved": 0.0, "stopped": None}
    fd = _open_append(path)
    try:
        with lock:  # a torn last line from an interrupted run must not swallow the next line
            if path.stat().st_size:
                with open(path, "rb") as f:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        _write(fd, b"\n")

        def work(job: tuple[str, PanelModel, str]) -> Reply | None:
            key, model, prompt = job
            est = estimate_cost([prompt], model, panel.max_out_tokens)
            with lock:
                if state["stopped"]:
                    return None
                if model.billed and state["spent"] + state["reserved"] + est > max_cost_usd + 1e-12:
                    state["stopped"] = (f"budget reached: US${usd(state['spent'])} spent of the "
                                        f"US${max_cost_usd:.2f} limit (--max-cost-usd), and the next call is "
                                        f"estimated at US${usd(est)}")
                    return None
                state["reserved"] += est
            try:
                try:
                    reply = call(model, prompt, panel, opener=opener, runner=runner, env=env, key=key)
                except Exception as e:  # noqa: BLE001 (never a traceback: the job gets an error Reply, the run goes on)
                    reply = _reply(key, model, scrub, error=f"{type(e).__name__}: {_first_line(str(e))}")
            except BaseException:  # an interrupt: drop the reservation alone, then let it through
                with lock:
                    state["reserved"] -= est
                raise
            with lock:  # settle in one step: a split here lets another worker see neither the reservation nor the spend
                state["reserved"] -= est
                if reply.billed:
                    state["spent"] += reply.cost_usd
            with lock:  # one writer at a time, so a line finished after a short write is never split by another
                try:
                    _write(fd, _line(reply))
                except Exception as e:  # noqa: BLE001 (serialising or writing: a clean stop, never a traceback)
                    why = _first_line(scrub(f"{type(e).__name__}: {e}"), 200)
                    state["stopped"] = state["stopped"] or f"can't write {path.name} ({why})"
                    try:
                        _write(fd, b"\n")  # end any part-written line, so the next line in flight stays whole
                    except Exception:  # noqa: BLE001 (best effort: the resume's torn-line guard covers it too)
                        pass
                    return None  # not in the folder, so not in `replies`
            return reply

        with ThreadPoolExecutor(max_workers=min(concurrency, len(todo))) as pool:
            for reply in pool.map(work, todo):
                if reply is not None:
                    latest[reply.key] = reply
    finally:
        os.close(fd)
    result.spent = round(state["spent"], 6)
    result.stopped = state["stopped"]
    return finish()


# ---------------------------------------------------------------- catalogue check

def _drift(configured: float, catalogue: float) -> bool:
    if configured == 0:
        return catalogue > 0
    return abs(catalogue - configured) / configured > DRIFT


def check_models(panel: Panel, *, opener: Callable | None = None, timeout: float = 30) -> list[str]:
    """Check every billed model against the gateway's free catalogue (`GET {base_url}/models`, no key): a slug the
    catalogue doesn't list, or a price more than 25% from the configured one, is a problem. An unreachable or
    unreadable catalogue is one problem."""
    opener = opener or default_opener or default_opener_for(timeout)
    request = urllib.request.Request(f"{panel.base_url}/models", method="GET", headers={"Accept": "application/json"})
    try:
        status, text = _open(opener, request)
    except Exception as e:  # noqa: BLE001 (a network boundary)
        why = _first_line(str(e) or type(e).__name__, 200)  # no key is sent to the catalogue
        return [f"can't reach the catalogue at {panel.base_url}/models ({why})"]
    if not 200 <= status < 300:
        return [f"the catalogue at {panel.base_url}/models answered HTTP {status}"]
    try:
        data = json.loads(text)
        listed = {m["id"]: m for m in data["data"] if isinstance(m, dict) and isinstance(m.get("id"), str)}
    except (ValueError, KeyError, TypeError):
        return [f"the catalogue at {panel.base_url}/models wasn't the JSON expected"]
    problems = []
    for m in panel.models:
        if not m.billed:
            continue
        entry = listed.get(m.model)
        if entry is None:
            problems.append(f"{m.name}: {m.model} isn't in the catalogue (renamed or withdrawn?)")
            continue
        pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
        for ours, theirs in (("price_in", "prompt"), ("price_out", "completion")):
            try:
                live = float(pricing[theirs]) * 1e6
            except (KeyError, TypeError, ValueError):
                problems.append(f"{m.name}: the catalogue gives no {theirs} price for {m.model}")
                continue
            configured = getattr(m, ours)
            if not math.isfinite(live) or _drift(configured, live):
                problems.append(f"{m.name}: {ours} is {configured:g} US$/M but the catalogue says {live:g} "
                                f"(more than {DRIFT:.0%} apart): update the panel file")
    return problems
