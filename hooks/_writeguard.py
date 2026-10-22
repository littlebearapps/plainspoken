"""What write_guard.py refuses: a Bash command that writes a reply file or a claims ledger (see its docstring).

Uses the publish gate's shell lexer (`_pushcmd.lex`, `segments`), so quotes, `$(…)`, backticks, redirections and
heredoc bodies are read the same way in both hooks."""
from __future__ import annotations

import re

import _pushcmd

PROTECTED = re.compile(r"[^\s'\"=<>|;&]*\.(?:(?:claims-|delivery-)?reply\.json|claims\.(?:toml|json))\b")
_ASSIGN = re.compile(r"(?:^|[\s;&|(])(?:(?:export|declare|local|readonly|typeset)\s+(?:-\w+\s+)*)?"
                     r"([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|[^\s;&|)]*)")
_WRITE_OPS = (">", ">>", ">|", "&>", "&>>", "<>", ">&")
_TARGET_ANY = {"tee", "truncate"}
_TARGET_LAST = {"cp", "mv", "install", "ln", "rsync"}
_IN_PLACE = {"sed", "perl"}
_INTERPRETERS = {"python", "node", "nodejs", "perl", "ruby", "php", "deno", "bun", "sh", "bash", "zsh", "dash", "ksh",
                 "fish"}


class _Hits:
    def __init__(self, command: str):
        names = [m.group(1) for m in _ASSIGN.finditer(command) if PROTECTED.search(m.group(2))]
        self.vars = re.compile(r"\$\{?(?:" + "|".join(map(re.escape, names)) + r")\b") if names else None

    def __call__(self, text: str | None) -> str | None:
        """The protected path `text` names (a variable assigned one counts), or None."""
        if not text:
            return None
        m = PROTECTED.search(text)
        if m:
            return m.group(0)
        if self.vars is not None and self.vars.search(text):
            return text
        return None


def _is_cli(args: list[str]) -> bool:
    """`python3 [opts] …/run.py …` or `python3 -m plainspoken …`: plainspoken's own CLI, which reads `--from`."""
    for k, a in enumerate(args):
        if a == "-m":
            return k + 1 < len(args) and args[k + 1] == "plainspoken"
        if a in ("-c", "-"):
            return False
        if not a.startswith("-"):
            return a.rsplit("/", 1)[-1] == "run.py"
    return False


def _segment(seg: _pushcmd.Segment, hit: _Hits) -> tuple[str, str] | None:
    for r in seg.redirs:
        target = r.target.text if r.target else None
        if r.op in _WRITE_OPS and hit(target):
            return hit(target), f"a {r.op} redirection"
        if r.body is not None and hit(r.body):
            return hit(r.body), "a heredoc that names it"
        if r.op == "<<<" and hit(target):
            return hit(target), "a here-string that names it"
    words = [w.text for w in seg.words]
    ci = _pushcmd._command_index(words)
    if ci >= len(words):
        return None
    cmd, args = words[ci].rsplit("/", 1)[-1], words[ci + 1:]
    named = next((hit(a) for a in args if hit(a)), None)
    if named is None:
        return None
    plain = [a for a in args if not a.startswith("-")]
    if cmd in _TARGET_ANY:
        return named, cmd
    if cmd in _TARGET_LAST and plain and hit(plain[-1]):
        return hit(plain[-1]), f"{cmd} onto it"
    if cmd == "dd" and any(a.startswith("of=") and hit(a) for a in args):
        return named, "dd of="
    if cmd in _IN_PLACE and any(a.startswith("-i") or a == "--in-place" for a in args):
        return named, f"{cmd} -i"
    base = "python" if re.fullmatch(r"python[0-9.]*", cmd) else cmd
    if base in _INTERPRETERS and not (base == "python" and _is_cli(args)):
        return named, f"a {cmd} command that names it"
    return None


def _scan(toks: list, hit: _Hits) -> tuple[str, str] | None:
    segs, _ = _pushcmd.segments(toks)
    for seg in segs:
        found = _segment(seg, hit)
        if found is not None:
            return found
        for w in seg.words + [r.target for r in seg.redirs if r.target]:
            for _kind, sub in w.subs:
                found = _scan(sub, hit)
                if found is not None:
                    return found
    return None


def problem(command: str) -> tuple[str, str] | None:
    """(the protected path, how the command writes it), or None when the command doesn't write one."""
    hit = _Hits(command)
    try:
        toks, _ = _pushcmd.lex(command)
    except (_pushcmd.ParseError, RecursionError, ValueError):
        named = hit(command)
        return (named, "a command the guard can't parse") if named else None
    return _scan(toks, hit)
