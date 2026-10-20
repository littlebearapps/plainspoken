"""Ablation table (Phase 6): the engine's grades of `draft_runs.py`'s drafts, one row per arm and model.

    python3 scripts/dev/ablation_table.py --drafts DIR --briefs evals/briefs [--profile P] [--content-type T]

Each draft in `<drafts>/<arm>/<model id>/` is graded by `rewrite.grade_many` against the brief with the same stem (a
number the brief has isn't new). Columns: drafts, mean words, BLOCK-bearing drafts, drafts over the em-dash cap,
drafts with a number the brief doesn't have. Arms come in the fixed order none, plugin, plugin+style, plugin+brief,
plugin+banlist; a folder that isn't an arm is left out. No model is called. Counts only: no composite score.
Exit codes: 0 table printed · 2 a missing folder, a draft with no brief, or a bad profile.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "lib") not in sys.path:
    sys.path.insert(0, str(REPO / "lib"))

from plainspoken import config, rewrite  # noqa: E402
from plainspoken.registry import load_config  # noqa: E402

ARM_ORDER = ("none", "plugin", "plugin+style", "plugin+brief", "plugin+banlist")  # draft_runs.ARM_ORDER
HEADER = ("Arm", "Model", "Drafts", "Mean words", "BLOCK-bearing drafts", "Em dash over cap",
          "Drafts with new numbers")


def rows(drafts: Path, briefs: Path, profile, content_type: str = "article") -> list[list[str]]:
    """One row per (arm, model id) folder that holds drafts, arms in the fixed order, model ids sorted."""
    cfg = load_config()
    out = []
    for arm in ARM_ORDER:
        folder = Path(drafts) / arm
        if not folder.is_dir():
            continue
        for model in sorted(p for p in folder.iterdir() if p.is_dir()):
            grades = rewrite.grade_many(model, briefs, profile, content_type, cfg)
            if not grades:
                continue
            n = len(grades)
            out.append([arm, model.name, str(n), f"{sum(g['words'] for g in grades) / n:.1f}",
                        str(sum(1 for g in grades if g["blocks"])),
                        str(sum(1 for g in grades if g["em_dashes"] > g["em_dash_cap"])),
                        str(sum(1 for g in grades if g["new_numbers"]))])
    return out


def render(table: list[list[str]]) -> str:
    lines = ["| " + " | ".join(HEADER) + " |", "|" + "|".join(["---"] * 2 + ["---:"] * 5) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in table]
    return "\n".join(lines)


def _fail(reason: str) -> int:
    print(f"ablation_table: {reason}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ablation_table.py", description="Tabulate engine grades per ablation arm.")
    p.add_argument("--drafts", type=Path, required=True, help="the --out folder of draft_runs.py")
    p.add_argument("--briefs", type=Path, default=REPO / "evals" / "briefs", help="the briefs the drafts came from")
    p.add_argument("--profile", help="the voice profile (default: the project's, else the plugin default)")
    p.add_argument("--content-type", default="article", help="the content type for the caps (default: article)")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    for name, folder in (("--drafts", args.drafts), ("--briefs", args.briefs)):
        if not folder.is_dir():
            return _fail(f"{name} {folder}: no such folder")
    try:
        prof, _ = config.resolve_profile_ex(args.profile, config.project_root(Path.cwd()), os.environ, "")
        table = rows(args.drafts, args.briefs, prof, args.content_type)
    except (ValueError, OSError) as e:  # a bad profile or content type, a draft with no brief, an unreadable file
        return _fail((str(e).strip().splitlines() or [type(e).__name__])[0])
    if not table:
        return _fail(f"{args.drafts}: no drafts under any arm folder ({', '.join(ARM_ORDER)})")
    print(f"Profile {prof.name} · content type {args.content_type} · graded against {args.briefs}\n")
    print(render(table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
