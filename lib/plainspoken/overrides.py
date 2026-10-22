"""Overrides (Phase 5): what people say about the engine's findings, what it missed, and what reached publication.

- `override`: a person dismisses or upholds a rule's findings in the current check (event `override`, actor
  `human`, with their `reason`). A dismissal carries facet `kind` (OVERRIDE_KINDS); an upheld finding carries no
  `kind`, since upholding needs no category. The spans are hashed exactly as capture hashed the same findings
  (`capture.span` for lint findings, `ledger.span_hash(rule, quote)` for a judge's evidence), so metrics join a
  dismissal to its fire.
- `hunks`: the sentence-level difference between the check snapshot (`<key>.checked.md`) and the current file. A
  snapshot is ignored while check capture is off, or when it's older than the last check made with capture off
  (`capture.capture_off_since`).
- `missed`: a person names a tell the engine missed in one hunk (event `diff`, actor `human`, outcome `missed`). The
  schema needs a rule on `diff` events, so a `--pattern` tell is logged with rule `?` and facet `pattern`.
- `published`: re-lints the current file and logs `survived_publish` (event `publish`, actor `publish`) for each
  BLOCK or WARN span present both in the check's saved lint and now, each judge-only WARN whose quoted span the file
  still holds, plus each justified rule in the current report. A span the person removed after the check isn't
  logged (it shows up as a hunk instead).

Refusals (no current check, no finding, no snapshot, a bad hunk number, capture off) are ValueErrors; bad usage (an
unknown rule, kind or pattern, an empty reason) is a UsageError. A ledger that can't be written safely raises
`ledger.LedgerError`. Nothing from the article reaches the ledger but hashes, and the finding's excerpt (or the hunk's
old text) only when excerpts are on; judge evidence is never stored.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from plainspoken import capture, config, justify, ledger, report
from plainspoken.doc import Doc, parse, split_sentences
from plainspoken.registry import load_config

OVERRIDE_KINDS = ("false_positive", "voice", "unfixable", "quote", "format", "other")
OUTCOMES = ("dismissed", "upheld")
JUDGED = ("judge", "lint+judge")
PATTERN = re.compile(r"[a-z0-9-]{1,40}")
PATTERN_RULE = "?"  # the rule of a `missed` event named by pattern (the schema needs a rule on `diff` events)
_BLOCK_LINE = re.compile(r"^\s*(#|```|~~~|\|)")  # a line that is a unit of its own (heading, fence, table row)
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")  # a code fence; the lines between two are code
_ITEM_LINE = re.compile(r"^\s*([-*+]\s|\d+[.)]\s|>)")  # a line that starts a new paragraph (list item, quote)


class UsageError(ValueError):
    """Bad usage: an unknown rule, kind or pattern, an empty reason, both or neither of rule and pattern."""


# --- shared -------------------------------------------------------------------------------------------------------

def _reports(root: Path, reports_dir: Path | None) -> Path:
    return Path(reports_dir) if reports_dir is not None else report.reports_dir_default(Path(root))


def _settings(root: Path) -> dict:
    """The kaizen settings; a ValueError when capture is off (there's nowhere to record anything)."""
    settings = config.kaizen_settings(Path(root), os.environ)
    if not settings.get("capture", True):
        raise ValueError("kaizen capture is off ([kaizen] capture = false), so nothing was recorded")
    return settings


def _reason(reason: str | None, required: bool) -> str | None:
    """One line, whitespace collapsed (make_event cuts it to 200 characters)."""
    if reason is None and not required:
        return None
    text = " ".join(str(reason or "").split())
    if not text:
        raise UsageError("--reason must say why, in a few words")
    return text


def _append(events: list[dict], settings: dict) -> list[dict]:
    """Append the events (each already valid: `make_event` checked it) in order."""
    for e in events:
        ledger.append(e, settings)
    return events


def _parse(data: bytes, article: Path, profile, content_type: str) -> Doc | None:
    """The parsed text, or None (only the `section` facet is lost)."""
    if profile is None:
        return None
    try:
        return parse(data.decode("utf-8"), path=str(article), profile=profile, content_type=content_type)
    except Exception:  # deliberate: an unparseable text only costs the section facet
        return None


def _ctype(lint: dict) -> str:
    ctype = lint.get("content_type", "article")
    return ctype if isinstance(ctype, str) else "article"


# --- dismiss / uphold ---------------------------------------------------------------------------------------------

def _current(path: Path, sha: str, what: str, article: Path) -> dict:
    data = justify.read_json(path)
    if data is None or data.get("article_sha256") != sha:
        raise ValueError(f"no current {what} for {Path(article).name}: run check first")
    return data


def _override_events(data: bytes, lint: dict, article: Path, root: Path, rule: str, outcome: str, extra: dict,
                     reason: str, line: int | None, paths: dict, profile: str | None, cfg) -> list[dict]:
    """The override events for rule `rule` in one check: `data` is the text it checked, `lint` its lint."""
    sha = hashlib.sha256(data).hexdigest()
    findings = [f for f in lint.get("findings") or () if capture.well_formed(f)]
    doc = _parse(data, article, config.profile_for_lint(lint, root, profile), _ctype(lint))
    base = {"ruleset_version": str(lint["ruleset_version"]), "profile": str(lint["profile"]),
            "doc_id": ledger.doc_id(article, root), "doc_sha": sha}
    events = []
    hits = [f for f in findings if f["rule"] == rule and f["severity"] in capture.CAPTURED
            and (line is None or f["line"] == line)]
    for f in hits:
        facets = capture.facets(f, doc, cfg)
        events.append(ledger.make_event(event="override", actor="human", outcome=outcome, rule=rule,
                                        severity=f["severity"], span_hash=capture.span(f, facets),
                                        facets={**facets, **extra}, reason=reason,
                                        excerpt=str(f.get("excerpt", "")) or None, **base))
    if not hits and rule in cfg.rules and cfg.rules[rule].method in JUDGED:
        merged = justify.read_json(paths["report"])
        if merged is not None and merged.get("article_sha256") == sha:
            rules = merged.get("rules") if isinstance(merged.get("rules"), dict) else {}
            for span, severity, facets in _judge_spans(rule, rules.get(rule), line, doc):
                events.append(ledger.make_event(event="override", actor="human", outcome=outcome, rule=rule,
                                                severity=severity, span_hash=span, facets={**facets, **extra},
                                                reason=reason, **base))
    return ledger.distinct(events)


def _earlier_finding(article: Path, root: Path, reports_dir: Path | None, paths: dict, rule: str) -> bool:
    """The previous check (the pair `check` keeps) has a BLOCK or WARN finding for `rule`; only picks a hint."""
    try:
        pairs = _snapshot_pairs(article, root, reports_dir, paths)
    except (ValueError, OSError):
        return False
    return any(isinstance(f, dict) and f.get("rule") == rule and f.get("severity") in capture.CAPTURED
               for _, lint in pairs[1:] for f in lint.get("findings") or ())


def _snapshot_pairs(article: Path, root: Path, reports_dir: Path | None, paths: dict) -> list[tuple[bytes, dict]]:
    """For `--from-snapshot`: the last check's (snapshot bytes, lint), then the check before it (the previous
    pair `check` keeps, `capture.previous_pair`), each only when its lint belongs to its snapshot. The check skill
    re-checks right after its fix pass, so a finding the fix pass removed is in the previous pair. The previous pair
    follows the same ignore rules as the snapshot (capture off, older than the capture-off stamp)."""
    data, snap = _snapshot(article, root, reports_dir)
    pairs, error = [], None
    try:
        pairs.append((data, _saved_lint(data, paths, article)))
    except ValueError as e:
        error = e
    prev_snap, prev_lint = capture.previous_pair(snap)
    try:
        prev = _snapshot(article, root, reports_dir, path=prev_snap)[0]
        lint = justify.read_json(prev_lint)
        if (isinstance(lint, dict) and isinstance(lint.get("findings"), list)
                and lint.get("article_sha256") == hashlib.sha256(prev).hexdigest()):
            pairs.append((prev, lint))
    except ValueError:
        pass  # no previous check (or one that's ignored): only the last one counts
    if not pairs:
        raise error
    return pairs


def _current_or_hint(paths: dict, sha: str, article: Path, root: Path, reports_dir: Path | None) -> dict:
    """The current lint; when there's none but the saved lint still matches the check snapshot (the file was edited
    after the check, as a fix pass does), the refusal names `--from-snapshot`."""
    try:
        return _current(paths["lint"], sha, "check", article)
    except ValueError as e:
        try:
            _saved_lint(_snapshot(article, root, reports_dir)[0], paths, article)
        except (ValueError, OSError):
            raise e from None
        raise ValueError(f"{e}, or pass --from-snapshot to use the last check's findings (the file changed "
                         "since)") from None


def _judge_spans(rid: str, entry: object, line: int | None, doc: Doc | None) -> list[tuple[str, str, dict]]:
    """The one (span hash, severity, facets) of a judge's `fail` for `rid`, exactly as `capture.merge_events` logs
    its fire: rule + the first evidence quote (`capture.first_quote`), else rule + `*`, with `section` from that
    quote's line. With `line`, the entry counts only when one of its evidence items is on that line (the person
    points at the finding); it still logs the entry's single span. Quotes are never kept."""
    if not isinstance(entry, dict) or not capture.JUDGE_SOURCE.fullmatch(str(entry.get("source", ""))):
        return []
    if entry.get("judge_verdict", entry.get("verdict")) != "fail" or entry.get("severity") not in ledger.SEVERITIES:
        return []
    evidence = entry.get("evidence") if isinstance(entry.get("evidence"), list) else []
    if line is not None and not any(isinstance(item, dict) and item.get("line") == line
                                    and not isinstance(item.get("line"), bool) for item in evidence):
        return []
    quote, quote_line = capture.first_quote(evidence)
    section = capture.section_of(quote_line, doc)
    return [(ledger.span_hash(rid, capture.NO_SPAN if quote is None else quote), entry["severity"],
             {} if section is None else {"section": section})]


def override(article: Path, root: Path, rule: str, outcome: str, kind: str | None, reason: str,
             line: int | None = None, *, reports_dir: Path | None = None, profile: str | None = None,
             from_snapshot: bool = False) -> list[dict]:
    """Record a person dismissing (`kind` from OVERRIDE_KINDS) or upholding (no `kind`) rule `rule`'s findings in the
    current check: one `override` event per span (only the finding on `line` when given). The spans are the rule's
    BLOCK or WARN findings in the current lint (`<key>.lint.json` whose `article_sha256` matches the file), else, for
    a judged rule, the current report's evidence for it. With `from_snapshot`, the text is the last check's
    snapshot (`<key>.checked.md`, with the lint saved with it) instead of the file, then the check before it (the
    previous pair), so a finding a fix pass removed can still be dismissed after the re-check. The first of those
    checks that has a finding for the rule is used. Returns the events appended."""
    if outcome not in OUTCOMES:
        raise UsageError(f"outcome must be one of {', '.join(OUTCOMES)}")
    if outcome == "dismissed" and kind not in OVERRIDE_KINDS:
        raise UsageError(f"--kind must be one of {', '.join(OVERRIDE_KINDS)}")
    if outcome == "upheld" and kind is not None:
        raise UsageError("uphold takes no --kind")
    reason = _reason(reason, required=True)
    article, root = Path(article), Path(root)
    cfg = load_config()
    paths = report.report_paths(article, _reports(root, reports_dir), root)
    if from_snapshot:
        pairs = _snapshot_pairs(article, root, reports_dir, paths)
    else:
        data = article.read_bytes()
        pairs = [(data, _current_or_hint(paths, hashlib.sha256(data).hexdigest(), article, root, reports_dir))]
    known = {f["rule"] for _, lint in pairs for f in lint.get("findings") or () if capture.well_formed(f)}
    if rule not in cfg.rules and rule not in known:
        raise UsageError(f"unknown rule {rule!r}")
    settings = _settings(root)
    extra = {"kind": kind} if kind is not None else {}
    events: list[dict] = []
    for data, lint in pairs:  # the first check (current, else the one before it) with a finding for the rule
        events = _override_events(data, lint, article, root, rule, outcome, extra, reason, line, paths, profile, cfg)
        if events:
            break
    if not events:
        where = f" on line {line}" if line is not None else ""
        which = ("the last check or the one before it" if len(pairs) > 1 else
                 "the last check" if from_snapshot else "the current check")
        hint = "" if from_snapshot or not _earlier_finding(article, root, reports_dir, paths, rule) else \
            ": the check before it has one (a fix pass removed it?), so pass --from-snapshot to dismiss that"
        raise ValueError(f"rule {rule} has no finding{where} in {which}{hint}")
    return _append(events, settings)


# --- diff / missed ------------------------------------------------------------------------------------------------

def _snapshot(article: Path, root: Path, reports_dir: Path | None, *, path: Path | None = None) -> tuple[bytes, Path]:
    """The check snapshot's bytes and path (`path`: another snapshot of the article, the previous one). A snapshot is
    ignored (a ValueError that says so) while check capture is off, and when it's older than the last time
    `check` ran with capture off: edits made then were never recorded, so hunks against it would be wrong."""
    snap = path or report.report_paths(Path(article), _reports(root, reports_dir), Path(root))["checked"]
    name = Path(article).name
    settings = _settings_or_none(root)
    on = settings is None or capture.source_on(settings, "check")
    try:
        if snap.is_symlink():
            raise OSError("symlinked")
        data, mtime = snap.read_bytes(), snap.stat().st_mtime
    except OSError:
        if not on:
            raise ValueError(f"no check snapshot for {name}: check saves one only when kaizen capture is on, and "
                             "it's off here ([kaizen] capture = false, or check left out of capture_sources)") \
                from None
        raise ValueError(f"no check snapshot for {name}: run check first") from None
    if not on:
        raise ValueError(f"the check snapshot for {name} is ignored: kaizen capture is off for check ([kaizen] "
                         "capture = false, or check left out of capture_sources), so edits since it may be "
                         "unrecorded; turn capture on and run check")
    since = capture.capture_off_since(settings)
    if since is not None and datetime.fromtimestamp(mtime, timezone.utc) < since:
        raise ValueError(f"the check snapshot for {name} is older than the last time kaizen capture was off "
                         f"({since:%Y-%m-%d %H:%M} UTC), so it's ignored: run check again")
    return data, snap


def _settings_or_none(root: Path) -> dict | None:
    """The kaizen settings, or None when they can't be built (the plain refusal message is the right one then)."""
    try:
        return config.kaizen_settings(Path(root), os.environ)
    except Exception:  # deliberate: this only picks a refusal message
        return None


def _units(text: str) -> list[tuple[str, int, int]]:
    """(sentence, first line, last line) for each sentence of `text`. A paragraph's lines are joined before it's
    split, so a sentence wrapped over two lines is one unit. Frontmatter lines, headings, table rows and every line
    of a fenced code block (fences included) are units of their own; a list item or quote line starts a new
    paragraph. A sentence the splitter returns reshaped (not found in its paragraph) spans the rest of the
    paragraph, so its lines are never placed short of where it sits."""
    lines = text.splitlines()
    fm_end = capture.frontmatter_end(lines)
    units: list[tuple[str, int, int]] = []
    para: list[tuple[int, str]] = []

    def flush() -> None:
        if not para:
            return
        joined, starts = "", []
        for ln, t in para:
            if joined:
                joined += " "
            starts.append((len(joined), ln))
            joined += t.strip()

        def line_at(offset: int) -> int:
            return [ln for start, ln in starts if start <= offset][-1]
        pos = 0
        for s in split_sentences(joined):
            i = joined.find(s, pos)
            if i < 0:  # the splitter reshaped it: cover the rest of the paragraph rather than guess a line
                units.append((s, line_at(pos), para[-1][0]))
                continue
            end = i + len(s)
            units.append((s, line_at(i), line_at(max(i, end - 1))))
            pos = end
        para.clear()

    fence: str | None = None  # the opening fence (``` or ~~~) while inside a fenced code block
    for n, raw in enumerate(lines, start=1):
        m = _FENCE.match(raw)
        if fence is not None or m:
            flush()  # a fenced line is code, never prose to join and split: each is a unit of its own
            if raw.strip():
                units.append((raw.strip(), n, n))
            if m and (fence is None or m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)):
                fence = m.group(1) if fence is None else None
        elif n <= fm_end or _BLOCK_LINE.match(raw):
            flush()
            if raw.strip():
                units.append((raw.strip(), n, n))
        elif not raw.strip():
            flush()
        else:
            if _ITEM_LINE.match(raw):
                flush()
            para.append((n, raw))
    flush()
    return units


def _hunks(old_text: str, new_text: str) -> list[dict]:
    old, new = _units(old_text), _units(new_text)
    sm = difflib.SequenceMatcher(None, [u[0] for u in old], [u[0] for u in new], autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            span = [old[i1][1], old[i2 - 1][2]]
        else:  # an insertion: the line of the old sentence it goes before (the last line at the end)
            at = old[i1][1] if i1 < len(old) else (old[-1][2] if old else 0)
            span = [at, at]
        out.append({"n": len(out) + 1, "old": " ".join(u[0] for u in old[i1:i2]),
                    "new": " ".join(u[0] for u in new[j1:j2]), "old_lines": span})
    return out


def hunks(article: Path, root: Path, *, reports_dir: Path | None = None) -> list[dict]:
    """The sentence-level difference between the check snapshot and the current file: `{"n", "old", "new",
    "old_lines": [a, b]}` per hunk, numbered from 1 (`difflib.SequenceMatcher` over sentences). `old_lines` are the
    snapshot's lines; an insertion has empty `old` and the line it goes before."""
    snap, _ = _snapshot(article, root, reports_dir)
    return _hunks(snap.decode("utf-8"), Path(article).read_text(encoding="utf-8"))


def _saved_lint(snap: bytes, paths: dict, article: Path) -> dict:
    """The lint `check` saved with the snapshot (its `article_sha256` is the snapshot's)."""
    lint = justify.read_json(paths["lint"])
    if (lint is None or lint.get("article_sha256") != hashlib.sha256(snap).hexdigest()
            or not isinstance(lint.get("findings"), list)):
        raise ValueError(f"the saved lint for {Path(article).name} doesn't match its check snapshot: run check again")
    return lint


def missed(article: Path, root: Path, n: int, rule: str | None = None, pattern: str | None = None,
           reason: str | None = None, *, reports_dir: Path | None = None) -> dict:
    """Record a tell the engine missed in hunk `n`: one `missed` event (event `diff`, actor `human`, severity null)
    with exactly one of `rule` (a ruleset id) or `pattern` (`[a-z0-9-]{1,40}`; logged as rule `?` + facet
    `pattern`). The span hash is `pattern or rule` + the hunk's old text; `doc_sha` is the snapshot's (the text the
    engine checked). Returns the event appended."""
    if (rule is None) == (pattern is None):
        raise UsageError("name exactly one of --rule and --pattern")
    cfg = load_config()
    if rule is not None and rule not in cfg.rules:
        raise UsageError(f"unknown rule {rule!r}")
    if pattern is not None and not PATTERN.fullmatch(pattern):
        raise UsageError("--pattern must be 1 to 40 of a-z, 0-9 and -")
    reason = _reason(reason, required=False)
    article, root = Path(article), Path(root)
    snap, _ = _snapshot(article, root, reports_dir)
    paths = report.report_paths(article, _reports(root, reports_dir), root)
    lint = _saved_lint(snap, paths, article)
    all_hunks = _hunks(snap.decode("utf-8"), article.read_text(encoding="utf-8"))
    if not 1 <= n <= len(all_hunks):
        have = f"hunks 1 to {len(all_hunks)}" if all_hunks else "no hunks (no changes since the last check)"
        raise ValueError(f"no hunk {n}: there are {have}")
    hunk = all_hunks[n - 1]
    if not hunk["old"]:
        raise ValueError(f"hunk {n} only adds text, so there's nothing the check could have missed")
    settings = _settings(root)
    facets: dict = {} if pattern is None else {"pattern": pattern}
    section = capture.section_of(hunk["old_lines"][0],
                                 _parse(snap, article, config.profile_for_lint(lint, root), _ctype(lint)))
    if section is not None:
        facets["section"] = section
    event = ledger.make_event(event="diff", actor="human", outcome="missed", rule=rule or PATTERN_RULE,
                              severity=None, ruleset_version=str(lint["ruleset_version"]),
                              profile=str(lint["profile"]), doc_id=ledger.doc_id(article, root),
                              doc_sha=hashlib.sha256(snap).hexdigest(),
                              span_hash=ledger.span_hash(pattern or rule, hunk["old"]), facets=facets, reason=reason,
                              excerpt=hunk["old"])
    return _append([event], settings)[0]


# --- published ----------------------------------------------------------------------------------------------------

def _judge_kept(merged: object, cfg, current: dict, saved: dict, *, data: bytes, snap_doc: Doc | None, did: str,
                article: Path, prof) -> list[dict]:
    """A judge-only WARN has no lint span, so it's kept when the published text still holds the span the judge
    quoted. For each rule whose method is `judge` that a judge failed at WARN in the report of the checked or the
    published text, `survived_publish` on the judge fire's own span (rule + the first evidence quote, as
    `capture.merge_events` hashes it) when that quote, normalised, is still in the published file. A verdict with no
    quote has no span to look for, so it counts nothing."""
    if not isinstance(merged, dict) or merged.get("article_sha256") not in (current["article_sha256"],
                                                                           saved.get("article_sha256")):
        return []
    doc = (snap_doc if merged.get("article_sha256") == saved.get("article_sha256")
           else _parse(data, article, prof, _ctype(current)))
    try:
        published_text = ledger.normalise(data.decode("utf-8"))
    except UnicodeDecodeError:
        return []
    rules = merged.get("rules") if isinstance(merged.get("rules"), dict) else {}
    out = []
    for rid, entry in rules.items():
        rule = cfg.rules.get(rid)
        if rule is None or rule.method != "judge" or not isinstance(entry, dict):
            continue
        if not capture.JUDGE_SOURCE.fullmatch(str(entry.get("source", ""))) or entry.get("severity") != "WARN":
            continue
        if entry.get("judge_verdict", entry.get("verdict")) != "fail":
            continue
        quote, line = capture.first_quote(entry.get("evidence"))
        if quote is None or ledger.normalise(quote) not in published_text:
            continue
        section = capture.section_of(line, doc)
        out.append(ledger.make_event(
            event="publish", actor="publish", outcome="survived_publish", rule=rid, severity="WARN",
            ruleset_version=str(current["ruleset_version"]), profile=str(current["profile"]), doc_id=did,
            doc_sha=current["article_sha256"], span_hash=ledger.span_hash(rid, quote),
            facets={} if section is None else {"section": section}))
    return out


def published(article: Path, root: Path, *, reports_dir: Path | None = None,
              profile: str | None = None) -> list[dict]:
    """Lint the current file and record `survived_publish` (event `publish`, actor `publish`) for each BLOCK or WARN
    span in the check's saved lint that the current lint still has (matched as `capture.fixed_events` matches, so a
    span is either fixed or survived), each judge-only WARN whose judged span the published file still holds
    (`_judge_kept`), plus each justified rule in the current report (rule + `*`, WARN, facet `kind`). It needs the
    check snapshot, the same ruleset and the check's profile. Returns the events appended."""
    article, root = Path(article), Path(root)
    snap, _ = _snapshot(article, root, reports_dir)
    paths = report.report_paths(article, _reports(root, reports_dir), root)
    saved = _saved_lint(snap, paths, article)
    cfg = load_config()
    if saved.get("ruleset_version") != cfg.version:
        raise ValueError(f"the ruleset changed since the check ({saved.get('ruleset_version')} → {cfg.version}): "
                         "run check again")
    prof = config.profile_for_lint(saved, root, profile)
    if prof is None:
        raise ValueError(f"can't find the profile the check used ({saved.get('profile')}): pass it with --profile")
    settings = _settings(root)
    current = report.run_lint(article, prof, _ctype(saved), cfg)
    snap_doc = _parse(snap, article, prof, _ctype(saved))
    now = {capture.match_key(f, cfg) for f in current["findings"] if capture.well_formed(f)}
    did = ledger.doc_id(article, root)
    events = [capture.finding_event(f, current, snap_doc, cfg, did, event="publish", actor="publish",
                             outcome="survived_publish", severity=f["severity"])
              for f in saved["findings"]
              if capture.well_formed(f) and f["severity"] in capture.CAPTURED and capture.match_key(f, cfg) in now]
    merged = justify.read_json(paths["report"])
    events += _judge_kept(merged, cfg, current, saved, data=article.read_bytes(), snap_doc=snap_doc, did=did,
                          article=article, prof=prof)
    if merged is not None and merged.get("article_sha256") == current["article_sha256"]:
        for item in merged.get("justified") or ():
            if (isinstance(item, dict) and isinstance(item.get("rule"), str) and item["rule"]
                    and item.get("kind") in justify.KINDS):
                events.append(ledger.make_event(
                    event="publish", actor="publish", outcome="survived_publish", rule=item["rule"], severity="WARN",
                    ruleset_version=str(current["ruleset_version"]), profile=str(current["profile"]), doc_id=did,
                    doc_sha=current["article_sha256"], span_hash=ledger.span_hash(item["rule"], capture.NO_SPAN),
                    facets={"kind": item["kind"]}))
    return _append(ledger.distinct(events), settings)
