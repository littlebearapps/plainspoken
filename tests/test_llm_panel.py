"""The model-panel adapter (Phase 6). Fakes only: no test touches the network or spawns `claude`."""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from plainspoken import __main__ as cli_main
from plainspoken.adapters import llm_panel as lp

REPO = Path(__file__).resolve().parents[1]
SHIPPED = REPO / "evals" / "panel.toml"
KEY = "sk-or-v1-SECRETSECRET0123456789"
ENV = {"OPENROUTER_API_KEY": KEY}


def panel_toml(models: str, **top) -> str:
    head = {"max_out_tokens": "800"}
    head.update(top)
    lines = [f"{k} = {v}" for k, v in head.items()]
    lines += ["", "[gateway]", 'transport = "openrouter"', 'base_url = "https://openrouter.test/api/v1"',
              'key_env = "OPENROUTER_API_KEY"', ""]
    return "\n".join(lines) + models


MODEL_OR = """
[[model]]
name = "grok"
vendor = "xAI"
model = "x-ai/grok-test"
price_in = 2.0
price_out = 10.0
"""

MODEL_CLI = """
[[model]]
name = "claude-opus"
vendor = "Anthropic"
transport = "claude-cli"
model = "claude-opus-5-5"
price_in = 0
price_out = 0
"""


def load(text: str) -> lp.Panel:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "panel.toml"
        p.write_text(text, encoding="utf-8")
        return lp.load_panel(p)


def or_answer(text="ok", model="x-ai/grok-test-0915", usage=None, provider=None) -> bytes:
    body = {"id": "gen-1", "model": model, "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": usage if usage is not None else {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0004}}
    if provider is not None:
        body["provider"] = provider
    return json.dumps(body).encode()


class FakeOpener:
    """Records every request; answers from a queue of (status, body) or exceptions (the last one repeats)."""

    def __init__(self, answers=None, cost=None):
        self.answers = list(answers or [])
        self.cost = cost
        self.requests = []
        self.lock = threading.Lock()

    def __call__(self, request):
        with self.lock:
            self.requests.append(request)
            if self.cost is not None:
                return 200, or_answer(usage={"prompt_tokens": 10, "completion_tokens": 5, "cost": self.cost})
            a = self.answers.pop(0) if len(self.answers) > 1 else (self.answers[0] if self.answers else
                                                                   (200, or_answer()))
        if isinstance(a, BaseException):
            raise a
        return a


def cli_json(result="judged", model="claude-opus-5-5", cost=0.0123, **over) -> str:
    body = {"type": "result", "is_error": False, "result": result, "total_cost_usd": cost,
            "usage": {"input_tokens": 50, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 5,
                      "output_tokens": 7},
            "modelUsage": {model: {"inputTokens": 65, "outputTokens": 7}}}
    body.update(over)
    return json.dumps(body)


class FakeRunner:
    def __init__(self, stdout=None, returncode=0, stderr="", error=None):
        self.stdout = stdout if stdout is not None else cli_json()
        self.returncode, self.stderr, self.error = returncode, stderr, error
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, args, *, input, cwd):
        with self.lock:
            self.calls.append({"args": list(args), "input": input, "cwd": cwd, "cwd_existed": Path(cwd).is_dir(),
                               "cwd_empty": not any(Path(cwd).iterdir())})
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)


class PanelConfigTests(unittest.TestCase):
    def test_load_panel_shipped(self):
        panel = lp.load_panel(SHIPPED)
        names = [m.name for m in panel.models]
        self.assertEqual(names, ["claude-opus", "glm", "openai", "gemini", "deepseek", "glimmer", "grok"])
        by = {m.name: m for m in panel.models}
        self.assertEqual(by["claude-opus"].transport, "claude-cli")
        self.assertEqual(by["claude-opus"].model, "claude-opus-5-5")
        self.assertEqual((by["claude-opus"].price_in, by["claude-opus"].price_out), (0, 0))
        self.assertEqual(by["glm"].model, "z-ai/glm-5.3")
        self.assertAlmostEqual(by["glm"].price_out, 4.8)
        self.assertEqual(by["openai"].model, "openai/gpt-6-luna")
        # OpenAI's only zero-retention host refused a harmless JR prompt (pilot, 2026-10-17), so the owner chose its
        # normal route for OpenAI: no training, short retention. Every other model keeps the panel's zdr.
        self.assertIs(by["openai"].zdr, False)
        self.assertEqual([m.name for m in panel.models if m.zdr is not None], ["openai"])
        self.assertEqual(by["glimmer"].model, "meta/muse-glimmer-30b")
        # Azure (OpenAI's only route under the owner's account-wide zero retention) refuses every JR prompt, so
        # OpenAI judges J1-J4 only (owner's decision, 2026-10-17); every other model judges every group
        self.assertEqual(by["openai"].groups, ("J1", "J2", "J3", "J4"))
        self.assertEqual([m.name for m in panel.models if m.groups is not None], ["openai"])
        self.assertEqual(by["gemini"].model, "google/gemini-3.8-flash")
        self.assertEqual(by["deepseek"].model, "deepseek/deepseek-v4.1-flash")
        self.assertAlmostEqual(by["deepseek"].price_in, 0.032)
        self.assertEqual(len({m.vendor for m in panel.models}), len(panel.models))  # one model per family
        self.assertEqual({m.transport for m in panel.models if m.name != "claude-opus"}, {"openrouter"})
        self.assertEqual(panel.base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(panel.key_env, "OPENROUTER_API_KEY")
        self.assertEqual(panel.max_out_tokens, 6000)  # reasoning models spent 2,000 thinking on JR prompts (pilot, 2026-10-17)
        # private text (the author's own writing in the blind test) only goes to providers that neither store nor
        # train on prompts
        self.assertEqual(panel.data_collection, "deny")
        self.assertTrue(panel.zdr)
        self.assertIn("eval panel check", SHIPPED.read_text(encoding="utf-8"))

    def test_load_panel_errors(self):
        cases = [
            (MODEL_OR.replace('model = "x-ai/grok-test"\n', ""), "model"),
            (MODEL_OR.replace('vendor = "xAI"', 'vendor = "xAI"\ntransport = "carrier-pigeon"'), "transport"),
            (MODEL_OR.replace("price_in = 2.0", "price_in = -1"), "price_in"),
            (MODEL_OR.replace("price_out = 10.0", 'price_out = "ten"'), "price_out"),
            (MODEL_OR + MODEL_OR, "name"),
            (MODEL_OR.replace('vendor = "xAI"', 'vendor = "xAI"\ncolour = "blue"'), "colour"),
        ]
        for text, key in cases:
            with self.subTest(key=key), self.assertRaises(lp.PanelError) as cm:
                load(panel_toml(text))
            self.assertIn(key, str(cm.exception))
            self.assertIsInstance(cm.exception, ValueError)
        for top, key in [({"max_out_tokens": "0"}, "max_out_tokens"), ({"surprise": "1"}, "surprise")]:
            with self.subTest(key=key), self.assertRaises(lp.PanelError) as cm:
                load(panel_toml(MODEL_OR, **top))
            self.assertIn(key, str(cm.exception))
        with self.assertRaises(lp.PanelError) as cm:
            load(panel_toml(MODEL_OR).replace('key_env = "OPENROUTER_API_KEY"', 'key_env = "not a var"'))
        self.assertIn("key_env", str(cm.exception))
        for line, key in [('data_collection = "maybe"', "data_collection"), ('zdr = "yes"', "zdr")]:
            with self.subTest(key=key), self.assertRaises(lp.PanelError) as cm:
                load(panel_toml(MODEL_OR).replace('key_env = "OPENROUTER_API_KEY"',
                                                  f'key_env = "OPENROUTER_API_KEY"\n{line}'))
            self.assertIn(key, str(cm.exception))
        with self.assertRaises(lp.PanelError) as cm:
            load(panel_toml(""))
        self.assertIn("model", str(cm.exception))
        with self.assertRaises(lp.PanelError):
            load("this isn't = = toml")
        with self.assertRaises(lp.PanelError):
            lp.load_panel(Path("/nonexistent/panel.toml"))

    def test_model_overrides_gateway_transport(self):
        panel = load(panel_toml(MODEL_CLI + MODEL_OR))
        self.assertEqual([m.transport for m in panel.models], ["claude-cli", "openrouter"])

    def test_estimate_cost(self):
        m = lp.PanelModel("x", "X", "openrouter", "x/y", 2, 10)
        self.assertEqual(lp.estimate_tokens("a" * 4000), 1000)
        self.assertEqual(lp.estimate_tokens("abcde"), 2)
        self.assertAlmostEqual(lp.estimate_cost(["a" * 4000], m, max_out_tokens=800), 0.001 * 2 + 0.0008 * 10)
        self.assertAlmostEqual(lp.estimate_cost(["a" * 4000] * 3, m, max_out_tokens=800),
                               3 * (0.001 * 2 + 0.0008 * 10))
        cli = lp.PanelModel("c", "Anthropic", "claude-cli", "claude-opus-5-5", 5, 25)
        self.assertEqual(lp.estimate_cost(["a" * 4000], cli, max_out_tokens=800), 0)


class IsAnthropicTests(unittest.TestCase):
    def test_vendor_wins_else_model_prefix(self):
        self.assertTrue(lp.is_anthropic("claude-opus-5-5"))
        self.assertTrue(lp.is_anthropic("Anthropic/claude-sonnet"))
        self.assertFalse(lp.is_anthropic("x-ai/grok-4.7"))
        self.assertFalse(lp.is_anthropic("openai/claude-lookalike"))
        self.assertTrue(lp.is_anthropic("some-alias", "Anthropic"))
        self.assertFalse(lp.is_anthropic("claude-proxy", "xAI"))
        self.assertFalse(lp.is_anthropic(""))
        for alias in ("opus", "Sonnet", "haiku", "claude-haiku-5", "opus[1m]"):  # the CLI's aliases
            self.assertTrue(lp.is_anthropic(alias), alias)
        for other in ("opusx", "gpt-opus", "magnum-opus"):
            self.assertFalse(lp.is_anthropic(other), other)


class ChildEnvTests(unittest.TestCase):
    def test_default_runner_passes_env(self):
        with mock.patch.object(subprocess, "run") as run:
            lp.default_runner_for(5, env={"A": "1"})(["x"], input="", cwd=".")
        self.assertEqual(run.call_args.kwargs["env"], {"A": "1"})

    def test_cli_transport_child_never_gets_the_key(self):
        panel = lp.Panel((), "https://openrouter.test/api/v1", "OPENROUTER_API_KEY", 2000)
        model = lp.PanelModel("claude-opus", "Anthropic", "claude-cli", "claude-opus-5-5", 0.0, 0.0)
        with mock.patch.object(subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 1, "", "boom")
            lp.call(model, "hi", panel, env={"OPENROUTER_API_KEY": "sk-or-secret", "PATH": "/bin"}, key="k")
        self.assertEqual(run.call_args.kwargs["env"], {"PATH": "/bin"})


class OpenRouterTests(unittest.TestCase):
    def setUp(self):
        self.panel = load(panel_toml(MODEL_OR))
        self.model = self.panel.models[0]
        patcher = mock.patch.object(lp, "RETRY_DELAY", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_openrouter_request_shape(self):
        op = FakeOpener()
        lp.call(self.model, "Judge this.", self.panel, opener=op, env=ENV)
        self.assertEqual(len(op.requests), 1)
        rq = op.requests[0]
        self.assertEqual(rq.full_url, "https://openrouter.test/api/v1/chat/completions")
        self.assertEqual(rq.get_method(), "POST")
        self.assertEqual(rq.get_header("Authorization"), f"Bearer {KEY}")
        self.assertEqual(rq.get_header("Content-type"), "application/json")
        body = json.loads(rq.data)
        self.assertEqual(body, {"model": "x-ai/grok-test", "messages": [{"role": "user", "content": "Judge this."}],
                                "temperature": 0, "max_tokens": 800, "usage": {"include": True},
                                "provider": {"data_collection": "deny"}})

    def test_model_groups(self):
        panel = load(panel_toml(MODEL_OR.replace('price_out = 10.0', 'price_out = 10.0\ngroups = ["J1", "J4"]')))
        self.assertEqual(panel.models[0].groups, ("J1", "J4"))
        self.assertIsNone(load(panel_toml(MODEL_OR)).models[0].groups)
        for bad in ('groups = ["J9"]', 'groups = []', 'groups = "J1"', 'groups = ["J1", "J1"]'):
            with self.subTest(bad=bad), self.assertRaises(lp.PanelError) as cm:
                load(panel_toml(MODEL_OR.replace('price_out = 10.0', f'price_out = 10.0\n{bad}')))
            self.assertIn("groups", str(cm.exception))

    def test_model_zdr_overrides_the_panel(self):
        text = panel_toml(MODEL_OR.replace('price_out = 10.0', 'price_out = 10.0\nzdr = false')).replace(
            'key_env = "OPENROUTER_API_KEY"', 'key_env = "OPENROUTER_API_KEY"\nzdr = true')
        panel = load(text)
        self.assertIs(panel.models[0].zdr, False)
        op = FakeOpener()
        lp.call(panel.models[0], "Judge this.", panel, opener=op, env=ENV)
        self.assertEqual(json.loads(op.requests[0].data)["provider"], {"data_collection": "deny"})
        with self.assertRaises(lp.PanelError) as cm:
            load(panel_toml(MODEL_OR.replace('price_out = 10.0', 'price_out = 10.0\nzdr = "no"')))
        self.assertIn("zdr", str(cm.exception))

    def test_openrouter_privacy_settings_reach_the_request(self):
        """The default refuses providers that may store prompts; `zdr = true` asks for zero-retention endpoints only,
        and `data_collection = "allow"` is honoured when a panel opts out on purpose."""
        for gateway, provider in [("", {"data_collection": "deny"}),
                                  ("zdr = true", {"data_collection": "deny", "zdr": True}),
                                  ('data_collection = "allow"', {"data_collection": "allow"})]:
            with self.subTest(gateway=gateway):
                panel = load(panel_toml(MODEL_OR).replace('key_env = "OPENROUTER_API_KEY"',
                                                          f'key_env = "OPENROUTER_API_KEY"\n{gateway}'))
                op = FakeOpener()
                lp.call(panel.models[0], "Judge this.", panel, opener=op, env=ENV)
                self.assertEqual(json.loads(op.requests[0].data)["provider"], provider)

    def test_openrouter_reply_records_the_serving_provider(self):
        """OpenRouter names the host that served the call; it's kept so run-to-run flips can be checked against host
        changes. No provider field (or a non-string) gives ""."""
        op = FakeOpener([(200, or_answer(provider="DeepInfra"))])
        self.assertEqual(lp.call(self.model, "Judge this.", self.panel, opener=op, env=ENV).provider, "DeepInfra")
        for answer in (or_answer(), or_answer(provider=["a"])):
            with self.subTest(answer=answer):
                r = lp.call(self.model, "Judge this.", self.panel, opener=FakeOpener([(200, answer)]), env=ENV)
                self.assertEqual(r.provider, "")
        # an empty answer still records who served it: a host that runs out of tokens is worth seeing
        body = {"model": "m", "provider": "Parasail",
                "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "length"}]}
        r = lp.call(self.model, "x", self.panel, opener=FakeOpener([(200, json.dumps(body).encode())]), env=ENV)
        self.assertIsNotNone(r.error)
        self.assertEqual(r.provider, "Parasail")

    def test_reply_lines_written_before_provider_still_read(self):
        """Run folders written before the provider field existed stay readable (and resumable)."""
        r = lp.call(self.model, "Judge this.", self.panel, opener=FakeOpener([(200, or_answer(provider="X"))]),
                    env=ENV)
        r = lp.Reply(**{**r.__dict__, "key": "J1-5b-001|grok"})
        old = {k: v for k, v in r.__dict__.items() if k != "provider"}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "replies.jsonl"
            path.write_text(json.dumps(old) + "\n" + json.dumps(r.__dict__) + "\n")
            lines = lp.reply_lines(path)
        self.assertEqual([x.provider for x in lines], ["", "X"])

    def test_openrouter_reply_and_cost(self):
        r = lp.call(self.model, "Judge this.", self.panel, opener=FakeOpener(), env=ENV)
        self.assertIsNone(r.error)
        self.assertEqual(r.text, "ok")
        self.assertEqual((r.name, r.model_requested, r.model_reported), ("grok", "x-ai/grok-test",
                                                                          "x-ai/grok-test-0915"))
        self.assertEqual((r.in_tokens, r.out_tokens), (100, 20))
        self.assertEqual(r.cost_usd, 0.0004)
        self.assertTrue(r.billed)
        self.assertRegex(r.at, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        # no usage.cost: computed from the token counts and the configured prices, rounded to 6 dp
        op = FakeOpener([(200, or_answer(usage={"prompt_tokens": 1000, "completion_tokens": 333}))])
        r = lp.call(self.model, "Judge this.", self.panel, opener=op, env=ENV)
        self.assertEqual(r.cost_usd, round(1000 * 2 / 1e6 + 333 * 10 / 1e6, 6))
        # a 200 with no message content is an error, never a reply
        op = FakeOpener([(200, json.dumps({"model": "m", "choices": []}).encode())])
        r = lp.call(self.model, "Judge this.", self.panel, opener=op, env=ENV)
        self.assertIsNotNone(r.error)
        self.assertEqual(r.text, "")
        op = FakeOpener([(200, b"<html>gateway</html>")])
        self.assertIn("JSON", lp.call(self.model, "x", self.panel, opener=op, env=ENV).error)
        # an empty answer says why it stopped: a reasoning model can spend the token budget before answering
        body = {"model": "m", "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "length"}]}
        op = FakeOpener([(200, json.dumps(body).encode())])
        r = lp.call(self.model, "x", self.panel, opener=op, env=ENV)
        self.assertIn("finish_reason length", r.error)

    def test_openrouter_retry_once_then_error(self):
        op = FakeOpener([(503, b"overloaded")])
        r = lp.call(self.model, "x", self.panel, opener=op, env=ENV)
        self.assertEqual(len(op.requests), 2)
        self.assertIn("503", r.error)
        self.assertEqual((r.text, r.cost_usd), ("", 0))
        op = FakeOpener([(429, b"slow down"), (200, or_answer())])
        r = lp.call(self.model, "x", self.panel, opener=op, env=ENV)
        self.assertEqual(len(op.requests), 2)
        self.assertIsNone(r.error)
        op = FakeOpener([TimeoutError("timed out")])
        r = lp.call(self.model, "x", self.panel, opener=op, env=ENV)
        self.assertEqual(len(op.requests), 2)
        self.assertIn("timed out", r.error)
        op = FakeOpener([(400, b'{"error": {"message": "bad model"}}')])  # not retried
        r = lp.call(self.model, "x", self.panel, opener=op, env=ENV)
        self.assertEqual(len(op.requests), 1)
        self.assertIn("400", r.error)

    def test_missing_key_is_error(self):
        op = FakeOpener()
        for env in ({}, {"OPENROUTER_API_KEY": "  "}):
            with self.subTest(env=env), self.assertRaises(lp.PanelError) as cm:
                lp.call(self.model, "x", self.panel, opener=op, env=env)
            self.assertIn("OPENROUTER_API_KEY", str(cm.exception))
        self.assertEqual(op.requests, [])
        with tempfile.TemporaryDirectory() as d, self.assertRaises(lp.PanelError):
            lp.run_batch([("k1", self.model, "x")], self.panel, Path(d), yes=True, opener=op, env={})
        self.assertEqual(op.requests, [])

    def test_key_never_written(self):
        echo = f"invalid key {KEY} (Bearer {KEY})".encode()
        err = urllib.error.HTTPError("https://openrouter.test/api/v1/chat/completions", 401,
                                     f"Unauthorized {KEY}", {"Authorization": f"Bearer {KEY}"}, io.BytesIO(echo))
        op = FakeOpener([err])
        r = lp.call(self.model, "x", self.panel, opener=op, env=ENV)
        self.assertIsNotNone(r.error)
        self.assertNotIn(KEY, json.dumps(r.__dict__))
        self.assertIn("***", r.error)
        for answer in (err, (500, echo), RuntimeError(f"socket said {KEY}"), (200, or_answer(text=f"echo {KEY}"))):
            with self.subTest(answer=type(answer).__name__), tempfile.TemporaryDirectory() as d:
                if isinstance(answer, urllib.error.HTTPError):
                    answer = urllib.error.HTTPError(answer.url, 401, f"Unauthorized {KEY}", {}, io.BytesIO(echo))
                err_out = io.StringIO()
                with contextlib.redirect_stderr(err_out), contextlib.redirect_stdout(err_out):
                    res = lp.run_batch([("k1", self.model, "x")], self.panel, Path(d), yes=True,
                                       opener=FakeOpener([answer]), env=ENV)
                written = (Path(d) / "replies.jsonl").read_text(encoding="utf-8")
                self.assertNotIn(KEY, written)
                self.assertNotIn(KEY, err_out.getvalue())
                self.assertNotIn(KEY, repr(res))
                self.assertEqual(len(written.splitlines()), 1)


class ClaudeCliTests(unittest.TestCase):
    def setUp(self):
        self.panel = load(panel_toml(MODEL_CLI))
        self.model = self.panel.models[0]

    def test_claude_cli_args_and_reply(self):
        runner = FakeRunner()
        here = os.getcwd()
        r = lp.call(self.model, "Judge this text.", self.panel, runner=runner, env={})
        self.assertEqual(len(runner.calls), 1)
        c = runner.calls[0]
        self.assertEqual(c["args"], ["claude", "-p", "--model", "claude-opus-5-5", "--safe-mode", "--tools", "",
                                     "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
                                     "--output-format", "json"])
        self.assertEqual(c["input"], "Judge this text.")
        self.assertTrue(c["cwd_existed"] and c["cwd_empty"])
        self.assertNotEqual(Path(c["cwd"]).resolve(), Path(here).resolve())
        self.assertFalse(Path(c["cwd"]).exists(), "the temp folder is removed afterwards")
        self.assertIsNone(r.error)
        self.assertEqual(r.text, "judged")
        self.assertEqual((r.model_requested, r.model_reported), ("claude-opus-5-5", "claude-opus-5-5"))
        self.assertFalse(r.billed)
        self.assertEqual(r.cost_usd, 0.0123)
        self.assertEqual((r.in_tokens, r.out_tokens), (65, 7))

    def test_claude_cli_several_models_and_errors(self):
        out = json.loads(cli_json())
        out["modelUsage"] = {"claude-opus-5-5": {}, "claude-haiku-4-5": {}}
        r = lp.call(self.model, "x", self.panel, runner=FakeRunner(json.dumps(out)), env={})
        self.assertEqual(r.model_reported, "claude-haiku-4-5+claude-opus-5-5")
        for runner, bit in [(FakeRunner(cli_json(is_error=True, result="Not logged in")), "Not logged in"),
                            (FakeRunner(json.dumps({"is_error": False, "modelUsage": {}})), "result"),
                            (FakeRunner("not json"), "JSON"),
                            (FakeRunner("", returncode=1, stderr="boom\nmore"), "boom"),
                            (FakeRunner(error=FileNotFoundError("claude")), "claude"),
                            (FakeRunner(error=subprocess.TimeoutExpired(["claude"], 180)), "timed out")]:
            with self.subTest(bit=bit):
                r = lp.call(self.model, "x", self.panel, runner=runner, env={})
                self.assertIsNotNone(r.error)
                self.assertIn(bit, r.error)
                self.assertEqual(r.text, "")
                self.assertFalse(Path(runner.calls[0]["cwd"]).exists())


class SamplingTests(unittest.TestCase):
    def test_openrouter_sends_the_temperature_it_records(self):
        self.assertEqual(lp.TEMPERATURE, 0)
        self.assertIn(f"temperature {lp.TEMPERATURE}", lp.SAMPLING["openrouter"])
        self.assertEqual(set(lp.SAMPLING), set(lp.TRANSPORTS))
        self.assertEqual(lp.sampling(["claude-cli", "openrouter", "claude-cli"]),
                         {"openrouter": lp.SAMPLING["openrouter"], "claude-cli": lp.SAMPLING["claude-cli"]})
        self.assertEqual(lp.sampling([]), {})


class ParseCliTests(unittest.TestCase):  # the drafting harness and the panel share parse_cli
    def body(self, **over) -> str:
        data = {"type": "result", "is_error": False, "result": "The answer.", "total_cost_usd": 0.42,
                "usage": {"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 100,
                          "output_tokens": 7},
                "modelUsage": {"claude-opus-5-5": {}, "claude-haiku-4-5": {}}}
        data.update(over)
        return json.dumps(data)

    def test_success(self):
        r = lp.parse_cli(0, self.body(), "")
        self.assertEqual((r.text, r.error, r.json), ("The answer.", None, True))
        self.assertEqual(r.models, ("claude-haiku-4-5", "claude-opus-5-5"))  # sorted
        self.assertEqual((r.in_tokens, r.out_tokens, r.cost_usd), (115, 7, 0.42))
        self.assertEqual(lp.parse_cli(0, self.body().encode("utf-8"), b""), r)  # bytes read the same

    def test_reported_errors_keep_the_usage(self):
        r = lp.parse_cli(0, self.body(is_error=True, result="Not logged in"), "")
        self.assertEqual((r.text, r.error, r.json), ("", "claude-cli reported an error: Not logged in", True))
        self.assertEqual((r.in_tokens, r.cost_usd), (115, 0.42))
        r = lp.parse_cli(1, self.body(result="  "), "boom\nmore")
        self.assertEqual(r.error, "claude-cli reported an error: boom")
        self.assertEqual(lp.parse_cli(0, self.body(result=""), "").error, "claude-cli: the output had no result")
        self.assertEqual(lp.parse_cli(0, self.body(result=None), "").error, "claude-cli: the output had no result")

    def test_output_that_isnt_a_json_object(self):
        for stdout in ("not json", "[1, 2]", "", None):
            r = lp.parse_cli(0, stdout, "")
            self.assertEqual((r.error, r.json, r.models), ("claude-cli: the output wasn't JSON", False, ()), stdout)
        self.assertEqual(lp.parse_cli(2, "", "Error: bad flag\nusage…").error, "claude-cli exited 2: Error: bad flag")
        self.assertEqual(lp.parse_cli(2, "partial out", "").error, "claude-cli exited 2: partial out")
        self.assertEqual(lp.parse_cli(2, None, None).error, "claude-cli exited 2: no message")

    def test_bad_usage_fields_read_as_zero(self):
        r = lp.parse_cli(0, self.body(total_cost_usd="lots", usage={"input_tokens": -3, "output_tokens": 2.5},
                                      modelUsage=["not", "a", "dict"]), "")
        self.assertEqual((r.in_tokens, r.out_tokens, r.cost_usd, r.models, r.error), (0, 0, 0.0, (), None))


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.panel = load(panel_toml(MODEL_CLI + MODEL_OR))
        self.cli, self.paid = self.panel.models
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "run"
        patcher = mock.patch.object(lp, "RETRY_DELAY", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def lines(self):
        return (self.out / "replies.jsonl").read_text(encoding="utf-8").splitlines()

    def test_paid_needs_yes(self):
        op = FakeOpener()
        res = lp.run_batch([("a", self.cli, "x"), ("b", self.paid, "y" * 4000)], self.panel, self.out, yes=False,
                           opener=op, runner=FakeRunner(), env=ENV)
        self.assertEqual(op.requests, [])
        self.assertTrue(res.stopped.startswith("paid run needs --yes (estimate US$"), res.stopped)
        self.assertEqual(res.replies, [])
        runner = FakeRunner()
        res = lp.run_batch([("a", self.cli, "x"), ("b", self.cli, "y")], self.panel, self.out, yes=False,
                           runner=runner, env={})
        self.assertIsNone(res.stopped)
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual([r.key for r in res.replies], ["a", "b"])
        self.assertEqual(res.spent, 0)

    def test_batch_stops_at_budget(self):
        # price_out 375/M × 800 tokens = US$0.30 estimated a call; the fake bills 0.30 a call
        panel = load(panel_toml(MODEL_OR.replace("price_out = 10.0", "price_out = 375.0")))
        model = panel.models[0]
        op = FakeOpener(cost=0.30)
        jobs = [(f"k{i}", model, "short prompt") for i in range(6)]
        res = lp.run_batch(jobs, panel, self.out, max_cost_usd=1.0, yes=True, concurrency=1, opener=op, env=ENV)
        self.assertEqual(len(op.requests), 3)
        self.assertIn("budget", res.stopped)
        self.assertIn("1.00", res.stopped)
        self.assertEqual(len(self.lines()), 3)
        self.assertAlmostEqual(res.spent, 0.9)
        self.assertEqual(len(res.replies), 3)
        # a rerun with the same folder counts the recorded spend: nothing more is called
        op2 = FakeOpener(cost=0.30)
        res = lp.run_batch(jobs, panel, self.out, max_cost_usd=1.0, yes=True, concurrency=1, opener=op2, env=ENV)
        self.assertEqual(op2.requests, [])
        self.assertEqual(res.skipped, 3)
        self.assertIn("budget", res.stopped)

    def test_budget_holds_under_concurrency(self):
        panel = load(panel_toml(MODEL_OR.replace("price_out = 10.0", "price_out = 375.0")))
        model = panel.models[0]
        op = FakeOpener(cost=0.30)
        jobs = [(f"k{i}", model, "short prompt") for i in range(40)]
        res = lp.run_batch(jobs, panel, self.out, max_cost_usd=1.0, yes=True, concurrency=8, opener=op, env=ENV)
        self.assertEqual(len(op.requests), 3)
        self.assertLessEqual(res.spent, 1.0)
        self.assertIn("budget", res.stopped)

    def test_batch_resume_skips_done(self):
        runner = FakeRunner()
        jobs = [(f"k{i}", self.cli, f"prompt {i}") for i in range(5)]
        lp.run_batch(jobs[:2], self.panel, self.out, runner=runner, env={})
        self.assertEqual(len(runner.calls), 2)
        runner2 = FakeRunner()
        res = lp.run_batch(jobs, self.panel, self.out, runner=runner2, env={})
        self.assertEqual(sorted(c["input"] for c in runner2.calls), ["prompt 2", "prompt 3", "prompt 4"])
        self.assertEqual(res.skipped, 2)
        self.assertEqual([r.key for r in res.replies], ["k0", "k1", "k2", "k3", "k4"])
        self.assertEqual(len(self.lines()), 5)
        runner3 = FakeRunner()
        res = lp.run_batch(jobs, self.panel, self.out, runner=runner3, env={})
        self.assertEqual(runner3.calls, [])
        self.assertEqual(res.skipped, 5)

    def test_batch_resume_torn_line(self):
        jobs = [(f"k{i}", self.cli, f"prompt {i}") for i in range(5)]
        lp.run_batch(jobs[:3], self.panel, self.out, runner=FakeRunner(), env={})
        whole = (self.out / "replies.jsonl").read_bytes()
        last = whole.rstrip(b"\n").rsplit(b"\n", 1)[1]
        torn = json.loads(last)["key"]  # lines land in completion order, so find which job the last one is
        (self.out / "replies.jsonl").write_bytes(whole[:len(whole) - len(last) - 1] + last[:len(last) // 2])
        runner = FakeRunner()
        res = lp.run_batch(jobs, self.panel, self.out, runner=runner, env={})
        self.assertEqual(sorted(c["input"] for c in runner.calls),
                         sorted([f"prompt {torn[1:]}", "prompt 3", "prompt 4"]))
        self.assertEqual(res.skipped, 2)
        good = []
        for line in self.lines():
            try:
                good.append(json.loads(line)["key"])
            except ValueError:
                pass
        self.assertEqual(sorted(good), ["k0", "k1", "k2", "k3", "k4"])

    def test_error_replies_are_recorded_and_retried_on_resume(self):
        jobs = [("k0", self.cli, "p0"), ("k1", self.cli, "p1")]
        res = lp.run_batch(jobs, self.panel, self.out, runner=FakeRunner("not json"), env={})
        self.assertEqual(len(res.replies), 2)
        self.assertTrue(all(r.error for r in res.replies))
        self.assertEqual(len(self.lines()), 2)
        runner = FakeRunner()
        res = lp.run_batch(jobs, self.panel, self.out, runner=runner, env={})
        self.assertEqual(len(runner.calls), 2)
        self.assertTrue(all(r.error is None for r in res.replies))

    def test_bad_jobs(self):
        for jobs in ([("k", self.cli, "a"), ("k", self.cli, "b")], [("", self.cli, "a")]):
            with self.subTest(jobs=jobs), self.assertRaises(lp.PanelError):
                lp.run_batch(jobs, self.panel, self.out, runner=FakeRunner(), env={})

    def test_replies_line_whole_under_concurrency(self):
        runner = FakeRunner(cli_json(result="x" * 20_000))
        jobs = [(f"k{i:03d}", self.cli, f"p{i}") for i in range(200)]
        res = lp.run_batch(jobs, self.panel, self.out, concurrency=8, runner=runner, env={})
        self.assertEqual(len(runner.calls), 200)
        lines = self.lines()
        self.assertEqual(len(lines), 200)
        self.assertEqual(sorted(json.loads(x)["key"] for x in lines), [k for k, _, _ in jobs])
        self.assertEqual(len(res.replies), 200)


class FixRoundTests(unittest.TestCase):
    """Atomic settlement, scrub before cut, no exception escapes a worker."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "run"
        patcher = mock.patch.object(lp, "RETRY_DELAY", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_settlement_is_atomic_under_concurrency(self):
        # estimate == actual == US$0.30, budget US$1.00, 3 workers. k0 returns first; the first lock release on its
        # thread after that sleeps, which opens any gap between dropping its reservation and recording its spend.
        # k1 returns while k0 sleeps and its worker takes k3: a split settlement lets k3 launch (4 calls, US$1.20).
        panel = load(panel_toml(MODEL_OR.replace("price_out = 10.0", "price_out = 375.0")))
        model = panel.models[0]
        prompt = "p" * 3  # estimate: 1 token × 2/M + 800 × 375/M ≈ 0.300002
        est = lp.estimate_cost([prompt + "0"], model, panel.max_out_tokens)
        local = threading.local()
        delays = {"k0": 0.05, "k1": 0.2, "k2": 1.2}
        requests = []
        guard = threading.Lock()

        def opener(request):
            key = json.loads(request.data)["messages"][0]["content"][len(prompt):]
            with guard:
                requests.append(key)
            time.sleep(delays.get("k" + key, 0.01))
            if key == "0":
                local.returned = True
            return 200, or_answer(usage={"prompt_tokens": 1, "completion_tokens": 800, "cost": est})

        class GappyLock:
            def __init__(self):
                self._lock = threading.Lock()

            def __enter__(self):
                self._lock.acquire()
                return self

            def __exit__(self, *exc):
                self._lock.release()
                if getattr(local, "returned", False) and not getattr(local, "slept", False):
                    local.slept = True
                    time.sleep(0.5)
                return False

        jobs = [(f"k{i}", model, f"{prompt}{i}") for i in range(8)]
        with mock.patch.object(lp, "_new_lock", GappyLock):
            res = lp.run_batch(jobs, panel, self.out, max_cost_usd=1.0, yes=True, concurrency=3, opener=opener,
                               env=ENV)
        self.assertEqual(len(requests), 3, requests)
        self.assertLessEqual(res.spent, 1.0)
        self.assertIn("budget", res.stopped)

    def test_key_across_the_cut_never_written(self):
        prefix = KEY[:8]
        straddle = "a" * 185 + " " + KEY + " tail"
        panel = load(panel_toml(MODEL_CLI + MODEL_OR))
        cli, paid = panel.models
        cases = [
            ("openrouter 200 error", paid, {"opener": FakeOpener([(200, json.dumps(
                {"model": "m", "error": {"message": straddle}}).encode())])}),
            ("openrouter 500 body", paid, {"opener": FakeOpener([(500, straddle.encode())])}),
            ("openrouter exception", paid, {"opener": FakeOpener([RuntimeError(straddle)])}),
            ("cli is_error", cli, {"runner": FakeRunner(cli_json(is_error=True, result=straddle))}),
            ("cli stderr", cli, {"runner": FakeRunner("", returncode=1, stderr=straddle)}),
            ("cli exception", cli, {"runner": FakeRunner(error=RuntimeError(straddle))}),
        ]
        for name, model, kw in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                r = lp.call(model, "x", panel, env=ENV, **kw)
                self.assertIsNotNone(r.error)
                self.assertNotIn(prefix, json.dumps(r.__dict__))
                kw2 = {k: (type(v)(v.answers) if isinstance(v, FakeOpener) else v) for k, v in kw.items()}
                lp.run_batch([("k1", model, "x")], panel, Path(d), yes=True, env=ENV, **kw2)
                self.assertNotIn(prefix, (Path(d) / "replies.jsonl").read_text(encoding="utf-8"))

    def test_lone_surrogate_reply_round_trips(self):
        # a model can send "\\ud800" as a JSON escape; the reply must still be written as one whole line and read back
        panel = load(panel_toml(MODEL_CLI + MODEL_OR))
        cli, paid = panel.models
        text = "\ud800 hi \udfff"
        for name, model, kw in [("claude-cli", cli, {"runner": FakeRunner(cli_json(result=text))}),
                                ("openrouter", paid, {"opener": FakeOpener([(200, or_answer(text=text))])})]:
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                res = lp.run_batch([("k1", model, "x"), ("k2", model, "y")], panel, Path(d), yes=True, env=ENV,
                                   **kw)
                self.assertIsNone(res.stopped)
                self.assertEqual([r.text for r in res.replies], [text, text])
                raw = (Path(d) / "replies.jsonl").read_bytes()
                self.assertEqual(len(raw.splitlines()), 2)
                raw.decode("utf-8")  # the file stays valid UTF-8
                latest, _ = lp.read_replies(Path(d) / "replies.jsonl")
                self.assertEqual({k: r.text for k, r in latest.items()}, {"k1": text, "k2": text})
                again = lp.run_batch([("k1", model, "x"), ("k2", model, "y")], panel, Path(d), yes=True, env=ENV,
                                     **kw)
                self.assertEqual(again.skipped, 2)

    def test_reply_that_cannot_be_written_stops_cleanly(self):
        panel = load(panel_toml(MODEL_CLI))
        cli = panel.models[0]
        with mock.patch.object(lp, "_line", side_effect=ValueError(f"cannot serialise {KEY}")):
            res = lp.run_batch([("k1", cli, "x"), ("k2", cli, "y")], panel, self.out, concurrency=1,
                               runner=FakeRunner(), env=ENV)
        self.assertIn("can't write", res.stopped)
        self.assertNotIn(KEY, res.stopped)

    def test_unexpected_worker_exception_is_an_error_reply(self):
        panel = load(panel_toml(MODEL_CLI + MODEL_OR))
        cli, paid = panel.models
        good = cli_json()

        def runner(args, *, input, cwd):
            if input == "boom":
                return None  # not a CompletedProcess: blows up after the runner returns
            return subprocess.CompletedProcess(args, 0, good, "")

        def opener(request):
            if json.loads(request.data)["messages"][0]["content"] == "bad":
                raise ValueError(f"weird {KEY}")
            return 200, or_answer()

        jobs = [("a", cli, "fine"), ("b", cli, "boom"), ("c", cli, "fine too"), ("d", paid, "bad"),
                ("e", paid, "ok")]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            res = lp.run_batch(jobs, panel, self.out, yes=True, concurrency=2, runner=runner, opener=opener,
                               env=ENV)
        by = {r.key: r for r in res.replies}
        self.assertEqual(sorted(by), ["a", "b", "c", "d", "e"])
        self.assertIsNotNone(by["b"].error)
        self.assertNotIn("\n", by["b"].error)
        self.assertIsNotNone(by["d"].error)
        self.assertNotIn(KEY, json.dumps(by["d"].__dict__))
        self.assertTrue(all(by[k].error is None for k in "ace"))
        written = (self.out / "replies.jsonl").read_text(encoding="utf-8")
        self.assertEqual(len(written.splitlines()), 5)
        self.assertNotIn(KEY, written + err.getvalue())
        # the worker path itself: an exception escaping `call` becomes the job's error Reply
        with mock.patch.object(lp, "call", side_effect=RuntimeError(f"surprise {KEY}\nsecond line")), \
                tempfile.TemporaryDirectory() as d:
            res = lp.run_batch([("z", cli, "x")], panel, Path(d), env=ENV)
            self.assertEqual(len(res.replies), 1)
            self.assertIn("surprise", res.replies[0].error)
            self.assertNotIn("second line", res.replies[0].error)
            self.assertNotIn(KEY, (Path(d) / "replies.jsonl").read_text(encoding="utf-8"))


class FollowUpsT3(unittest.TestCase):
    """Panel."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "run"
        patcher = mock.patch.object(lp, "RETRY_DELAY", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_budget_stop_halts_the_unbilled_calls_too(self):  # by design: one budget per batch
        panel = load(panel_toml(MODEL_OR.replace("price_out = 10.0", "price_out = 375.0") + MODEL_CLI))
        paid, cli = panel.models
        runner = FakeRunner()
        jobs = [("p1", paid, "x"), ("p2", paid, "x"), ("c1", cli, "x"), ("c2", cli, "x")]
        res = lp.run_batch(jobs, panel, self.out, max_cost_usd=0.5, yes=True, concurrency=1,
                           opener=FakeOpener(cost=0.30), runner=runner, env=ENV)
        self.assertIn("budget", res.stopped)
        self.assertEqual([r.key for r in res.replies], ["p1"])
        self.assertEqual(runner.calls, [])  # the claude-cli jobs after the stop wait for the resume

    def test_budget_stop_is_documented(self):
        from plainspoken import evalcli
        guide = (REPO / "guides" / "evals.md").read_text(encoding="utf-8")
        self.assertIn("one budget per batch", guide)
        parser = __import__("argparse").ArgumentParser()
        evalcli.add_parser(parser.add_subparsers())
        for argv in (["eval", "judges", "--help"], ["eval", "blind", "run", "--help"]):
            out = io.StringIO()
            with self.subTest(argv=argv), contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                parser.parse_args(argv)
            self.assertIn("claude-cli", " ".join(out.getvalue().split()), argv)

    def test_short_write_finishes_the_line(self):
        panel = load(panel_toml(MODEL_CLI))
        cli = panel.models[0]
        real = os.write
        calls = []

        def short(fd, data):  # the first write of each line lands only half its bytes
            calls.append(len(data))
            n = real(fd, bytes(data[:max(1, len(data) // 2)]) if len(calls) % 2 else bytes(data))
            return n
        jobs = [(f"k{i}", cli, f"p{i}") for i in range(3)]
        with mock.patch.object(lp.os, "write", short):
            res = lp.run_batch(jobs, panel, self.out, concurrency=1, runner=FakeRunner(), env=ENV)
        self.assertIsNone(res.stopped)
        latest, _ = lp.read_replies(self.out / lp.REPLIES)
        self.assertEqual(sorted(latest), ["k0", "k1", "k2"])
        self.assertEqual(len((self.out / lp.REPLIES).read_text(encoding="utf-8").splitlines()), 3)

    def test_float_token_counts_are_not_a_reply(self):
        good = lp.Reply(key="k", name="m", model_requested="x", model_reported="x", text="t", in_tokens=10,
                        out_tokens=5, cost_usd=0.5, billed=False, at="2026-10-19T00:00:00Z", error=None)
        line = lp._line(good)
        self.assertEqual(lp._from_line(line), good)
        for field_name in ("in_tokens", "out_tokens"):
            d = json.loads(line)
            d[field_name] = 10.5
            with self.subTest(field=field_name):
                self.assertIsNone(lp._from_line(json.dumps(d).encode()))
        d = json.loads(line)
        d["cost_usd"] = 1  # a whole-dollar cost is still a cost
        self.assertEqual(lp._from_line(json.dumps(d).encode()).cost_usd, 1)

    def test_unwritten_reply_is_not_returned(self):
        panel = load(panel_toml(MODEL_CLI))
        cli = panel.models[0]
        real = lp._line

        def line(r):
            if r.key == "k1":
                raise ValueError("cannot serialise")
            return real(r)
        with mock.patch.object(lp, "_line", line):
            res = lp.run_batch([("k0", cli, "a"), ("k1", cli, "b")], panel, self.out, concurrency=1,
                               runner=FakeRunner(), env=ENV)
        self.assertIn("can't write", res.stopped)
        self.assertEqual([r.key for r in res.replies], ["k0"])  # what the folder holds, nothing more
        latest, _ = lp.read_replies(self.out / lp.REPLIES)
        self.assertEqual(sorted(latest), ["k0"])

    def test_estimate_models_comma_names_no_model(self):
        prompt = Path(self.tmp.name) / "p.txt"
        prompt.write_text("hello", encoding="utf-8")
        for value in (",", " , "):
            with self.subTest(value=value):
                code, out, err = run_cli("eval", "panel", "estimate", "--panel", str(SHIPPED), "--models", value,
                                         str(prompt))
                self.assertEqual(code, 2)
                self.assertIn("--models names no model", err)
                self.assertEqual(out, "")


CATALOGUE = {"data": [
    {"id": "x-ai/grok-test", "pricing": {"prompt": "0.000002", "completion": "0.00001"}},
    {"id": "moonshotai/kimi-test", "pricing": {"prompt": "0.000000304", "completion": "0.00002"}},
]}


class CheckModelsTests(unittest.TestCase):
    def setUp(self):
        extra = """
[[model]]
name = "kimi"
vendor = "Moonshot"
model = "moonshotai/kimi-test"
price_in = 0.304
price_out = 11.588

[[model]]
name = "ghost"
vendor = "Nobody"
model = "nobody/ghost-1"
price_in = 1
price_out = 1
"""
        self.panel = load(panel_toml(MODEL_CLI + MODEL_OR + extra))

    def test_check_models(self):
        op = FakeOpener([(200, json.dumps(CATALOGUE).encode())])
        problems = lp.check_models(self.panel, opener=op)
        self.assertEqual(len(op.requests), 1)
        self.assertEqual(op.requests[0].full_url, "https://openrouter.test/api/v1/models")
        self.assertIsNone(op.requests[0].get_header("Authorization"))
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(any("ghost" in p and "nobody/ghost-1" in p for p in problems))
        self.assertTrue(any("kimi" in p and "price_out" in p for p in problems))
        self.assertFalse(any("grok" in p for p in problems))

    def test_check_models_unreachable(self):
        problems = lp.check_models(self.panel, opener=FakeOpener([OSError("no route")]))
        self.assertEqual(len(problems), 1)
        self.assertIn("no route", problems[0])
        problems = lp.check_models(self.panel, opener=FakeOpener([(200, b"nope")]))
        self.assertEqual(len(problems), 1)


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_main.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class PanelCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def test_panel_check_cli(self):
        cat = {"data": [{"id": m.model, "pricing": {"prompt": str(m.price_in / 1e6), "completion":
                                                    str(m.price_out / 1e6)}}
                        for m in lp.load_panel(SHIPPED).models if m.transport == "openrouter"]}
        with mock.patch.object(lp, "default_opener", FakeOpener([(200, json.dumps(cat).encode())])):
            code, out, err = run_cli("eval", "panel", "check")
        self.assertEqual(code, 0, err)
        self.assertIn(f"{len(cat['data'])} billed models", out)
        cat["data"].pop()
        with mock.patch.object(lp, "default_opener", FakeOpener([(200, json.dumps(cat).encode())])):
            code, out, err = run_cli("eval", "panel", "check", "--panel", str(SHIPPED))
        self.assertEqual(code, 1)
        self.assertIn("problem:", out)
        self.assertIn("plainspoken: eval panel check:", err)
        code, out, err = run_cli("eval", "panel", "check", "--panel", str(self.d / "missing.toml"))
        self.assertEqual(code, 2)
        self.assertIn("plainspoken: eval panel check:", err)

    def test_panel_estimate_cli(self):
        a, b = self.d / "a.txt", self.d / "b.txt"
        a.write_text("a" * 4000, encoding="utf-8")
        b.write_text("b" * 400, encoding="utf-8")
        code, out, err = run_cli("eval", "panel", "estimate", "--panel", str(SHIPPED), "--models",
                                 "grok,claude-opus", str(a), str(b))
        self.assertEqual(code, 0, err)
        self.assertIn("grok", out)
        self.assertIn("claude-opus", out)
        self.assertNotIn("kimi", out)
        self.assertIn("1100", out)  # 1000 + 100 estimated input tokens
        grok = (1100 * 2 + 2 * lp.load_panel(SHIPPED).max_out_tokens * 6) / 1e6
        self.assertIn(f"{grok:.4f}", out)
        self.assertIn("total", out.lower())
        code, out, err = run_cli("eval", "panel", "estimate", "--panel", str(SHIPPED), str(a))
        self.assertEqual(code, 0, err)
        self.assertIn("gemini", out)
        code, _, err = run_cli("eval", "panel", "estimate", "--panel", str(SHIPPED), "--models", "nope", str(a))
        self.assertEqual(code, 2)
        self.assertIn("nope", err)
        code, _, err = run_cli("eval", "panel", "estimate", "--panel", str(SHIPPED), str(self.d / "missing.txt"))
        self.assertEqual(code, 2)
        self.assertIn("plainspoken: eval panel estimate:", err)


if __name__ == "__main__":
    unittest.main()
