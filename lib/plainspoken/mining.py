"""Kaizen tell mining (Phase 5): model drafts written from the fixed briefs, compared with a human corpus.

`kaizen mine` reads drafts a skill has already generated (`DIR/<model id>/*.md`, one folder per model) and never calls
a model itself. It finds:
- **phrases**: 2–4 word phrases (lower-cased word tokens, inside one sentence) that one model writes far more often
  than the human corpus does, in enough of that model's drafts. Phrases made only of stopwords, phrases with a word
  from the briefs (topic words, not tells), phrases already in a ruleset list and phrases that contain a tell already
  listed are skipped. Overlapping phrases collapse to the longest one that keeps at least 80% of the shorter one's
  count; two adjacent windows of one longer phrase (`it's worth noting` / `worth noting that`) keep the window that
  starts with a content word.
- **moves**: every draft and corpus file is linted, and each rule's fire rate per 1,000 words is put through the same
  ratio and share tests. A shadow rule that passes is a promote candidate (one per rule, naming every model that
  passed it); an active rule that passes is evidence only.

At most `max_candidates` candidates in total, ranked by ratio × share, are materialised through
`calibrate.materialise` (the same diff, base hash, corpus effect and id as calibrate's; a candidate whose id is
already stored is skipped before its corpus effect is measured) and stored as proposals with
trigger `mined` and the model id in `model`. They stay in the local queue: each is written through the file adapter
(`<proposals_dir>/proposals/<id>.md`, `adapter: "file"`) whatever `[kaizen] adapter` says, so a person decides it
there and `kaizen decisions` reads it back; it's never emitted to github or trello (calibrate's re-send skips it).
An add-term is keyed on (list, phrase, model), so an open or recently rejected phrase isn't proposed again even after
another apply changed rule 32's models. A model is added to rule 32's `models` only when no equivalent spelling is
there already ('.' and '-' compare the same, so `claude-opus-5-5` is `claude-opus-5.5`, and the ruleset's spelling
stays). Topic words come from each brief's `Topic:` paragraph only. Mining never edits the ruleset.
"""
from __future__ import annotations

import re
import tomllib
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from plainspoken import adapters, calibrate, ledger, proposals, registry, report
from plainspoken.adapters import file as file_adapter
from plainspoken.doc import parse

BRIEFS = Path(__file__).resolve().parents[2] / "evals" / "briefs"
HELDOUT = ".heldout"  # marks a folder of held-out eval data (blind.HELDOUT)
MODEL_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
TRIGGER = "mined"
KEEP = 0.8  # a longer phrase absorbs a shorter one when it keeps at least this share of its count
# The mining bar: a model with fewer drafts is skipped. One draft per brief (6) is too few for the share test
# ("in at least half of one model's drafts") to mean much; read at call time, so tests may lower it.
MIN_MODEL_DRAFTS = 10
_INTS = ("ngram_min", "ngram_max", "min_drafts", "max_candidates")
_FLOATS = ("min_draft_share", "ratio", "smoothing_per_1k")
_STRS = ("target_list", "target_rule")
_TOKEN = re.compile(r"[a-z0-9']+")
_SENTENCE = re.compile(r"[.!?\n]+")
_PATTERN = re.compile(r"[\\^$\[\](){}*+?|]")
_FIRES = ("BLOCK", "WARN")


class MiningError(ValueError):
    """Bad input for `kaizen mine` (the CLI exits 2): the message names the folder, file or model id."""


def _first_line(e: BaseException) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


# --- settings ------------------------------------------------------------------------------------------------------

def load_settings(path: Path = calibrate.DEFAULT, cfg=None) -> dict:
    """`[mining]` from `data/kaizen.toml`, validated against the ruleset (`cfg`, default `registry.load_config()`)."""
    cfg = registry.load_config() if cfg is None else cfg
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: not valid TOML ({e})") from None
    m = raw.get("mining")
    if not isinstance(m, dict):
        raise ValueError(f"{path}: missing [mining]")
    known = set(_INTS + _FLOATS + _STRS) | {"not_tell_lists"}
    if set(m) - known:
        raise ValueError(f"{path}: unknown [mining] setting(s) {sorted(set(m) - known)}")
    out: dict = {}
    for key in _INTS:
        v = m.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise ValueError(f"{path}: [mining] {key} must be a non-negative integer")
        out[key] = v
    for key in _FLOATS:
        v = m.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise ValueError(f"{path}: [mining] {key} must be a number above 0")
        out[key] = float(v)
    for key in _STRS:
        if not isinstance(m.get(key), str):
            raise ValueError(f"{path}: [mining] {key} must be a string")
        out[key] = m[key]
    if out["ngram_min"] < 1 or out["ngram_max"] < out["ngram_min"]:
        raise ValueError(f"{path}: [mining] needs 1 ≤ ngram_min ≤ ngram_max")
    if out["min_draft_share"] > 1 or out["min_drafts"] < 1:
        raise ValueError(f"{path}: [mining] min_draft_share must be at most 1 and min_drafts at least 1")
    if out["target_list"] not in cfg.lists:
        raise ValueError(f"{path}: [mining] target_list: unknown list {out['target_list']!r}")
    if out["target_rule"] not in cfg.rules:
        raise ValueError(f"{path}: [mining] target_rule: unknown rule {out['target_rule']!r}")
    names = m.get("not_tell_lists")
    if not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
        raise ValueError(f"{path}: [mining] not_tell_lists must be a list of ruleset list names")
    for name in names:
        if name not in cfg.lists:
            raise ValueError(f"{path}: [mining] not_tell_lists: unknown list {name!r}")
    out["not_tell_lists"] = frozenset(names)  # lists whose entries aren't tells (function words, human markers)
    return out


# --- phrases -------------------------------------------------------------------------------------------------------

def tokens(text: str) -> list[str]:
    """Lower-cased word tokens `[a-z0-9']+`, typographic apostrophes straightened, edge apostrophes dropped."""
    found = _TOKEN.findall(text.lower().replace("’", "'").replace("‘", "'"))
    return [t for t in (w.strip("'") for w in found) if t]


def sentences(text: str) -> list[list[str]]:
    """The token lists of a markdown file's sentences. `doc.parse` drops frontmatter, fenced code, HTML, URLs, link
    targets and headings and joins a paragraph's hard-wrapped lines (as markdown renders them); each paragraph, list
    item or table row is then split on `.`, `!`, `?` and any line break left."""
    out = []
    for para in parse(text).prose_paragraphs():
        for chunk in _SENTENCE.split(para.text):
            toks = tokens(chunk)
            if toks:
                out.append(toks)
    return out


def _tally(docs: list[list[list[str]]], n_min: int, n_max: int) -> tuple[Counter, Counter, int]:
    """(occurrences, documents containing it, total words) for every n-gram of n_min..n_max words."""
    counts: Counter = Counter()
    in_docs: Counter = Counter()
    words = 0
    for sents in docs:
        seen = set()
        for s in sents:
            words += len(s)
            for n in range(n_min, n_max + 1):
                for i in range(len(s) - n + 1):
                    g = tuple(s[i:i + n])
                    counts[g] += 1
                    seen.add(g)
        in_docs.update(seen)
    return counts, in_docs, words


def _eligible(g: tuple, stopwords: frozenset, brief_words: frozenset) -> bool:
    return not all(t in stopwords for t in g) and not any(t in brief_words for t in g)


def phrase_rates(texts: list[str], n_min: int, n_max: int, *, stopwords: Iterable[str] = (),
                 brief_words: Iterable[str] = ()) -> dict[str, tuple[float, int]]:
    """phrase → (rate per 1,000 words, documents containing it) over `texts` (markdown), skipping phrases made only of
    `stopwords` and phrases containing one of `brief_words`."""
    stop, brief = frozenset(stopwords), frozenset(brief_words) - frozenset(stopwords)
    counts, in_docs, words = _tally([sentences(t) for t in texts], n_min, n_max)
    w = max(words, 1)
    return {" ".join(g): (n * 1000 / w, in_docs[g]) for g, n in counts.items() if _eligible(g, stop, brief)}


def is_pattern(entry: str) -> bool:
    """A list entry written as a regular expression (rules.toml keeps a few, e.g. `balance_patterns`)."""
    return bool(_PATTERN.search(entry))


def _contains(longer: tuple, shorter: tuple) -> bool:
    n = len(shorter)
    return 0 < n <= len(longer) and any(longer[i:i + n] == shorter for i in range(len(longer) - n + 1))


class _Listed:
    """Phrases the ruleset already has: equal (lower-cased, whitespace-normalised) to an entry of any list, or
    containing an entry of a tell list (a literal by its tokens, a pattern by regex). `not_tell` names the lists that
    aren't tell lists (`[mining] not_tell_lists`)."""

    def __init__(self, cfg, not_tell: frozenset = frozenset()):
        self.exact = {" ".join(e.lower().split()) for entries in cfg.lists.values() for e in entries}
        self.parts: list[tuple] = []
        self.patterns: list[re.Pattern] = []
        for name, entries in cfg.lists.items():
            if name in not_tell:
                continue
            for e in entries:
                if is_pattern(e):
                    try:
                        self.patterns.append(re.compile(e, re.I))
                    except re.error:
                        continue
                elif tokens(e):
                    self.parts.append(tuple(tokens(e)))

    def __call__(self, g: tuple) -> bool:
        phrase = " ".join(g)
        return (phrase in self.exact or any(_contains(g, p) for p in self.parts)
                or any(p.search(phrase) for p in self.patterns))


def _collapse(found: dict[tuple, dict], counts: Counter, stopwords: frozenset) -> list[tuple]:
    """The phrases left once overlaps collapse: longest first; a phrase inside a longer one (kept or merged) with at
    least KEEP of its count goes; of two adjacent windows of one longer phrase that occurs at least KEEP as often,
    the window starting with a content word stays (then the more frequent, then the first alphabetically)."""
    order = sorted(found, key=lambda g: (-len(g), g[0] in stopwords, -counts[g], " ".join(g)))
    seen: list[tuple] = []
    kept: list[tuple] = []
    for g in order:
        n = counts[g]
        drop = any(len(k) > len(g) and _contains(k, g) and counts[k] >= KEEP * n for k in seen)
        if not drop:
            for k in kept:
                if len(k) != len(g):
                    continue
                joined = k + g[-1:] if k[1:] == g[:-1] else g + k[-1:] if g[1:] == k[:-1] else None
                if joined is not None and counts.get(joined, 0) >= KEEP * n:
                    drop = True
                    break
        seen.append(g)
        if not drop:
            kept.append(g)
    return kept


# --- inputs --------------------------------------------------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise MiningError(f"{path}: can't read ({_first_line(e)})") from None


def _doc(path: Path) -> list[list[str]]:
    try:
        return sentences(_read(path))
    except MiningError:
        raise
    except ValueError as e:  # an unclosed or broken frontmatter block
        raise MiningError(f"{path}: can't parse ({_first_line(e)})") from None


def drafts(drafts_dir: Path) -> dict[str, list[Path]]:
    """{model id: its *.md drafts}, from `DIR/<model id>/*.md`. A hidden folder is skipped; any other folder whose
    name isn't a model id is a MiningError, and so is a folder with no drafts at all."""
    d = Path(drafts_dir)
    if not d.is_dir():
        raise MiningError(f"{d}: no such folder of drafts (expected {d}/<model id>/*.md)")
    out: dict[str, list[Path]] = {}
    for sub in sorted(d.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        if not MODEL_ID.fullmatch(sub.name):
            raise MiningError(f"{sub.name!r} isn't a model id (letters, digits, . _ - and at most 64 characters): "
                              f"rename {sub}")
        files = sorted(p for p in sub.glob("*.md") if p.is_file())
        if files:
            out[sub.name] = files
    if not out:
        raise MiningError(f"no drafts in {d} (expected {d}/<model id>/*.md)")
    return out


def _topic(text: str) -> str | None:
    """The text of a brief's `Topic:` paragraphs (from the `Topic:` line to the next blank line), or None."""
    out, inside = [], False
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:6].lower() == "topic:":
            inside = True
            out.append(line[6:])
        elif inside and line.strip():
            out.append(line)
        else:
            inside = False
    return "\n".join(out) if out else None


def refuse_heldout(briefs_dir: Path) -> None:
    """MiningError when `briefs_dir` holds a `.heldout` marker: held-out eval data (the blind reader test's pairs,
    say) is never mined, or its texts would leak into the ruleset that's measured against them."""
    if (Path(briefs_dir) / HELDOUT).exists():
        raise MiningError(f"{briefs_dir} holds a {HELDOUT} marker: it's held-out eval data, never mined")


def brief_words(briefs_dir: Path, stopwords: Iterable[str]) -> frozenset[str]:
    """Topic words: the non-stopword words of each brief's `Topic:` paragraph. The rest of a brief
    (audience, format, length, instructions) never blocks a phrase. A brief with no `Topic:` paragraph is a
    MiningError."""
    d = Path(briefs_dir)
    refuse_heldout(d)
    files = sorted(p for p in d.glob("*.md") if p.is_file()) if d.is_dir() else []
    if not files:
        raise MiningError(f"no briefs in {d} (expected {d}/*.md)")
    stop = frozenset(stopwords)
    out: set[str] = set()
    for f in files:
        topic = _topic(_read(f))
        if topic is None:
            raise MiningError(f"{f}: no Topic: paragraph, so its topic words are unknown")
        out.update(t for t in tokens(topic) if t not in stop)
    return frozenset(out)


# --- moves ---------------------------------------------------------------------------------------------------------

def _fires(path: Path, cfg, profile, shadow: set[str]) -> Counter:
    try:
        lint = report.run_lint(Path(path), profile, "article", cfg=cfg)
    except (ValueError, OSError) as e:
        raise MiningError(f"{path}: can't lint ({_first_line(e)})") from None
    return Counter(f["rule"] for f in lint["findings"]
                   if f.get("severity") in _FIRES or (f["rule"] in shadow and f.get("severity") == "INFO"))


def _test(rate: float, corpus_rate: float, hits: int, n: int, m: Mapping) -> tuple[float, float] | None:
    """(ratio, share) when the ratio and share tests pass, else None."""
    share = hits / n if n else 0.0
    ratio = rate / (corpus_rate + m["smoothing_per_1k"])
    if hits < m["min_drafts"] or share < m["min_draft_share"] or ratio < m["ratio"]:
        return None
    return round(ratio, 2), round(share, 2)


# --- candidates ----------------------------------------------------------------------------------------------------

def _blocked(settings: Mapping, now: datetime, cooldown_days: int) -> set[str]:
    """Keys of stored proposals still open (pending or approved, not applied), or rejected within the cooldown."""
    if not settings.get("proposals_dir"):
        return set()
    events = ledger.read(settings)[0] if settings.get("ledger_dir") else []
    out = set()
    for p in proposals.stored(settings):
        state = proposals.status(p["id"], events)
        if state in ("pending", "approved"):
            out.add(p.get("key"))
        elif state == "rejected":
            d = proposals.decision(p["id"], events)
            try:
                if now - datetime.fromisoformat(d["ts"]) < timedelta(days=cooldown_days):
                    out.add(p.get("key"))
            except (TypeError, ValueError, KeyError):
                out.add(p.get("key"))
    return out


def model_norm(model: str) -> str:
    """A model id for comparison: '.' and '-' are the same (`claude-opus-5.5` is `claude-opus-5-5`)."""
    return str(model).replace(".", "-")


def _phrase_candidate(x: Mapping, cfg, m: Mapping) -> dict:
    rule = m["target_rule"]
    models = list(cfg.rules[rule].models)
    edits = [{"kind": "list_add", "list": m["target_list"], "values": [x["phrase"]]}]
    if model_norm(x["model"]) not in {model_norm(have) for have in models}:  # an equivalent spelling stays as it is
        edits.append({"kind": "rule_field", "rule": rule, "field": "models", "new": models + [x["model"]]})
    reason = (f'model {x["model"]}: "{x["phrase"]}" at {x["ratio"]}x the human rate, in {x["drafts"]} of '
              f'{x["of"]} drafts')
    return {"rule": rule, "trigger": TRIGGER, "action": "add-term", "edits": edits, "reason": reason,
            "evidence": dict(x), "docs": x["drafts"], "narrow": False, "excerpts": [], "model": x["model"],
            "label": x["phrase"], "score": x["ratio"] * x["share"], "key": term_key(m["target_list"], x["phrase"],
                                                                                    x["model"])}


def term_key(target_list: str, phrase: str, model: str) -> str:
    """An add-term candidate's key: its list, phrase and model, not its edits, so a `models` change made
    by another apply doesn't make a rejected or open phrase look new."""
    return proposals.digest({"trigger": TRIGGER, "action": "add-term", "list": target_list, "phrase": phrase,
                             "model": model})[:12]


def _promote_candidate(x: Mapping, others: list[Mapping] = ()) -> dict:
    """One promote for a shadow rule: led by its top-ranked model `x`, naming every model whose drafts passed,
    with each one's figures in `evidence["by_model"]`."""
    passed = [x, *others]
    names = [str(y["model"]) for y in passed]
    reason = (f'model{"s" if len(names) > 1 else ""} {", ".join(names)}: shadow rule {x["rule"]} fires at '
              + "; ".join(f'{y["ratio"]}x the human rate in {y["drafts"]} of {y["of"]} drafts ({y["model"]})'
                          for y in passed))
    evidence = {**dict(x), "models": sorted(names)}
    if others:
        evidence["by_model"] = {str(y["model"]): {k: y[k] for k in ("ratio", "share", "drafts", "of")} for y in passed}
    return {"rule": x["rule"], "trigger": TRIGGER, "action": "promote",
            "edits": [{"kind": "rule_field", "rule": x["rule"], "field": "status", "new": None}], "reason": reason,
            "evidence": evidence, "docs": x["drafts"], "narrow": False, "excerpts": [], "model": x["model"],
            "label": x["rule"], "score": x["ratio"] * x["share"]}


def _promote_candidates(moves: list[dict]) -> list[dict]:
    """One promote candidate per shadow rule, however many models passed it."""
    by_rule: dict[str, list[dict]] = {}
    for x in moves:
        if x["action"] == "promote":
            by_rule.setdefault(x["rule"], []).append(x)
    out = []
    for passed in by_rule.values():
        passed.sort(key=lambda y: (-y["ratio"] * y["share"], y["model"]))
        out.append(_promote_candidate(passed[0], passed[1:]))
    return out


def _emit(p: dict, settings: Mapping) -> None:
    """Write the proposal's local `.md` through the file adapter, whatever `[kaizen] adapter` says: a
    mined proposal is never sent outward, but a person decides it there like any other. A failed write leaves
    `emit_error` and no `ref`; the next `kaizen mine` writes it again."""
    try:
        adapters.send(p, settings, lambda: file_adapter.FileAdapter(settings))
    except adapters.AdapterError:
        pass  # recorded on the proposal by send
    except adapters.NotSaved as e:
        p["save_error"] = str(e)


def mine(drafts_dir: Path, corpus_paths: list[Path], briefs_dir: Path | None, cfg, profile, settings: Mapping, *,
         now: datetime | None = None, dry_run: bool = False, rules_path: Path | None = None) -> dict:
    """Mine once. Returns `{"models": {model: {"drafts", "words"[, "skipped"]}}, "corpus": {"files", "words"},
    "phrases": [...], "moves": [...], "candidates": [proposal, ...], "dry_run"}`. A model with fewer than
    `MIN_MODEL_DRAFTS` drafts is skipped (`skipped` says why). Unless `dry_run`, each candidate is stored as a
    proposal and logged as one `mine` event (`proposed`, facet `model`); nothing is sent or applied. Raises
    MiningError for bad input, including no model reaching the bar."""
    now = datetime.now(timezone.utc) if now is None else now
    refuse_heldout(BRIEFS if briefs_dir is None else briefs_dir)  # before anything is read
    m = settings.get("mining") or load_settings(cfg=cfg)
    by_model = drafts(drafts_dir)
    corpus = list(corpus_paths)
    if not corpus:
        raise MiningError("no human corpus: pass --corpus GLOB or set [kaizen] human_corpus")
    stop = frozenset(cfg.lists.get("repeat_stopwords", ()))
    brief = brief_words(BRIEFS if briefs_dir is None else briefs_dir, stop)
    listed = _Listed(cfg, m["not_tell_lists"])
    shadow = {r.id for r in cfg.rules.values() if r.status == "shadow"}
    n_min, n_max = m["ngram_min"], m["ngram_max"]
    if not dry_run and settings.get("proposals_dir"):
        for waiting in adapters.unsent_mined(settings):
            _emit(waiting, settings)

    corpus_docs = [_doc(p) for p in corpus]
    c_counts, _, c_words = _tally(corpus_docs, n_min, n_max)
    c_w = max(c_words, 1)
    c_fires: Counter = Counter()
    for p in corpus:
        c_fires.update(_fires(p, cfg, profile, shadow))

    models, phrases, moves = {}, [], []
    bar = MIN_MODEL_DRAFTS
    if all(len(files) < bar for files in by_model.values()):
        have = ", ".join(f"{m}: {len(f)}" for m, f in by_model.items())
        raise MiningError(f"no model has at least {bar} drafts ({have}): write each brief more than once")
    for model, files in by_model.items():
        docs = [_doc(p) for p in files]
        n = len(files)
        counts, in_docs, words = _tally(docs, n_min, n_max + 1)  # one word longer, for adjacent windows
        w = max(words, 1)
        models[model] = {"drafts": n, "words": words}
        if n < bar:
            models[model]["skipped"] = f"fewer than {bar} drafts"
            continue
        found: dict[tuple, dict] = {}
        for g, k in counts.items():
            if len(g) > n_max or in_docs[g] < m["min_drafts"] or not _eligible(g, stop, brief):
                continue
            rate, c_rate = k * 1000 / w, c_counts.get(g, 0) * 1000 / c_w
            passed = _test(rate, c_rate, in_docs[g], n, m)
            if passed is None or listed(g):
                continue
            found[g] = {"model": model, "phrase": " ".join(g), "draft_rate": round(rate, 2),
                        "corpus_rate": round(c_rate, 2), "ratio": passed[0], "share": passed[1],
                        "drafts": in_docs[g], "of": n, "count": k}
        phrases += [found[g] for g in _collapse(found, counts, stop)]
        fired = [_fires(p, cfg, profile, shadow) for p in files]
        total = sum(fired, Counter())
        for rid in sorted(total, key=calibrate._natural):
            rate, c_rate = total[rid] * 1000 / w, c_fires.get(rid, 0) * 1000 / c_w
            hits = sum(1 for f in fired if f.get(rid))
            passed = _test(rate, c_rate, hits, n, m)
            if passed is None:
                continue
            status = cfg.rules[rid].status if rid in cfg.rules else "active"
            moves.append({"model": model, "rule": rid, "status": status, "draft_rate": round(rate, 2),
                          "corpus_rate": round(c_rate, 2), "ratio": passed[0], "share": passed[1], "drafts": hits,
                          "of": n, "action": "promote" if status == "shadow" else "evidence"})

    def rank(c):
        return (-c["score"], c["label"], c["model"])

    phrases.sort(key=lambda x: (-x["ratio"] * x["share"], x["phrase"], x["model"]))
    cands = sorted([_phrase_candidate(x, cfg, m) for x in phrases]
                   + _promote_candidates(moves), key=rank)
    blocked = _blocked(settings, now, calibrate._cal(settings)["triggers"]["cooldown_days"])
    known = {p["id"] for p in proposals.stored(settings)} if settings.get("proposals_dir") else set()
    out: list[dict] = []
    for c in cands:
        if len(out) >= m["max_candidates"]:
            break
        model = c.pop("model")
        c.pop("label"), c.pop("score")
        c["key"] = c.get("key") or calibrate.candidate_key(c)
        if c["key"] in blocked:
            continue
        p = calibrate.materialise(c, rules_path, cfg, profile, corpus, now, skip_ids=known)
        if p is None:  # stored already (applied, superseded…): not measured again
            continue
        p["model"] = model
        known.add(p["id"])
        blocked.add(c["key"])
        if not dry_run:
            proposals.save(p, settings)
            _emit(p, settings)
            try:
                ledger.append(ledger.make_event(event="mine", actor="engine", outcome="proposed",
                                                ruleset_version=cfg.version,
                                                profile=getattr(profile, "name", None) or "unknown",
                                                rule=p["rule"], proposal=p["id"], facets={"model": model}, ts=now),
                              settings)
            except ledger.LedgerError:
                pass  # the proposal is stored; an unwritable ledger mustn't stop mining (as in calibrate)
        out.append(p)
    return {"models": models, "corpus": {"files": len(corpus), "words": c_words}, "phrases": phrases,
            "moves": moves, "candidates": out, "dry_run": dry_run}
