"""Validate the Claude Code marketplace and plugin with local structural checks."""

from __future__ import annotations

import json
import argparse
import shutil
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-claude",
        action="store_true",
        help="fail when the Claude CLI is not installed",
    )
    args = parser.parse_args(argv)
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
    plugin_root = ROOT / "plugins" / "voxcode"
    source = ROOT / entry["source"].replace("/", "/")
    if not source.is_dir():
        raise ValueError(f"plugin source does not exist: {source}")
    if "__GITHUB_OWNER__" in (
        plugin_root / ".mcp.json"
    ).read_text(encoding="utf-8") or "__GITHUB_OWNER__" in (
        plugin_root / "hooks" / "hooks.json"
    ).read_text(encoding="utf-8"):
        raise ValueError("GitHub owner placeholder remains in plugin launch files")
    for relative in (
        ".claude-plugin/plugin.json",
        ".mcp.json",
        "hooks/hooks.json",
    ):
        if not (plugin_root / relative).is_file():
            raise ValueError(f"required plugin file is missing: {relative}")
    claude = shutil.which("claude")
    if claude is None:
        message = "warning: Claude CLI check skipped (claude executable not found)"
        print(message)
        if args.require_claude:
            print("error: --require-claude was specified")
            return 1
        return 0
    command = [claude, "plugin", "validate", str(ROOT)]
    result = subprocess.run(command, cwd=ROOT)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
