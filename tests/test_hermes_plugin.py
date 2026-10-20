import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_shim():
    spec = importlib.util.spec_from_file_location("_hermes_shim", REPO / ".hermes-plugin" / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeCtx:
    def __init__(self):
        self.skills, self.hooks = [], {}

    def register_skill(self, name, path, description=""):
        self.skills.append((name, path, description))

    def register_hook(self, event, fn):
        self.hooks[event] = fn


class HermesShim(unittest.TestCase):
    def setUp(self):
        self.ctx = FakeCtx()
        load_shim().register(self.ctx)

    def test_registers_every_skill_as_a_path_with_its_description(self):
        names = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md"))
        self.assertEqual([s[0] for s in self.ctx.skills], names)
        for name, path, description in self.ctx.skills:
            self.assertIsInstance(path, Path, name)
            self.assertTrue(path.is_file(), name)
            self.assertGreater(len(description), 20, name)

    def test_bootstrap_on_the_first_turn_only(self):
        hook = self.ctx.hooks["pre_llm_call"]
        context = hook(is_first_turn=True, session_id="s", user_message="hi")["context"]
        self.assertIn(str(REPO / "hosts" / "hermes.md"), context)
        self.assertIsNone(hook(is_first_turn=False))

    def test_manifest_declares_the_hook_it_registers(self):
        text = (REPO / ".hermes-plugin" / "plugin.yaml").read_text(encoding="utf-8")
        self.assertIn("name: plainspoken", text)
        for event in self.ctx.hooks:
            self.assertIn(f"- {event}", text)


if __name__ == "__main__":
    unittest.main()
