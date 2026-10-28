"""`doctor` and the host checks `setup` prints (#113): warnings only, nothing written, never `ok` for what a script
can't see, and the only command run is `python3 --version`."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from plainspoken import __main__ as cli_main
from plainspoken import doctor, setup
from tests.test_cli import REPO, cli

PY = "/usr/bin/python3"


def done(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class Fakes:
    """Patch PATH lookups, the one command doctor runs, and os.access for one test. `bins` maps a command to its path
    (absent = not on PATH); `version` is what `python3 --version` gives (a CompletedProcess or an exception)."""

    def __init__(self, case: unittest.TestCase, bins: dict | None = None, version=None, writable: bool = True):
        self.bins = {"python3": PY, "git": "/usr/bin/git"} if bins is None else bins
        self.version = done("Python 3.12.1\n") if version is None else version
        self.calls: list[list[str]] = []
        self.writable = writable
        for target, fn in (("plainspoken.doctor.shutil.which", self.which), ("plainspoken.doctor._run", self.run),
                           ("plainspoken.doctor.os.access", self.access)):
            p = mock.patch(target, side_effect=fn)
            p.start()
            case.addCleanup(p.stop)

    def which(self, cmd, path=None):
        return self.bins.get(cmd)

    def run(self, args, env):
        self.calls.append(list(args))
        if list(args) != [self.bins.get("python3"), "--version"]:
            raise AssertionError(f"doctor may only run python3 --version, not {args}")
        if isinstance(self.version, BaseException):
            raise self.version
        return self.version

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
        self.assertEqual((c.status, c.fix), ("ok", ""))
        self.assertIn("3.12.1", c.detail)
        # older than 3.11 (some pythons print the version on stderr)
        Fakes(self, version=done("", stderr="Python 3.10.4\n"))
        c = self.checks("codex")["python3"]
        self.assertEqual(c.status, "WARN")
        self.assertIn("3.10.4", c.detail)
        self.assertIn("3.11", c.fix)
        # not on PATH at all
        f = Fakes(self, bins={"git": "/usr/bin/git"})
        c = self.checks("hermes")["python3"]
        self.assertEqual(c.status, "WARN")
        self.assertIn("PATH", c.detail)
        self.assertIn("3.11", c.fix)
        self.assertEqual(f.calls, [])

    def test_python3_version_unreadable_is_not_checked(self):
        Fakes(self, version=done("something else\n"))
        c = self.checks("claude-code")["python3"]
        self.assertEqual(c.status, "not checked")
        self.assertFalse(c.static)

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

    def test_reports_folder_permissions_and_nothing_created(self):
        Fakes(self)
        c = self.checks("claude-code")["reports folder"]
        self.assertEqual(c.status, "ok")
        self.assertIn("file permissions allow", c.detail)
        self.assertNotIn("is writable", c.detail)
        Fakes(self, writable=False)
        c = self.checks("claude-code")["reports folder"]
        self.assertEqual(c.status, "WARN")
        self.assertIn(".plainspoken", c.detail)
        self.assertTrue(c.fix)
        self.assertFalse((self.root / ".plainspoken").exists())

    def test_git_missing_warns_only_when_the_gate_is_on(self):
        Fakes(self, bins={"python3": PY})
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


class LocaleRow(Base):  # #121: the resolved locale and where it came from; the system locale is a hint only
    def row(self, env=None, plugin_locale=None, host="claude-code") -> doctor.Check:
        Fakes(self)
        found = {c.name: c for c in doctor.run_checks(host, self.root, {**self.env, **(env or {})},
                                                      plugin_locale=plugin_locale)}
        return found["locale"]

    def test_each_source(self):
        self.assertTrue(self.row(plugin_locale="en-US").detail.startswith("en-US (plugin option)"))
        self.assertTrue(self.row().detail.startswith("en-AU (default)"))
        self.write_user_config('[locale]\nvariant = "en-GB"\n')
        self.assertTrue(self.row(plugin_locale="en-US").detail.startswith("en-GB (user-wide config, "))
        self.write_project_config('[locale]\nvariant = "en-US"\n')
        self.assertTrue(self.row().detail.startswith("en-US (project config, .plainspoken/config.toml)"))
        (self.root / ".plainspoken" / "profiles").mkdir()
        (self.root / ".plainspoken" / "profiles" / "mine.toml").write_text(
            '[profile]\nname = "mine"\nlocale = "en-GB"\n', encoding="utf-8")
        self.write_project_config('[engine]\nprofile = "mine"\n')
        self.assertTrue(self.row().detail.startswith("en-GB (profile)"))

    def test_hint_when_the_system_suggests_another_variant(self):
        c = self.row(env={"LANG": "en_US.UTF-8"})
        self.assertEqual(c.status, "ok")
        self.assertIn("en_US.UTF-8", c.detail)
        self.assertIn("suggests en-US", c.detail)
        self.assertIn('[locale] variant = "en-US"', c.fix)
        self.assertIn(str(self.home / ".config" / "plainspoken" / "config.toml"), c.fix)

    def test_lc_all_beats_lc_messages_beats_lang(self):
        self.assertIn("suggests en-GB", self.row(env={"LC_ALL": "en_GB.UTF-8", "LANG": "en_US.UTF-8"}).detail)
        self.assertIn("suggests en-US", self.row(env={"LC_MESSAGES": "en_US", "LANG": "en_GB.UTF-8"}).detail)
        self.assertIn("suggests en-US", self.row(env={"LC_ALL": "", "LANG": "en_US.utf8@euro"}).detail)

    def test_matching_system_locale_has_no_fix(self):
        c = self.row(env={"LANG": "en_AU.UTF-8"})
        self.assertEqual((c.status, c.fix), ("ok", ""))
        self.assertNotIn("suggests", c.detail)

    def test_no_suggestion_for_other_or_unset_locales(self):
        for value in ("C.UTF-8", "POSIX", "C", "en_NZ.UTF-8", "fr_FR.UTF-8"):
            with self.subTest(lang=value):
                c = self.row(env={"LANG": value})
                self.assertNotIn("suggests", c.detail)
                self.assertEqual(c.fix, "")
        c = self.row()
        self.assertEqual(c.status, "not checked")
        self.assertIn("isn't set", c.detail)

    def test_the_fix_names_the_file_that_wins(self):
        self.write_project_config('[locale]\nvariant = "en-AU"\n')
        self.assertIn(".plainspoken/config.toml", self.row(env={"LANG": "en_GB.UTF-8"}).fix)

    def test_never_warn(self):
        for env in ({}, {"LANG": "en_US.UTF-8"}, {"LANG": "C.UTF-8"}, {"LC_ALL": "en_GB.UTF-8"}):
            for plugin in (None, "en-US", "en-NZ", "${user_config.locale}"):
                with self.subTest(env=env, plugin=plugin):
                    self.assertNotEqual(self.row(env=env, plugin_locale=plugin).status, "WARN")

    def test_every_shell_host_has_the_row_and_chat_hosts_none(self):
        for host in ("codex", "hermes"):
            self.assertEqual(self.row(host=host).name, "locale")
        self.assertNotIn("locale", {c.name for c in doctor.run_checks("claude-ai", self.root, self.env)})

    def test_setup_never_shows_the_row(self):
        checks = [doctor.Check("locale", "not checked", "en-AU (default); the system locale isn't set")]
        self.assertEqual(doctor.setup_lines("codex", checks), [])

    def test_cli_passes_the_plugin_locale(self):
        r = cli("doctor", "--host", "claude-code", "--plugin-profile", "default", "--plugin-locale", "en-GB",
                cwd=self.root, env={**self.env, "PATH": os.environ.get("PATH", "")})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"\n  (ok|not checked)\s+locale: en-GB \(plugin option\)")


STATIC = {
    "claude-code": {"Bash permission"},
    "codex": {"hooks trusted", "sandbox writes", "judges"},
    "hermes": {"hermes chat --query-file", "hermes chat --oneshot", "hermes chat --source", "Hermes profile",
               "working folder", "toolsets"},
}


class HostChecks(Base):
    def test_claude_code_agents_and_bash_permission(self):
        Fakes(self)
        found = self.checks("claude-code")
        self.assertEqual(found["plugin agents"].status, "ok")
        perm = found["Bash permission"]
        self.assertEqual((perm.status, perm.static), ("not checked", True))
        self.assertEqual(perm.fix, f"allow Bash to run python3 {doctor.plugin_root()}/lib/run.py")
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        with mock.patch("plainspoken.doctor.plugin_root", return_value=empty):
            c = self.checks("claude-code")["plugin agents"]
        self.assertEqual(c.status, "WARN")
        self.assertIn("tells-judge", c.detail)

    def test_by_design_rows_are_static(self):
        Fakes(self, bins={"python3": PY, "git": "/usr/bin/git", "codex": "/opt/bin/codex", "hermes": "/opt/bin/h"})
        for host, names in STATIC.items():
            with self.subTest(host=host):
                found = self.checks(host)
                self.assertEqual({n for n, c in found.items() if c.static}, names)
                for name in names:
                    self.assertEqual(found[name].status, "not checked", name)
                    self.assertTrue(found[name].fix, name)

    def test_codex_cli_found_or_not_checked(self):
        f = Fakes(self, bins={"python3": PY, "git": "/usr/bin/git", "codex": "/opt/bin/codex"})
        found = self.checks("codex")  # never run: even `codex --version` writes helper files under ~/.codex
        self.assertEqual(found["codex CLI"].status, "ok")
        self.assertIn("/opt/bin/codex", found["codex CLI"].detail)
        self.assertEqual(f.calls, [[PY, "--version"]])
        for name, needle in (("hooks trusted", "/hooks"), ("hooks trusted", "every plugin update"),
                             ("sandbox writes", ".plainspoken/reports"), ("judges", "spawn_agent")):
            self.assertEqual(found[name].status, "not checked", name)
            self.assertIn(needle, found[name].detail + found[name].fix, name)
        Fakes(self)
        c = self.checks("codex")["codex CLI"]
        self.assertEqual((c.status, c.static), ("not checked", True))

    def test_hermes_found_is_never_run_and_the_flags_are_left_to_confirm(self):
        f = Fakes(self, bins={"python3": PY, "git": "/usr/bin/git", "hermes": "/opt/bin/hermes"})
        found = self.checks("hermes")
        self.assertEqual(found["hermes CLI"].status, "ok")
        self.assertEqual(f.calls, [[PY, "--version"]])
        for flag in doctor.HERMES_FLAGS:
            c = found[f"hermes chat {flag}"]
            self.assertEqual((c.status, c.static), ("not checked", True), flag)
            self.assertEqual(c.fix, "confirm `hermes chat --help` lists --query-file, --oneshot and --source")

    def test_hermes_missing(self):
        Fakes(self)
        found = self.checks("hermes")
        self.assertEqual(found["hermes CLI"].status, "WARN")
        for flag in doctor.HERMES_FLAGS:
            self.assertEqual(found[f"hermes chat {flag}"].status, "not checked", flag)
            self.assertIn("no hermes on PATH", found[f"hermes chat {flag}"].detail)

    def test_hermes_profile_user_config_and_toolsets(self):
        Fakes(self, bins={"python3": PY, "git": "/usr/bin/git", "hermes": "/opt/bin/hermes"})
        found = self.checks("hermes")
        self.assertIn("not set (the sticky active profile applies)", found["Hermes profile"].detail)
        self.assertEqual(found["Hermes profile"].status, "not checked")
        self.assertEqual(found["user-wide config"].status, "WARN")
        self.assertIn("--scope user", found["user-wide config"].fix)
        tools = found["toolsets"]
        self.assertEqual(tools.status, "not checked")
        for tool in ("terminal", "read_file", "write_file", "patch", "delegate_task"):
            self.assertIn(tool, tools.detail)
        profile = self.home / ".hermes" / "profiles" / "work"
        self.env["HERMES_HOME"] = str(profile)
        c = self.checks("hermes")["Hermes profile"]  # set, but no such folder
        self.assertEqual((c.status, c.static), ("WARN", False))
        self.assertIn("isn't a folder", c.detail)
        profile.mkdir(parents=True)
        self.write_user_config('[nudge]\nmode = "on"\n')
        found = self.checks("hermes")
        self.assertEqual(found["Hermes profile"].status, "ok")
        self.assertIn(str(profile), found["Hermes profile"].detail)
        self.assertEqual(found["user-wide config"].status, "ok")

    def test_user_config_missing_is_fine_off_hermes(self):
        Fakes(self)
        self.assertEqual(self.checks("codex")["user-wide config"].status, "ok")

    def test_chat_hosts_run_nothing_and_say_so(self):
        f = Fakes(self, bins={})
        for host in ("claude-ai", "chatgpt"):
            with self.subTest(host=host):
                found = doctor.run_checks(host, self.root, self.env)
                self.assertTrue(found)
                self.assertEqual({c.status for c in found}, {"not checked"})
                text = " ".join(c.detail for c in found)
                for needle in ("no shell", "lint", "judges", "hooks", "guidance"):
                    self.assertIn(needle, text)
        self.assertEqual(f.calls, [])

    def test_the_only_command_is_python3_version(self):
        """The exact allowlist: `<python3 on PATH> --version` once a run, and nothing else, on every host (a `--help`
        or `--version` isn't read-only by itself: codex and hermes both write when started)."""
        f = Fakes(self, bins={"python3": PY, "git": "/usr/bin/git", "hermes": "/opt/bin/hermes",
                              "codex": "/opt/bin/codex"})
        for host in setup.HOSTS:
            doctor.run_checks(host, self.root, self.env)
        self.assertEqual(f.calls, [[PY, "--version"]] * len(doctor.SHELL_HOSTS))


class Runner(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "process groups are POSIX")
    def test_a_timeout_kills_the_whole_process_group(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pid_file = tmp / "pid"
        child = ("import subprocess, sys, time; p = subprocess.Popen([sys.executable, '-c', 'import time; "
                 f"time.sleep(60)']); open({str(pid_file)!r}, 'w').write(str(p.pid)); time.sleep(60)")
        started = time.monotonic()
        with mock.patch("plainspoken.doctor.TIMEOUT", 1), self.assertRaises(subprocess.TimeoutExpired):
            doctor._run([sys.executable, "-c", child], dict(os.environ))
        # Killing only the child leaves the grandchild holding the pipes, and _run waits out its 60 s sleep.
        self.assertLess(time.monotonic() - started, 1 + 3, "_run waited for the grandchild instead of killing it")
        grandchild = int(pid_file.read_text())
        for _ in range(50):
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.kill(grandchild, 9)
            self.fail("the grandchild outlived the timeout")

    def test_run_returns_the_output(self):
        r = doctor._run([sys.executable, "--version"], dict(os.environ))
        self.assertEqual(r.returncode, 0)
        self.assertIn("Python 3.", r.stdout + r.stderr)


class Failures(Base):
    def test_a_check_that_raises_is_not_checked_without_a_traceback(self):
        Fakes(self)
        with mock.patch("plainspoken.doctor.shutil.which", side_effect=RuntimeError("tok-123 secret")):
            found = self.checks("claude-code")
        c = found["python3"]
        self.assertEqual((c.status, c.static), ("not checked", False))
        self.assertIn("RuntimeError", c.detail)
        text = "\n".join(doctor.format(list(found.values())))
        self.assertNotIn("tok-123", text)
        self.assertNotIn("Traceback", text)

    def test_a_timeout_is_not_checked(self):
        Fakes(self, version=subprocess.TimeoutExpired(["python3"], 10))
        c = self.checks("claude-code")["python3"]
        self.assertEqual((c.status, c.static), ("not checked", False))
        self.assertIn("timed out", c.detail)

    def test_format_layout_and_summary(self):
        rows = [doctor.Check("a", "ok", "fine"), doctor.Check("b", "WARN", "broken", "mend it"),
                doctor.Check("c", "not checked", "can't see", "confirm it")]
        lines = doctor.format(rows)
        self.assertEqual(lines[0], "  ok           a: fine")
        self.assertEqual(lines[1], "  WARN         b: broken -> mend it")
        self.assertEqual(lines[2], "  not checked  c: can't see -> confirm it")
        self.assertEqual(doctor.summary(rows), "1 ok | 1 WARN | 1 not checked")
        self.assertEqual(doctor.heading("codex"), "plainspoken doctor | codex | checks only, nothing changed")


def tree(*folders: Path) -> dict[str, bytes]:
    out = {}
    for folder in folders:
        for p in sorted(folder.rglob("*")):
            out[str(p)] = p.read_bytes() if p.is_file() else b"<dir>"
    return out


def fake_bin(folder: Path, name: str, marker: Path) -> None:
    """A `name` on PATH that leaves `marker` behind if anything ever runs it."""
    script = folder / name
    script.write_text(f"#!/bin/sh\necho ran >> '{marker}'\n", encoding="utf-8")
    script.chmod(0o755)


class Command(Base):
    def run_cli(self, *args, env=None):
        """The CLI with the real PATH (so the real python3 and git are looked up), unless `env` sets one."""
        return cli(*args, cwd=self.root, env={**self.env, "PATH": os.environ.get("PATH", ""), **(env or {})})

    def test_doctor_writes_nothing_on_any_host(self):
        before = tree(self.root, self.home)
        for host in setup.HOSTS:
            with self.subTest(host=host):
                r = self.run_cli("doctor", "--host", host)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(r.stdout.startswith(f"{doctor.heading(host)}\n"))
                self.assertRegex(r.stdout.strip().splitlines()[-1], r"^\d+ ok \| \d+ WARN \| \d+ not checked$")
                self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertEqual(tree(self.root, self.home), before)

    @unittest.skipUnless(os.name == "posix", "the fakes are shell scripts")
    def test_doctor_and_setup_never_run_hermes_or_codex(self):
        bin_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bin_dir, ignore_errors=True)
        marker = self.home / "ran.txt"
        for name in ("hermes", "codex", "git"):
            fake_bin(bin_dir, name, marker)
        path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        for args in (("doctor", "--host", "hermes"), ("doctor", "--host", "codex"),
                     ("setup", "--host", "hermes", "--status"), ("setup", "--host", "codex", "--status"),
                     ("setup", "--host", "hermes", "--scope", "user", "--nudge", "on", "--dry-run")):
            with self.subTest(args=args):
                r = self.run_cli(*args, env={"PATH": path})
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertFalse(marker.exists(), f"{args} ran a fake command")
        self.assertIn(f"hermes CLI: {bin_dir / 'hermes'}", self.run_cli("doctor", "--host", "hermes",
                                                                       env={"PATH": path}).stdout)

    def test_chat_hosts_print_the_no_shell_lines(self):
        for host in ("claude-ai", "chatgpt"):
            r = self.run_cli("doctor", "--host", host)
            body = r.stdout.splitlines()[1:-1]
            self.assertTrue(body)
            self.assertTrue(all(line.startswith("  not checked  ") for line in body), body)
            self.assertIn("no shell", r.stdout)
            self.assertIn("0 ok | 0 WARN", r.stdout)
        self.assertFalse((self.root / ".plainspoken").exists())

    def test_warnings_exit_0_and_a_bad_host_exits_2(self):
        r = self.run_cli("doctor", "--host", "hermes", env={"PATH": "/nowhere"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"WARN\s+python3: ")  # no python3 on that PATH
        self.assertRegex(r.stdout, r"WARN\s+hermes CLI: ")
        self.assertEqual(self.run_cli("doctor", "--host", "nope").returncode, 2)

    def test_json(self):
        r = self.run_cli("doctor", "--host", "codex", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(set(row), {"name", "status", "detail", "fix", "static"})
            self.assertIn(row["status"], doctor.STATUSES)

    def test_ascii_console(self):
        """A console that can't print UTF-8 (cp1252, ascii) still gets the block, and the exit codes don't move."""
        ascii_env = {"PYTHONIOENCODING": "ascii", "PATH": "/nowhere"}
        for args in (("doctor", "--host", "hermes"), ("doctor", "--host", "codex", "--json")):
            with self.subTest(args=args):
                r = self.run_cli(*args, env=ascii_env)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("WARN", r.stdout)
        for host in ("chatgpt", "claude-ai"):  # the paste-in text has a "→": replaced, never a crash
            with self.subTest(host=host):
                r = self.run_cli("setup", "--host", host, env=ascii_env)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("Settings ? ", r.stdout)
                self.assertIn("Paste:", r.stdout)
                self.assertIn("no shell", r.stderr)
        r = self.run_cli("setup", "--host", "hermes", "--scope", "user", "--nudge", "on", env=ascii_env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Host checks", r.stdout)
        self.assertNotIn("internal error", r.stderr)
        self.assertTrue((self.home / ".config" / "plainspoken" / "config.toml").is_file())


class Launcher(unittest.TestCase):
    """lib/run.py refuses an old python3 with one line and exit 2, before any plainspoken import (#113 I1)."""

    def load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("plainspoken_run_launcher", REPO / "lib" / "run.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_too_old(self):
        run = self.load()
        self.assertEqual(run.too_old((3, 10, 12, "final", 0)),
                         "plainspoken needs Python 3.11 or newer; this python3 is 3.10.12")
        self.assertIsNone(run.too_old((3, 11, 0, "final", 0)))
        self.assertIsNone(run.too_old(sys.version_info))

    def test_an_old_python_gets_one_line_and_exit_2(self):
        code = ("import runpy, sys; sys.version_info = (3, 10, 12, 'final', 0); "
                f"sys.argv = ['run.py', 'doctor', '--host', 'codex']; runpy.run_path({str(REPO / 'lib' / 'run.py')!r}, "
                "run_name='__main__')")
        with tempfile.TemporaryDirectory() as cwd:
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=cwd)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stderr, "plainspoken needs Python 3.11 or newer; this python3 is 3.10.12\n")
        self.assertEqual(r.stdout, "")

    def test_the_launcher_imports_no_plainspoken_module_before_the_check(self):
        text = (REPO / "lib" / "run.py").read_text(encoding="utf-8")
        head = text[:text.index("def _run")]
        self.assertNotRegex(head, r"(?m)^\s*(?:from|import) plainspoken")
        self.assertLess(text.index("too_old()"), text.index("from plainspoken"))

    def test_the_launcher_parses_on_an_old_interpreter(self):
        """No f-string and no annotation anywhere in lib/run.py, so a python3 older than 3.6 still reaches the check."""
        import ast
        text = (REPO / "lib" / "run.py").read_text(encoding="utf-8")
        tree = ast.parse(text, feature_version=(3, 7))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.JoinedStr, ast.AnnAssign)):
                found.append(f"{type(node).__name__} line {node.lineno}")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
                found.append(f"return annotation line {node.lineno}")
            if isinstance(node, ast.arg) and node.annotation is not None:
                found.append(f"annotation line {node.lineno}")
        self.assertEqual(found, [])
        self.assertNotIn("from __future__", text)


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
            doctor.Check("Bash permission", "not checked", "can't see it", "allow Bash", static=True)]

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
        self.assertIn("WARN         python3: no python3 on PATH -> install Python 3.11 or later", tail)
        self.assertNotIn("git: found", tail)
        self.assertNotIn("Bash permission", tail)
        self.assertIn("doctor --host claude-code lists 1 thing to confirm by hand", tail)
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

    def test_a_healthy_machine_gets_no_block(self):
        static = [doctor.Check("git", "ok", "found"),
                  doctor.Check("hooks trusted", "not checked", "can't see it", "run /hooks", static=True)]
        _, out, err = self.main("--host", "codex", "--status", checks=static)
        self.assertNotIn("Host checks", out + err)
        self.assertNotIn("confirm by hand", out + err)

    def test_a_check_that_failed_is_shown_without_a_warning(self):
        failed = [doctor.Check("python3", "not checked", "timed out after 10 s")]
        _, out, _ = self.main("--host", "codex", "--status", checks=failed)
        self.assertIn("not checked  python3: timed out after 10 s", out)
        self.assertNotIn("confirm by hand", out)

    def test_a_check_that_raises_never_changes_setup(self):
        rc_clean, out_clean, _ = self.main("--host", "claude-code", "--nudge", "on")
        clean = self.config()
        shutil.rmtree(self.root / ".plainspoken")
        rc, out, _ = self.main("--host", "claude-code", "--nudge", "on", raises=True)
        self.assertEqual((rc, out, self.config()), (rc_clean, out_clean, clean))

    def test_chat_hosts_send_the_no_shell_lines_to_stderr(self):
        rc_clean, out_clean, _ = self.main("--host", "chatgpt")
        rc, out, err = self.main("--host", "chatgpt", checks=doctor.run_checks("chatgpt", self.root, self.env))
        self.assertEqual((rc, out), (rc_clean, out_clean))  # the paste-in text alone on stdout
        self.assertIn("Custom instructions", out)
        self.assertIn("no shell", err)
        self.assertNotIn("Host checks", out)
        self.assertFalse((self.root / ".plainspoken").exists())

    def test_real_checks_through_the_cli(self):
        r = cli("setup", "--host", "codex", "--status", cwd=self.root, env={**self.env, "PATH": "/nowhere"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"lint after edits: on\n\nHost checks")
        self.assertRegex(r.stdout, r"WARN\s+python3: ")
        self.assertIn("doctor --host codex lists 4 things to confirm by hand", r.stdout)


if __name__ == "__main__":
    unittest.main()
