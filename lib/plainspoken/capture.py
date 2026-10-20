"""Capture (Phase 5): lint findings become kaizen ledger events.

- `facets`: what a finding may say about itself without article text: a ruleset word (`term`), the kind of section it
  sits in (`section`), the 12f metric (`metric`) and the 7d shape (`form`).
- `lint_events`: one `fired` event per BLOCK or WARN finding (and per `[shadow]` finding, as INFO).
- `fixed_events`: the check-to-check diff, one `fixed` event per BLOCK or WARN span the edit removed.
- `merge_events`: the judges' own verdicts (`fired` / `passed`, with `agree` on lint+judge rules) and each JR-reviewed
  justification (`justified:<kind>`, then `jr_accept` / `jr_reject`). Judge evidence and justification reasons are
  hashed or dropped, never stored, even with excerpts on: they aren't the user's text, and a rubric change makes
  them stale.
- `engine_detail`: an engine message cut to one line of at most 200 characters, with its free-text slots (a rule id
  or group read from a file, a file name) replaced, for `friction.jsonl`.
- `record`: appends events and never raises. A capture error prints one `plainspoken: kaizen capture skipped: …` line
  on stderr and, where the settings can be built, logs `capture_error` friction; the command's own output and exit
  code don't change. A source left out of `[kaizen] capture_sources` records nothing (`source_on`).

A span is `ledger.span_hash(rule, excerpt)`. An aggregate finding (`AGGREGATE`: the excerpt is a tally or summary,
such as 4b's total or the em-dash count) hashes `"<severity>:<metric or doc>"` instead, so a changed tally that still
fires is the same span. A 12f metric finding (line 0) hashes its metric name, so the same MATTR finding on two
articles is the same span. The finding's excerpt rides along in `excerpt`; `ledger.append` drops it unless
excerpts are on. Nothing else carries article text.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from plainspoken import config, justify, ledger, report
from plainspoken.checks_structural import in_faq
from plainspoken.doc import Doc, parse
from plainspoken.registry import load_config

CAPTURED = ("BLOCK", "WARN")
SHADOW_PREFIX = "[shadow] "
STACCATO_RULES = ("7d", "NR-2")
_QUOTED = re.compile(r"“([^”]+)”")
_TRIM = " \t.,;:!?…'\"’‘"
_METRIC_PREFIXES = (("mattr ", "mattr"), ("burstiness ", "burstiness"), ("ttr ", "ttr"))
_SLOP = "slop metrics tripped"
_HEX64 = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL_KEY = re.compile(r"^[A-Za-z_\"'][^:]*:")


# --- facets ------------------------------------------------------------------------------------------------------

_MEMO: dict[str, tuple[object, object]] = {}


def _memo(slot: str, obj: object, build: Callable[[object], object]):
    """`build(obj)`, worked out once while `obj` (a ruleset or a parsed doc, never changed after it's made) is the
    last one seen in `slot`: a lint's findings share one ruleset and one doc, so the facet work isn't redone per
    finding. A strong reference is kept, so an id can't be reused by another object."""
    held = _MEMO.get(slot)
    if held is None or held[0] is not obj:
        held = (obj, build(obj))
        _MEMO[slot] = held
    return held[1]


def _ruleset_words(cfg) -> frozenset[str]:
    return _memo("words", cfg, lambda c: frozenset(w.lower() for items in c.lists.values() for w in items))


def _term(finding: dict, cfg) -> str | None:
    """The normalised excerpt, or a “quoted” word from the message, when it is exactly an entry in a ruleset list."""
    words = _ruleset_words(cfg)
    candidates = [str(finding.get("excerpt", ""))] + _QUOTED.findall(str(finding.get("message", "")))
    for text in candidates:
        word = ledger.normalise(text).strip(_TRIM)
        if word and word in words and len(word) <= ledger.MAX_FACET:
            return word
    return None


def _metric(finding: dict) -> str | None:
    if finding.get("rule") != "12f":
        return None
    excerpt = str(finding.get("excerpt", ""))
    for prefix, name in _METRIC_PREFIXES:
        if excerpt.startswith(prefix):
            return name
    return "slop" if _SLOP in str(finding.get("message", "")) else None


def _form(finding: dict, doc: Doc | None) -> str | None:
    """7d / NR-2: `no-long` when the finding names a section (its heading, or `(intro)`), else `short-run`. Without
    the doc the message tells them apart (only a run's message counts consecutive sentences)."""
    if finding.get("rule") not in STACCATO_RULES:
        return None
    excerpt = str(finding.get("excerpt", ""))
    if doc is None:
        return "short-run" if "consecutive" in str(finding.get("message", "")) else "no-long"
    names = {"(intro)"} | {title for _, _, title in doc.headings} | {s.heading for s in doc.sections if s.heading}
    return "no-long" if excerpt in names else "short-run"


def frontmatter_end(lines: list[str]) -> int:
    """The line number of the closing `---` (0 when there's no frontmatter)."""
    if not lines or lines[0] != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].startswith("---"):
            return i + 1
    return 0


def _faq_frontmatter_lines(doc: Doc, end: int) -> set[int]:
    """The frontmatter lines under the profile's FAQ key, from the key to the next top-level key."""
    key = doc.profile.faq_frontmatter_key
    if not key or not end:
        return set()
    out: set[int] = set()
    inside = False
    for ln in range(2, end):
        line = doc.lines[ln - 1]
        if re.match(rf"^{re.escape(key)}\s*:", line):
            inside = True
        elif _TOP_LEVEL_KEY.match(line):
            inside = False
        if inside:
            out.add(ln)
    return out


def _frontmatter(doc: Doc) -> tuple[int, set[int]]:
    end = frontmatter_end(doc.lines)
    return end, _faq_frontmatter_lines(doc, end)


def section_of(line: object, doc: Doc | None) -> str | None:
    """The `section` facet of a 1-based line: `faq`, `question`, `intro` or `other` (None without a doc or line)."""
    if doc is None or not isinstance(line, int) or isinstance(line, bool) or line <= 0:
        return None
    end, faq_lines = _memo("frontmatter", doc, _frontmatter)
    if line <= end:
        return "faq" if line in faq_lines else "intro"
    before = [(level, title) for ln, level, title in doc.headings if ln <= line]
    if not before:
        return "intro"
    if in_faq(doc, line):  # the test 12d's FAQ knob uses (checks_structural)
        return "faq"
    return "question" if before[-1][1].rstrip().endswith("?") else "other"


def facets(finding: dict, doc: Doc | None, cfg) -> dict:
    """The finding's facets (see the module docstring). `doc` is the parsed text the finding was made from; with
    None there's no `section`, and `form` comes from the message."""
    out: dict = {}
    term = _term(finding, cfg)
    if term is not None:
        out["term"] = term
    section = section_of(finding.get("line"), doc)
    if section is not None:
        out["section"] = section
    metric = _metric(finding)
    if metric is not None:
        out["metric"] = metric
    form = _form(finding, doc)
    if form is not None:
        out["form"] = form
    return out


def _always(finding: dict) -> bool:
    return True


def _whole_document(finding: dict) -> bool:
    return finding.get("line") == 0


def _slop(finding: dict) -> bool:
    return _metric(finding) == "slop"


# Aggregate findings: the excerpt is a tally or a summary, not a span of text, so a changed
# tally that still fires must stay the same span. (rule, severity) -> which of that pair's findings are aggregates.
# Left out on purpose, because their excerpt is a real line of the article: 24's curly-quote finding (line > 0), and
# 4a2's "“However,” opens N sentences" WARN (line > 0, the first such sentence). 12f's MATTR, burstiness and TTR
# findings hash their metric name (the schema's whole-document rule), not this key.
AGGREGATE: dict[tuple[str, str], Callable[[dict], bool]] = {
    ("1", "BLOCK"): _always,        # em-dash tally ("lines [...]")
    ("NR-1", "BLOCK"): _always,     # the narrative em-dash tally
    ("4b", "BLOCK"): _always,       # total sentence-opening transitions ("{word: n, ...}")
    ("2b", "WARN"): _always,        # _count_rule: Claude WARN words
    ("4a2", "BLOCK"): _whole_document,  # _count_rule: conversational transitions
    ("4a2", "WARN"): _whole_document,   # the same tally at WARN (not the However finding)
    ("23", "WARN"): _always,        # _count_rule: filler phrases
    ("25", "WARN"): _always,        # _count_rule: vague quantifiers
    ("24", "WARN"): _whole_document,  # bold density ("N bold spans / M words"), not curly quotes
    ("12f", "WARN"): _slop,         # "N slop metrics tripped" (the excerpt is the metrics dict)
    ("15", "WARN"): _always,        # "N expanded vs M contracted"
    ("HM", "WARN"): _always,        # no human markers
    ("NR-5", "WARN"): _always,      # "shortest Nw, longest Mw"
    ("NR-6", "WARN"): _always,      # no opinion marker
}


def aggregate_key(finding: dict, finding_facets: dict | None = None) -> str | None:
    """`metric or "doc"` when the finding is an aggregate (AGGREGATE), else None. A whole-document finding with no
    metric that isn't listed (a future rule) is treated as an aggregate too: line 0 never points at text."""
    rule, severity = str(finding.get("rule")), str(finding.get("severity"))
    metric = (finding_facets or {}).get("metric") or _metric(finding)
    test = AGGREGATE.get((rule, severity))
    if test is not None and test(finding):
        return metric or "doc"
    if finding.get("line") == 0 and not metric:
        return "doc"
    return None


def span(finding: dict, finding_facets: dict | None = None) -> str:
    """The finding's span hash:
    - an aggregate (AGGREGATE): rule + `"<severity>:<metric or doc>"`, so a changed tally is the same span;
    - another whole-document (line 0) finding: rule + metric (12f MATTR, burstiness, TTR);
    - anything else: rule + excerpt."""
    rule = str(finding["rule"])
    key = aggregate_key(finding, finding_facets)
    if key is not None:
        return ledger.span_hash(rule, f"{finding['severity']}:{key}")
    if finding.get("line") == 0:
        return ledger.span_hash(rule, (finding_facets or {}).get("metric") or _metric(finding) or "")
    return ledger.span_hash(rule, str(finding.get("excerpt", "")))


# --- events ------------------------------------------------------------------------------------------------------

def doc_sha(lint: dict) -> str | None:
    """The lint's `article_sha256` when it's 64 lower-case hex, else None."""
    sha = lint.get("article_sha256")
    return sha if isinstance(sha, str) and _HEX64.fullmatch(sha) else None


def finding_event(finding: dict, lint: dict, doc: Doc | None, cfg, did: str, *, event: str, actor: str,
                  outcome: str, severity: str) -> dict:
    """One event for a lint finding: its facets, span hash and excerpt (the one builder `check`, `kaizen published`
    and the history backfill share)."""
    f = facets(finding, doc, cfg)
    return ledger.make_event(event=event, actor=actor, outcome=outcome, ruleset_version=str(lint["ruleset_version"]),
                             profile=str(lint["profile"]), rule=str(finding["rule"]), severity=severity, doc_id=did,
                             doc_sha=doc_sha(lint), span_hash=span(finding, f), facets=f,
                             excerpt=str(finding.get("excerpt", "")) or None)


def well_formed(finding: object) -> bool:
    """A finding capture can use: a rule, a severity, an int line, and string excerpt and message."""
    return (isinstance(finding, dict) and isinstance(finding.get("rule"), str) and finding["rule"] != ""
            and isinstance(finding.get("severity"), str) and isinstance(finding.get("line"), int)
            and not isinstance(finding.get("line"), bool) and isinstance(finding.get("excerpt", ""), str)
            and isinstance(finding.get("message", ""), str))


def _is_shadow(finding: dict) -> bool:
    return finding["severity"] == "INFO" and finding.get("message", "").startswith(SHADOW_PREFIX)


def lint_events(lint: dict, doc: Doc | None, cfg, root: Path, actor: str = "lint", event: str = "lint", *,
                doc_id: str | None = None) -> list[dict]:
    """One `fired` event per BLOCK or WARN finding; `[shadow]` findings are logged as `fired` with severity INFO.
    CANDIDATEs go to the judges and INFO isn't a tell. `doc_id` overrides the path-derived id (a history backfill
    passes `ledger.label_id("article-<n>")`). Duplicate events (same id) are listed once."""
    did = doc_id or ledger.doc_id(Path(lint["article"]), root)
    out = []
    for f in lint["findings"]:
        if not well_formed(f):
            continue
        if f["severity"] in CAPTURED:
            out.append(finding_event(f, lint, doc, cfg, did, event=event, actor=actor, outcome="fired",
                              severity=f["severity"]))
        elif _is_shadow(f):
            out.append(finding_event(f, lint, doc, cfg, did, event=event, actor=actor, outcome="fired",
                                     severity="INFO"))
    return ledger.distinct(out)


def match_key(finding: dict, cfg) -> tuple:
    """What the fixed diff matches on. An aggregate matches by rule and key whatever its severity, so a tally that
    moves between WARN and BLOCK (4a2) is still firing, not fixed."""
    f = facets(finding, None, cfg)
    agg = aggregate_key(finding, f)
    if agg is not None:
        return finding["rule"], "aggregate", agg
    return finding["rule"], span(finding, f), f.get("term")


def _comparable(previous: object, current: dict) -> bool:
    """`previous` is a lint of the same article (by file name; the caller read it from the article's own report
    key) made with the same profile, profile file, ruleset and content type, of a different version of the text."""
    if not isinstance(previous, dict) or not isinstance(previous.get("findings"), list):
        return False
    if previous.get("article_sha256") == current.get("article_sha256"):
        return False
    same = ("profile", "profile_sha256", "ruleset_version")
    if any(previous.get(k) != current.get(k) for k in same):
        return False
    if previous.get("content_type", "article") != current.get("content_type", "article"):
        return False
    try:
        return Path(str(previous.get("article"))).name == Path(str(current["article"])).name
    except (KeyError, TypeError, ValueError):
        return False


def fixed_events(previous: dict | None, current: dict, doc: Doc | None, cfg, root: Path, *,
                 doc_id: str | None = None) -> list[dict]:
    """When `previous` is a lint for the same article with a different `article_sha256`, one `fixed` event (event
    `fix`, actor `lint`) for each BLOCK or WARN span in `previous` that's gone from `current`. A span is matched on
    rule, span hash and term; a span still present at any severity isn't fixed. `doc` is the parsed text `previous`
    was made from (the check snapshot), or None, which leaves out the `section` facet. The events carry the current
    `article_sha256`. A damaged `previous` gives no events, never an error."""
    if not _comparable(previous, current):
        return []
    now = {match_key(f, cfg) for f in current["findings"] if well_formed(f)}
    did = doc_id or ledger.doc_id(Path(current["article"]), root)
    out = []
    for f in previous["findings"]:
        if well_formed(f) and f["severity"] in CAPTURED and match_key(f, cfg) not in now:
            out.append(finding_event(f, current, doc, cfg, did, event="fix", actor="lint", outcome="fixed",
                              severity=f["severity"]))
    return ledger.distinct(out)


# --- recording ---------------------------------------------------------------------------------------------------

def _first_line(e: BaseException) -> str:
    return (str(e).strip().splitlines() or [""])[0]


def _skipped(e: BaseException, source: str, settings: dict | None) -> None:
    """One stderr line, plus `capture_error` friction when there are settings. Never raises."""
    try:
        detail = f"{type(e).__name__}: {_first_line(e)}"
        if settings is not None:
            ledger.friction("capture_error", source, detail, settings)
        print(f"plainspoken: kaizen capture skipped: {detail}", file=sys.stderr)
    except Exception:  # deliberate: capture must never break the command
        pass


# The `[kaizen] capture_sources` name for each `record` source; a source not listed here is its own name.
SOURCE_NAMES = {"judge-record": "judge"}


def source_on(settings: dict, source: str) -> bool:
    """Capture is on and `source` (a `record` source, or a CAPTURE_SOURCES name) is in `[kaizen] capture_sources`."""
    names = settings.get("capture_sources", config.CAPTURE_SOURCES)
    return bool(settings.get("capture", True)) and SOURCE_NAMES.get(source, source) in names


def record(events: Iterable[dict] | Callable[[], Iterable[dict]], root: Path, source: str, *,
           frictions: Iterable[tuple[str, str]] = ()) -> None:
    """Append each event to the project's ledger (`config.kaizen_settings(root)`). `events` may be a callable that
    builds them, called only when capture is on, so building errors are capture errors too. `frictions` are
    `(kind, detail)` pairs logged to `friction.jsonl` first (with `source`), so a later capture error doesn't lose
    them. Capture off, or `source` left out of `[kaizen] capture_sources`: nothing. Any exception: `capture_error`
    friction (where the settings could be built) plus one stderr line; the other events are still tried. Never
    raises."""
    settings = None
    try:
        settings = config.kaizen_settings(Path(root), os.environ)
        if not source_on(settings, source):
            return
        for kind, detail in frictions:
            ledger.friction(kind, source, detail, settings)
        first: Exception | None = None
        for e in (events() if callable(events) else events):
            try:
                ledger.append(e, settings)
            except Exception as err:  # keep trying the rest; report the first
                first = first or err
        if first is not None:
            raise first
    except Exception as e:  # deliberate: capture must never break the command
        _skipped(e, source, settings)


def _parsed(data: bytes, path: Path, profile, content_type: str) -> Doc:
    return parse(data.decode("utf-8"), path=str(path), profile=profile, content_type=content_type)


def for_lint(lint: dict, path: Path, profile, cfg, root: Path, source: str) -> None:
    """Record `lint_events` for a lint just made of `path` (the lint-watch hook). Never raises."""
    def build() -> list[dict]:
        data = Path(path).read_bytes()
        if hashlib.sha256(data).hexdigest() != lint.get("article_sha256"):
            raise ValueError("the article changed while it was being checked")
        return lint_events(lint, _parsed(data, path, profile, lint.get("content_type", "article")), cfg, root)
    record(build, root, source)


CAPTURE_OFF = "capture-off.txt"  # in `proposals_dir`: when `check` last ran with check capture off
SNAPSHOT_SUFFIX = ".checked.md"
PREV_LINT_SUFFIX = ".prev.lint.json"


def previous_pair(snapshot: Path) -> tuple[Path, Path]:
    """(`<key>.prev.checked.md`, `<key>.prev.lint.json`) beside the snapshot `<key>.checked.md`: the check before the
    last one, kept so `kaizen dismiss --from-snapshot` reaches a finding a fix pass removed and a re-check
    overwrote. One pair per key."""
    snapshot = Path(snapshot)
    key = snapshot.name[:-len(SNAPSHOT_SUFFIX)] if snapshot.name.endswith(SNAPSHOT_SUFFIX) else snapshot.stem
    return snapshot.parent / f"{key}.prev{SNAPSHOT_SUFFIX}", snapshot.parent / f"{key}{PREV_LINT_SUFFIX}"


def _rotate(snapshot: Path, before: bytes | None, previous: dict | None, lint: dict) -> None:
    """At a saving check of a new version, the snapshot and lint it replaces become the previous pair, when they
    belong together (the old lint's `article_sha256` is the old snapshot's). Otherwise any previous pair is removed,
    so it's always the check right before the current one. Never raises."""
    prev_snap, prev_lint = previous_pair(snapshot)
    try:
        if not isinstance(previous, dict) or previous.get("article_sha256") == lint.get("article_sha256"):
            return  # the same text checked again: the previous pair stays
        if before is not None and hashlib.sha256(before).hexdigest() == previous.get("article_sha256"):
            report.write_atomic(prev_lint, json.dumps(previous, indent=2, ensure_ascii=False) + "\n")
            report.write_atomic(prev_snap, before)
            return
        for p in (prev_snap, prev_lint):
            if not p.is_symlink():
                p.unlink(missing_ok=True)
    except Exception:  # deliberate: capture must never break the command
        pass


def capture_off_since(settings: dict | None) -> datetime | None:
    """When `check` last ran with check capture off (`<proposals_dir>/capture-off.txt`), or None. A snapshot older
    than this may miss edits nobody recorded, so `kaizen diff` ignores it. Never raises."""
    try:
        path = Path(settings["proposals_dir"]) / CAPTURE_OFF
        if path.is_symlink() or not path.is_file():
            return None
        when = datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
        return when if when.tzinfo is not None else None
    except Exception:  # deliberate: an unreadable stamp only means a stale snapshot isn't caught by its age
        return None


def _capture_off(settings: dict, reports: Path | None) -> None:
    """Check capture is off: stamp the time, then delete the check snapshots in `reports` (every regular
    `*.checked.md`, previous ones included, and `*.prev.lint.json`; symlinks are left alone), so `kaizen diff` never
    shows hunks against a text nobody's edits were recorded from. The stamp is written only in a project that has a ledger (capture was on at some point): one
    that never captured has no snapshots to outdate. Never raises."""
    try:
        if Path(settings["ledger_dir"]).is_dir():
            report.write_atomic(Path(settings["proposals_dir"]) / CAPTURE_OFF,
                                datetime.now(timezone.utc).isoformat() + "\n")
    except Exception:  # deliberate: capture must never break the command
        pass
    try:
        found = ([] if reports is None else
                 sorted([*Path(reports).glob(f"*{SNAPSHOT_SUFFIX}"), *Path(reports).glob(f"*{PREV_LINT_SUFFIX}")]))
    except OSError:
        found = []
    for snap in found:
        try:
            if not snap.is_symlink() and snap.is_file():
                snap.unlink()
        except OSError:
            continue


def for_check(lint: dict, path: Path, profile, cfg, root: Path, *, previous: dict | None = None,
              snapshot: Path | None = None, reports: Path | None = None) -> None:
    """Capture for `check`. `snapshot` is `<key>.checked.md` when the lint was saved to its report key (None with
    `--no-save` or `--out`): the previous snapshot is read, the article's checked bytes replace it (atomically), and
    `fixed_events` against `previous` (the lint that was there before) join the `fired` ones; the replaced snapshot
    and lint become the previous pair (`previous_pair`). The settings come
    first: with capture off, or `check` left out of `[kaizen] capture_sources`, nothing is recorded or snapshotted,
    and the snapshots and previous pairs already in `reports` (the reports folder) are deleted, with the time stamped.
    Settings
    that can't be built mean one skip line and no snapshot. Never raises."""
    try:
        settings = config.kaizen_settings(Path(root), os.environ)
    except Exception as e:  # deliberate: capture must never break the command
        _skipped(e, "check", None)
        return
    if not source_on(settings, "check"):
        _capture_off(settings, reports if reports is not None else (snapshot.parent if snapshot else None))
        return
    try:
        data = Path(path).read_bytes()
        if hashlib.sha256(data).hexdigest() != lint.get("article_sha256"):
            if snapshot is not None and not Path(snapshot).is_symlink():
                Path(snapshot).unlink(missing_ok=True)  # never leave the old text beside the lint just saved
            raise ValueError("the article changed while it was being checked")
        before = None
        if snapshot is not None:
            try:
                before = None if snapshot.is_symlink() else snapshot.read_bytes()
            except OSError:
                before = None
            _rotate(snapshot, before, previous, lint)
            try:
                report.write_atomic(snapshot, data)
            except Exception:
                try:
                    Path(snapshot).unlink(missing_ok=True)  # never leave a snapshot that doesn't match the lint
                except OSError:
                    pass
                raise
    except Exception as e:  # deliberate: capture must never break the command
        _skipped(e, "check", settings)
        return
    ctype = lint.get("content_type", "article")

    def build() -> list[dict]:
        events = lint_events(lint, _parsed(data, path, profile, ctype), cfg, root)
        if snapshot is not None and previous is not None:
            prev_doc = None
            if before is not None and hashlib.sha256(before).hexdigest() == previous.get("article_sha256"):
                try:
                    prev_doc = _parsed(before, path, profile, ctype)
                except Exception:  # an unparseable old snapshot only costs the section facet
                    prev_doc = None
            events += fixed_events(previous, lint, prev_doc, cfg, root)
        return events
    record(build, root, "check")


# --- merge, JR and judge-record ----------------------------------------------------------------------------------

JUDGE_SOURCE = re.compile(r"judge:(J[1-4])")
FLAGGED = ("BLOCK", "CANDIDATE")  # what counts as the lint "having" a finding for a lint+judge rule
NO_SPAN = "*"  # the span text of a verdict without a quote, and of every justification
_VERDICTS = {"fail": "fired", "pass": "passed"}
_REVIEWS = {"accept": "jr_accept", "reject": "jr_reject"}


def first_quote(evidence: object) -> tuple[str | None, int | None]:
    """(the first evidence item's quote, its line) — the first item that is an object with a non-empty quote."""
    for item in evidence if isinstance(evidence, list) else ():
        if isinstance(item, dict) and isinstance(item.get("quote"), str) and item["quote"].strip():
            line = item.get("line")
            return item["quote"], line if isinstance(line, int) and not isinstance(line, bool) else None
    return None, None


def merge_events(merged: dict, doc: Doc | None, cfg, root: Path, *, doc_id: str | None = None) -> list[dict]:
    """The events a merged report adds to the ledger:
    - each rule entry a judge decided (`source` `judge:Jn`): `fired` for the judge's own `fail`, `passed` for its
      `pass` (event `judge`, actor `judge:Jn`; a lint BLOCK that overrides the verdict doesn't change it, and a
      `passed` carries the rule's own severity, not that BLOCK). The span is the rule + the first evidence quote,
      else rule + `*`. On a lint+judge rule, facet `agree` is (the entry's lint findings hold a BLOCK or CANDIDATE
      for the rule) == (the judge failed it); `section` comes from the quote's line;
    - each JR-reviewed justification: `justified:<kind>` (event `justify`, actor `human`), then `jr_accept` or
      `jr_reject` (event `jr`, actor `jr`, facet `kind`), both WARN on rule + `*`, never with the reason.
    Lint-only entries are left to `check`. Each entry's findings are the ones the merge used (the saved lint when
    it was current, else a fresh one), so the lint isn't read again. `doc` is the parsed merged text (or None: no
    `section`). `doc_id` overrides the path-derived id. Damaged entries are skipped."""
    did = doc_id or ledger.doc_id(Path(merged["article"]), root)
    base = {"ruleset_version": str(merged["ruleset_version"]), "profile": str(merged["profile"]), "doc_id": did,
            "doc_sha": doc_sha(merged)}
    out = []
    rules = merged.get("rules")
    for rid, entry in (rules.items() if isinstance(rules, dict) else ()):
        if not isinstance(entry, dict) or not isinstance(rid, str) or not rid:
            continue
        group = JUDGE_SOURCE.fullmatch(str(entry.get("source", "")))
        verdict = entry.get("judge_verdict", entry.get("verdict"))
        severity = entry.get("severity")
        if group is None or verdict not in _VERDICTS or severity not in ledger.SEVERITIES:
            continue
        quote, line = first_quote(entry.get("evidence"))
        facets: dict = {}
        rule = cfg.rules.get(rid)
        if rule is not None and rule.method == "lint+judge":
            findings = entry.get("findings")
            flagged = any(isinstance(f, dict) and f.get("rule") == rid and f.get("severity") in FLAGGED
                          for f in (findings if isinstance(findings, list) else ()))
            facets["agree"] = flagged == (verdict == "fail")
        section = section_of(line, doc)
        if section is not None:
            facets["section"] = section
        if verdict == "pass" and rule is not None:
            severity = rule.severity  # the merged BLOCK on a passed rule is the lint's, not the judge's
        out.append(ledger.make_event(event="judge", actor=f"judge:{group.group(1)}", outcome=_VERDICTS[verdict],
                                     rule=rid, severity=severity,
                                     span_hash=ledger.span_hash(rid, NO_SPAN if quote is None else quote),
                                     facets=facets, **base))
    for item in merged.get("justified") or ():
        if not (isinstance(item, dict) and isinstance(item.get("rule"), str) and item["rule"]
                and item.get("kind") in justify.KINDS and item.get("review") in _REVIEWS):
            continue
        rid, kind = item["rule"], item["kind"]
        span_text = ledger.span_hash(rid, NO_SPAN)
        out.append(ledger.make_event(event="justify", actor="human", outcome=f"justified:{kind}", rule=rid,
                                     severity="WARN", span_hash=span_text, **base))
        out.append(ledger.make_event(event="jr", actor="jr", outcome=_REVIEWS[item["review"]], rule=rid,
                                     severity="WARN", span_hash=span_text, facets={"kind": kind}, **base))
    return ledger.distinct(out)


# The engine messages with a free-text slot: a value read from a file (a rule id or group a judge or a person wrote,
# a ruleset version) or a file name. Each named group `v…` is kept only when it's a short token, else it becomes
# `?`; the other groups are engine text.
_SLOTS = tuple(re.compile(p) for p in (
    r"(?P<a>(?:J[1-4]|JR): bad verdict entry for rule )(?P<v>.*)",
    r"(?P<a>JR: no verdict for rule )(?P<v>.*)",
    r"(?P<a>justify: rule )(?P<v>.*)(?P<b> is justified twice)",
    r"(?P<a>justify: rule )(?P<v>.*)(?P<b>: (?:kind|reason) must be .*)",
    r"(?P<a>lint report made under ruleset )(?P<v1>.*)(?P<b>, current is )(?P<v2>.*)"
    r"(?P<c> \(the ruleset changed\) — rerun `check`)",
    r"(?P<a>reply is for group )(?P<v>.*)(?P<b>, expected (?:J[1-4]|JR))",
))
_FIXED = ((re.compile(r"justify: item without a rule: .*"), "justify: item without a rule"),
          (re.compile(r"no current lint for .*: run `check` first"), "no current lint for the article: run `check` first"))
# A slot keeps only what the engine itself names: a rule id (`7b`, `4a2`, `NR-2`, `HM`), a judge group (`J1`…`J4`,
# `JR`) or a ruleset version (`4.3.0`), quoted or not. Anything else, even one short word, may be article text.
_TOKEN = re.compile(r"'?(?:\d{1,3}[a-z]{0,2}\d?|[A-Z]{2}(?:-\d{1,2})?|J[1-4]|\d{1,4}(?:\.\d{1,4}){1,3})'?")


def engine_detail(message: object) -> str:
    """An engine message for `friction.jsonl`: its first line, free-text slots replaced (see `_SLOTS`), at most 200
    characters."""
    text = (str(message).strip().splitlines() or [""])[0]
    for pattern, fixed in _FIXED:
        if pattern.fullmatch(text):
            return fixed
    for pattern in _SLOTS:
        m = pattern.fullmatch(text)
        if m:
            parts = sorted(pattern.groupindex.items(), key=lambda kv: kv[1])
            text = "".join(m[name] if not name.startswith("v") or _TOKEN.fullmatch(m[name]) else "?"
                           for name, _ in parts)
            break
    return text[:ledger.MAX_DETAIL]


def _incomplete_detail(merged: dict) -> str:
    problems = [engine_detail(p) for p in merged.get("problems") or ()]
    if problems:
        return "; ".join(problems)[:ledger.MAX_DETAIL]
    missing = merged.get("coverage", {}).get("missing") or []
    return engine_detail(f"missing verdicts: {', '.join(map(str, missing))}")


def _merged_doc(merged: dict, article: Path, profile) -> Doc | None:
    """The merged text, parsed; None when the file changed since the merge or won't parse (only `section` is lost)."""
    try:
        data = Path(article).read_bytes()
        if hashlib.sha256(data).hexdigest() != merged.get("article_sha256"):
            return None
        return _parsed(data, article, profile, merged.get("content_type", "article"))
    except Exception:  # deliberate: a missing doc only costs the section facet
        return None


def for_merge(merged: dict, article: Path, profile, root: Path) -> None:
    """Capture for `merge`, after the report is written: `merge_events`, plus `merge_incomplete` friction when the
    status is INCOMPLETE. Never raises."""
    try:
        frictions = [("merge_incomplete", _incomplete_detail(merged))] if merged.get("status") == "INCOMPLETE" else []
    except Exception:  # deliberate: capture must never break the command
        frictions = [("merge_incomplete", "INCOMPLETE")]

    def build() -> list[dict]:
        return merge_events(merged, _merged_doc(merged, article, profile), load_config(), root)
    record(build, root, "merge", frictions=frictions)


def for_rejected_reply(reason: object, root: Path) -> None:
    """`judge_reply_rejected` friction for a judge reply `judge-record` refused. Never raises."""
    try:
        frictions = [("judge_reply_rejected", engine_detail(reason))]
    except Exception:  # deliberate: capture must never break the command
        frictions = [("judge_reply_rejected", "rejected")]
    record((), root, "judge-record", frictions=frictions)
