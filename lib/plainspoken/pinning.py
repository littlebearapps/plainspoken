"""Passage pinning: locate a supporting passage in saved source text, hash it, build the ledger's `binding` fields, and
recheck existing pins offline against the saved sources.

Anti-fabrication contract: a passage is located by `str.find` over normalised text, never generated or extracted by a
model. A passage that can't be located is a refusal, never a guess.

Hashing is over NORMALISED text (typographic quotes straightened, whitespace collapsed, case kept), so a cosmetic
re-render of a page doesn't break a pin while any change of wording does. Hashes are `sha256:<hex>`, as the ledger
schema expects.

No network: this module never fetches a page. The host saves the source text under `[claims] sources_dir` (default
`.plainspoken/sources/`) and `binding.source_snapshot` names that file, project-relative. `recheck` reads only those
files and never follows a path out of the project. A snapshot that resolves (symlinks followed) outside sources_dir,
or that is the article itself, is `snapshot_outside_sources` and isn't read: an article can never be its own source.

`normalise_evidence` is a looser comparison for quoting a checker's evidence against an article (the two ellipsis
forms, markdown link syntax and case also ignored). It is never used for pins. The four normalisation rules (pins,
evidence, gaps, sign-off) are listed together in docs/report-contract.md.
"""
from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from plainspoken import config
from plainspoken._util import safe_relative  # re-exported: the one project-relative path rule

__all__ = ["MAX_PASSAGE_WORDS", "BindingFields", "Pin", "binding_fields", "locate_passage", "normalise_evidence",
           "normalise_text", "pin_hashes", "recheck", "safe_relative", "sha256_str", "snapshot_problem",
           "source_problem", "status_reasons"]

# Passages are bounded to about 75 words; refuse a little above that so an honest 76-word cut isn't bounced.
MAX_PASSAGE_WORDS = 80

_QUOTES = {"“": '"', "”": '"', "‘": "'", "’": "'", "«": '"', "»": '"'}
_WS = re.compile(r"\s+")
# `[text](url)` or `![alt](url)`: the url may be `<…>` or hold one level of balanced parentheses, and an optional
# title ("…", '…' or (…)) may follow it.
_MD_LINK = re.compile(r"""!?\[([^\]]*)\]\(\s*(?:<[^<>]*>|(?:[^()\s]|\([^()\s]*\))*)"""
                      r"""(?:\s+(?:"[^"]*"|'[^']*'|\([^()]*\)))?\s*\)""")
_UNSAFE_PATH = ("not a project-relative path (absolute, empty, `..` or a NUL character), so it wasn't read: "
                "save the source under the project and name it relative to the project root")


def normalise_text(s: str) -> str:
    """Straighten typographic quotes, collapse whitespace runs to one space and strip. Case is kept."""
    for k, v in _QUOTES.items():
        s = s.replace(k, v)
    return _WS.sub(" ", s).strip()


def normalise_evidence(s: str) -> str:
    """`normalise_text`, then `…` becomes `...`, markdown links `[text](url)` become `text` and images `![alt](url)`
    become `alt`, then casefold. For verbatim-evidence matching only; pins never use it."""
    return _MD_LINK.sub(r"\1", normalise_text(s).replace("\u2026", "...")).casefold()


def sha256_str(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Pin:
    start: int  # offsets in the NORMALISED source text
    end: int
    passage_norm: str


def locate_passage(source_text: str, passage: str) -> Pin | None:
    """Find the normalised passage inside the normalised source, or None."""
    src = normalise_text(source_text)
    needle = normalise_text(passage)
    if not needle:
        return None
    idx = src.find(needle)
    if idx < 0:
        return None
    return Pin(start=idx, end=idx + len(needle), passage_norm=needle)


def pin_hashes(source_text: str, passage: str) -> dict[str, str]:
    """`passage_sha256` and `source_text_sha256` for a passage that must be locatable in the source.

    Raises ValueError when it isn't: a pin over a passage the source doesn't contain is exactly the defect pinning
    exists to catch.
    """
    pin = locate_passage(source_text, passage)
    if pin is None:
        raise ValueError("passage not locatable in source text")
    return {
        "passage_sha256": sha256_str(pin.passage_norm),
        "source_text_sha256": sha256_str(normalise_text(source_text)),
    }


class _PinnedPassage(TypedDict):
    passage: str
    passage_sha256: str
    source_text_sha256: str
    retrieved_at: str


class BindingFields(_PinnedPassage, total=False):
    """The pinned-passage fields of a ledger `binding` (or of one `additional_passages` item), as the schema names
    them. `source_url` and `locator` are only ever added to an additional passage (`claims_tools.pin_fragment`).
    (`total=False` rather than NotRequired: this module's annotations are strings, which NotRequired can't see.)"""
    source_snapshot: str
    source_url: str
    locator: str


def binding_fields(source_text: str, passage: str, *, retrieved_at: str,
                   source_snapshot: str | None) -> BindingFields:
    """The ready-to-paste `binding` fields, or ValueError (a refusal, never a guess)."""
    words = len(passage.split())
    if words == 0:
        raise ValueError("empty passage")
    if words > MAX_PASSAGE_WORDS:
        raise ValueError(f"passage too long ({words} words > {MAX_PASSAGE_WORDS}) — cut a tighter passage")
    if source_snapshot is not None and not safe_relative(source_snapshot):
        raise ValueError(f"source_snapshot {source_snapshot!r} is {_UNSAFE_PATH}")
    pin = locate_passage(source_text, passage)
    if pin is None:
        raise ValueError("passage not locatable in source text — re-cut it verbatim from the saved source text; "
                         "never paraphrase, never hand-write a hash")
    fields: BindingFields = {
        "passage": pin.passage_norm,
        "passage_sha256": sha256_str(pin.passage_norm),
        "source_text_sha256": sha256_str(normalise_text(source_text)),
        "retrieved_at": retrieved_at,
    }
    if source_snapshot is not None:
        fields["source_snapshot"] = source_snapshot
    return fields


# --- where a source may live -------------------------------------------------------------------------------------

def source_problem(project_root: Path, path: Path, sources_dir: str, articles: Iterable[Path] = ()) -> str | None:
    """Why the file at `path` (absolute, or relative to the project root) can't be a pinned source, or None.

    It must resolve, symlinks followed, inside `sources_dir` (project-relative) and must not be one of `articles`:
    an article can never be its own source. Raises OSError / ValueError / RuntimeError when a path can't be
    resolved (a symlink loop, on every Python: `config.resolve_path`)."""
    root = config.resolve_path(Path(project_root))
    resolved = config.resolve_path(root / path)
    shown = Path(path).as_posix()
    if resolved != Path(os.path.abspath(root / path)):
        target = resolved.relative_to(root).as_posix() if resolved.is_relative_to(root) else str(resolved)
        shown += f" (a link to {target})"
    folder = sources_dir.rstrip("/\\") + "/"
    if resolved in {config.resolve_path(Path(a)) for a in articles}:
        return (f"{shown} is the article; an article can never be its own source: save the source's text under "
                f"{folder} and pin from that")
    if not resolved.is_relative_to(config.resolve_path(root / sources_dir)):
        return (f"{shown} isn't under the sources folder {folder} (`[claims] sources_dir`): save the source's text "
                "there and pin from that")
    return None


def snapshot_problem(project_root: Path, rel: str, source_text: str) -> str | None:
    """Why `rel` (project-relative, already in the right place: `source_problem`) can't be recorded as the
    `source_snapshot` of a pin cut from `source_text`, or None. It must be a readable UTF-8 file holding the same
    text as the source (`normalise_text`), because recheck reads it and compares `source_text_sha256` with it: a pin
    to anything else would fail its first recheck."""
    path = Path(project_root) / rel
    try:
        if not path.exists():
            return f"{rel} not found: save the source's text there first, or leave --snapshot-path out"
        if not path.is_file():
            return f"{rel} isn't a file"
        saved = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return f"{rel} isn't UTF-8 text"
    except (OSError, ValueError) as e:
        return f"{rel} can't be read ({type(e).__name__})"
    if normalise_text(saved) != normalise_text(source_text):
        return (f"{rel} doesn't hold the same text as --source, so recheck would read another page: pin from the "
                "file you'll keep")
    return None


# --- offline recheck ---------------------------------------------------------------------------------------------

def _read_snapshot(root: Path, rel: object, sources_dir: str,
                   articles: tuple[Path, ...]) -> tuple[str | None, str, str]:
    """(normalised text, "", "") or (None, why it couldn't be used, the result kind). Never raises; never reads
    outside the project, outside sources_dir, or the article."""
    if not safe_relative(rel):
        return None, f"source_snapshot {rel!r} is {_UNSAFE_PATH}", "snapshot_missing"
    try:
        root_resolved = config.resolve_path(Path(root))
        path = config.resolve_path(root_resolved / rel)
        if not path.is_relative_to(root_resolved):
            return None, f"source_snapshot {rel} resolves outside the project, so it wasn't read", "snapshot_missing"
        problem = source_problem(root_resolved, Path(rel), sources_dir, articles)
        if problem is not None:
            return None, f"source_snapshot {problem}; it wasn't read", "snapshot_outside_sources"
        if not path.exists():
            return None, f"source_snapshot {rel} not found", "snapshot_missing"
        if not path.is_file():
            return None, f"source_snapshot {rel} isn't a file", "snapshot_missing"
        return normalise_text(path.read_bytes().decode("utf-8")), "", ""
    except UnicodeDecodeError:
        return None, f"source_snapshot {rel} isn't UTF-8 text", "snapshot_missing"
    except (OSError, ValueError, RuntimeError) as e:
        return None, f"source_snapshot {rel} can't be read ({type(e).__name__})", "snapshot_missing"


def _check_passage(passage: object, recorded_passage: object, recorded_source: object,
                   snapshot: tuple[str | None, str, str] | None, label: str) -> tuple[str, str]:
    """(result, detail) for one pinned passage against an already-read snapshot (None: no snapshot named)."""
    if not isinstance(passage, str) or not passage.strip():
        return "unchecked", f"{label}: the passage isn't text"
    if snapshot is None:
        return "unchecked", f"{label}: no binding.source_snapshot, so there's no saved source to recheck against"
    text, why, failed = snapshot
    if text is None:
        return failed, f"{label}: {why}"
    needle = normalise_text(passage)
    if text.find(needle) < 0:
        return "passage_missing", (f"{label}: the passage is no longer in the saved source; re-cut it verbatim "
                                   "from the current text or re-verify the claim")
    if recorded_passage != sha256_str(needle):
        why_hash = ("no passage_sha256 recorded" if recorded_passage is None
                    else "passage_sha256 doesn't match the pinned passage")
        return "passage_hash_mismatch", (f"{label}: {why_hash}; the ledger was edited by hand or the hash is "
                                         "stale, so re-pin it")
    if recorded_source is None:
        return "ok", f"{label}: passage found; no source_text_sha256 recorded, so source drift isn't checked"
    if recorded_source != sha256_str(text):
        return "source_changed", (f"{label}: the saved source changed since the pin (source_text_sha256 differs), "
                                  "but the passage is still found; re-read the context before keeping the claim")
    return "ok", f"{label}: passage found and both hashes match"


def _articles(ledger: dict, project_root: Path, article: Path | None) -> tuple[Path, ...]:
    """The resolved article paths no snapshot may be: the ledger's `source_file` and the article being checked."""
    out = []
    for p in ((Path(project_root) / ledger["source_file"]) if safe_relative(ledger.get("source_file")) else None,
              article):
        if p is not None:
            try:
                out.append(config.resolve_path(Path(p)))
            except (OSError, ValueError, RuntimeError):
                pass
    return tuple(out)


def _sources_dir(project_root: Path, sources_dir: str | None) -> str:
    """The given sources_dir, else `[claims] sources_dir` from the project config (ConfigError when malformed)."""
    return config.claims_settings(Path(project_root))["sources_dir"] if sources_dir is None else sources_dir


def _rechecked(ledger: object, project_root: Path, sources_dir: str, article: Path | None = None):
    """Yield `(claim, kind, result, detail)` per pinned passage. `kind` is "primary", "additional" or
    "additional_url" (an additional passage evidenced on another page). Never raises."""
    if not isinstance(ledger, dict) or not isinstance(ledger.get("claims"), list):
        return
    articles = _articles(ledger, project_root, article)
    cache: dict[str, tuple[str | None, str, str]] = {}

    def snapshot_for(rel: object) -> tuple[str | None, str, str]:
        key = repr(rel)
        if key not in cache:
            cache[key] = _read_snapshot(project_root, rel, sources_dir, articles)
        return cache[key]

    for claim in ledger["claims"]:
        if not isinstance(claim, dict) or "binding" not in claim:
            continue
        binding = claim["binding"]
        if not isinstance(binding, dict):
            yield claim, "primary", "unchecked", "binding isn't a table, so there's no pinned passage to recheck"
            continue
        extras = binding.get("additional_passages")
        extras = extras if isinstance(extras, list) else []
        if "passage" not in binding and not extras:
            continue
        snap = snapshot_for(binding["source_snapshot"]) if "source_snapshot" in binding else None
        if "passage" in binding:
            yield (claim, "primary", *_check_passage(binding["passage"], binding.get("passage_sha256"),
                                                     binding.get("source_text_sha256"), snap, "passage"))
        for i, item in enumerate(extras, start=1):
            label = f"additional passage {i}"
            if not isinstance(item, dict):
                yield claim, "additional", "unchecked", f"{label}: not a table"
            elif item.get("source_url"):
                yield claim, "additional_url", "unchecked", (f"{label}: evidenced on another page (source_url), "
                                                             "and the ledger names no saved source for it")
            else:
                yield (claim, "additional", *_check_passage(item.get("passage"), item.get("passage_sha256"),
                                                            item.get("source_text_sha256"), snap, label))


def _claim_id(claim: dict) -> str | None:
    return claim.get("claim_id") if isinstance(claim.get("claim_id"), str) else None


def recheck(ledger: dict, project_root: Path, *, sources_dir: str | None = None) -> list[dict]:
    """Recheck every pinned passage against its saved source, offline.

    Returns one `{"claim_id", "result", "detail"}` per pinned passage (the primary passage first, then each
    `additional_passages` item, which the detail labels). `result` is one of `ok`, `passage_missing`,
    `passage_hash_mismatch`, `source_changed`, `snapshot_missing`, `snapshot_outside_sources` or `unchecked`.
    `snapshot_outside_sources`: the snapshot resolves (symlinks followed) outside `sources_dir`, or is the ledger's
    `source_file`, so it isn't read. `sources_dir` defaults to `[claims] sources_dir` in the project config.
    Additional passages are rechecked against the primary `binding.source_snapshot` (the schema gives them no
    snapshot of their own), so the same rule applies to them; one with a `source_url` is evidenced on another page,
    so it's `unchecked`. Claims with no pinned passage are skipped. Bad ledger input never raises: it becomes a
    result with a detail, or is skipped when there's nothing to check. A malformed `[claims]` config raises
    config.ConfigError.
    """
    folder = _sources_dir(project_root, sources_dir)
    return [{"claim_id": _claim_id(claim), "result": result, "detail": detail}
            for claim, _kind, result, detail in _rechecked(ledger, project_root, folder)]


_FAILED = ("passage_missing", "passage_hash_mismatch", "snapshot_missing", "snapshot_outside_sources")


def status_reasons(ledger: dict, project_root: Path, *, sources_dir: str | None = None,
                   article: Path | None = None) -> tuple[list[str], list[str]]:
    """(incomplete, notes) about the pins of every claim that isn't `removed`, for `claims status`.

    Incomplete: a `verified` claim with no `binding.passage`; a passage that's missing from its saved source, whose
    hash doesn't match, or whose snapshot can't be read; a snapshot outside `sources_dir` or that is the article
    (the ledger's `source_file`, or `article` when given): `snapshot_outside_sources`; a primary passage with no
    snapshot to recheck it against (`unchecked`). Notes, which never stop a PASS: `source_changed` (the passage is
    still there verbatim) and an additional passage evidenced on another page (`source_url`). A malformed
    `[claims]` config raises config.ConfigError."""
    folder = _sources_dir(project_root, sources_dir)
    items = ledger.get("claims") if isinstance(ledger, dict) else None
    live = [c for c in (items if isinstance(items, list) else []) if isinstance(c, dict)
            and c.get("status") != "removed"]
    incomplete: list[str] = []
    notes: list[str] = []
    for c in live:
        binding = c.get("binding")
        if c.get("status") == "verified" and not (isinstance(binding, dict) and "passage" in binding):
            incomplete.append(f"{_claim_id(c) or '-'} is verified but has no pinned passage (binding.passage): "
                              "pin its supporting passage with `claims pin`")
    source_file = ledger.get("source_file") if isinstance(ledger, dict) else None
    for claim, kind, result, detail in _rechecked({"claims": live, "source_file": source_file}, project_root, folder,
                                                  article):
        line = f"{_claim_id(claim) or '-'} {result}: {detail}"
        if result == "source_changed" or kind == "additional_url":
            notes.append(f"note: {line}")
        elif result in _FAILED or result == "unchecked":
            incomplete.append(f"pin {line}")
    return incomplete, notes
