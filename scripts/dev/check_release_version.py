"""plugin.json version must equal the release-please manifest version."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(root: str) -> int:
    base = Path(root)
    plugin = json.loads((base / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version")
    manifest = json.loads((base / ".release-please-manifest.json").read_text(encoding="utf-8")).get(".")
    if not plugin or plugin != manifest:
        print(f"version mismatch: plugin.json={plugin!r} release-please={manifest!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
