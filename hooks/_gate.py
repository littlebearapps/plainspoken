"""The publish gate's checks: what each `git push` sends, and does every pushed gated file have a current PASS.

Command parsing lives in _pushcmd.py; this module resolves refs and hashes files. Scope and limits:
docs/claude-code-facts.md section 6."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import _common
import _pushcmd

_UNVERIFIABLE_FLAGS = {"--all", "--mirror", "--tags", "--delete", "--prune", "-d"}
_PUSH_ARG_OPTS = {"--repo", "--receive-pack", "--exec", "-o", "--push-option"}
_PATHS = ("-c", "core.quotePath=false")


class _Unverifiable(Exception):
    pass


@dataclass(frozen=True)
class _Target:
    rev: str  # "HEAD" or a commit sha
    bases: tuple[str, ...]  # remote-side refs to diff against (`base...rev`, so from the merge-base), first that works


def _git(project: Path, *args: str, cfg: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *cfg, *args], cwd=project, capture_output=True)


def _out(r: subprocess.CompletedProcess) -> str | None:
    return r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else None


def _cfg(push: _pushcmd.Push) -> tuple[str, ...]:
    return tuple(x for v in push.config for x in ("-c", v))


def _alias(project: Path):
    def lookup(name: str, config: list[str]) -> str | None:
        return _out(_git(project, "config", "--get", f"alias.{name}", cfg=tuple(x for v in config for x in ("-c", v))))
    return lookup


def scan(command: str, project: Path) -> tuple[list[list[str]], list[str]]:
    """(the argument lists of each `git push` in the command, reasons the command can't be verified)."""
    pushes, problems = _pushcmd.parse(command, _alias(project))
    return [p.args for p in pushes], problems


def involves_push(command: str, project: Path) -> bool:
    """True when the command runs `git push`, or can't be parsed well enough to rule one out."""
    pushes, problems = _pushcmd.parse(command, _alias(project))
    return bool(pushes or problems)


def _same_repo(push: _pushcmd.Push, project: Path, cwd: Path) -> bool:
    if not push.chdir and push.git_dir is None:
        return True
    where = cwd
    for d in push.chdir:
        where = where / d
    extra = ("--git-dir", str(where / push.git_dir)) if push.git_dir is not None else ()
    ask = ("rev-parse", "--show-toplevel", "--absolute-git-dir")
    try:
        theirs = _out(subprocess.run(["git", *extra, *ask], cwd=where, capture_output=True))
    except OSError:
        return False
    mine = _out(_git(project, *ask))
    return theirs is not None and theirs == mine


def _default_bases(remote: str) -> tuple[str, ...]:
    """The remote's default branch, for a push with no tracking ref: its HEAD, else main, else master."""
    return tuple(f"refs/remotes/{remote}/{b}" for b in ("HEAD", "main", "master"))


def _targets(push: _pushcmd.Push, project: Path, cwd: Path) -> tuple[list[_Target], list[str]]:
    """(what this push sends, reasons it can't be verified)."""
    if push.unverifiable:
        return [], [f"can't verify what this push sends: git {push.unverifiable[0]}"]
    if not _same_repo(push, project, cwd):
        where = " ".join(f"-C {d}" for d in push.chdir) or f"--git-dir {push.git_dir}"
        return [], [f"can't verify what this push sends: git {where} is not this project's repository"]
    cfg, args = _cfg(push), push.args
    positional, repo_opt, i = [], None, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            positional += args[i + 1:]
            break
        if a in _UNVERIFIABLE_FLAGS or (a.startswith("-") and not a.startswith("--") and "d" in a[1:] and a != "-o"):
            return [], [f"can't verify what this push sends: {a}"]
        if a.startswith("-"):
            name, eq, val = a.partition("=")
            if name in _PUSH_ARG_OPTS and not eq:
                val = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if name == "--repo":
                repo_opt = val
            i += 1
            continue
        positional.append(a)
        i += 1
    remote = positional[0] if positional else repo_opt  # the positional repository beats --repo (as git does)
    refspecs = positional[1:]
    head = _out(_git(project, "rev-parse", "--verify", "-q", "HEAD^{commit}"))
    branch = _out(_git(project, "symbolic-ref", "--short", "-q", "HEAD"))
    if not refspecs:
        if (_out(_git(project, "config", "--get", "push.default", cfg=cfg)) or "") == "matching":
            return [], ["can't verify what this push sends: push.default is matching"]
        if remote is None and branch:
            for key in (f"branch.{branch}.pushRemote", "remote.pushDefault", f"branch.{branch}.remote"):
                remote = _out(_git(project, "config", "--get", key, cfg=cfg))
                if remote:
                    break
        remote = remote or "origin"
        if _out(_git(project, "config", "--get-all", f"remote.{remote}.push", cfg=cfg)):
            return [], [f"can't verify what this push sends: remote.{remote}.push is configured"]
        return [_Target("HEAD", ("@{push}", "@{upstream}", *_default_bases(remote)))], []
    targets, problems = [], []
    for spec in refspecs:
        src, _, dst = spec.lstrip("+").partition(":")
        if not src or "*" in spec:
            problems.append(f"can't verify what this push sends: {spec}")
            continue
        if src in ("HEAD", branch, f"refs/heads/{branch}"):
            sha = head
        else:
            sha = None if src.startswith("-") else _out(
                _git(project, "rev-parse", "--verify", "-q", f"{src}^{{commit}}"))
        if sha is None:
            problems.append(f"can't verify what this push sends: {spec}")
            continue
        if not dst:
            if src == "HEAD":
                dst = branch or ""
            elif _git(project, "rev-parse", "--verify", "-q",
                      f"refs/heads/{src.removeprefix('refs/heads/')}").returncode == 0:
                dst = src
        dst = dst.removeprefix("refs/heads/")
        # The destination's tracking ref; for a new branch, the remote's default branch (`git push -u origin HEAD`
        # then checks what the branch adds since the merge-base, as a bare push with an upstream does).
        bases = ()
        if remote:
            bases = (f"refs/remotes/{remote}/{dst}",) if dst and not dst.startswith("refs/") else ()
            bases += _default_bases(remote)
        targets.append(_Target("HEAD" if sha == head else sha, bases))
    return list(dict.fromkeys(targets)), problems


def _paths(r: subprocess.CompletedProcess) -> list[str]:
    return [os.fsdecode(p) for p in r.stdout.split(b"\0") if p]


def _pushed(project: Path, target: _Target) -> list[str] | None:
    for base in target.bases:
        r = _git(project, *_PATHS, "diff", "--no-renames", "--relative", "--name-only", "-z", f"{base}...{target.rev}")
        if r.returncode == 0:
            return _paths(r)
    return None


def _inside(project: Path, rel: str) -> bool:
    try:
        (project / rel).resolve().relative_to(project.resolve())
        return True
    except (ValueError, OSError):
        return False


def _ls_tree(project: Path, rev: str) -> list[str]:
    r = _git(project, *_PATHS, "ls-tree", "-r", "--name-only", "-z", rev)
    if r.returncode != 0:
        raise _Unverifiable(f"can't list the files in {rev}")
    return _paths(r)


def _committed_hash(project: Path, rel: str, rev: str = "HEAD") -> tuple[str | None, bool]:
    """(sha256 of the file as committed at `rev`, rev readable). (None, True) means the path is absent there.

    Raises _Unverifiable when the path is there but its content can't be read."""
    if _git(project, "rev-parse", "--verify", "-q", f"{rev}^{{commit}}").returncode != 0:
        return None, False
    r = _git(project, "--literal-pathspecs", "ls-tree", "-z", rev, "--", rel)
    if r.returncode != 0:
        raise _Unverifiable(f"can't verify {rel}: git ls-tree failed")
    entry = r.stdout.split(b"\0", 1)[0]
    if not entry:
        return None, True  # deleted (or never added): nothing of it is pushed
    meta = entry.split(b"\t", 1)[0].split()
    if len(meta) != 3 or meta[1] != b"blob":
        raise _Unverifiable(f"can't verify {rel}: not a regular file in {rev}")
    blob = _git(project, "cat-file", "blob", meta[2].decode("ascii", "replace"))
    if blob.returncode != 0:
        raise _Unverifiable(f"can't verify {rel}: git can't read its committed content")
    return hashlib.sha256(blob.stdout).hexdigest(), True


def _clean(project: Path, rel: str) -> bool:
    """The working-tree file matches HEAD once git's filters (autocrlf, clean, LFS) are applied."""
    return _git(project, "--literal-pathspecs", "diff", "--quiet", "HEAD", "--", rel).returncode == 0


class _Stamps:
    """The profile_sha256 and ruleset_version a current report must carry, resolved the way lint-watch resolves the
    profile: per file, since `[engine] profiles` can give each file its own (cached per profile). A resolution error
    is kept and reported per file (can't verify)."""

    def __init__(self, project: Path):
        self._project, self._cache = project, {}

    def get(self, art: Path | None = None) -> dict[str, str] | str:
        from plainspoken import config
        from plainspoken.registry import load_config
        try:
            key = config.profile_for(art, self._project) if art is not None else None
            if key not in self._cache:
                prof = config.resolve_profile(None, self._project, os.environ, plugin_option="default", target=art)
                self._cache[key] = {"profile_sha256": prof.sha256, "ruleset_version": load_config().version}
            return self._cache[key]
        except (ValueError, OSError) as e:  # ProfileError and ConfigError are ValueErrors
            return f"{type(e).__name__}: {(str(e).splitlines() or [''])[0]}"


def _stale_stamp(rep: dict, want: dict[str, str]) -> str | None:
    if rep.get("ruleset_version") != want["ruleset_version"]:
        return (f"report is stale (made under ruleset {rep.get('ruleset_version')!r}, "
                f"current is {want['ruleset_version']!r})")
    if rep.get("profile_sha256") != want["profile_sha256"]:
        return ("report is stale (made with another profile, or the profile or its calibration notes changed); "
                "if you chose the profile in the plugin settings, also set [engine] profile in .plainspoken/config.toml "
                "(a session that loads the plugin with --plugin-dir gives its hooks no plugin settings)")
    return None


def _problems(project: Path, globs: list[str], target: _Target, stamps: _Stamps | None = None) -> list[str]:
    from plainspoken import report
    stamps = stamps or _Stamps(project)
    files = _pushed(project, target)
    try:
        if files is None:  # no remote-side base: every gated file in the pushed commit's tree (fail closed)
            files = _ls_tree(project, target.rev)
    except _Unverifiable as e:
        return [str(e)]
    out = []
    reports = project / ".plainspoken" / "reports"
    for rel in sorted({f for f in files if any(_common.glob_match(f, g) for g in globs)}):
        if rel == ".git" or rel.startswith(".git/") or "/.git/" in rel:
            continue
        if not _inside(project, rel):
            out.append(f"{rel}: path resolves outside the project")
            continue
        art = project / rel
        try:
            committed, rev_ok = _committed_hash(project, rel, target.rev)
        except _Unverifiable as e:
            out.append(str(e))
            continue
        if not rev_ok:
            out.append(f"can't verify {rel}: {target.rev} is not a readable commit")
            continue
        if committed is None:
            continue
        if target.rev == "HEAD" and art.is_file() and _clean(project, rel):
            current = report.sha256(art)  # the bytes the check read; git's filters may differ from the blob
        else:
            current = committed
        rep_path = report.report_paths(art, reports, project)["report"]
        try:
            rep = json.loads(rep_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out.append(f"{rel}: no plainspoken report (run /plainspoken:check {rel})")
            continue
        if not isinstance(rep, dict):
            out.append(f"{rel}: report is not a JSON object")
        elif rep.get("article_sha256") != current:
            out.append(f"{rel}: report is stale (the committed file differs from the one checked)")
        elif rep.get("status") != "PASS":
            out.append(f"{rel}: last check was {rep.get('status')}, not PASS")
        elif isinstance(want := stamps.get(art), str):
            out.append(f"{rel}: can't verify the report: the profile can't be resolved ({want})")
        elif stale := _stale_stamp(rep, want):
            out.append(f"{rel}: {stale}")
    return out


def check(command: str, project: Path, cwd: Path | None = None) -> list[str]:
    """Problems that should stop this command; [] when it's allowed."""
    pushes, problems = _pushcmd.parse(command, _alias(project))
    if not pushes and not problems:
        return []
    from plainspoken import config
    globs = config.gate_paths(project)
    if not globs:
        return []
    out = list(problems)
    targets: list[_Target] = []
    for push in pushes:
        t, p = _targets(push, project, cwd or project)
        targets += t
        out += p
    stamps = _Stamps(project)
    for target in dict.fromkeys(targets):
        out += _problems(project, globs, target, stamps)
    return list(dict.fromkeys(out))
