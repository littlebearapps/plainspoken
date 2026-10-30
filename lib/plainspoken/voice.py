"""Voice-profile helpers for the skills: anchor passages, a summary, and rhythm measured from samples.

Skills call these through the CLI (`anchors`, `voice-stats`, `profile`); they never read profile TOML themselves."""
from __future__ import annotations

import statistics
from collections import Counter
from pathlib import Path

from plainspoken import config, metrics
from plainspoken.doc import parse
from plainspoken.profile import Anchor, Profile, default

MIN_WORDS = 300
MAX_ANCHOR_BYTES = 256 * 1024  # an anchor is a passage, not a book; also bounds a read of something odd
LONG, SHORT = 25, 8


class VoiceError(ValueError):
    """An anchor or sample that can't be used. The message names it."""


def _read_anchor_file(a: Anchor) -> str:
    """The anchor file's text. Refuses (VoiceError) anything but a regular file inside the profile's project, up to
    MAX_ANCHOR_BYTES: an untrusted profile must not pull ~/.ssh or a FIFO into the model's context. The project is
    the nearest folder from the profile up holding .git or .plainspoken/config.toml, else the profile's own folder;
    CLAUDE_PROJECT_DIR is ignored, so a session started in the home folder can't widen it."""
    def refuse(why: str) -> VoiceError:
        return VoiceError(f"anchor {a.id!r}: can't read {a.path} ({why})")

    base = Path(a.base)
    try:
        root = config.project_root(base, env={})
        f = (base / a.path).resolve()  # follows symlinks, so a link out of the project is caught below
        if not f.is_relative_to(root):
            raise refuse(f"outside the project {root}")
        if not f.is_file():  # directories, FIFOs and devices: never opened
            raise refuse("not a regular file")
        with f.open("rb") as fh:
            data = fh.read(MAX_ANCHOR_BYTES + 1)
        if len(data) > MAX_ANCHOR_BYTES:
            raise refuse(f"too big: over {MAX_ANCHOR_BYTES // 1024} KB")
        return data.decode("utf-8")
    except VoiceError:
        raise
    except (OSError, ValueError) as e:  # ValueError: a NUL byte in the path, or text that isn't UTF-8
        raise refuse(type(e).__name__) from None


def anchor_text(a: Anchor) -> str:
    if a.text:
        return a.text.strip()
    lines = _read_anchor_file(a).splitlines()
    if a.lines:
        first, last = a.lines
        if last > len(lines):
            raise VoiceError(f"anchor {a.id!r}: lines {first}-{last} but {a.path} has {len(lines)}")
        lines = lines[first - 1:last]
    return "\n".join(lines).strip()


def anchors_for(p: Profile, tag: str | None, limit: int) -> list[tuple[Anchor, str]]:
    """The first `limit` anchors with `tag` (all anchors when it's None), in profile order. Raises on an unreadable one."""
    picked = [a for a in p.anchors if tag is None or tag in a.tags][:max(limit, 0)]
    return [(a, anchor_text(a)) for a in picked]


def anchors_lenient(p: Profile, tag: str | None, limit: int) -> tuple[list[tuple[Anchor, str]], list[str]]:
    """Like anchors_for, but an unreadable anchor is skipped (with a message) and the next one fills its place."""
    found: list[tuple[Anchor, str]] = []
    skipped: list[str] = []
    for a in (a for a in p.anchors if tag is None or tag in a.tags):
        if len(found) >= max(limit, 0):
            break
        try:
            found.append((a, anchor_text(a)))
        except VoiceError as e:
            skipped.append(str(e))
    return found, skipped


def summary_lines(p: Profile) -> list[str]:
    """The two voice lines `profile` adds to its summary."""
    tags = Counter(t for a in p.anchors for t in a.tags)
    tag_text = ", ".join(f"{t} {n}" for t, n in sorted(tags.items()))
    reader = p.reader_persona or "not set"
    blends = ", ".join(f"{k}={v}" for k, v in sorted(p.voice.get("blends", {}).items())) or "none"
    writer = p.voice.get("identity", {}).get("writer") or "not set"
    return [
        f"writer: {writer} (pronoun {p.pronoun}) · reader: {reader} (Year {p.comprehension_floor} floor)",
        f"registers: {', '.join(r.name for r in p.registers) or 'none'} · blends: {blends} · "
        f"anchors: {len(p.anchors)}{f' ({tag_text})' if tag_text else ''}",
    ]


def voice_lines(p: Profile, content_type: str | None = None, locale: str | None = None) -> list[str]:
    """Everything the skills draft and check from, as plain lines (`profile --voice`). `locale` is the resolved
    spelling locale with its source, e.g. `en-US (plugin option)`; None leaves the line out."""
    v = p.voice
    ident, voice_t, rhythm = v.get("identity", {}), v.get("voice", {}), v.get("rhythm", {})
    reader, lex, avoid = v.get("reader", {}), v.get("lexicon", {}), v.get("avoid", {})
    glossary = reader.get("glossary")
    glossary_path = str((Path(p.source).parent / glossary).resolve()) if glossary else "none"
    notes = voice_t.get("tone_notes", {})
    tone = ", ".join(f"{k} {val}" + (f" ({notes[k]})" if k in notes else "")
                     for k, val in voice_t.get("tone", {}).items()) or "not set"
    kinds = [content_type] if content_type else list(v.get("blends", {}) | v.get("formatting", {}))
    out = [
        f"voice profile: {p.name}",
        *([f"locale: {locale}"] if locale else []),
        f"writer: {ident.get('writer') or 'not set'} (pronoun {p.pronoun})",
        f"reader: {p.reader_persona or 'not set'} (Year {p.comprehension_floor} floor) · glossary: {glossary_path}",
        "principles:", *[f"- {x}" for x in voice_t.get("principles", [])],
        f"opinion pattern: {voice_t.get('opinion_pattern', 'not set')}",
        f"humour: {voice_t.get('humour', 'not set')} · emoji max {voice_t.get('emoji_max', 'not set')} · "
        f"exclamation max {voice_t.get('exclamation_max', 'not set')}",
        f"tone: {tone}",
        "rhythm: " + (" · ".join(f"{k.replace('_', ' ')} {val}" for k, val in rhythm.items()) or "not set"),
        "habits: " + (" · ".join(f"{k} " + ", ".join(f'"{x}"' for x in lex[k])
                                 for k in ("starters", "fillers", "closers") if lex.get(k)) or "none"),
    ]
    for kind in kinds:
        if kind in v.get("blends", {}):
            out.append(f"blend ({kind}): {v['blends'][kind]}")
        if kind in v.get("formatting", {}):
            out.append(f"formatting ({kind}): {v['formatting'][kind]}")
    out += ["avoid moves:", *[f"- {x}" for x in avoid.get("moves", [])],
            f"avoid topics: {'; '.join(avoid.get('topics', [])) or 'none'}"]  # a topic may hold a comma
    return out


def stats(paths: list[Path]) -> dict[str, float | int]:
    """Sentence rhythm measured across sample files, in the shape of a profile's [rhythm] table."""
    lengths: list[int] = []
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise VoiceError(f"can't read sample {path} ({type(e).__name__})") from None
        doc = parse(text, path=str(path), profile=default())
        lengths += [len(s.words) for s in doc.all_sentences() if s.words]
    words = sum(lengths)
    if words < MIN_WORDS:
        raise VoiceError(f"too little text to measure: {words} words (need {MIN_WORDS})")
    return {
        "files": len(paths),
        "words": words,
        "sentence_mean": round(statistics.mean(lengths), 1),
        "sentence_sd": round(statistics.pstdev(lengths), 1),
        "burstiness": round(metrics.burstiness(lengths), 2),
        "long_share": round(sum(n >= LONG for n in lengths) / len(lengths), 2),
        "short_share": round(sum(n <= SHORT for n in lengths) / len(lengths), 2),
    }


def stats_toml(st: dict[str, float | int]) -> str:
    return "\n".join([
        "[rhythm]",
        f"sentence_mean = {st['sentence_mean']}",
        f"sentence_sd = {st['sentence_sd']}",
        f"burstiness = {st['burstiness']}",
        f"long_share = {st['long_share']}  # sentences of {LONG}+ words",
        f"short_share = {st['short_share']}  # sentences of {SHORT} words or fewer",
        f"# measured from {st['files']} file(s), {st['words']} words",
    ]) + "\n"
