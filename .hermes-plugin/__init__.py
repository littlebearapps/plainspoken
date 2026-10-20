"""plainspoken for Hermes Agent: registers the plugin's skills and tells the model where the plugin lives.

Install: `hermes plugins install littlebearapps/plainspoken --enable`, then start a new session. Hermes ignores
`.claude-plugin/`, so this folder is the Hermes entry point; the skills, agents and engine are the same files Claude
Code and Codex use. How the skills run here (paths, the judges as one-shot `hermes chat` processes, what's missing):
`hosts/hermes.md`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_MARKER = "plainspoken plugin for hermes"


def _frontmatter_loader():
    # The engine's own YAML-subset reader, loaded by path so nothing is added to sys.path.
    spec = importlib.util.spec_from_file_location("_plainspoken_frontmatter", ROOT / "lib" / "plainspoken" / "frontmatter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load


def _skill_files() -> list[Path]:
    skills = ROOT / "skills"
    found = sorted(p for p in skills.glob("*/SKILL.md") if p.is_file())
    if not found:
        # A bootstrap that skips quietly is how a broken install passes for a working one.
        raise RuntimeError(f"plainspoken: no skills under {skills}. Reinstall with "
                           "`hermes plugins install littlebearapps/plainspoken --enable`.")
    return found


def _description(skill_md: Path, load) -> str:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return ""
    block = text.split("\n---", 1)[0].split("\n", 1)[1] if "\n" in text else ""
    return str(load(block).get("description") or "")


def bootstrap() -> str:
    return (f"<!-- {BOOTSTRAP_MARKER} -->\n"
            f"plainspoken (writing skills: check, humanize, write, plain-language, voice and others) is installed. "
            f"Its plugin root is `{ROOT}`. Before you use any plainspoken skill, read `{ROOT}/hosts/hermes.md` once: "
            f"the skills are written for Claude Code and that note says how to run them here.")


def register(ctx):
    load = _frontmatter_loader()
    for skill_md in _skill_files():
        # register_skill needs a pathlib.Path (a str disables the whole plugin) and the description (without it the
        # skill shows blank in the list and the model can't pick it).
        ctx.register_skill(skill_md.parent.name, skill_md, description=_description(skill_md, load))

    text = bootstrap()

    def pre_llm_call(is_first_turn=None, **kwargs):
        # A pre_llm_call return is Hermes' documented way to add context; it's appended to the first user message.
        return {"context": text} if is_first_turn else None

    ctx.register_hook("pre_llm_call", pre_llm_call)
