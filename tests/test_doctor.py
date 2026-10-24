"""`doctor` and the host checks `setup` prints (#113): warnings only, nothing written, never `ok` for what a script
can't see."""
import io
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from plainspoken import __main__ as cli_main
from plainspoken import doctor, setup
from tests.test_cli import cli

HELP_ALL = ("usage: hermes chat [-h] [-q QUERY] [--query-file FILE] [--oneshot] [-Q] [-t TOOLSETS]\n"
            "  --source SOURCE  where the session came from\n")
HELP_NO_SOURCE = "usage: hermes chat [-h] [--query-file FILE] [--oneshot] [--sources-dir DIR]\n"


def done(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class Fakes:
    """Patch PATH lookups, commands and os.access for one test. `bins` maps a command to its path (absent = not on
    PATH); `outputs` maps a command's argv tail (as a tuple) to its CompletedProcess."""

    def __init__(self, case: unittest.TestCase, bins: dict | None = None, outputs: dict | None = None,
                 writable: bool = True):
        self.bins = {"python3": "/usr/bin/python3", "git": "/usr/bin/git"} if bins is None else bins
        self.outputs = {("python3", "--version"): done("Python 3.12.1\n")} if outputs is None else outputs
        self.calls: list[tuple[list[str], dict]] = []
        self.writable = writable
        for target, fn in (("plainspoken.doctor.shutil.which", self.which),
                           ("plainspoken.doctor.subprocess.run", self.run),
                           ("plainspoken.doctor.os.access", self.access)):
            p = mock.patch(target, side_effect=fn)
            p.start()
            case.addCleanup(p.stop)

    def which(self, cmd, path=None):
        return self.bins.get(cmd)

    def run(self, args, **kw):
        self.calls.append((list(args), kw))
        name = Path(args[0]).name
        key = (name, *args[1:])
        if key not in self.outputs:
            raise AssertionError(f"unexpected command {args}")
        out = self.outputs[key]
        if isinstance(out, BaseException):
            raise out
        return out

    def access(self, path, mode):
        return self.writable


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        (self.root / ".git").mkdir()
        self.env = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"), "PATH": "/nowhere"}

    def checks(self, host: str) -> dict[str, doctor.Check]:
        return {c.name: c for c in doctor.run_checks(host, self.root, self.env)}

    def write_project_config(self, text: str) -> None:
        (self.root / ".plainspoken").mkdir(exist_ok=True)
        (self.root / ".plainspoken" / "config.toml").write_text(text, encoding="utf-8")

    def write_user_config(self, text: str) -> None:
        path = self.home / ".config" / "plainspoken" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class ShellChecks(Base):
    def test_python3_ok_old_and_missing(self):
        Fakes(self)
        c = self.checks("claude-code")["python3"]
        self.assertEqual(c.status, "ok")
        self.assertIn("3.12.1", c.detail)
        self.assertEqual(c.fix, "")

    def test_python3_older_than_311_warns(self):
        Fakes(self, outputs={("python3", "--version"): done("", stderr="Python 3.10.4\n")})
        c = self.checks("codex")["python3"]
        self.assertEqual(c.status, "WARN")
        self.assertIn("3.10.4", c.detail)
        self.assertIn("3.11", c.fix)

    def test_python3_missing_warns(self):
        Fakes(self, bins={"git": "/usr/bin/git"}, outputs={})
        c = self.checks("hermes")["python3"]
        self.assertEqual(c.status, "WARN")
        self.assertIn("PATH", c.detail)
        self.assertIn("3.11", c.fix)

    def test_python3_version_unreadable_is_not_checked(self):
        Fakes(self, outputs={("python3", "--version"): done("something else\n")})
        self.assertEqual(self.checks("claude-code")["python3"].status, "not checked")

    def test_plugin_files_present_and_missing(self):
        Fakes(self)
        self.assertEqual(self.checks("claude-code")["plugin files"].status, "ok")
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        with mock.patch("plainspoken.doctor.plugin_root", return_value=empty):
            c = self.checks("claude-code")["plugin files"]
        self.assertEqual(c.status, "WARN")
        for part in ("lib/run.py", "data/rules.toml", "skills/"):
            self.assertIn(part, c.detail)

    def test_reports_folder_writable_or_not_and_nothing_created(self):
        Fakes(self)
        self.assertEqual(self.checks("claude-code")["reports folder"].status, "ok")
        Fakes(self, writable=False)
        c = self.checks("claude-code")["reports folder"]
        self.assertEqual(c.status, "WARN")
        self.assertIn(".plainspoken", c.detail)
        self.assertTrue(c.fix)
        self.assertFalse((self.root / ".plainspoken").exists())

    def test_git_missing_warns_only_when_the_gate_is_on(self):
        Fakes(self, bins={"python3": "/usr/bin/python3"})
        self.assertEqual(self.checks("claude-code")["git"].status, "ok")
        self.write_project_config('[gate]\npaths = ["posts/*.md"]\nstrictness = "block"\n')
        c = self.checks("claude-code")["git"]
        self.assertEqual(c.status, "WARN")
        self.assertIn("block", c.detail)
        self.assertIn("git", c.fix)

    def test_git_present_is_ok(self):
        Fakes(self)
        self.write_project_config('[gate]\npaths = ["posts/*.md"]\nstrictness = "warn"\n')
        self.assertEqual(self.checks("codex")["git"].status, "ok")

    def test_configs_parse_or_warn_with_the_first_line(self):
        Fakes(self)
        found = self.checks("claude-code")
        self.assertEqual((found["project config"].status, found["user-wide config"].status), ("ok", "ok"))
        self.write_project_config("[nudge\n")
        self.write_user_config('[engine]\nprofile = "x"\n')
        found = self.checks("claude-code")
        self.assertEqual(found["project config"].status, "WARN")
        self.assertIn("not valid TOML", found["project config"].detail)
        self.assertEqual(found["user-wide config"].status, "WARN")
        self.assertIn("unknown section [engine]", found["user-wide config"].detail)
        self.assertNotIn("\n", found["project config"].detail)


class HostChecks(Base):
    def test_claude_code_agents_and_bash_permission(self):
        Fakes(self)
        found = self.checks("claude-code")
        self.assertEqual(found["plugin agents"].status, "ok")
        perm = found["Bash permission"]
        self.assertEqual(perm.status, "not checked")
        self.assertEqual(perm.fix, f"allow Bash to run python3 {doctor.plugin_root()}/lib/run.py")
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        with mock.patch("plainspoken.doctor.plugin_root", return_value=empty):
            c = self.checks("claude-code")["plugin agents"]
        self.assertEqual(c.status, "WARN")
        self.assertIn("tells-judge", c.detail)

    def test_codex_cli_found_or_not_checked(self):
        Fakes(self, bins={"python3": "/usr/bin/python3", "git": "/usr/bin/git", "codex": "/opt/bin/codex"},
              outputs={("python3", "--version"): done("Python 3.12.1\n")})
        found = self.checks("codex")  # never run: even `codex --version` writes helper files under ~/.codex
        self.assertEqual(found["codex CLI"].status, "ok")
        self.assertIn("/opt/bin/codex", found["codex CLI"].detail)
        for name, needle in (("hooks trusted", "/hooks"), ("sandbox writes", ".plainspoken/reports"),
                             ("judges", "spawn_agent")):
            self.assertEqual(found[name].status, "not checked", name)
            self.assertIn(needle, found[name].detail + found[name].fix, name)
        Fakes(self)
        self.assertEqual(self.checks("codex")["codex CLI"].status, "not checked")

    def hermes(self, help_text: str):
        return Fakes(self, bins={"python3": "/usr/bin/python3", "git": "/usr/bin/git", "hermes": "/opt/bin/hermes"},
                     outputs={("python3", "--version"): done("Python 3.12.1\n"),
                              ("hermes", "chat", "--help"): done(help_text)})

    def test_hermes_flags_all_listed(self):
        self.hermes(HELP_ALL)
        found = self.checks("hermes")
        self.assertEqual(found["hermes CLI"].status, "ok")
        for flag in doctor.HERMES_FLAGS:
            self.assertEqual(found[f"hermes chat {flag}"].status, "ok", flag)

    def test_hermes_missing_source_warns_naming_it(self):
        self.hermes(HELP_NO_SOURCE)
        found = self.checks("hermes")
        c = found["hermes chat --source"]
        self.assertEqual(c.status, "WARN")
        self.assertIn("--source", c.detail)
        self.assertTrue(c.fix)
        self.assertEqual(found["hermes chat --query-file"].status, "ok")
        self.assertEqual(found["hermes chat --oneshot"].status, "ok")
        line = "\n".join(doctor.format(list(found.values())))
        self.assertRegex(line, r"WARN\s+hermes chat --source: .*--source.* → ")

    def test_hermes_missing(self):
        Fakes(self)
        found = self.checks("hermes")
        self.assertEqual(found["hermes CLI"].status, "WARN")
        for flag in doctor.HERMES_FLAGS:
            self.assertEqual(found[f"hermes chat {flag}"].status, "not checked", flag)

    def test_hermes_profile_user_config_and_toolsets(self):
        self.hermes(HELP_ALL)
        found = self.checks("hermes")
        self.assertIn("not set (the sticky active profile applies)", found["Hermes profile"].detail)
        self.assertNotEqual(found["Hermes profile"].status, "ok")
        self.assertEqual(found["user-wide config"].status, "WARN")
        self.assertIn("--scope user", found["user-wide config"].fix)
        tools = found["toolsets"]
        self.assertEqual(tools.status, "not checked")
        for tool in ("terminal", "read_file", "write_file", "patch", "delegate_task"):
            self.assertIn(tool, tools.detail)
        self.env["HERMES_HOME"] = str(self.home / ".hermes" / "profiles" / "work")
        self.write_user_config('[nudge]\nmode = "on"\n')
        found = self.checks("hermes")
        self.assertEqual(found["Hermes profile"].status, "ok")
        self.assertIn(self.env["HERMES_HOME"], found["Hermes profile"].detail)
        self.assertEqual(found["user-wide config"].status, "ok")

    def test_user_config_missing_is_fine_off_hermes(self):
        Fakes(self)
        self.assertEqual(self.checks("codex")["user-wide config"].status, "ok")

    def test_chat_hosts_run_nothing_and_say_so(self):
        Fakes(self, bins={}, outputs={})
        for host in ("claude-ai", "chatgpt"):
            with self.subTest(host=host):
                found = doctor.run_checks(host, self.root, self.env)
                self.assertTrue(found)
                self.assertEqual({c.status for c in found}, {"not checked"})
                text = " ".join(c.detail for c in found)
                for needle in ("no shell", "lint", "judges", "hooks", "guidance"):
                    self.assertIn(needle, text)

    def test_only_short_read_only_commands(self):
        f = Fakes(self, bins={"python3": "/usr/bin/python3", "git": "/usr/bin/git", "hermes": "/h", "codex": "/c"},
                  outputs={("python3", "--version"): done("Python 3.12.1\n"), ("hermes", "chat", "--help"):
                           done(HELP_ALL)})
        for host in setup.HOSTS:
            doctor.run_checks(host, self.root, self.env)
        self.assertTrue(f.calls)
        for args, kw in f.calls:
            self.assertIn(args[-1], ("--version", "--help"), args)
            self.assertLessEqual(kw.get("timeout", 99), 10, args)


class Failures(Base):
    def test_a_check_that_raises_is_not_checked_without_a_traceback(self):
        Fakes(self)
        with mock.patch("plainspoken.doctor.shutil.which", side_effect=RuntimeError("tok-123 secret")):
            found = self.checks("claude-code")
        c = found["python3"]
        self.assertEqual(c.status, "not checked")
        self.assertIn("RuntimeError", c.detail)
        text = "\n".join(doctor.format(list(found.values())))
        self.assertNotIn("tok-123", text)
        self.assertNotIn("Traceback", text)

    def test_a_timeout_is_not_checked(self):
        Fakes(self, outputs={("python3", "--version"): subprocess.TimeoutExpired(["python3"], 10)})
        c = self.checks("claude-code")["python3"]
        self.assertEqual(c.status, "not checked")
        self.assertIn("timed out", c.detail)

    def test_format_layout_and_summary(self):
        rows = [doctor.Check("a", "ok", "fine"), doctor.Check("b", "WARN", "broken", "mend it"),
                doctor.Check("c", "not checked", "can't see", "confirm it")]
        lines = doctor.format(rows)
        self.assertEqual(lines[0], "  ok           a: fine")
        self.assertEqual(lines[1], "  WARN         b: broken → mend it")
        self.assertEqual(lines[2], "  not checked  c: can't see → confirm it")
        self.assertEqual(doctor.summary(rows), "1 ok · 1 WARN · 1 not checked")


def tree(*folders: Path) -> dict[str, bytes]:
    out = {}
    for folder in folders:
        for p in sorted(folder.rglob("*")):
            out[str(p)] = p.read_bytes() if p.is_file() else b"<dir>"
    return out


class Command(Base):
    def run_cli(self, *args, env=None):
        """The CLI with the real PATH (so the real python3, git, codex and hermes are looked up), unless `env` sets
        one."""
        return cli(*args, cwd=self.root, env={**self.env, "PATH": os.environ.get("PATH", ""), **(env or {})})

    def test_doctor_writes_nothing_on_any_host(self):
        before = tree(self.root, self.home)
        for host in setup.HOSTS:
            with self.subTest(host=host):
                r = self.run_cli("doctor", "--host", host)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(r.stdout.startswith(f"plainspoken doctor · {host} · checks only, nothing changed\n"))
                self.assertRegex(r.stdout.strip().splitlines()[-1], r"^\d+ ok · \d+ WARN · \d+ not checked$")
                self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertEqual(tree(self.root, self.home), before)

    def test_chat_hosts_print_the_no_shell_lines(self):
        for host in ("claude-ai", "chatgpt"):
            r = self.run_cli("doctor", "--host", host)
            body = r.stdout.splitlines()[1:-1]
            self.assertTrue(body)
            self.assertTrue(all(line.startswith("  not checked  ") for line in body), body)
            self.assertIn("no shell", r.stdout)
            self.assertIn("0 ok · 0 WARN", r.stdout)
        self.assertFalse((self.root / ".plainspoken").exists())

    def test_warnings_exit_0_and_a_bad_host_exits_2(self):
        bin_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bin_dir, ignore_errors=True)
        fake = bin_dir / "hermes"
        fake.write_text(f"#!/bin/sh\nprintf '%s' '{HELP_NO_SOURCE}'\n", encoding="utf-8")
        fake.chmod(0o755)
        r = self.run_cli("doctor", "--host", "hermes", env={"PATH": str(bin_dir)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"WARN\s+hermes chat --source: ")
        self.assertRegex(r.stdout, r"WARN\s+python3: ")  # no python3 on that PATH
        self.assertEqual(self.run_cli("doctor", "--host", "nope").returncode, 2)

    def test_json(self):
        r = self.run_cli("doctor", "--host", "codex", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(set(row), {"name", "status", "detail", "fix"})
            self.assertIn(row["status"], doctor.STATUSES)


class SetupPrintsWarnings(Base):
    """setup runs the same checks after its normal output; its file and exit code don't change."""

    def main(self, *argv: str, checks=None, raises: bool = False) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_", "CLAUDE_PROJECT_DIR"))}
        env.update(self.env)
        old = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, old)
        side = RuntimeError("boom") if raises else None
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("plainspoken.doctor.run_checks", return_value=checks or [], side_effect=side), \
                redirect_stdout(out), redirect_stderr(err):
            rc = cli_main.main(["setup", *argv])
        os.chdir(old)
        return rc, out.getvalue(), err.getvalue()

    WARN = [doctor.Check("python3", "WARN", "no python3 on PATH", "install Python 3.11 or later"),
            doctor.Check("git", "ok", "found"),
            doctor.Check("Bash permission", "not checked", "can't see it", "allow Bash")]

    def config(self) -> str:
        return (self.root / ".plainspoken" / "config.toml").read_text(encoding="utf-8")

    def test_apply_prints_warnings_after_and_writes_the_same_file(self):
        args = ("--host", "claude-code", "--nudge", "on", "--rule", "on")
        rc_clean, out_clean, _ = self.main(*args)
        clean = self.config()
        shutil.rmtree(self.root / ".plainspoken")
        rc, out, _ = self.main(*args, checks=self.WARN)
        self.assertEqual((rc, self.config()), (rc_clean, clean))
        self.assertTrue(out.startswith(out_clean), out)
        tail = out[len(out_clean):]
        self.assertIn("Host checks (warnings only; setup changed nothing because of them):", tail)
        self.assertIn("WARN         python3: no python3 on PATH → install Python 3.11 or later", tail)
        self.assertNotIn("git: found", tail)
        self.assertIn("1 check needs you to confirm: run doctor --host claude-code", tail)
        self.assertEqual(tomllib.loads(clean)["nudge"]["mode"], "on")

    def test_every_path_prints_them_and_keeps_its_exit_code(self):
        for args in (("--host", "codex", "--status"), ("--host", "codex", "--nudge", "on", "--dry-run"),
                     ("--host", "hermes", "--scope", "user", "--remove"), ("--host", "codex", "--rule", "on")):
            with self.subTest(args=args):
                rc_clean, out_clean, err_clean = self.main(*args)
                rc, out, err = self.main(*args, checks=self.WARN)
                self.assertEqual((rc, err), (rc_clean, err_clean))
                self.assertTrue(out.startswith(out_clean))
                self.assertIn("WARN         python3:", out[len(out_clean):])
        self.assertFalse((self.root / ".plainspoken").exists())

    def test_clean_checks_add_nothing(self):
        _, out, _ = self.main("--host", "codex", "--status",
                              checks=[doctor.Check("git", "ok", "found")])
        self.assertNotIn("Host checks", out)

    def test_a_check_that_raises_never_changes_setup(self):
        rc_clean, out_clean, _ = self.main("--host", "claude-code", "--nudge", "on")
        clean = self.config()
        shutil.rmtree(self.root / ".plainspoken")
        rc, out, _ = self.main("--host", "claude-code", "--nudge", "on", raises=True)
        self.assertEqual((rc, out, self.config()), (rc_clean, out_clean, clean))

    def test_chat_hosts_print_the_no_shell_lines_after_the_paste_text(self):
        rc, out, _ = self.main("--host", "chatgpt", checks=doctor.run_checks("chatgpt", self.root, self.env))
        self.assertEqual(rc, 0)
        paste = out.index("Custom instructions")
        self.assertGreater(out.index("no shell"), paste)
        self.assertFalse((self.root / ".plainspoken").exists())

    def test_real_checks_through_the_cli(self):
        r = cli("setup", "--host", "codex", "--status", cwd=self.root, env={**self.env, "PATH": "/nowhere"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"lint after edits: on\n\nHost checks")
        self.assertRegex(r.stdout, r"WARN\s+python3: ")


if __name__ == "__main__":
    unittest.main()
