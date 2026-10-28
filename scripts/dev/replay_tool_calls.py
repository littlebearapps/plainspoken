"""Replay local transcripts through the tool-call check's detector (#124): counts only, nothing written.

A maintainer script, not a user command: transcript formats aren't a stable interface. It reads Claude Code
transcripts (`~/.claude/projects/**/*.jsonl`, `tool_use` blocks) and Codex sessions (`~/.codex/sessions/**/*.jsonl`,
`function_call` items) at run time, puts every tool call through the shipped name filter, the argument walk and the
prose detector with the settings given, and prints counts. It never prints or stores a tool's arguments, a tool or
server name, or any text from a transcript. `--lint` also lints each candidate with the default profile and counts
findings by word band.

    python3 -m scripts.dev.replay_tool_calls                      # both default folders
    python3 -m scripts.dev.replay_tool_calls --min-words 40 --lint --json

Run it before a release and after a change to the shipped lists (`data/tool-call.toml`).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
from plainspoken import ledger, toolcall  # noqa: E402


def calls(obj: object) -> Iterator[tuple[str, dict]]:
    """(tool name, arguments) for every tool call found anywhere in one transcript line."""
    if isinstance(obj, dict):
        kind = obj.get("type")
        if kind == "tool_use" and isinstance(obj.get("name"), str) and isinstance(obj.get("input"), dict):
            yield obj["name"], obj["input"]
            return
        if kind == "function_call" and isinstance(obj.get("name"), str):
            args = obj.get("arguments")
            try:
                args = json.loads(args) if isinstance(args, str) else args
            except ValueError:
                args = None
            if isinstance(args, dict):
                yield obj["name"], args
            return
        for v in obj.values():
            yield from calls(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from calls(v)


def files(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.jsonl")) if folder.is_dir() else []


def replay(sources: list[tuple[str, Path]], settings: dict, lint: bool = False) -> dict:
    """The counts for every transcript under each `(host, folder)`."""
    out = {"files": 0, "calls": 0, "decisions": Counter(), "outcomes": Counter(), "candidates_by_band": Counter(),
           "findings_by_band": Counter(), "block_by_band": Counter()}
    profile = cfg = None
    if lint:
        from plainspoken import textlint
        from plainspoken.profile import load
        from plainspoken.registry import load_config
        profile, cfg = load("default"), load_config()
    for host, folder in sources:
        for path in files(folder):
            out["files"] += 1
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for raw in lines:
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                for name, args in calls(obj):
                    out["calls"] += 1
                    decision = toolcall.name_decision(name, host, settings) or "checked"
                    out["decisions"][decision] += 1
                    if decision != "checked":
                        continue
                    for field in toolcall.walk(args, settings["skip_fields"], settings["min_words"]):
                        out["outcomes"][field.outcome.split(":")[0] if field.outcome.startswith("not-prose")
                                        else field.outcome] += 1
                        if field.outcome != "candidate":
                            continue
                        band = ledger.word_bucket(field.words)
                        out["candidates_by_band"][band] += 1
                        if lint:
                            found = textlint.lint_text(field.text, profile, cfg=cfg)
                            n = textlint.counts(found)
                            out["findings_by_band"][band] += any(n.values())
                            out["block_by_band"][band] += bool(n["BLOCK"])
    return {k: dict(v) if isinstance(v, Counter) else v for k, v in out.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--claude-dir", type=Path, default=Path.home() / ".claude" / "projects")
    ap.add_argument("--codex-dir", type=Path, default=Path.home() / ".codex" / "sessions")
    ap.add_argument("--min-words", type=int, default=toolcall.MIN_WORDS)
    ap.add_argument("--include", action="append", default=[], help="a tool glob checked even when the list skips it")
    ap.add_argument("--skip", action="append", default=[], help="a tool glob to skip as well")
    ap.add_argument("--lint", action="store_true", help="lint each candidate (default profile) and count findings")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    settings = {**toolcall.settings_defaults(), "mode": "warn", "min_words": args.min_words,
                "include": args.include, "skip": args.skip}
    out = replay([("claude-code", args.claude_dir), ("codex", args.codex_dir)], settings, lint=args.lint)
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    print(f"{out['files']} transcript files, {out['calls']} tool calls (min_words {args.min_words})")
    for key in ("decisions", "outcomes", "candidates_by_band", "findings_by_band", "block_by_band"):
        if out[key]:
            print(f"  {key}: " + ", ".join(f"{k} {v}" for k, v in sorted(out[key].items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
