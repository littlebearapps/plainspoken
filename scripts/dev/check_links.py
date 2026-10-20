"""Fail on a markdown link that leaves the plugin root or points at a missing file (no outside dependency).

http(s), mailto (in any case) and in-page anchors are fine. `${CLAUDE_PLUGIN_ROOT}/…` resolves from the root.
Anything else must resolve inside the root and exist. A target may hold balanced parentheses, or anything inside <…>.
Links inside fenced or inline code are ignored."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

SKIP_PREFIXES = (".git/", "tests/fixtures/", "evals/results/", ".superpowers/")
SKIP_FILES = ("CHANGELOG.md",)
ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}/"
_FENCE = re.compile(r"(?ms)^(```|~~~).*?^\1[^\n]*$")
_CODE = re.compile(r"`[^`\n]*`")
# A destination is <anything but angle brackets> or a run without spaces whose parentheses balance (two levels, as
# CommonMark allows), then an optional "title", 'title' or (title).
_DEST = r"(?:<([^<>\n]*)>|((?:[^\s()<>]|\((?:[^\s()<>]|\([^\s()<>]*\))*\))+))"
_INLINE = re.compile(r"!?\[[^\]\n]*\]\(\s*" + _DEST + r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\)")
_REFDEF = re.compile(r"(?m)^ {0,3}\[[^\]\n]+\]:\s*(?:<([^<>\n]*)>|(\S+))(?:\s.*)?$")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


@dataclass(frozen=True)
class Bad:
    path: str
    line: int
    target: str
    why: str


def _blank(m: re.Match) -> str:
    return re.sub(r"[^\n]", " ", m.group(0))


def _targets(text: str):
    text = _CODE.sub(_blank, _FENCE.sub(_blank, text))
    for pattern in (_INLINE, _REFDEF):
        for m in pattern.finditer(text):
            yield text.count("\n", 0, m.start()) + 1, m.group(1) if m.group(1) is not None else m.group(2)


def _check(root: Path, f: Path, line: int, target: str) -> Bad | None:
    rel = f.relative_to(root).as_posix()
    if target.lower().startswith(("http://", "https://", "mailto:", "#")):
        return None
    if target.startswith(ROOT_VAR):
        base, target_path = root, target[len(ROOT_VAR):]
    elif target.startswith(("/", "~")) or _SCHEME.match(target):
        return Bad(rel, line, target, "outside the plugin root")
    else:
        base, target_path = f.parent, target
    p = (base / target_path.split("#", 1)[0]).resolve()
    if not p.is_relative_to(root):
        return Bad(rel, line, target, "outside the plugin root")
    if not p.exists():
        return Bad(rel, line, target, "missing")
    return None


def scan(root: Path) -> list[Bad]:
    root = Path(root).resolve()
    out: list[Bad] = []
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root).as_posix()
        if rel.startswith(SKIP_PREFIXES) or rel in SKIP_FILES:
            continue
        text = f.read_text(encoding="utf-8")
        for line, target in _targets(text):
            bad = _check(root, f, line, target)
            if bad:
                out.append(bad)
    return sorted(out, key=lambda b: (b.path, b.line, b.target))


def main(argv: list[str]) -> int:
    root = Path(argv[0] if argv else ".")
    if not root.is_dir():
        print(f"plainspoken: check-links: no such folder {root}", file=sys.stderr)
        return 2
    try:
        bad = scan(root)
    except (OSError, UnicodeDecodeError) as e:
        print(f"plainspoken: check-links: can't read a file: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    for b in bad:
        print(f"{b.path}:{b.line}: link '{b.target}': {b.why}")
    print(f"check-links: {len(bad)} bad link(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
