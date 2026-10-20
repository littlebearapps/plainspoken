import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "publish_gate.py"
sys.path.insert(0, str(REPO / "lib"))
sys.path.insert(0, str(REPO / "hooks"))
from plainspoken import profile, report  # noqa: E402
from plainspoken.registry import load_config  # noqa: E402
import _gate  # noqa: E402


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.remote, self.project = self.tmp / "remote.git", self.tmp / "proj"
        git("init", "--bare", "-q", "-b", "main", str(self.remote), cwd=self.tmp)
        git("clone", "-q", str(self.remote), str(self.project), cwd=self.tmp)
        git("checkout", "-q", "-B", "main", cwd=self.project)
        (self.project / "README").write_text("x\n", encoding="utf-8")
        git("add", ".", cwd=self.project); git("commit", "-qm", "init", cwd=self.project)
        git("push", "-q", "-u", "origin", "HEAD", cwd=self.project)
        (self.project / ".plainspoken").mkdir()
        (self.project / ".plainspoken" / "config.toml").write_text('[engine]\nprofile = "default"\n[gate]\npaths = ["docs/**/*.md"]\n', encoding="utf-8")
        (self.project / "docs").mkdir()
        self.art = self.project / "docs" / "post.md"
        self.art.write_text("I fixed it on Friday.\n", encoding="utf-8")
        git("add", ".", cwd=self.project); git("commit", "-qm", "post", cwd=self.project)

    def run_gate(self, strictness="block", command="git push"):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_"))}
        env["CLAUDE_PROJECT_DIR"] = str(self.project)
        if strictness is not None:
            env["CLAUDE_PLUGIN_OPTION_STRICTNESS"] = strictness
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.project),
                   "tool_input": {"command": command}}
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                              text=True, env=env, cwd=self.project)

    def write_report(self, status="PASS", sha=None, art=None, **stamps):
        art = art or self.art
        p = report.report_paths(art, self.project / ".plainspoken" / "reports", self.project)["report"]
        p.parent.mkdir(parents=True, exist_ok=True)
        body = {"status": status, "article_sha256": sha or report.sha256(art),
                "profile_sha256": profile.default().sha256, "ruleset_version": load_config().version, **stamps}
        p.write_text(json.dumps(body), encoding="utf-8")

    def decision(self, r):
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout.strip() else None

    def out(self, r):
        return json.loads(r.stdout) if r.stdout.strip() else {}

    def reason(self, r):
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"] if r.stdout.strip() else ""

    def commit_file(self, rel, text):
        path = self.project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git("add", ".", cwd=self.project); git("commit", "-qm", rel, cwd=self.project)
        return path

    def test_watch_is_silent(self):
        r = self.run_gate("watch")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_block_without_report_denies(self):
        r = self.run_gate()
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("docs/post.md", r.stdout)

    def test_block_with_current_pass_allows(self):
        self.write_report()
        r = self.run_gate()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_stale_pass_denies(self):
        self.write_report(sha="0" * 64)
        self.assertEqual(self.decision(self.run_gate()), "deny")

    def test_pass_under_another_ruleset_or_profile_denies(self):
        for stamps, word in (({"ruleset_version": "0.0.0-old"}, "ruleset"), ({"profile_sha256": "0" * 64}, "profile"),
                             ({"ruleset_version": None}, "ruleset")):
            with self.subTest(stamps=stamps):
                self.write_report(**stamps)
                r = self.run_gate()
                self.assertEqual(self.decision(r), "deny")
                self.assertIn(word, self.reason(r))

    def test_per_file_profile_stamps(self):  # the report must carry the file's own profile
        prof = self.project / ".plainspoken" / "profiles"
        prof.mkdir()
        (prof / "quiet.toml").write_text('[profile]\nname = "quiet"\n[rules]\ndisabled = ["2"]\n', encoding="utf-8")
        (self.project / ".plainspoken" / "config.toml").write_text(
            '[engine]\nprofile = "default"\nprofiles = [{ glob = "docs/**", profile = "quiet" }]\n'
            '[gate]\npaths = ["docs/**/*.md"]\n', encoding="utf-8")
        self.write_report()  # made with the default profile: stale for a docs/ file
        r = self.run_gate()
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("profile", self.reason(r))
        self.write_report(profile_sha256=profile.load(str(prof / "quiet.toml")).sha256)
        r = self.run_gate()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""))

    def test_unresolvable_profile_is_unverifiable(self):
        self.write_report()
        (self.project / ".plainspoken" / "config.toml").write_text(
            '[engine]\nprofile = "no-such-profile"\n[gate]\npaths = ["docs/**/*.md"]\n', encoding="utf-8")
        r = self.run_gate()
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("can't verify", self.reason(r))
        self.assertIn("profile", self.reason(r))

    def test_fail_status_denies(self):
        self.write_report(status="UNRESOLVED")
        self.assertEqual(self.decision(self.run_gate()), "deny")

    def test_warn_mode_warns_without_blocking(self):
        r = self.run_gate("warn")
        self.assertEqual(r.returncode, 0)
        self.assertIn("systemMessage", json.loads(r.stdout))

    def test_non_push_command_ignored(self):
        self.assertEqual(self.run_gate(command="git status").stdout.strip(), "")

    def test_malformed_stdin_in_block_mode_denies(self):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project), "CLAUDE_PLUGIN_OPTION_STRICTNESS": "block"}
        r = subprocess.run([sys.executable, str(HOOK)], input="{bad", capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_every_push_spelling_is_gated(self):
        for cmd in ("git -C . push", "git -c k=v push", "FOO=1 git push", "sudo git push", "(git push)",
                    "echo hi\ngit push", "cd . && git push", "env FOO=1 git push", "bash -c 'git push'",
                    "git --git-dir=.git push origin"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.decision(self.run_gate(command=cmd)), "deny")

    def test_non_push_spellings_ignored(self):
        for cmd in ("echo git push", "git pushx", "git commit -m 'a; git push'", "git status && echo pushed"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_gate(command=cmd).stdout.strip(), "")

    def test_unparseable_push_command_fails_closed_in_block_mode(self):
        r = self.run_gate(command="git 'push")
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("could not parse", r.stdout)

    def test_tokenizer_unit(self):
        scan = lambda c: _gate.scan(c, self.project)  # noqa: E731
        self.assertEqual(scan("sudo -u bob git -C x push origin")[0], [["origin"]])
        self.assertEqual(scan("git log --grep push"), ([], []))
        self.assertEqual(scan("bash -c 'git push'")[0], [[]])
        pushes, problems = scan('echo "git push')
        self.assertEqual(pushes, [])
        self.assertIn("could not parse", problems[0])

    def test_committed_hash_matches_report_sha256(self):
        committed, ok = _gate._committed_hash(self.project, "docs/post.md")
        self.assertTrue(ok)
        self.assertEqual(committed, report.sha256(self.art))

    def test_pass_for_committed_version_survives_uncommitted_edit(self):
        self.write_report()
        self.art.write_text("An unpushed local edit.\n", encoding="utf-8")
        self.assertEqual(self.run_gate().stdout.strip(), "")

    def test_pass_for_uncommitted_edit_fails_when_head_differs(self):
        self.art.write_text("An unpushed local edit.\n", encoding="utf-8")
        self.write_report()  # PASS for the edit on disk, which HEAD does not have
        self.assertEqual(self.decision(self.run_gate()), "deny")

    def test_deleted_file_is_skipped(self):
        git("rm", "-q", "docs/post.md", cwd=self.project); git("commit", "-qm", "rm", cwd=self.project)
        self.assertEqual(self.run_gate().stdout.strip(), "")

    def test_non_object_report_has_a_reason(self):
        p = report.report_paths(self.art, self.project / ".plainspoken" / "reports", self.project)["report"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[1, 2]", encoding="utf-8")
        r = self.run_gate()
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("not a JSON object", r.stdout)

    def test_no_upstream_fallback_ignores_git_dir_and_symlinks(self):
        git("branch", "--unset-upstream", cwd=self.project)
        git("remote", "remove", "origin", cwd=self.project)
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "evil.md").write_text("x\n", encoding="utf-8")
        (self.project / "docs" / "link").symlink_to(outside, target_is_directory=True)
        (self.project / "docs" / "flink.md").symlink_to(outside / "evil.md")
        (self.project / ".git" / "docs").mkdir()
        (self.project / ".git" / "docs" / "x.md").write_text("x\n", encoding="utf-8")
        r = self.run_gate()
        self.assertEqual(self.decision(r), "deny")  # docs/post.md still has no report
        self.assertIn("docs/post.md", r.stdout)
        for bad in ("evil.md", "flink.md", ".git"):
            self.assertNotIn(bad, r.stdout)

    def test_pushed_symlink_leaving_the_project_is_flagged(self):
        outside = self.tmp / "outside.md"
        outside.write_text("x\n", encoding="utf-8")
        (self.project / "docs" / "sneak.md").symlink_to(outside)
        git("add", ".", cwd=self.project); git("commit", "-qm", "s", cwd=self.project)
        self.assertIn("outside the project", self.run_gate().stdout)

    def branch_with_other_version(self):
        git("checkout", "-q", "-b", "feature", "HEAD~1", cwd=self.project)
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs" / "post.md").write_text("A different feature version.\n", encoding="utf-8")
        git("add", ".", cwd=self.project); git("commit", "-qm", "feature", cwd=self.project)
        git("checkout", "-q", "main", cwd=self.project)

    def test_refspec_from_another_branch_checks_that_commit(self):
        self.branch_with_other_version()
        self.write_report()  # PASS for main's docs/post.md only
        self.assertEqual(self.run_gate(command="git push origin HEAD").stdout.strip(), "")
        self.assertEqual(self.run_gate(command="git push origin main:main").stdout.strip(), "")
        r = self.run_gate(command="git push origin feature:main")
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("docs/post.md", r.stdout)
        self.assertEqual(self.decision(self.run_gate(command="git push origin feature")), "deny")

    def test_unverifiable_pushes_are_denied(self):
        for cmd in ("git push --all", "git push origin --mirror", "git push --tags", "git push --delete origin x",
                    "git push origin :gone", "git push origin nonexistent-ref", "git push origin 'refs/heads/*:refs/x/*'"):
            with self.subTest(cmd=cmd):
                r = self.run_gate(command=cmd)
                self.assertEqual(self.decision(r), "deny")
                self.assertIn("can't verify what this push sends", r.stdout)

    def test_unverifiable_pushes_only_warn_in_warn_mode(self):
        r = self.run_gate("warn", command="git push --all")
        self.assertIn("systemMessage", json.loads(r.stdout))

    def test_shell_tricks_near_a_push_are_denied(self):
        for cmd in ("$(echo git) push", "`echo git` push", "eval git push", "echo origin | xargs git push",
                    "git push <<< x", "f() { git push; }; f", "function f { git push; }"):
            with self.subTest(cmd=cmd):
                r = self.run_gate(command=cmd)
                self.assertEqual(self.decision(r), "deny")
                self.assertIn("can't be verified", r.stdout)

    def test_alias_for_push_is_detected(self):
        git("config", "alias.p", "push", cwd=self.project)
        git("config", "alias.sp", "!sh -c 'git push'", cwd=self.project)
        git("config", "alias.st", "status", cwd=self.project)
        self.assertEqual(self.decision(self.run_gate(command="git p")), "deny")
        self.assertEqual(self.decision(self.run_gate(command="git sp")), "deny")
        self.assertEqual(self.run_gate(command="git st").stdout.strip(), "")
        self.write_report()
        self.assertEqual(self.run_gate(command="git p origin HEAD").stdout.strip(), "")

    def test_gate_paths_unset_means_no_trick_denials(self):
        (self.project / ".plainspoken" / "config.toml").write_text('[engine]\nprofile = "default"\n', encoding="utf-8")
        self.assertEqual(self.run_gate(command="$(echo git) push").stdout.strip(), "")


    def test_non_ascii_gated_path_is_checked(self):
        self.write_report()
        self.commit_file("docs/café.md", "Un café.\n")
        r = self.run_gate()
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("docs/café.md", self.reason(r))

    def test_unreadable_committed_blob_is_unverifiable_not_deleted(self):
        self.write_report()
        oid = subprocess.run(["git", "rev-parse", "HEAD:docs/post.md"], cwd=self.project, capture_output=True,
                             text=True, check=True).stdout.strip()
        (self.project / ".git" / "objects" / oid[:2] / oid[2:]).unlink()
        self.art.write_text("A local edit, so the committed blob must be read.\n", encoding="utf-8")
        r = self.run_gate()
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("can't verify docs/post.md", self.reason(r))

    def test_redirections_and_comments_do_not_break_refspecs(self):
        self.write_report()
        for cmd in ("git push origin main 2>&1", "git push origin main 2>/dev/null", "git push origin main > /tmp/log",
                    "git push origin main &>/dev/null", "git push origin main # deploy",
                    "git push origin main 2>&1 | tail -3", "git push -u origin main >>log 2>&1 # ship it"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_gate(command=cmd).stdout.strip(), "")
        self.assertEqual(_gate.scan("git push origin main 2>&1 # x", self.project), ([["origin", "main"]], []))

    def test_compound_commands_are_gated(self):
        for cmd in ("if true; then git push; fi", "{ git push; }", "timeout 60 git push", "timeout -s INT 60 git push",
                    "while true; do git push; done", "! git push", "time -p git push", "if git push; then echo ok; fi"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.decision(self.run_gate(command=cmd)), "deny")

    def test_markers_away_from_a_push_are_ignored(self):
        self.write_report()
        heredoc_commit = "git commit -m \"$(cat <<'EOF'\nfix(gate): don't push (yet)\nEOF\n)\""
        for cmd in ("git log --grep=push | xargs echo", "pushd x", 'git commit -m "push $(date)"',
                    "git log --oneline | xargs -n1 echo push", heredoc_commit, heredoc_commit + " && git push"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_gate(command=cmd).stdout.strip(), "")

    def test_markers_inside_a_push_still_deny(self):
        for cmd in ("echo $(git push)", "git push origin \"$(git branch --show-current)\"", "git $(echo push)"):
            with self.subTest(cmd=cmd):
                r = self.run_gate(command=cmd)
                self.assertEqual(self.decision(r), "deny")
                self.assertIn("can't be verified", r.stdout)

    def test_repo_option_both_spellings(self):
        other = self.tmp / "other.git"
        git("init", "--bare", "-q", "-b", "main", str(other), cwd=self.tmp)
        git("remote", "add", "other", str(other), cwd=self.project)
        git("config", "remote.other.push", "refs/heads/main:refs/heads/release", cwd=self.project)
        self.write_report()
        self.assertEqual(self.run_gate(command="git push").stdout.strip(), "")
        for cmd in ("git push --repo=other", "git push --repo other"):
            with self.subTest(cmd=cmd):
                r = self.run_gate(command=cmd)
                self.assertEqual(self.decision(r), "deny")
                self.assertIn("remote.other.push is configured", self.reason(r))

    def test_alias_chains_and_option_aliases(self):
        git("config", "alias.p1", "p2", cwd=self.project)
        git("config", "alias.p2", "push", cwd=self.project)
        git("config", "alias.fp", "-c push.default=current push", cwd=self.project)
        git("config", "alias.mp", "-c push.default=matching push", cwd=self.project)
        git("config", "alias.loop", "loop", cwd=self.project)
        self.assertEqual(self.decision(self.run_gate(command="git p1")), "deny")
        self.assertEqual(self.decision(self.run_gate(command="git fp")), "deny")
        self.write_report()
        self.assertEqual(self.run_gate(command="git p1").stdout.strip(), "")
        self.assertEqual(self.run_gate(command="git loop").stdout.strip(), "")
        self.assertIn("push.default is matching", self.reason(self.run_gate(command="git mp")))

    def test_shell_alias_expansion_is_parsed(self):
        self.branch_with_other_version()
        self.write_report()  # PASS for main's docs/post.md only
        git("config", "alias.sp2", "!git push origin feature:main", cwd=self.project)
        git("config", "alias.sp3", "!git push origin HEAD", cwd=self.project)
        r = self.run_gate(command="git sp2")
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("docs/post.md", self.reason(r))
        self.assertEqual(self.run_gate(command="git sp3").stdout.strip(), "")

    def test_dash_c_dir_in_another_repo_is_unverifiable(self):
        git("clone", "-q", str(self.remote), str(self.tmp / "other"), cwd=self.tmp)
        self.write_report()
        r = self.run_gate(command="git -C ../other push")
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("not this project's repository", self.reason(r))
        for cmd in ("git -C docs push", f"git -C {self.project} push", "git -C docs -C .. push"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_gate(command=cmd).stdout.strip(), "")

    def test_matching_push_default_and_remote_push_config_are_unverifiable(self):
        self.write_report()
        self.assertIn("push.default is matching",
                      self.reason(self.run_gate(command="git -c push.default=matching push")))
        git("config", "push.default", "matching", cwd=self.project)
        self.assertEqual(self.decision(self.run_gate()), "deny")
        self.assertEqual(self.run_gate(command="git push origin main").stdout.strip(), "")
        git("config", "--unset", "push.default", cwd=self.project)
        git("config", "remote.origin.push", "refs/heads/main:refs/heads/release", cwd=self.project)
        self.assertIn("remote.origin.push is configured", self.reason(self.run_gate()))

    def test_explicit_refspec_diffs_against_the_destination_tracking_ref(self):
        git("push", "-q", "origin", "main:release", cwd=self.project)  # release already has docs/post.md (no report)
        other = self.commit_file("docs/other.md", "Another post.\n")
        self.write_report(art=other)
        self.assertEqual(self.run_gate(command="git push origin main:release").stdout.strip(), "")
        self.assertIn("docs/post.md", self.reason(self.run_gate(command="git push origin main:main")))

    def test_explicit_refspec_without_a_tracking_ref_checks_the_whole_tree(self):
        git("push", "-q", "origin", "main", cwd=self.project)  # docs/post.md is already on origin/main, no report
        other = self.commit_file("docs/other.md", "Another post.\n")
        self.write_report(art=other)
        self.assertEqual(self.run_gate().stdout.strip(), "")  # upstream diff: only docs/other.md is new
        git("update-ref", "-d", "refs/remotes/origin/main", cwd=self.project)  # no destination, HEAD, main or master
        r = self.run_gate(command="git push origin main:brandnew")
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("docs/post.md", self.reason(r))

    def test_report_hash_uses_the_working_tree_when_git_filters_differ(self):
        self.art.write_bytes(b"line one\nline two\n")
        git("add", ".", cwd=self.project); git("commit", "-qm", "lf", cwd=self.project)
        git("config", "core.autocrlf", "true", cwd=self.project)
        self.art.unlink()
        git("checkout", "--", "docs/post.md", cwd=self.project)
        self.assertIn(b"\r\n", self.art.read_bytes())
        self.write_report()  # the hash of the CRLF bytes the check read
        self.assertEqual(self.run_gate().stdout.strip(), "")


    def new_branch_on_top_of_origin_head(self):
        git("push", "-q", "origin", "main", cwd=self.project)  # docs/post.md predates the gate: on origin, no report
        git("remote", "set-head", "origin", "main", cwd=self.project)
        git("checkout", "-q", "-b", "topic", cwd=self.project)
        return self.commit_file("docs/new.md", "A new post.\n")

    def test_new_branch_push_diffs_against_the_remote_default_branch(self):
        self.write_report(art=self.new_branch_on_top_of_origin_head())
        for cmd in ("git push -u origin HEAD", "git push -u origin topic"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.run_gate(command=cmd).stdout.strip(), "")

    def test_new_branch_push_with_an_unchecked_new_file_is_denied(self):
        self.new_branch_on_top_of_origin_head()
        r = self.run_gate(command="git push -u origin HEAD")
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("docs/new.md", self.reason(r))
        self.assertNotIn("docs/post.md", self.reason(r))

    def test_first_push_fallback_lists_the_committed_tree(self):
        self.write_report()
        self.commit_file("docs/second.md", "Committed, unchecked.\n").unlink()  # deleted in the working tree only
        git("branch", "--unset-upstream", cwd=self.project)
        git("remote", "remove", "origin", cwd=self.project)
        r = self.run_gate()
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("docs/second.md", self.reason(r))


    def test_new_branch_without_origin_head_diffs_against_origin_main_or_master(self):
        git("push", "-q", "origin", "main", cwd=self.project)  # docs/post.md is on origin/main, no report
        git("remote", "set-head", "origin", "-d", cwd=self.project)
        git("checkout", "-q", "-b", "feat", cwd=self.project)
        new = self.commit_file("docs/new.md", "A new post.\n")
        self.assertEqual(self.decision(self.run_gate(command="git push -u origin feat")), "deny")  # new.md unchecked
        self.assertNotIn("docs/post.md", self.reason(self.run_gate(command="git push -u origin feat")))
        self.write_report(art=new)
        self.assertEqual(self.run_gate(command="git push -u origin feat").stdout.strip(), "")
        git("push", "-q", "origin", "main:master", cwd=self.project)
        git("update-ref", "-d", "refs/remotes/origin/main", cwd=self.project)
        self.assertEqual(self.run_gate(command="git push -u origin feat").stdout.strip(), "")  # via origin/master

    def test_bare_push_fallback_uses_the_resolved_remote(self):
        git("push", "-q", "origin", "main", cwd=self.project)
        git("remote", "rename", "origin", "up", cwd=self.project)
        git("config", "remote.pushDefault", "up", cwd=self.project)
        git("checkout", "-q", "-b", "feat", cwd=self.project)  # no upstream, nothing on up/feat
        self.write_report(art=self.commit_file("docs/new.md", "A new post.\n"))
        self.assertEqual(self.run_gate().stdout.strip(), "")  # diffed against up/main, not the whole tree

    # ---- [gate] strictness in the project config -----------------------------------------------------------------

    def set_strictness(self, value: str) -> None:
        (self.project / ".plainspoken" / "config.toml").write_text(
            f'[engine]\nprofile = "default"\n[gate]\npaths = ["docs/**/*.md"]\nstrictness = {value}\n',
            encoding="utf-8")

    def test_project_config_strictness_without_the_plugin_option(self):
        self.set_strictness('"block"')
        self.assertEqual(self.decision(self.run_gate(None)), "deny")
        self.set_strictness('"warn"')
        self.assertIn("systemMessage", json.loads(self.run_gate(None).stdout))

    def test_project_config_strictness_beats_the_plugin_option(self):
        self.set_strictness('"watch"')
        self.assertEqual(self.run_gate("block").stdout.strip(), "")

    def write_config(self, text: str) -> None:
        (self.project / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def test_bad_strictness_value_warns_and_never_denies(self):
        self.set_strictness('"blok"')
        out = self.out(self.run_gate(None))
        self.assertNotIn("hookSpecificOutput", out)
        self.assertIn("strictness", out["systemMessage"])
        self.assertIn("not checking this push", out["systemMessage"])
        self.assertEqual(self.run_gate(None, command="git status").stdout.strip(), "")

    def test_invalid_toml_warns_and_never_denies(self):
        self.write_config("[gate\n")
        out = self.out(self.run_gate(None))
        self.assertNotIn("hookSpecificOutput", out)
        self.assertIn("not valid TOML", out["systemMessage"])

    def test_bad_config_with_watch_in_the_file_is_silent(self):
        self.write_config('[gate]\nstrictness = "watch"\ncolour = "red"\n')
        self.assertEqual(self.run_gate(None).stdout.strip(), "")

    def test_bad_config_denies_when_the_file_says_block(self):
        self.write_config('[gate]\nstrictness = "block"\npaths = ["docs/**/*.md"]\ncolour = "red"\n')
        r = self.run_gate(None)
        self.assertEqual(self.decision(r), "deny")
        self.assertIn("can't read the gate settings", self.reason(r))

    def test_bad_config_saying_block_is_silent_on_a_non_push(self):
        self.write_config('[gate]\nstrictness = "block"\npaths = ["docs/**/*.md"]\ncolour = "red"\n')
        for command in ("git status", "git log --oneline"):
            r = self.run_gate(None, command=command)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), command)

    def test_bad_config_denies_when_the_plugin_option_is_block(self):
        self.write_config("[gate\n")
        self.assertEqual(self.decision(self.run_gate("block")), "deny")

    def test_stale_profile_hint_names_engine_profile(self):
        self.write_report(profile_sha256="0" * 64)
        reason = self.reason(self.run_gate())
        self.assertIn("[engine] profile", reason)
        # README §Host setup / claude-code-facts §11: only a --plugin-dir session's hooks miss the plugin settings
        self.assertIn("--plugin-dir", reason)
        self.assertNotIn("hooks may not see plugin settings", reason)
