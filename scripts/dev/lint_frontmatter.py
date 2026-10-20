"""Lint skill and agent frontmatter: required keys, description caps, portable names and fields, SKILL.md length."""
from __future__ import annotations

import re
import sys
from pathlib import Path

DESC_CAP = 1536  # description + when_to_use, per Claude Code skills docs
PORTABLE_DESC_CAP = 1024  # description alone, per the Agent Skills spec (agentskills.io)
MAX_SKILL_LINES = 500
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME = 64

# Fields the Agent Skills spec allows. Every other tool reads only these.
PORTABLE_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Claude Code extras: allowed, but stripped for other tools, so nothing a skill needs may live here.
CLAUDE_ONLY_FIELDS = {
    "when_to_use", "disable-model-invocation", "user-invocable", "argument-hint",
    "paths", "context", "agent", "model", "effort", "hooks", "shell",
}


BLOCK_INDICATOR = re.compile(r"^[|>][1-9]?[+-]?[1-9]?$")


def parse_frontmatter(text: str) -> dict[str, str]:
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    key: str | None = None
    block: list[str] = []
    is_block = False

    def flush() -> None:
        nonlocal key, block
        if key is not None:
            out[key] = ("\n" if is_block else " ").join(block).strip()
        key, block = None, []

    for line in lines[1:]:
        if line.strip() == "---":
            break
        if key is not None and (line.startswith((" ", "\t")) or line.strip() == ""):
            if is_block or line.strip():
                block.append(line.strip())
            continue
        flush()
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            key = k
            if BLOCK_INDICATOR.match(v):
                is_block, block = True, []
            else:
                is_block, block = False, [v.strip('"').strip("'")]
    flush()
    return out


PLAIN_START_BAD = ("@", "`", "%", "&", "*", "!", "?", ",", "- ", "#")


def strict_yaml_problems(text: str) -> list[tuple[str, str]]:
    """Return (key, reason) for unquoted plain scalars that strict YAML parsers reject."""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    out: list[tuple[str, str]] = []
    key: str | None = None
    plain = False  # inside a multi-line plain scalar

    def judge(k: str, v: str) -> None:
        if ": " in v:
            out.append((k, "contains ': ' (colon-space) in an unquoted value; double-quote the value"))
        elif v.endswith(":"):
            out.append((k, "ends with ':' in an unquoted value; double-quote the value"))
        elif " #" in v:
            out.append((k, "contains ' #' in an unquoted value (starts a comment); double-quote the value"))

    for line in lines[1:]:
        if line.strip() == "---":
            break
        if key is not None and line.startswith((" ", "\t")):
            if plain and line.strip():
                judge(key, line.strip())
            continue
        key, plain = None, False
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            key = k
            if not v or BLOCK_INDICATOR.match(v) or v[0] in "\"'[{":
                continue
            plain = True
            if v.startswith(PLAIN_START_BAD):
                out.append((k, f"unquoted value starts with '{v[0]}', which strict YAML rejects; double-quote the value"))
            judge(k, v)
    return out


def _check_yaml(path: Path, text: str, errors: list[str]) -> None:
    for k, why in strict_yaml_problems(text):
        errors.append(f"{path}: frontmatter key '{k}' {why}")


def _check(path: Path, fm: dict[str, str], errors: list[str]) -> None:
    for req in ("name", "description"):
        if not fm.get(req):
            errors.append(f"{path}: missing '{req}'")
    total = len(fm.get("description", "")) + len(fm.get("when_to_use", ""))
    if total > DESC_CAP:
        errors.append(f"{path}: description + when_to_use = {total} chars (cap {DESC_CAP})")


def _check_skill(path: Path, folder: str, fm: dict[str, str], errors: list[str]) -> None:
    _check(path, fm, errors)
    name = fm.get("name", "")
    if name:
        if len(name) > MAX_NAME or not NAME_RE.match(name):
            errors.append(f"{path}: name '{name}' must be 1-{MAX_NAME} lowercase letters, digits and single hyphens")
        if name != folder:
            errors.append(f"{path}: name '{name}' must match its folder '{folder}'")
    desc = len(fm.get("description", ""))
    if desc > PORTABLE_DESC_CAP:
        errors.append(f"{path}: description = {desc} chars (portable cap {PORTABLE_DESC_CAP})")
    for key in fm:
        if key not in PORTABLE_FIELDS | CLAUDE_ONLY_FIELDS:
            errors.append(f"{path}: unknown frontmatter field '{key}'")


def main(root: str) -> int:
    base = Path(root)
    errors: list[str] = []
    skills = base / "skills"
    if skills.is_dir():
        for d in sorted(p for p in skills.iterdir() if p.is_dir()):
            f = d / "SKILL.md"
            if not f.exists():
                errors.append(f"{d}: no SKILL.md")
                continue
            text = f.read_text(encoding="utf-8")
            n = len(text.splitlines())
            if n > MAX_SKILL_LINES:
                errors.append(f"{f}: {n} lines (max {MAX_SKILL_LINES})")
            _check_yaml(f, text, errors)
            _check_skill(f, d.name, parse_frontmatter(text), errors)
    agents = base / "agents"
    if agents.is_dir():
        for f in sorted(agents.rglob("*.md")):
            text = f.read_text(encoding="utf-8")
            _check_yaml(f, text, errors)
            fm = parse_frontmatter(text)
            _check(f, fm, errors)
            if "memory" in fm:
                errors.append(f"{f}: agents must not set 'memory' (judges stay memoryless)")
    styles = base / "output-styles"
    if styles.is_dir():
        for f in sorted(styles.rglob("*.md")):
            _check_yaml(f, f.read_text(encoding="utf-8"), errors)
    for e in errors:
        print(e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
