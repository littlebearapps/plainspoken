"""Export each skill with Claude-only frontmatter stripped, so other tools' validators can check it.

CI runs the Agent Skills reference validator (`agentskills validate`) on the output.
This is also the first piece of the later multi-tool build.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from scripts.dev.lint_frontmatter import CLAUDE_ONLY_FIELDS


def _strip(text: str) -> str:
    lines = text.lstrip("\ufeff").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    out = [lines[0]]
    skipping = False
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "".join(out + lines[i:])
        top_level = not line.startswith((" ", "\t")) and line.strip() != ""
        if top_level:
            key = line.split(":", 1)[0].strip()
            skipping = key in CLAUDE_ONLY_FIELDS
        if not skipping:
            out.append(line)
    return text  # unterminated frontmatter: leave untouched; the validator reports it


def export(root: Path, out: Path) -> list[Path]:
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    skills = root / "skills"
    if not skills.is_dir():
        return exported
    for src in sorted(p for p in skills.iterdir() if p.is_dir() and (p / "SKILL.md").exists()):
        dst = out / src.name
        shutil.copytree(src, dst)
        skill = dst / "SKILL.md"
        skill.write_text(_strip(skill.read_text(encoding="utf-8")), encoding="utf-8")
        exported.append(dst)
    return exported


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: portable_export.py <plugin-root> <out-dir>")
    for d in export(Path(sys.argv[1]), Path(sys.argv[2])):
        print(d)
