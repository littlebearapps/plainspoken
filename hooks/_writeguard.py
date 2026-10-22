"""What write_guard.py refuses: a Bash command that writes a reply file or a claims ledger (see its docstring).

Uses the publish gate's shell lexer (`_pushcmd.lex`, `segments`), so quotes, `$(…)`, backticks, redirections and
heredoc bodies are read the same way in both hooks."""
from __future__ import annotations

import os
import re

import _pushcmd

PROTECTED = re.compile(r"[^\s'\"=<>|;&]*\.(?:(?:claims-|delivery-)?reply\.json|claims\.(?:toml|json))\b")
_ASSIGN = re.compile(r"(?:^|[\s;&|(])(?:(?:export|declare|local|readonly|typeset)\s+(?:-\w+\s+)*)?"
                     r"([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|[^\s;&|)]*)")
_WRITE_OPS = (">", ">>", ">|", "&>", "&>>", "<>", ">&")
_TARGET_ANY = {"tee", "truncate"}
_TARGET_LAST = {"cp", "mv", "install", "ln", "rsync"}
_IN_PLACE = {"sed", "perl"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
_INTERPRETERS = {"python", "node", "nodejs", "perl", "ruby", "php", "deno", "bun"} | _SHELLS
_INLINE = {"python": "c", "node": "ep", "nodejs": "ep", "bun": "ep", "perl": "eE", "ruby": "e", "php": "r",
           **dict.fromkeys(_SHELLS, "c")}  # the one-letter flag that takes code (bundles too: `bash -lc`, `perl -pe`)
_INLINE_LONG = {"node": ("--eval", "--print"), "nodejs": ("--eval", "--print"), "bun": ("--eval", "--print"),
                "deno": ("eval",)}
_BY_EXT = {"py": "python", "sh": "bash", "bash": "bash", "js": "node", "rb": "ruby", "pl": "perl", "php": "php"}
_MAX_DEPTH = 3
_MAX_SCRIPT = 1 << 20
# A call in Python, Node, Ruby, Perl or PHP code that can write a file (or run a shell that might). Reading
# (`open(p)`, `open(p, 'rb')`, `json.load`, `tomllib.load`, `print`) matches none of these.
_CODE_WRITES = re.compile(r"""
    \b\w*open\w*\s*\((?:[^()'"]|'[^']*'|"[^"]*"|\((?:[^()]|\([^()]*\))*\))*?['"][rbtU]*[wax+][rbtwax+U]*['"]
  | \bopen\s*\(?\s*(?:my\s+)?[$\w]+\s*,\s*['"]\s*\+?[>|]                    # Perl: open(my $f, '>', …)
  | \.(?:write_text|write_bytes|touch|rename)\s*\(
  | \b(?:os\.(?:replace|truncate|system|popen|spawn\w*|exec\w*)|shutil\.\w+|subprocess\.\w+)\s*\(
  | \b(?:writeFile|appendFile|createWriteStream|copyFile|rename|truncate|execSync|spawnSync|execFile|
         file_put_contents|fwrite|fputs|system)\w*\s*\(
  | \b(?:File|IO)\.write\b
""", re.X)


class _Hits:
    def __init__(self, command: str, cwd: str | None = None):
        self.source, self.cwd = command, cwd
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


def _program(base: str, args: list[str]) -> tuple[str, str | None]:
    """How an interpreter gets its code: ("code", text), ("file", path), ("module", name) or ("stdin", None)."""
    k = 0
    while k < len(args):
        a = args[k]
        if a in _INLINE_LONG.get(base, ()) or (base in _INLINE and re.fullmatch(f"-[A-Za-z]*[{_INLINE[base]}]", a)):
            return "code", args[k + 1] if k + 1 < len(args) else ""
        if base == "python" and a == "-m":
            return "module", args[k + 1] if k + 1 < len(args) else None
        if a == "-" or (base in _SHELLS and a == "-s"):
            return "stdin", None
        if (base == "python" and a in ("-W", "-X")) or (base in _SHELLS and a in ("-o", "-O", "+o", "+O")):
            k += 2
            continue
        if not a.startswith("-") and not (base in ("deno", "bun") and a == "run"):
            return "file", a
        k += 1
    return "stdin", None


def _own(path: str) -> bool:
    """Whether `path` is part of plainspoken itself (the installed plugin or a checkout: its tests write ledgers)."""
    d = os.path.dirname(os.path.realpath(path))
    while True:
        if os.path.isfile(os.path.join(d, "hooks", "_writeguard.py")):
            return True
        up = os.path.dirname(d)
        if up == d:
            return False
        d = up


def _read(path: str, cwd: str | None) -> str | None:
    """A script's text, if it's a readable file of sane size; "" for plainspoken's own; None when unseen."""
    path = os.path.expanduser(os.path.expandvars(path))
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > _MAX_SCRIPT:
            return None
        if _own(path):
            return ""
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _shell_writes(text: str, hit: _Hits, depth: int) -> tuple[str, str] | None | bool:
    """What a shell script writes (as `problem`), or False when it can't be parsed."""
    inner = _Hits(hit.source + "\n" + text, hit.cwd)
    try:
        toks, _ = _pushcmd.lex(text)
    except (_pushcmd.ParseError, RecursionError, ValueError):
        return False
    return _scan(toks, inner, depth + 1)


def _interpreter(cmd: str, base: str, args: list[str], seg: _pushcmd.Segment, hit: _Hits,
                 depth: int, kind: str, prog: str | None) -> tuple[str, str] | None:
    """Refused when the program names a protected path (or the command does) and writes files, or can't be seen."""
    text = where = None
    if kind == "code":
        text, where = prog, f"{cmd} code"
    elif kind == "file" and prog:
        text, where = _read(prog, hit.cwd), f"the script {prog}"
    elif kind == "stdin":
        for r in seg.redirs:
            if r.body is not None:
                text, where = r.body, f"a {cmd} heredoc"
            elif r.op == "<<<" and r.target:
                text, where = r.target.text, f"a {cmd} here-string"
            elif r.op == "<" and r.target:
                text, where = _read(r.target.text, hit.cwd), f"the script {r.target.text}"
    named = next((hit(a) for a in args if hit(a)), None) or hit(text)
    if text is not None and base in _SHELLS and depth < _MAX_DEPTH:  # followed command by command
        found = _shell_writes(text, hit, depth)
        if found is not False:
            return found
        return (named, f"{where}, which the guard can't parse") if named else None
    if named is None:
        return None
    if text is None or depth >= _MAX_DEPTH:
        return named, f"a {cmd} command whose code the guard can't see"
    if _CODE_WRITES.search(text):
        return named, f"{where}, which writes files"
    return None


def _segment(seg: _pushcmd.Segment, hit: _Hits, depth: int) -> tuple[str, str] | None:
    words = [w.text for w in seg.words]
    ci = _pushcmd._command_index(words)
    cmd, args = (words[ci].rsplit("/", 1)[-1], words[ci + 1:]) if ci < len(words) else ("", [])
    base = "python" if re.fullmatch(r"python[0-9.]*", cmd) else cmd
    script = _BY_EXT.get(cmd.rpartition(".")[2]) if "." in cmd and base not in _INTERPRETERS else None
    interp = (base in _INTERPRETERS and not (base == "python" and _is_cli(args))) or script is not None
    for r in seg.redirs:
        target = r.target.text if r.target else None
        if r.op in _WRITE_OPS and hit(target):
            return hit(target), f"a {r.op} redirection"
        if r.body is not None and not interp and hit(r.body) and (
                _CODE_WRITES.search(r.body) or _shell_writes(r.body, hit, depth)):
            return hit(r.body), "a heredoc that holds a script that writes it"
    named = next((hit(a) for a in args if hit(a)), None)
    if cmd in _IN_PLACE and named and any(re.match(r"-[A-Za-z]*i", a) or a == "--in-place" for a in args):
        return named, f"{cmd} -i"
    if script is not None:  # ./build.py, run by its shebang
        return _interpreter(cmd, script, args, seg, hit, depth, "file", words[ci])
    if interp:
        return _interpreter(cmd, base, args, seg, hit, depth, *_program(base, args))
    if named is None:
        return None
    plain = [a for a in args if not a.startswith("-")]
    if cmd in _TARGET_ANY:
        return named, cmd
    if cmd in _TARGET_LAST and plain and hit(plain[-1]):
        return hit(plain[-1]), f"{cmd} onto it"
    if cmd == "dd" and any(a.startswith("of=") and hit(a) for a in args):
        return named, "dd of="
    return None


def _scan(toks: list, hit: _Hits, depth: int = 0) -> tuple[str, str] | None:
    segs, _ = _pushcmd.segments(toks)
    for seg in segs:
        found = _segment(seg, hit, depth)
        if found is not None:
            return found
        for w in seg.words + [r.target for r in seg.redirs if r.target]:
            for _kind, sub in w.subs:
                found = _scan(sub, hit, depth)
                if found is not None:
                    return found
    return None


def problem(command: str, cwd: str | None = None) -> tuple[str, str] | None:
    """(the protected path, how the command writes it), or None when the command doesn't write one.

    `cwd` resolves a script run by name (`python3 build.py`, `bash x.sh`), whose file is read to see what it writes."""
    hit = _Hits(command, cwd)
    try:
        toks, _ = _pushcmd.lex(command)
    except (_pushcmd.ParseError, RecursionError, ValueError):
        named = hit(command)
        return (named, "a command the guard can't parse") if named else None
    return _scan(toks, hit)
