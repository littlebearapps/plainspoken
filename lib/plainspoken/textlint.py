"""Lint text that has no file: what the tool-call check (#124) and the chat-reply check (#125) share.

`lint_text` picks the content type the way `check -` does (social under 300 words, else article) and runs
`report.lint_text`; `counts`, `rules` and `noisy` read the result; `summary` turns several lints into one short note,
cut to a number of findings and characters a host will carry without spilling it to a file. It imports the lint
engine (`report`, `registry`), never the command line, so a hook pays for the lint only.
"""
from __future__ import annotations

from plainspoken import report
from plainspoken.profile import Profile

SOCIAL_WORDS = 300  # under this many words, text lints as social (`check -` uses the same number)
SHOWN = ("BLOCK", "WARN")


def content_type_for(text: str) -> str:
    return "social" if len(text.split()) < SOCIAL_WORDS else "article"


def lint_text(text: str, profile: Profile, *, content_type: str | None = None, cfg=None,
              label: str = "<text>") -> dict:
    """The lint of `text` (a newline is added at the end when it has none, as `check -` does)."""
    body = text if text.endswith("\n") else text + "\n"
    return report.lint_text(body, profile, content_type or content_type_for(text), cfg, label=label)


def counts(lint: dict) -> dict[str, int]:
    out = {sev: 0 for sev in SHOWN}
    for f in lint["findings"]:
        if f["severity"] in out:
            out[f["severity"]] += 1
    return out


def noisy(lint: dict) -> bool:
    """Any BLOCK or WARN."""
    return any(counts(lint).values())


def rules(lint: dict) -> list[str]:
    """`r<id>` for each rule with a BLOCK or WARN, once each, BLOCKs first."""
    out: list[str] = []
    for sev in SHOWN:
        for f in lint["findings"]:
            rid = f"r{f['rule']}"
            if f["severity"] == sev and rid not in out:
                out.append(rid)
    return out


def count_text(n: dict[str, int]) -> str:
    return f"{n['BLOCK'] or 'no'} BLOCK, {n['WARN'] or 'no'} WARN"


def summary(lints: list[tuple[str, dict]], max_findings: int = 15, max_chars: int = 2000) -> str:
    """One heading line per `(label, lint)` with its counts, then its BLOCK and WARN findings (rule, line, message),
    at most `max_findings` in all and `max_chars` characters, with a line saying what was left out."""
    lines: list[str] = []
    shown = left = 0
    for label, lint in lints:
        lines.append(f"{label} ({lint.get('metrics', {}).get('words', '?')} words, {lint.get('content_type')}): "
                     f"{count_text(counts(lint))}")
        for sev in SHOWN:
            for f in lint["findings"]:
                if f["severity"] != sev:
                    continue
                if shown >= max_findings:
                    left += 1
                    continue
                lines.append(f"  {sev:5} r{f['rule']:<4} L{f['line']:<3} {str(f['message'])[:140]}")
                shown += 1
    if left:
        lines.append(f"  … {left} more finding(s) not shown")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars - 12].rsplit("\n", 1)[0] + "\n  … (cut)"
    return text
