import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lib"))

from plainspoken import hosts  # noqa: E402


def cli(*args, cwd: Path, input: str | None = None):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("PLAINSPOKEN_", "CLAUDE_PLUGIN_OPTION_"))}
    e["PYTHONPATH"] = str(REPO / "lib")
    return subprocess.run([sys.executable, "-m", "plainspoken", *args], cwd=cwd, capture_output=True, text=True,
                          env=e, input=input)


class AgentPrompt(unittest.TestCase):
    def test_every_agent_file_exists(self):
        self.assertEqual(sorted(hosts.AGENTS), sorted(p.stem for p in hosts.agents_dir().glob("*.md")))

    def test_body_then_opener_then_input(self):
        out = hosts.agent_prompt("tells-judge", '{"group": "J1"}\n')
        self.assertNotIn("omitClaudeMd", out)
        self.assertTrue(out.startswith("You are one of four independent judges."))
        self.assertTrue(out.endswith('Judge this. Your input:\n{"group": "J1"}\n'))

    def test_line_picks_one_non_blank_line(self):
        out = hosts.agent_prompt("tells-judge", '{"g": 1}\n\n{"g": 2}\n{"g": 3}\n', line=2)
        self.assertTrue(out.endswith('Your input:\n{"g": 2}\n'))
        self.assertNotIn('{"g": 1}', out)

    def test_cold_reader_has_no_opener(self):
        out = hosts.agent_prompt("cold-reader", "Reader: a busy treasurer\nFile: /tmp/x.md\n")
        self.assertTrue(out.endswith("\n\nReader: a busy treasurer\nFile: /tmp/x.md\n"))

    def test_bad_input_raises(self):
        for name, payload, line in (("nobody", "x", None), ("tells-judge", "", None), ("tells-judge", "a\n", 2)):
            with self.assertRaises(ValueError):
                hosts.agent_prompt(name, payload, line)


class AgentReply(unittest.TestCase):
    def test_cuts_session_line_and_fence(self):
        text = '```json\n{"group": "J3", "verdicts": []}\n```\n\nsession_id: local-abc\n'
        self.assertEqual(json.loads(hosts.agent_reply(text)), {"group": "J3", "verdicts": []})

    def test_no_object_raises(self):
        for text in ("nothing here", "[1, 2]", "{not json}"):
            with self.assertRaises(ValueError):
                hosts.agent_reply(text)


class HostCli(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        (self.cwd / "post.md").write_text("Text.\n", encoding="utf-8")

    def test_judge_input_pipes_into_agent_prompt(self):
        cli("check", "post.md", "--profile", "default", cwd=self.cwd)
        lines = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd).stdout
        r = cli("agent-prompt", "tells-judge", "--line", "4", cwd=self.cwd, input=lines)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.splitlines()[-1])["group"], "J4")

    def test_judge_input_alone_fills_the_host_jsonl(self):  # #162: Codex and Hermes save stdout as input.jsonl
        r = cli("judge-input", "post.md", "--profile", "default", cwd=self.cwd)  # no check first: it lints itself
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("anti-AI lint", r.stderr)
        self.assertEqual(len([ln for ln in r.stdout.splitlines() if ln.strip()]), 4)
        for n, group in enumerate(("J1", "J2", "J3", "J4"), 1):
            prompt = cli("agent-prompt", "tells-judge", "--line", str(n), cwd=self.cwd, input=r.stdout)
            self.assertEqual(prompt.returncode, 0, prompt.stderr)
            self.assertEqual(json.loads(prompt.stdout.splitlines()[-1])["group"], group)

    def test_host_notes_say_the_lint_prints_on_stderr(self):
        for name in ("codex.md", "hermes.md"):
            text = (REPO / "hosts" / name).read_text(encoding="utf-8")
            (line,) = [ln for ln in text.splitlines() if "RUN judge-input" in ln and "input.jsonl" in ln]
            with self.subTest(host=name):
                self.assertIn("the lint and any hold print on stderr", line)
                self.assertIn("see check step 1", line)

    def test_agent_prompt_empty_input_exits_2(self):
        r = cli("agent-prompt", "tells-judge", cwd=self.cwd, input="")
        self.assertEqual(r.returncode, 2)
        self.assertIn("empty input", r.stderr)

    def test_agent_reply_round_trip_and_failure(self):
        ok = cli("agent-reply", cwd=self.cwd, input='{"a": 1}\nsession_id: x\n')
        self.assertEqual((ok.returncode, ok.stdout), (0, '{"a": 1}\n'))
        bad = cli("agent-reply", cwd=self.cwd, input="no reply")
        self.assertEqual(bad.returncode, 2)


if __name__ == "__main__":
    unittest.main()
