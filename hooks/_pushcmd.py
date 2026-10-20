"""Command parsing for the publish gate: which `git push` invocations a Bash command runs.

A small shell lexer (quotes, escapes, `$(…)`, backticks, `${…}`, redirections, comments, heredocs), then a scan of
each simple command for git, past wrappers (`sudo`, `env`, `timeout 60`, …) and compound keywords (`if`, `then`,
`{`, `!`, …). Pushes come back as `Push` records; anything the gate can't model comes back as a reason.

Scope: a guardrail against accidental pushes, not a security boundary (docs/claude-code-facts.md section 6)."""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Callable

PARSE = "could not parse the command, so it is treated as a git push"

_OPS = (";;", "&&", "||", "|&", ";", "&", "|")
_REDIRS = ("<<<", "<<-", "<<", "<>", "<&", ">>", ">&", ">|", "&>>", "&>", "<", ">")
_WORD_END = set(" \t\n;&|()<>")

_RESERVED = {"if", "then", "else", "elif", "do", "while", "until", "{", "!", "fi", "done", "}", "esac"}
_WRAPPERS = {"sudo", "env", "command", "exec", "nice", "time", "nohup", "timeout"}
_WRAPPER_ARG_OPTS = {"sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U"}, "nice": {"-n"},
                     "env": {"-u", "-C", "-S"}, "timeout": {"-s", "-k", "--signal", "--kill-after"}}
_GIT_ARG_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_MAX_ALIAS = 5
_MAX_DEPTH = 3

BUILTINS = set("""add am apply archive bisect blame branch bugreport bundle cat-file checkout cherry cherry-pick clean clone
commit config count-objects credential daemon describe diff difftool fast-import fetch format-patch fsck gc grep hash-object
help init log ls-files ls-remote ls-tree maintenance merge merge-base mergetool mv name-rev notes pull push range-diff rebase
reflog remote repack replace request-pull rerere reset restore rev-parse revert rm send-email shell shortlog show show-branch
sparse-checkout stash status submodule switch symbolic-ref tag update-ref var verify-commit verify-tag version whatchanged
worktree""".split())


class ParseError(ValueError):
    pass


@dataclass
class Word:
    text: str  # quotes and escapes removed; substitutions kept as written
    subs: list[tuple[str, list]] = field(default_factory=list)  # (kind, lexed tokens) for $( ` <(


@dataclass
class Redir:
    op: str
    target: Word | None
    body: str | None = None  # heredoc body


@dataclass
class Segment:
    words: list[Word] = field(default_factory=list)
    redirs: list[Redir] = field(default_factory=list)


@dataclass
class Push:
    args: list[str]
    chdir: list[str] = field(default_factory=list)  # -C values, in order
    config: list[str] = field(default_factory=list)  # -c values
    git_dir: str | None = None
    unverifiable: list[str] = field(default_factory=list)  # global options the gate can't model


# ---- lexer ---------------------------------------------------------------------------------------------------------

def _skip_dollar_brace(s: str, i: int) -> int:
    """`i` at the `{` of `${`; returns the index after the matching `}`."""
    depth = 0
    while i < len(s):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        elif s[i] == "\\":
            i += 1
        i += 1
    raise ParseError("unclosed ${")


def _backtick(s: str, i: int) -> tuple[list, int]:
    """`i` after the opening backtick; returns (lexed body, index after the closing backtick)."""
    body, j = [], i
    while j < len(s):
        if s[j] == "\\" and j + 1 < len(s):
            body.append(s[j + 1] if s[j + 1] in "`$\\" else s[j:j + 2])
            j += 2
        elif s[j] == "`":
            return lex("".join(body))[0], j + 1
        else:
            body.append(s[j])
            j += 1
    raise ParseError("unclosed backtick")


def _read_word(s: str, i: int) -> tuple[Word, int]:
    text, subs, n = [], [], len(s)
    if s.startswith(("<(", ">("), i):  # process substitution
        toks, j = lex(s, i + 2, closer=")")
        subs.append(("<(", toks))
        text.append(s[i:j])
        i = j
    while i < n and s[i] not in _WORD_END:
        c = s[i]
        if c == "\\":
            if i + 1 < n and s[i + 1] != "\n":
                text.append(s[i + 1])
            i += 2
        elif c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                raise ParseError("unclosed '")
            text.append(s[i + 1:j])
            i = j + 1
        elif c == "$" and s.startswith("$'", i):
            j = i + 2
            while j < n and s[j] != "'":
                j += 2 if s[j] == "\\" else 1
            if j >= n:
                raise ParseError("unclosed $'")
            text.append(s[i + 2:j])
            i = j + 1
        elif c == '"':
            i = _read_dquote(s, i + 1, text, subs)
        elif c == "$" and s.startswith("$(", i):
            toks, j = lex(s, i + 2, closer=")")
            subs.append(("$(", toks))
            text.append(s[i:j])
            i = j
        elif c == "$" and s.startswith("${", i):
            j = _skip_dollar_brace(s, i + 1)
            text.append(s[i:j])
            i = j
        elif c == "`":
            toks, j = _backtick(s, i + 1)
            subs.append(("`", toks))
            text.append(s[i:j])
            i = j
        else:
            text.append(c)
            i += 1
    return Word("".join(text), subs), i


def _read_dquote(s: str, i: int, text: list, subs: list) -> int:
    """`i` after the opening `"`; appends to text/subs, returns the index after the closing `"`."""
    n = len(s)
    while i < n:
        c = s[i]
        if c == '"':
            return i + 1
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "\n":
                pass
            elif nxt in '$`"\\':
                text.append(nxt)
            else:
                text.append(s[i:i + 2])
            i += 2
        elif s.startswith("$(", i):
            toks, j = lex(s, i + 2, closer=")")
            subs.append(("$(", toks))
            text.append(s[i:j])
            i = j
        elif s.startswith("${", i):
            j = _skip_dollar_brace(s, i + 1)
            text.append(s[i:j])
            i = j
        elif c == "`":
            toks, j = _backtick(s, i + 1)
            subs.append(("`", toks))
            text.append(s[i:j])
            i = j
        else:
            text.append(c)
            i += 1
    raise ParseError('unclosed "')


def _read_heredocs(s: str, i: int, pending: list[Redir]) -> int:
    """Consume heredoc bodies starting at `i` (just after a newline); returns the index after the last one."""
    n = len(s)
    for redir in pending:
        delim = redir.target.text if redir.target else ""
        lines = []
        while i < n:
            j = s.find("\n", i)
            end = n if j < 0 else j
            line = s[i:end]
            cmp = line.lstrip("\t") if redir.op == "<<-" else line
            if cmp == delim:
                i = end + 1 if j >= 0 else n
                break
            if delim and cmp.startswith(delim) and cmp[len(delim):].lstrip().startswith(")"):
                i += line.index(")", len(line) - len(cmp) + len(delim))  # `EOF)` closes a $( on the same line
                break
            lines.append(line)
            i = end + 1 if j >= 0 else n
        redir.body = "\n".join(lines)
    return i


def lex(s: str, i: int = 0, closer: str | None = None) -> tuple[list, int]:
    """Tokens (Word, Redir, or an operator string) from `i`. With closer=")", stops after the matching `)`."""
    toks: list = []
    pending: list[Redir] = []
    depth, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t":
            i += 1
        elif s.startswith("\\\n", i):
            i += 2
        elif c == "\n":
            toks.append(";")
            i += 1
            if pending:
                i = _read_heredocs(s, i, pending)
                pending = []
        elif c == "#":
            j = s.find("\n", i)
            i = n if j < 0 else j
        elif c == ")":
            if closer == ")" and depth == 0:
                return toks, i + 1
            depth = max(depth - 1, 0)
            toks.append(")")
            i += 1
        elif c == "(":
            depth += 1
            toks.append("(")
            i += 1
        elif (c in "<>" and not s.startswith("(", i + 1)) or s.startswith("&>", i):
            op = next(o for o in _REDIRS if s.startswith(o, i))
            i += len(op)
            while i < n and s[i] in " \t":
                i += 1
            target = None
            if i < n and s[i] not in _WORD_END:
                target, i = _read_word(s, i)
            redir = Redir(op, target)
            toks.append(redir)
            if op in ("<<", "<<-"):
                pending.append(redir)
        elif c in ";&|":
            op = next(o for o in _OPS if s.startswith(o, i))
            toks.append(op)
            i += len(op)
        else:
            word, i = _read_word(s, i)
            if word.text.isdigit() and not word.subs and i < n and s[i] in "<>":
                continue  # a file-descriptor number, as in 2>&1
            toks.append(word)
    if closer:
        raise ParseError("unclosed $(")
    return toks, i


def segments(toks: list) -> tuple[list[Segment], bool]:
    """Simple commands, and whether the tokens define a shell function (`f() {…}` or `function f`)."""
    out, cur, func = [], Segment(), False
    for k, t in enumerate(toks):
        if isinstance(t, str):
            if t == "(" and k > 0 and isinstance(toks[k - 1], Word) and k + 1 < len(toks) and toks[k + 1] == ")":
                func = True
            if cur.words or cur.redirs:
                out.append(cur)
            cur = Segment()
        elif isinstance(t, Redir):
            cur.redirs.append(t)
        else:
            cur.words.append(t)
    if cur.words or cur.redirs:
        out.append(cur)
    for seg in out:
        tokens = [w.text for w in seg.words]
        ci = _command_index(tokens)
        func = func or (ci < len(tokens) and tokens[ci] == "function")
    return out, func


# ---- scan ----------------------------------------------------------------------------------------------------------

def _is_assignment(tok: str) -> bool:
    name, eq, _ = tok.partition("=")
    return bool(eq) and bool(name) and name.replace("_", "a").isalnum() and not name[:1].isdigit()


def _command_index(tokens: list[str]) -> int:
    """Index of the command word after assignments, compound keywords and wrappers (len(tokens) when none)."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        base = tok.rsplit("/", 1)[-1]
        if tok in _RESERVED or _is_assignment(tok):
            i += 1
        elif base in _WRAPPERS:
            i += 1
            while i < len(tokens) and (tokens[i].startswith("-") or (base == "env" and _is_assignment(tokens[i]))):
                i += 2 if tokens[i] in _WRAPPER_ARG_OPTS.get(base, ()) else 1
            if base == "timeout" and i < len(tokens):
                i += 1  # the duration
        else:
            return i
    return i


def _flat_words(words: list[Word]) -> list[str]:
    """Word texts, including every word inside their substitutions (recursively)."""
    out = []
    for w in words:
        out.append(w.text)
        for _, toks in w.subs:
            out += _flat_words([t for t in toks if isinstance(t, Word)])
    return out


class _Scan:
    def __init__(self, alias: Callable[[str, list[str]], str | None]):
        self.alias = alias
        self.pushes: list[Push] = []
        self.problems: list[str] = []

    def command(self, text: str, depth: int, inherit: Push, in_shell_alias: bool, alias_depth: int) -> None:
        try:
            toks = lex(text)[0]
        except ParseError:
            self.problems.append(PARSE)
            return
        segs, func = segments(toks)
        for seg in segs:
            self.segment(seg, func, depth, inherit, in_shell_alias, alias_depth)

    def segment(self, seg: Segment, func: bool, depth: int, inherit: Push, in_shell_alias: bool,
                alias_depth: int) -> None:
        tokens = [w.text for w in seg.words]
        ci = _command_index(tokens)
        before = len(self.pushes)
        cmd = tokens[ci].rsplit("/", 1)[-1] if ci < len(tokens) else ""
        if cmd in _SHELLS and depth < _MAX_DEPTH:
            self.shell(tokens[ci + 1:], seg, depth, inherit, in_shell_alias, alias_depth)
        elif cmd == "git":
            self.git(tokens[ci + 1:], Push([], list(inherit.chdir), list(inherit.config), inherit.git_dir),
                     depth, in_shell_alias, alias_depth)
        flat = _flat_words(seg.words)
        if cmd == "eval":
            try:
                flat += [w.text for w in lex(" ".join(tokens[ci + 1:]))[0] if isinstance(w, Word)]
            except ParseError:
                pass
        relevant = len(self.pushes) > before or (
            "push" in flat and any(w.rsplit("/", 1)[-1] == "git" for w in flat))
        if not relevant:
            return
        labels = []
        kinds = {k for w in seg.words for k, _ in w.subs}
        kinds |= {k for r in seg.redirs if r.target for k, _ in r.target.subs}
        labels += [lab for k, lab in (("$(", "$("), ("`", "a backtick"), ("<(", "a process substitution"))
                   if k in kinds]
        if any(r.op == "<<<" for r in seg.redirs):
            labels.append("a here-string")
        if cmd in ("eval", "xargs"):
            labels.append(cmd)
        if func:
            labels.append("a function definition")
        if labels:
            self.problems.append(f"the command uses {labels[0]} near a push, so what it sends can't be verified")

    def shell(self, args: list[str], seg: Segment, depth: int, inherit: Push, in_shell_alias: bool,
              alias_depth: int) -> None:
        for j, a in enumerate(args[:-1]):
            if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
                self.command(args[j + 1], depth + 1, inherit, in_shell_alias, alias_depth)
                return
        for r in seg.redirs:  # `bash <<EOF` / `bash <<< "…"`: the shell runs the text as commands
            text = r.body if r.op in ("<<", "<<-") else r.target.text if r.op == "<<<" and r.target else None
            if text:
                self.command(text, depth + 1, inherit, in_shell_alias, alias_depth)

    def git(self, toks: list[str], push: Push, depth: int, in_shell_alias: bool, alias_depth: int) -> None:
        i = 0
        while i < len(toks) and toks[i].startswith("-"):
            name, eq, val = toks[i].partition("=")
            if name in _GIT_ARG_OPTS and not eq:
                val = toks[i + 1] if i + 1 < len(toks) else ""
                i += 2
            else:
                i += 1
            if name == "-C":
                push.chdir.append(val)
            elif name == "-c":
                push.config.append(val)
            elif name == "--git-dir":
                push.git_dir = val
            elif name in ("--namespace", "--config-env"):
                push.unverifiable.append(name)
        if i >= len(toks):
            return
        sub, rest = toks[i], toks[i + 1:]
        if sub == "push":
            push.args = rest
            self.pushes.append(push)
            return
        if sub in BUILTINS or alias_depth >= _MAX_ALIAS:
            return
        exp = self.alias(sub, push.config)
        if exp is None:
            return
        if exp.startswith("!"):
            if in_shell_alias:  # one level of shell-alias expansion only
                if re.search(r"\bpush\b", exp):
                    self.problems.append(f"can't verify what this push sends: nested shell alias {sub}")
                return
            text = exp[1:] + "".join(" " + shlex.quote(a) for a in rest)
            self.command(text, depth + 1, push, True, alias_depth + 1)
            return
        try:
            words = shlex.split(exp)
        except ValueError:
            if re.search(r"\bpush\b", exp):
                self.problems.append(f"can't verify what this push sends: alias {sub}")
            return
        self.git(words + rest, push, depth, in_shell_alias, alias_depth + 1)


def parse(command: str, alias: Callable[[str, list[str]], str | None]) -> tuple[list[Push], list[str]]:
    """(each `git push` the command runs, reasons it can't be verified).

    `alias(name, -c values)` returns a git alias's expansion, or None."""
    s = _Scan(alias)
    s.command(command, 0, Push([]), False, 0)
    return s.pushes, list(dict.fromkeys(s.problems))
