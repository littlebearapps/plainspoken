"""Check that every engine command the docs and skills show still exists.

Scans README.md, guides/, hosts/ and skills/*/SKILL.md for `run.py <command> …` and `RUN <command> …`, then asks the
CLI itself (`run.py <command> [<subcommand>] --help`) whether the command, its subcommand and every `--flag` written
after it are real. Free: no model is called. Exit 1 lists each stale command with the file and line it's on.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DOCS = ("README.md", "guides/*.md", "hosts/*.md", "skills/*/SKILL.md")
_CALL = re.compile(r"(?:\brun\.py|\bRUN)\s+([a-z][a-z-]*)((?:\s+(?:[a-z][a-z-]*|--[a-z][a-z-]*|-))*)")
_FLAG = re.compile(r"--[a-z][a-z-]*")
_CHOICES = re.compile(r"\{([a-z][a-z0-9,-]*)\}")


def _help(root: Path, args: list[str], cache: dict) -> str | None:
    key = tuple(args)
    if key not in cache:
        done = subprocess.run([sys.executable, str(root / "lib" / "run.py"), *args, "--help"], capture_output=True,
                              text=True, cwd=root)
        cache[key] = done.stdout if done.returncode == 0 else None
    return cache[key]


def calls(root: Path) -> list[tuple[Path, int, str, list[str]]]:
    """(file, line, command, the words and flags after it) for every engine call written in the docs."""
    out = []
    for pattern in DOCS:
        for path in sorted(root.glob(pattern)):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for m in _CALL.finditer(line):
                    out.append((path, n, m.group(1), m.group(2).split()))
    return out


def problems(root: Path) -> list[str]:
    cache: dict = {}
    top = _help(root, [], cache) or ""
    commands = set(next(iter(_CHOICES.findall(top)), "").split(","))
    found = []
    for path, n, cmd, rest in calls(root):
        where = f"{path.relative_to(root)}:{n}"
        if cmd not in commands:
            found.append(f"{where}: `{cmd}` isn't a run.py command")
            continue
        args = [cmd]
        text = _help(root, args, cache) or ""
        words = [w for w in rest if not w.startswith("-")]
        stale = False
        while words:  # walk down nested subcommands (`eval blind build`) while the usage line offers a choice
            subs = _CHOICES.findall(text.split("\n\n", 1)[0])
            if not subs:
                break
            if words[0] not in subs[0].split(","):
                found.append(f"{where}: `{' '.join(args)} {words[0]}` isn't a `{' '.join(args)}` subcommand")
                stale = True
                break
            args.append(words.pop(0))
            text = _help(root, args, cache) or ""
        if stale:
            continue
        for flag in (w for w in rest if _FLAG.fullmatch(w)):
            if flag not in text:
                found.append(f"{where}: `{' '.join(args)}` has no {flag}")
    return found


def main(argv: list[str]) -> int:
    root = Path(argv[0] if argv else ".").resolve()
    found = problems(root)
    for line in found:
        print(line)
    print(f"check-doc-commands: {len(calls(root))} call(s), {len(found)} stale")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
