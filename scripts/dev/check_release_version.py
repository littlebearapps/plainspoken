"""Every host manifest's version must equal the release-please manifest version.

Claude Code reads .claude-plugin/plugin.json and is required. Codex (.codex-plugin/plugin.json) and Hermes Agent
(.hermes-plugin/plugin.yaml) are checked when present; release-please bumps all three (release-please-config.json).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_YAML_VERSION = re.compile(r"^version:\s*['\"]?([^'\"\s#]+)", re.M)


def _versions(base: Path) -> dict[str, str | None]:
    found = {".claude-plugin/plugin.json": json.loads(
        (base / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version")}
    codex = base / ".codex-plugin" / "plugin.json"
    if codex.exists():
        found[".codex-plugin/plugin.json"] = json.loads(codex.read_text(encoding="utf-8")).get("version")
    hermes = base / ".hermes-plugin" / "plugin.yaml"
    if hermes.exists():
        m = _YAML_VERSION.search(hermes.read_text(encoding="utf-8"))
        found[".hermes-plugin/plugin.yaml"] = m.group(1) if m else None
    return found


def main(root: str) -> int:
    base = Path(root)
    manifest = json.loads((base / ".release-please-manifest.json").read_text(encoding="utf-8")).get(".")
    bad = {path: v for path, v in _versions(base).items() if not v or v != manifest}
    for path, v in bad.items():
        print(f"version mismatch: {path}={v!r} release-please={manifest!r}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
