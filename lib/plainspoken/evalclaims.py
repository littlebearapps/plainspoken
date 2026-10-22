"""Claims-checker validation (Phase 6 evals): the CL golden cases → one Claude model → per-claim verdicts → accuracy.

`prompt_for` turns a CL case into one self-contained prompt: the CL part of `data/rubrics/claims-inline.md`, the whole
claims rubric (`data/rubrics/claims.md`, the file the `claims-checker` agent reads), an `Input` block with the hashes
`claims checker-input` would give, the article and its ledger (`golden.claims_ledger`, as JSON). A case's id, origin
and labels (`expect`, `why`) never reach a prompt.

`verdicts` reads a reply as `claims record` does (`checker.parse_reply`, `checker.verify`): a claim the reply files a
`blocking` finding against is `fail`, any other claim `pass` (a warning is still a pass). A reply that isn't the
JSON asked for, or whose call failed, is an **error** for each of its claims, never a pass or a fail; a case with
no reply yet is **missing**. `score` compares the verdicts with the labels: per case, per rule and overall, with
accuracy, TPR (fails caught) and TNR (passes left alone), each with a 95% Wilson interval. The positive label is
`fail`, so a checker that blocks everything scores TNR 0, and one that blocks nothing scores TPR 0.

The run is Claude only: `claude -p` on the subscription (`llm_panel` transport `claude-cli`). Nothing is billed;
the CLI reports a notional cost (what the tokens would cost through the API), and `estimate` prices a prompt at the
model's list price so `eval claims --max-cost-usd` can stop before the notional spend would pass the cap."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path

from plainspoken import checker, evalprompts
from plainspoken import evalmetrics as em
from plainspoken.adapters.llm_panel import PanelModel, Reply, estimate_tokens, usd
from plainspoken.golden import CLAIMS, CL_RULES, GoldenCase, claims_ledger, text_sha256

SCHEMA = 1
RUBRICS = Path(__file__).resolve().parents[2] / "data" / "rubrics"
RUBRIC = RUBRICS / "claims.md"
INLINE = RUBRICS / "claims-inline.md"
POSITIVE = "fail"
ARTICLE_NAME = "article.md"
LEDGER_NAME = "article.claims.json"
# US$ per million tokens, input and output: Anthropic's list prices (cached 2026-10-06). Only the estimate uses them.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
ALIASES = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
CLI_OVERHEAD_TOKENS = 2500  # input `claude -p` adds to each prompt (about 2,300 in the 2026-10-21 judge runs)
EST_OUT_TOKENS = 1500  # a reply with a few findings, thinking included
_MODEL = re.compile(r"claude-[a-z0-9][a-z0-9.-]*|opus|sonnet|haiku")
ERROR_MAX = 160


def claude_model(model: str) -> bool:
    """A model `claude -p --model` takes: a `claude-…` id or one of the CLI's aliases. Nothing from another vendor,
    and no gateway slug (`anthropic/…`)."""
    return isinstance(model, str) and _MODEL.fullmatch(model.strip()) is not None


def list_price(model: str) -> tuple[float, float] | None:
    """(input, output) US$ per million tokens for a known model or alias, else None."""
    return PRICES.get(ALIASES.get(model, model))


def make_model(model: str, price_in: float, price_out: float) -> PanelModel:
    """The one model a run uses, on the `claude-cli` transport (never billed). Its prices are list prices, for the
    estimate only."""
    return PanelModel(name=model, vendor="Anthropic", transport="claude-cli", model=model, price_in=price_in,
                      price_out=price_out)


# ---------------------------------------------------------------- the prompt

def ledger_text(case: GoldenCase) -> str:
    return json.dumps(claims_ledger(case), indent=2, ensure_ascii=False) + "\n"


def input_block(case: GoldenCase) -> dict:
    """The checker's input, as `claims checker-input` gives it, for the inline files."""
    return {"article": ARTICLE_NAME, "ledger": LEDGER_NAME, "rubric": RUBRIC.name, "regulated_matrix": "none",
            "article_sha256": text_sha256(case.text), "ledger_sha256": text_sha256(ledger_text(case)),
            "matrix_sha256": "none"}


def _inline_part() -> str:
    return evalprompts._block(INLINE, "##", "CL").split("\n", 1)[1].strip()


def prompt_for(case: GoldenCase) -> str:
    """The self-contained prompt for one CL case: the wrapper, the rubric, the input, the article, the ledger."""
    if case.group != CLAIMS:
        raise ValueError(f"prompt_for is for {CLAIMS} cases, not {case.group}")
    body = json.dumps(input_block(case), indent=2, ensure_ascii=False)
    led = ledger_text(case)
    parts = [_inline_part(), RUBRIC.read_text(encoding="utf-8").strip()]
    for title, lang, text in (("Input", "json", body), (f"Article ({ARTICLE_NAME})", "markdown", case.text),
                              (f"Ledger ({LEDGER_NAME})", "json", led)):
        fence = evalprompts._fence(text)
        parts.append(f"## {title}\n\n{fence}{lang}\n{text.rstrip(chr(10))}\n{fence}")
    return "\n\n".join(parts) + "\n"


def job_key(case_id: str, model_name: str) -> str:
    return f"{case_id}|{model_name}"


def jobs(cases: list[GoldenCase], model: PanelModel) -> list[tuple[str, PanelModel, str]]:
    return [(job_key(c.id, model.name), model, prompt_for(c)) for c in cases if c.group == CLAIMS]


def prompts_sha256(job_list: Iterable[tuple[str, PanelModel, str]]) -> str:
    """One hash over every job's key and prompt: a changed case, rubric or wrapper gives a new hash."""
    h = hashlib.sha256()
    for key, _, prompt in job_list:
        h.update(key.encode("utf-8") + b"\0" + prompt.encode("utf-8") + b"\0")
    return h.hexdigest()


def estimate(prompt: str, model: PanelModel) -> float:
    """Notional US$ for one call: the prompt plus the CLI's overhead in, EST_OUT_TOKENS out, at list price."""
    return ((estimate_tokens(prompt) + CLI_OVERHEAD_TOKENS) * model.price_in + EST_OUT_TOKENS * model.price_out) / 1e6


# ---------------------------------------------------------------- reading a reply

def verdicts(text: str, case: GoldenCase) -> dict:
    """What a reply says about each of the case's claims. ValueError when the reply can't be scored (not the JSON
    the rubric asks for, or a finding whose severity isn't blocking or warning).

    `{"verdicts": {claim_id: "fail"|"pass"}, "classes": {claim_id: [blocking classes]}, "warnings": {claim_id:
    [warning classes]}, "extra": [blocking findings naming no claim of the case, as "class: evidence"],
    "reply_result", "unverified": findings whose evidence isn't verbatim, "hashes_ok"}`."""
    reply = checker.parse_reply(text)
    checked = checker.verify(reply, case.text, claims_ledger(case))
    ids = [c["claim_id"] for c in case.claims]
    blocking: dict[str, list[str]] = {i: [] for i in ids}
    warnings: dict[str, list[str]] = {i: [] for i in ids}
    extra = []
    for f in checked["findings"]:
        cid, cls = f.get("claim_id"), str(f.get("class"))
        if cid in blocking:
            (blocking if f["severity"] == "blocking" else warnings)[cid].append(cls)
        elif f["severity"] == "blocking":
            extra.append(f"{cls}: {str(f.get('evidence'))[:80]}")
    want = input_block(case)
    hashes_ok = all(reply.get(k) == want[k] for k in ("article_sha256", "ledger_sha256", "matrix_sha256"))
    return {"verdicts": {i: ("fail" if blocking[i] else "pass") for i in ids}, "classes": blocking,
            "warnings": warnings, "extra": extra, "reply_result": reply.get("result"),
            "unverified": checked["unverified_evidence"], "hashes_ok": hashes_ok}


# ---------------------------------------------------------------- scoring

def _rates(pairs: list[tuple[str, str | None]]) -> dict:
    conf = em.confusion(pairs, POSITIVE)
    right = conf["tp"] + conf["tn"]
    answered = right + conf["fp"] + conf["fn"]
    lo, hi = em.wilson(right, answered)
    acc = {"value": right / answered if answered else None, "k": right, "n": answered, "ci": [lo, hi]}
    return {**conf, "accuracy": acc, **em.rates(conf)}


def _case_row(case: GoldenCase, reply: Reply | None) -> dict:
    row = {"id": case.id, "rule": case.rule, "label": case.label, "status": case.status,
           "expected_result": "BLOCKED" if case.label == "fail" else "PASS", "missing": reply is None, "error": None,
           "reply_result": None, "extra": [], "unverified": 0, "hashes_ok": None, "cost_usd": 0.0, "claims": []}
    got: dict | None = None
    if reply is not None:
        row["cost_usd"] = reply.cost_usd
        if reply.error is not None:
            row["error"] = f"call failed: {reply.error}"[:ERROR_MAX]
        else:
            try:
                got = verdicts(reply.text, case)
            except ValueError as e:
                row["error"] = f"unscorable reply: {e}"[:ERROR_MAX]
    if got is not None:
        row.update(reply_result=got["reply_result"], extra=got["extra"], unverified=got["unverified"],
                   hashes_ok=got["hashes_ok"])
    for c in case.claims:
        cid = c["claim_id"]
        answer = None if got is None else got["verdicts"][cid]
        row["claims"].append({"claim_id": cid, "expect": c["expect"], "got": answer,
                              "ok": None if answer is None else answer == c["expect"],
                              "blocking": [] if got is None else got["classes"][cid],
                              "warnings": [] if got is None else got["warnings"][cid], "why": c["why"]})
    return row


def score(cases: list[GoldenCase], replies: dict[str, Reply], model: str, *,
          calls: Iterable[Reply] | None = None) -> dict:
    """The summary for `cases` against `replies` (key → newest reply). `calls` (every recorded call, retries
    included) gives the notional cost; without it, the scored replies do."""
    cl = [c for c in cases if c.group == CLAIMS]
    rows = [_case_row(c, replies.get(job_key(c.id, model))) for c in cl]
    answered = [r for r in rows if not r["missing"]]
    pairs = [(x["expect"], x["got"]) for r in answered for x in r["claims"]]
    by_rule = {}
    for rule in [r for r in CL_RULES if any(c.rule == r for c in cl)]:
        by_rule[rule] = _rates([(x["expect"], x["got"]) for r in answered if r["rule"] == rule for x in r["claims"]])
    scored = [r for r in answered if r["error"] is None]
    if calls is None:
        ids = {c.id for c in cl}
        calls = [r for r in replies.values() if r.key.split("|", 1)[0] in ids]
    return {"schema": SCHEMA, "model": model, "claims": _rates(pairs), "rules": by_rule,
            "cases": {"n": len(rows), "missing": len(rows) - len(answered),
                      "errors": sum(r["error"] is not None for r in answered),
                      "all_claims_right": sum(all(x["ok"] for x in r["claims"]) for r in scored),
                      "result_right": sum(r["reply_result"] == r["expected_result"] for r in scored),
                      "scored": len(scored), "hash_mismatches": sum(r["hashes_ok"] is False for r in scored)},
            "notional_usd": round(sum(r.cost_usd for r in calls), 6), "rows": rows}


# ---------------------------------------------------------------- report

def _rate(r: dict) -> str:
    lo, hi = r["ci"]
    value = "n/a" if r["value"] is None else f"{r['value']:.2f}"
    return f"{value} [{lo:.2f}–{hi:.2f}] ({r['k']}/{r['n']})"


def _claim_line(x: dict) -> str:
    mark = "error" if x["ok"] is None else ("ok" if x["ok"] else "MISS")
    detail = ""
    if x["got"] is not None:
        found = ", ".join(x["blocking"]) or "no blocking finding"
        warn = f"; warnings: {', '.join(x['warnings'])}" if x["warnings"] else ""
        detail = f" (got {x['got']}: {found}{warn})"
    return f"  {mark:<5} {x['claim_id']} expect {x['expect']}{detail}"


def render(summary: dict) -> str:
    """Per case: the expected and given result and each claim's verdict; then the accuracy, TPR and TNR overall and
    per rule, and the misses to file."""
    run = summary.get("run") or {}
    lines = [f"# Claims-checker validation: {run.get('id', 'run')}", "",
             f"- Model: {summary['model']} (claude -p on the subscription; nothing billed)",
             f"- Cost: US${usd(summary['notional_usd'])} notional"]
    if run.get("stopped"):
        lines.append(f"- Stopped early: {run['stopped']}")
    lines += ["", "A claim's verdict is fail when the reply files a blocking finding against it, else pass. An error "
              "(a failed call or a reply that isn't the JSON asked for) is never a pass or a fail.", "", "## Cases", ""]
    for r in summary["rows"]:
        if r["missing"]:
            lines.append(f"{r['id']}: not run")
            continue
        head = f"{r['id']} ({r['rule']}, {r['status']}): expected {r['expected_result']}, "
        head += f"got {r['reply_result']}" if r["error"] is None else r["error"]
        lines.append(head)
        lines += [_claim_line(x) for x in r["claims"]]
        lines += [f"  extra blocking finding (no claim of this case): {e}" for e in r["extra"]]
        notes = []
        if r["unverified"]:
            notes.append(f"{r['unverified']} finding(s) quote evidence that isn't verbatim")
        if r["hashes_ok"] is False:
            notes.append("the reply's hashes aren't the input's (claims record would refuse it)")
        lines += [f"  note: {n}" for n in notes]
    c, cases = summary["claims"], summary["cases"]
    lines += ["", "## Accuracy", "",
              f"- Claims: accuracy {_rate(c['accuracy'])} · TPR, fails caught {_rate(c['tpr'])} · "
              f"TNR, passes left alone {_rate(c['tnr'])} · errors {c['errors']}",
              f"- Cases: every claim right in {cases['all_claims_right']} of {cases['scored']} scored · result "
              f"(PASS/BLOCKED) right in {cases['result_right']} of {cases['scored']} · errors {cases['errors']} · "
              f"not run {cases['missing']}"]
    if summary["rules"]:
        lines += ["", "| rule | accuracy | TPR | TNR | errors |", "|---|---|---|---|---|"]
        for rule, r in summary["rules"].items():
            lines.append(f"| {rule} | {_rate(r['accuracy'])} | {_rate(r['tpr'])} | {_rate(r['tnr'])} | "
                         f"{r['errors']} |")
    misses = [(r["id"], x) for r in summary["rows"] for x in r["claims"] if x["ok"] is False]
    lines += ["", "## Misses", ""]
    if misses:
        lines += [f"- {cid} {x['claim_id']}: expected {x['expect']}, got {x['got']}. {x['why']}" for cid, x in misses]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"
