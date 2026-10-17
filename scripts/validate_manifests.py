"""Validate the Claude Code marketplace and plugin with local structural checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    marker = ROOT / "plugins" / "voxcode" / ".dev-mode"
    if marker.exists():
        print("error: dev mode is enabled; run `python scripts/dev_mode.py off`")
        return 1
    marketplace = load(ROOT / ".claude-plugin" / "marketplace.json")
    plugin = load(ROOT / "plugins" / "voxcode" / ".claude-plugin" / "plugin.json")
    if marketplace.get("name") != "voxcode":
        raise ValueError("marketplace name must be voxcode")
    entries = marketplace.get("plugins")
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("marketplace must contain exactly one plugin entry")
    entry = entries[0]
    if entry.get("name") != plugin.get("name") or entry.get("source") != "./plugins/voxcode":
        raise ValueError("marketplace entry does not match plugin manifest")
    if "__GITHUB_OWNER__" not in (
        ROOT / "plugins" / "voxcode" / ".mcp.json"
    ).read_text(encoding="utf-8"):
        print("warning: GitHub owner placeholder has already been replaced")
    command = ["claude", "plugin", "validate", str(ROOT)]
    result = subprocess.run(command, cwd=ROOT)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
