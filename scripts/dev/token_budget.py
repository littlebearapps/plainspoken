"""Fail when plainspoken's always-on context cost goes over budget.

`claude plugin details` reports skill and agent listing cost but counts hooks as free, so
measured hook output is passed in with --hook-tokens.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from scripts.dev.lint_frontmatter import parse_frontmatter

BUDGET = 500
_COST = re.compile(r"Always-on:\s*~?([\d.,]+)(k?)\s*tok")  # `~1,025` past 1,000


def always_on_tokens(details: str) -> int:
    m = _COST.search(details)
    if not m:
        raise ValueError("no 'Always-on' line in `claude plugin details` output")
    n = float(m.group(1).replace(",", ""))
    return round(n * 1000) if m.group(2) else round(n)


_ROW = re.compile(r"(?m)^\s+([a-z0-9][a-z0-9-]*)\s+~?([\d.,]+)(k?)\s+(?:~|<)")


def component_costs(details: str) -> dict[str, int]:
    """Per-component always-on cost from the `Per-component` table of `claude plugin details`. ValueError when the
    table is missing or no row parses: the manual-only costs couldn't be left out, so the total can't be trusted."""
    if "Per-component" not in details:
        raise ValueError("no 'Per-component' table in `claude plugin details` output")
    table = details.split("Per-component", 1)[1]
    costs = {m.group(1): round(float(m.group(2).replace(",", "")) * (1000 if m.group(3) else 1))
             for m in _ROW.finditer(table)}
    if not costs:
        raise ValueError("can't read any row of the 'Per-component' table in `claude plugin details` output")
    return costs


def manual_only(root: Path) -> set[str]:
    """Skills with disable-model-invocation: true. Their descriptions aren't in context (Claude Code skills docs,
    invocation table, checked 2026-10-12), but `claude plugin details` still counts them."""
    out = set()
    for f in sorted(Path(root).glob("skills/*/SKILL.md")):
        if parse_frontmatter(f.read_text(encoding="utf-8")).get("disable-model-invocation") == "true":
            out.add(f.parent.name)
    return out


def counted(details: str, root: Path) -> tuple[int, dict[str, int]]:
    costs = component_costs(details)
    missing = sorted(manual_only(root) - set(costs))
    if missing:
        raise ValueError(f"manual-only skill(s) {', '.join(missing)} not in the 'Per-component' table")
    left_out = {name: costs[name] for name in sorted(manual_only(root))}
    return always_on_tokens(details) - sum(left_out.values()), left_out


def verdict(*, always_on: int, hook_tokens: int, budget: int, left_out: dict[str, int] | None = None) -> int:
    total = always_on + hook_tokens
    note = ""
    if left_out:
        note = " (manual-only left out: " + ", ".join(f"{n} {t}" for n, t in left_out.items()) + ")"
    print(f"always-on {always_on}{note} + hooks {hook_tokens} = {total} tokens (budget {budget})")
    return 0 if total <= budget else 1


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--hook-tokens", type=int, default=0)
    ap.add_argument("--budget", type=int, default=BUDGET)
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"plainspoken: token-budget: {args.root} is not a folder", file=sys.stderr)
        return 2
    try:
        details = subprocess.run(
            ["claude", "--plugin-dir", args.root, "plugin", "details", "plainspoken"],
            capture_output=True, text=True, check=True,
        ).stdout
        always_on, left_out = counted(details, root)
    except (OSError, subprocess.CalledProcessError, ValueError) as e:
        said = [ln.strip() for ln in (getattr(e, "stderr", None) or "").splitlines() if ln.strip()]
        if isinstance(e, subprocess.CalledProcessError) and said:  # claude's own reason, not just its exit code
            reason = f"claude exited {e.returncode}: {said[0]}"
        else:
            reason = (str(e).splitlines() or [type(e).__name__])[0]
        print(f"plainspoken: token-budget: {reason}", file=sys.stderr)
        return 2
    return verdict(always_on=always_on, hook_tokens=args.hook_tokens, budget=args.budget, left_out=left_out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
