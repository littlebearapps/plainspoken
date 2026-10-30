"""Small helpers more than one module needs, kept in one place so their rules can't drift apart. Stdlib only, and
safe to import from the hooks on any python3."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from pathlib import Path

__all__ = ["clip", "graphemes", "is_absolute", "now_iso", "path_key", "safe_relative", "write_safe"]

_DRIVE = re.compile(r"^[A-Za-z]:")


def path_key(path: Path, root: Path) -> str:
    """`<stem>-<8 hex>`, the hex from the file's project-relative POSIX path (its absolute path when it's outside
    `root`): two `index.md` files in different folders get different keys. The report files and the claims ledger
    are both named with it (docs/report-contract.md)."""
    resolved = Path(path).resolve()
    try:
        rel = resolved.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        rel = resolved.as_posix()
    return f"{resolved.stem}-{hashlib.sha256(rel.encode('utf-8')).hexdigest()[:8]}"


def safe_relative(value: object) -> bool:
    """A project-relative path, judged on the text alone (the one rule for every path a config or ledger names):
    non-empty, no NUL character, not absolute (POSIX or Windows, or drive-relative like `C:x`) and no `..` part
    (split on `/` and `\\`). Where the path leads once links are followed is `claims_tools.project_relative`'s job."""
    if not isinstance(value, str) or not value.strip() or "\x00" in value or is_absolute(value):
        return False
    return ".." not in re.split(r"[\\/]", value)


def is_absolute(value: str) -> bool:
    """A POSIX or Windows absolute path, or a drive-relative one (`C:x`), judged on the text alone."""
    return value.startswith(("/", "\\")) or _DRIVE.match(value) is not None


def now_iso() -> str:
    """Local time now, ISO 8601 with its UTC offset, to the second."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clip(text: str, limit: int) -> str:
    """`text` cut to `limit` characters, ending in `…` when it was cut."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _extends(ch: str) -> bool:
    """Joins the character before it: a combining or enclosing mark (variation selectors are marks too), ZWNJ or ZWJ,
    a skin-tone modifier, or a tag character (the letters of a subdivision flag)."""
    cp = ord(ch)
    return (unicodedata.category(ch) in ("Mn", "Mc", "Me") or ch in "\u200c\u200d" or 0x1F3FB <= cp <= 0x1F3FF
            or 0xE0020 <= cp <= 0xE007F)


def _pictograph(ch: str) -> bool:
    cp = ord(ch)
    return unicodedata.category(ch) == "So" or 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF


def graphemes(text: str) -> int:
    """How many characters a reader sees in `text`: a stdlib approximation of Unicode's extended grapheme clusters
    (UAX #29). Marks, variation selectors, skin tones and tags join the character before; a ZWJ joins two
    pictographs; regional indicators pair into one flag; CR LF is one. Rarer joins (conjoining Hangul jamo, prepended
    marks, Indic conjuncts) count apart, so the count only ever errs high: safe against a platform's limit."""
    count, prev, pict, ri_open = 0, "", False, False
    for ch in text:
        ri = 0x1F1E6 <= ord(ch) <= 0x1F1FF
        if not count or prev in "\r\n" or unicodedata.category(prev) == "Cc":
            join = prev == "\r" and ch == "\n"
        elif unicodedata.category(ch) == "Cc":
            join = False
        else:
            join = _extends(ch) or (prev == "\u200d" and pict and _pictograph(ch)) or (ri and ri_open)
        if not join:
            count += 1
            pict = _pictograph(ch)
        ri_open = ri and not join
        prev = ch
    return count


def write_safe(text: str, stream) -> None:
    """Write `text` to `stream`, replacing any character the stream's encoding can't take (an arrow, a path) with
    `?`, so a console that can't print UTF-8 (ascii, cp1252) never turns output into a crash."""
    encoding = getattr(stream, "encoding", None) or "utf-8"
    stream.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    stream.flush()
