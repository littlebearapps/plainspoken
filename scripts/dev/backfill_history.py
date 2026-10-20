"""Build a kaizen ledger from a host engine's history (the retrodiction fixture).

    python3 -m scripts.dev.backfill_history --manifest M.json --out ledger.jsonl [--profile-map GLOB=PROFILE ...]

The manifest names the host's old lint reports and article texts. It holds real paths, so keep it out of the repo:

    {"ruleset_version": "3", "profile": "host", "ts": "2026-09-27T00:00:00+00:00",
     "articles": [{"lint": "path/a.json", "text": "path/a.md", "published": true,
                   "judges": ["path/a.J1.judge.json", ...], "justify": "path/a.justify.json",
                   "jr": "path/a.JR.judge.json"}, ...],
     "overrides": [{"article": 0, "rule": "12f", "metric": "mattr", "outcome": "dismissed", "kind": "unfixable",
                    "reason": "..."}]}

`ts` is one ISO timestamp for every event, or `{"lint": ts, "publish": ts, "override": ts}` (one per event family;
judge, justify and JR events take the `lint` one). Relative paths are read from the manifest's folder. `article` in
an override is the article's index in the list. `judges`, `justify` and `jr` are optional.

For each article (index n, doc id `ledger.label_id("article-<n>")`, never the host path):
- the text is parsed with plainspoken's `doc.parse` and the shipped default profile (FAQ sections by heading), and
  the old lint's BLOCK and WARN findings become `fired` events (`capture.lint_events`, event `backfill`, actor `lint`);
- a published article adds a `survived_publish` event (event `backfill`, actor `publish`) for every WARN span. BLOCK
  spans are fired only: a BLOCK never counts as kept. The schema allows a `reason` only on override, diff and
  decision events, so these carry none;
- its judge files (J1–J4: `{"group", "article_sha256", "verdicts": [{"rule", "verdict", "severity", "evidence"}]}`),
  justify file (`{"article_sha256", "items": [{"rule", "kind", "reason"}]}`) and JR file (`{"group": "JR",
  "article_sha256", "justify_sha256", "verdicts": [{"rule", "verdict": "accept" | "reject"}]}`) become the events
  `merge` records (`capture.merge_events`: each judge's own verdict, `agree` on lint+judge rules, and each
  JR-reviewed justification), as event `backfill`. Each file must be for the text's version (and the JR file for
  that justify file). Evidence quotes and reasons are never kept: a span is hashed.
Then each override becomes an `override` event (actor `human`) on the matching finding's span, with facet `kind`.

`--profile-map GLOB=PROFILE` (repeatable, first match wins) parses each article whose `text` path (as the manifest
writes it) matches GLOB with PROFILE (a profile name or file) instead of the default profile, so per-domain profiles
can be backfilled. With a map, an article's doc id is `label_id("<profile name>:article-<n>")` and its events carry
that profile name, so the ledgers of several manifests never share a doc id; an article no glob matches keeps the
default profile and is labelled with the manifest's `profile`.

Excerpts are always dropped, so the output holds hashes, ruleset words, section kinds and metric names only.
`--blank-doc-sha` drops the one hash of the host's text too (`doc_sha` null). Every `ts` must be the ledger's UTC
form. It writes nothing but `--out`, and prints counts of the events it wrote. Exit 0 ok, 2 bad input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from plainspoken import capture, config, judges, justify, ledger  # noqa: E402
from plainspoken.doc import parse  # noqa: E402
from plainspoken.profile import default as default_profile  # noqa: E402
from plainspoken.registry import load_config  # noqa: E402

FAMILIES = ("lint", "publish", "override")
_VERDICT_FILES = ("judges", "justify", "jr")


class BadManifest(ValueError):
    """The manifest, a lint report or an override can't be used."""


def doc_label(n: int, prefix: str | None = None) -> str:
    return ledger.label_id(f"article-{n}" if prefix is None else f"{prefix}:article-{n}")


def parse_map(pairs: list[str] | None, cfg) -> list[tuple[str, object]]:
    """`GLOB=PROFILE` pairs as (glob, loaded profile), checked against the ruleset."""
    out = []
    for pair in pairs or ():
        glob, sep, value = str(pair).partition("=")
        if not sep or not glob.strip() or not value.strip():
            raise BadManifest(f"--profile-map {pair!r}: need GLOB=PROFILE")
        try:
            prof = config.resolve_profile(value.strip(), Path.cwd(), {})
            cfg.check_profile(prof)
        except (ValueError, OSError) as e:
            raise BadManifest(f"--profile-map {pair!r}: {str(e).splitlines()[0] if str(e) else e}") from None
        out.append((glob.strip(), prof))
    return out


def _json(base: Path, rel: object, what: str) -> dict:
    try:
        data = json.loads(_read(base, rel, what).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BadManifest(f"{what}: not JSON") from None
    if not isinstance(data, dict):
        raise BadManifest(f"{what}: not a JSON object")
    return data


def _same_text(data: dict, sha: object, what: str) -> None:
    if data.get("article_sha256") != sha:
        raise BadManifest(f"{what}: made for another version of the article (article_sha256 differs)")


def _verdicts(a: dict, n: int, base: Path, lint: dict) -> dict | None:
    """A merged-report-like `{"rules", "justified"}` from the article's judge, justify and JR files (None when it
    names none), for `capture.merge_events`. Fails closed on a file for another version of the text."""
    if not any(k in a for k in _VERDICT_FILES):
        return None
    sha = lint.get("article_sha256")
    rules: dict = {}
    judge_files = a.get("judges", [])
    if not isinstance(judge_files, list):
        raise BadManifest(f"articles[{n}].judges: need a list of paths")
    for i, rel in enumerate(judge_files):
        what = f"articles[{n}].judges[{i}]"
        data = _json(base, rel, what)
        group = data.get("group")
        if group not in judges.GROUPS:
            raise BadManifest(f"{what}: group must be one of {', '.join(judges.GROUPS)}")
        _same_text(data, sha, what)
        for v in data.get("verdicts") or ():
            if not (isinstance(v, dict) and isinstance(v.get("rule"), str) and v["rule"]
                    and v.get("verdict") in ("pass", "fail") and v.get("severity") in ledger.SEVERITIES):
                raise BadManifest(f"{what}: each verdict needs a rule, a verdict (pass or fail) and a severity")
            rules[v["rule"]] = {"source": f"judge:{group}", "verdict": v["verdict"], "severity": v["severity"],
                                "evidence": v.get("evidence") if isinstance(v.get("evidence"), list) else [],
                                "findings": [f for f in lint["findings"]
                                             if isinstance(f, dict) and f.get("rule") == v["rule"]]}
    justified = []
    if "justify" in a or "jr" in a:
        if not ("justify" in a and "jr" in a):
            raise BadManifest(f"articles[{n}]: justify and jr go together (a justification counts once reviewed)")
        raw = _read(base, a["justify"], f"articles[{n}].justify")
        just = _json(base, a["justify"], f"articles[{n}].justify")
        _same_text(just, sha, f"articles[{n}].justify")
        jr = _json(base, a["jr"], f"articles[{n}].jr")
        _same_text(jr, sha, f"articles[{n}].jr")
        if jr.get("group") != "JR" or jr.get("justify_sha256") != hashlib.sha256(raw).hexdigest():
            raise BadManifest(f"articles[{n}].jr: not the JR review of that justify file")
        reviews = {}
        for v in jr.get("verdicts") or ():
            if not (isinstance(v, dict) and isinstance(v.get("rule"), str) and v.get("verdict") in ("accept",
                                                                                                  "reject")):
                raise BadManifest(f"articles[{n}].jr: each verdict needs a rule and accept or reject")
            reviews[v["rule"]] = v["verdict"]
        for item in just.get("items") or ():
            if not (isinstance(item, dict) and isinstance(item.get("rule"), str) and item.get("kind") in justify.KINDS):
                raise BadManifest(f"articles[{n}].justify: each item needs a rule and a kind")
            if item["rule"] in reviews:
                justified.append({"rule": item["rule"], "kind": item["kind"], "review": reviews[item["rule"]]})
    return {"rules": rules, "justified": justified}


def _as_backfill(events: list[dict]) -> list[dict]:
    """`merge_events` output relabelled as event `backfill` (the actor stays: judge:Jn, human or jr)."""
    keep = ("ruleset_version", "profile", "actor", "outcome", "rule", "severity", "doc_id", "doc_sha", "span_hash",
            "facets")
    return [ledger.make_event(event="backfill", **{k: e[k] for k in keep}) for e in events]


def _ts(manifest: dict, family: str) -> str:
    ts = manifest.get("ts")
    value = ts.get(family) if isinstance(ts, dict) else ts
    if not isinstance(value, str) or not ledger.valid_ts(value):
        raise BadManifest(f"ts: need the ledger's UTC form (YYYY-MM-DDTHH:MM:SS+00:00) for {family} events, "
                          f"got {value!r}")
    return value


def _read(base: Path, rel: object, what: str) -> bytes:
    if not isinstance(rel, str) or not rel:
        raise BadManifest(f"{what}: need a path")
    path = Path(rel) if Path(rel).is_absolute() else base / rel
    try:
        return path.read_bytes()
    except OSError as e:
        raise BadManifest(f"{what}: can't read {path} ({e.strerror or e})") from None


def _with_ts(events: list[dict], ts: str) -> list[dict]:
    """The events with `ts` set (the id doesn't cover `ts`) and `excerpt` dropped."""
    out = []
    for e in events:
        e = {k: v for k, v in e.items() if k != "excerpt"}
        e["ts"] = ts
        errors = ledger.validate(e)
        if errors:
            raise BadManifest("bad event: " + "; ".join(errors))
        out.append(e)
    return out


def _override(o: object, n_articles: int, lints: list[dict], docs: list, cfg, manifest: dict,
              labels: list[str]) -> dict:
    if not isinstance(o, dict):
        raise BadManifest("overrides: each entry must be an object")
    n, rule = o.get("article"), o.get("rule")
    if not (isinstance(n, int) and not isinstance(n, bool) and 0 <= n < n_articles):
        raise BadManifest(f"override: article must be an index from 0 to {n_articles - 1}")
    if o.get("outcome") not in ("dismissed", "upheld"):
        raise BadManifest("override: outcome must be dismissed or upheld")
    kind, reason = o.get("kind"), o.get("reason")
    if (o["outcome"] == "dismissed") != isinstance(kind, str):
        raise BadManifest("override: a dismissal needs a kind, an uphold takes none")
    if not isinstance(reason, str) or not reason.strip():
        raise BadManifest("override: need a reason")
    lint, doc = lints[n], docs[n]
    hits = []
    for f in lint["findings"]:
        if not (capture.well_formed(f) and f["rule"] == rule and f["severity"] in capture.CAPTURED):
            continue
        facets = capture.facets(f, doc, cfg)
        if "metric" in o and facets.get("metric") != o["metric"]:
            continue
        hits.append((f, facets))
    if len(hits) != 1:
        raise BadManifest(f"override on article {n}, rule {rule!r}: matches {len(hits)} findings, need exactly 1")
    f, facets = hits[0]
    return ledger.make_event(event="override", actor="human", outcome=o["outcome"], rule=str(rule),
                             severity=f["severity"], ruleset_version=str(manifest["ruleset_version"]),
                             profile=str(lint["profile"]), doc_id=labels[n], doc_sha=capture.doc_sha(lint),
                             span_hash=capture.span(f, facets),
                             facets={**facets, **({"kind": kind} if kind is not None else {})},
                             reason=" ".join(reason.split()), ts=_ts(manifest, "override"))


def build(manifest: dict, base: Path, cfg=None, profile_map: list[tuple[str, object]] | None = None,
          blank_doc_sha: bool = False) -> tuple[list[dict], dict]:
    """(the events, counts) for a parsed manifest whose relative paths are under `base`. `profile_map` is
    `parse_map`'s (glob, profile) list. `blank_doc_sha` writes every `doc_sha` as null."""
    cfg = load_config() if cfg is None else cfg
    for key in ("ruleset_version", "profile"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise BadManifest(f"{key}: need a string")
    articles = manifest.get("articles")
    if not isinstance(articles, list) or not articles:
        raise BadManifest("articles: need a non-empty list")
    events: list[dict] = []
    lints, docs, labels = [], [], []
    counts = {"articles": len(articles), "published": 0, "fired": 0, "survived_publish": 0, "judge": 0,
              "justify": 0, "override": 0}
    for n, a in enumerate(articles):
        if not isinstance(a, dict) or not isinstance(a.get("published"), bool):
            raise BadManifest(f"articles[{n}]: need lint, text and published (true or false)")
        try:
            lint = json.loads(_read(base, a.get("lint"), f"articles[{n}].lint").decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise BadManifest(f"articles[{n}].lint: not a JSON lint report") from None
        if not isinstance(lint, dict) or not isinstance(lint.get("findings"), list):
            raise BadManifest(f"articles[{n}].lint: not a lint report (no findings list)")
        profile, name, label = default_profile(), manifest["profile"], doc_label(n)
        if profile_map:
            hit = next((prof for glob, prof in profile_map if config.glob_match(str(a.get("text")), glob)), None)
            if hit is not None:
                profile, name = hit, hit.name
            label = doc_label(n, name)
        lint = {**lint, "ruleset_version": manifest["ruleset_version"], "profile": name, "article": f"article-{n}"}
        try:
            text = _read(base, a.get("text"), f"articles[{n}].text").decode("utf-8")
        except UnicodeDecodeError:
            raise BadManifest(f"articles[{n}].text: not UTF-8") from None
        doc = parse(text, profile=profile, content_type="article")
        lints.append(lint)
        docs.append(doc)
        labels.append(label)
        fired = capture.lint_events(lint, doc, cfg, base, actor="lint", event="backfill", doc_id=label)
        events += _with_ts(fired, _ts(manifest, "lint"))
        if a["published"]:
            counts["published"] += 1
            kept = ledger.distinct(
                capture.finding_event(f, lint, doc, cfg, label, event="backfill", actor="publish",
                               outcome="survived_publish", severity="WARN")
                for f in lint["findings"] if capture.well_formed(f) and f["severity"] == "WARN")
            events += _with_ts(kept, _ts(manifest, "publish"))
        verdicts = _verdicts(a, n, base, lint)
        if verdicts is not None:
            merged = {**verdicts, "article": f"article-{n}", "article_sha256": lint.get("article_sha256"),
                      **{k: lint.get(k) for k in ("profile", "profile_sha256", "ruleset_version")}}
            made = _with_ts(_as_backfill(capture.merge_events(merged, doc, cfg, base, doc_id=label)),
                            _ts(manifest, "lint"))
            events += made
    overrides = manifest.get("overrides", [])
    if not isinstance(overrides, list):
        raise BadManifest("overrides: need a list")
    for o in overrides:
        events.append(_override(o, len(articles), lints, docs, cfg, manifest, labels))
    events = ledger.distinct(events)
    if blank_doc_sha:
        events = ledger.distinct(_blanked(e) for e in events)
    # counted from the events written: a repeated override or finding is one event, so it counts once
    counts.update(fired=sum(1 for e in events if e["event"] == "backfill" and e["outcome"] == "fired"
                            and e["actor"] == "lint"),
                  survived_publish=sum(1 for e in events if e["outcome"] == "survived_publish"),
                  judge=sum(1 for e in events if e["event"] == "backfill" and e["actor"].startswith("judge:")),
                  justify=sum(1 for e in events if e["event"] == "backfill" and e["actor"] in ("human", "jr")),
                  override=sum(1 for e in events if e["event"] == "override"))
    return events, counts


def _blanked(e: dict) -> dict:
    """`e` with no `doc_sha` (a hash of the host's text) and its id recomputed."""
    out = {**e, "doc_sha": None}
    out["id"] = ledger.event_id(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backfill a kaizen ledger from a host engine's history.")
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--profile-map", action="append", metavar="GLOB=PROFILE",
                    help="parse articles whose text path matches GLOB with PROFILE; doc ids are prefixed by its name")
    ap.add_argument("--blank-doc-sha", action="store_true",
                    help="write every doc_sha (a hash of the host's article text) as null")
    args = ap.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise BadManifest("the manifest must be a JSON object")
        cfg = load_config()
        events, counts = build(manifest, args.manifest.resolve().parent, cfg, parse_map(args.profile_map, cfg),
                               args.blank_doc_sha)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"backfill_history: can't read the manifest ({e})", file=sys.stderr)
        return 2
    except (BadManifest, ledger.LedgerError) as e:
        print(f"backfill_history: {e}", file=sys.stderr)
        return 2
    lines = "".join(json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for e in events)
    try:
        args.out.write_text(lines, encoding="utf-8")
    except OSError as e:
        print(f"backfill_history: can't write {args.out} ({e.strerror or e})", file=sys.stderr)
        return 2
    print(f"backfill_history: {counts['articles']} articles ({counts['published']} published): "
          f"{counts['fired']} fired, {counts['survived_publish']} survived_publish, {counts['judge']} judge, "
          f"{counts['justify']} justify, {counts['override']} override; {len(events)} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
