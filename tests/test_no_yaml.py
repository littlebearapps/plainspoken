import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoPyYAML(unittest.TestCase):
    def test_nothing_imports_yaml_outside_the_differential_test(self):
        pat = re.compile(r"^\s*(import yaml|from yaml\b)", re.M)
        offenders = [str(p.relative_to(ROOT)) for d in ("lib", "scripts", "tests") for p in (ROOT / d).rglob("*.py")
                     if p.name != "test_frontmatter.py" and pat.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])


def unused_imports(source: str) -> list[str]:
    """Names a module imports and never uses. A `# noqa` on the import's first line marks a deliberate re-export,
    and so does a name in `__all__`."""
    import ast
    tree, lines = ast.parse(source), source.splitlines()
    imported: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and getattr(node, "module", "") != "__future__":
            if "noqa" in lines[node.lineno - 1]:
                continue
            for a in node.names:
                imported[a.asname or a.name.split(".")[0]] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    exported = {e.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets)
                for e in n.value.elts if isinstance(e, ast.Constant)}
    return sorted(f"{name} (line {line})" for name, line in imported.items() if name not in used | exported)


class NoUnusedImports(unittest.TestCase):
    def test_no_module_imports_what_it_never_uses(self):
        offenders = [f"{p.relative_to(ROOT)}: {name}" for d in ("lib", "scripts", "hooks", "tests")
                     for p in sorted((ROOT / d).rglob("*.py")) if p.name != "__init__.py"
                     for name in unused_imports(p.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])

    def test_the_scan_sees_an_unused_import(self):
        self.assertEqual(unused_imports("import os\nimport re\nre.compile('x')\n"), ["os (line 1)"])
        self.assertEqual(unused_imports("from a import b  # noqa: F401\n"), [])
        self.assertEqual(unused_imports("from a import b\n__all__ = ['b']\n"), [])
