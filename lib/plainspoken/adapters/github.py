"""The `github` adapter: one issue per proposal through the `gh` CLI, and decisions from the issue's comments.

`gh` runs through an injectable `runner(args) -> (code, stdout, stderr)` (tests pass a fake). The default runs it
without a shell, with a 60-second timeout and prompts off; `gh` keeps its own credentials, so none pass through here.
Only unedited, unhidden comments on the proposal's own issue whose `author.login` is in `[kaizen] approvers`
(case-insensitively, as GitHub logins are) count, and a comment decides only when its whole body is one plain
decision line (`adapters.parse_decision`). The issue body never counts.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from plainspoken import proposals
from plainspoken.adapters import (Adapter, AdapterError, first_line, is_approver, iso,
                                  looks_like_decision, near_misses, outward_decide, parse_decision,
                                  render, title)

TITLE_MAX = 120
BODY_MAX = 60_000  # GitHub's limit is 65,536 characters
TIMEOUT = 60
_ISSUE_URL = re.compile(r"https://\S+/issues/(\d+)")
_NUMBER = re.compile(r"\d{1,10}")
TOKEN_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")


def default_runner(args: list[str]) -> tuple[int, str, str]:
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT, env=env, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return 127, "", "gh isn't installed or isn't on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", f"gh timed out after {TIMEOUT} seconds"
    except OSError as e:
        return 126, "", f"gh couldn't run ({e})"
    return r.returncode, r.stdout or "", r.stderr or ""


_decide = outward_decide  # the one `## Decide` text, shared with the other outward adapter


class GitHubAdapter(Adapter):
    name = "github"
    SKIP_NOTE = "gh didn't say whether they were edited — upgrade gh"

    def __init__(self, settings: Mapping, runner: Callable | None = None):
        gh = dict(settings.get("github") or {})
        self.repo = gh.get("repo")
        if not self.repo:
            raise AdapterError("[kaizen.github] repo isn't set: name the repository (owner/name) that gets the "
                               "proposal issues")
        self.labels = [str(x) for x in gh.get("labels") or []]
        self.approvers = list(settings.get("approvers") or [])
        if not self.approvers:
            raise AdapterError("[kaizen] approvers is empty: name the GitHub logins whose comments may decide")
        self.runner = runner or default_runner
        self.folder = proposals._folder(settings)

    @staticmethod
    def _scrub(text: str) -> str:
        """`text` without the value of any GitHub token in the environment (gh never prints one, but its messages are
        shown and stored)."""
        for name in TOKEN_ENV:
            secret = (os.environ.get(name) or "").strip()
            if secret:
                text = text.replace(secret, "***")
        return text

    def _run(self, args: list[str], what: str) -> str:
        try:
            code, out, err = self.runner(args)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            raise AdapterError(f"gh {what} couldn't run ({first_line(self._scrub(str(e)))[:200]})") from None
        if code != 0:  # scrub first, then cut: a secret straddling the cut can't leave a prefix behind
            raise AdapterError(f"gh {what} failed (exit {code}): "
                               f"{first_line(self._scrub(err or out or 'no message'))[:200]}")
        return out or ""

    def emit_proposal(self, p: dict) -> str:
        """`gh issue create`; the ref is the issue number from the URL gh prints."""
        body = render(p, _decide(self.approvers), outward=True, max_chars=BODY_MAX)
        try:  # the body file lives in the proposals folder for the moment gh reads it (writes stay in .plainspoken/)
            self.folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.folder, prefix=".gh-body-", suffix=".md")
        except OSError as e:
            raise AdapterError(f"{self.folder}: can't write the issue body for gh ({e})") from None
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
            args = ["gh", "issue", "create", "--repo", self.repo, "--title", title(p, TITLE_MAX)]
            for label in self.labels:
                args += ["--label", label]
            args += ["--body-file", tmp]
            out = self._run(args, "issue create")
        finally:
            Path(tmp).unlink(missing_ok=True)
        found = _ISSUE_URL.findall(out)
        if not found:
            raise AdapterError(f"gh issue create printed no issue URL for {self.repo}, so the issue number is unknown")
        return found[-1]

    def read_decisions(self, p: dict) -> list[dict]:
        """Decisions from the comments on the proposal's own issue: the issue body (the plugin's text) must name the
        proposal id, and each comment's URL must point at that issue. Comments that were edited
        (`includesCreatedEdit`) or hidden (`isMinimized`) don't count, since a maintainer can edit someone else's
        comment, and it fails closed: a comment without both flags (an older gh) is skipped and counted in
        `skipped`. Logins match `approvers` case-insensitively, as GitHub logins are; `gh --json comments` gives the
        login only, not an immutable account id, so a renamed account's old login could be taken by someone else."""
        ref = str(p.get("ref") or "")
        if not _NUMBER.fullmatch(ref):
            raise AdapterError(f"the proposal's github ref {ref!r} isn't an issue number")
        out = self._run(["gh", "issue", "view", ref, "--repo", self.repo, "--json", "body,comments"],
                        f"issue view {ref}")
        try:
            data = json.loads(out)
            comments = data["comments"]
            if not isinstance(comments, list):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise AdapterError(f"gh issue view {ref} didn't return the comments as JSON") from None
        if f"**{p['id']}**" not in str(data.get("body") or ""):
            raise AdapterError(f"issue #{ref} in {self.repo} isn't the one made for {p['id']} (its body doesn't name "
                               "it), so none of its comments can decide this proposal")
        found, misses = [], []
        for c in comments:
            if not isinstance(c, dict):
                continue
            url = c.get("url")
            if isinstance(url, str) and f"/issues/{ref}#" not in url:
                continue  # not a comment on this issue
            login = (c.get("author") or {}).get("login") if isinstance(c.get("author"), dict) else None
            if not isinstance(login, str) or not login or not is_approver(login, self.approvers):
                continue
            body = str(c.get("body") or "")
            parsed = parse_decision(body)
            if parsed is None:
                if looks_like_decision(body):  # an approver meant to decide: tell them to repost
                    misses.append((login, iso(c.get("createdAt"))))
                continue
            edited, hidden = c.get("includesCreatedEdit"), c.get("isMinimized")
            if not (isinstance(edited, bool) and isinstance(hidden, bool)):
                self.skipped += 1  # fail closed: an older gh that doesn't report either can't prove it's unedited
                continue
            if edited or hidden:
                continue
            found.append({"verdict": parsed[0], "by": login, "reason": parsed[1], "at": iso(c.get("createdAt"))})
        self.near += near_misses(misses, found)
        return sorted(found, key=lambda d: d["at"] or "")
