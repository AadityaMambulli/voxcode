"""Temporarily point the Claude plugin at this checkout's virtual environment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "voxcode"
MCP_PATH = PLUGIN / ".mcp.json"
HOOKS_PATH = PLUGIN / "hooks" / "hooks.json"
MARKER = PLUGIN / ".dev-mode"
PACKAGE_SPEC = (
    "voxcode[audio,stt,vad,mcp] @ "
    "git+https://github.com/__GITHUB_OWNER__/voxcode.git"
)


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def on() -> None:
    python = Path(os.environ.get("VIRTUAL_ENV", ROOT / ".venv")) / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"virtual-environment Python not found: {python}")
    mcp = {
        "mcpServers": {
            "voxcode": {
                "command": str(python),
                "args": ["-m", "voxcode.mcp_server"],
                "env": {
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONPATH": str(ROOT / "src"),
                },
            }
        }
    }
    hooks = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'"{python}" "${{CLAUDE_PLUGIN_ROOT}}/hooks/summarize_stop.py" --dev',
                        }
                    ],
                }
            ]
        }
    }
    _write(MCP_PATH, mcp)
    _write(HOOKS_PATH, hooks)
    MARKER.write_text("dev mode\n", encoding="utf-8")
    print(f"dev mode on: {python}")
    print(f"MCP: {MCP_PATH}")
    print(f"hooks: {HOOKS_PATH}")


def off() -> None:
    _write(
        MCP_PATH,
        {
            "mcpServers": {
                "voxcode": {
                    "command": "uvx",
                    "args": ["--from", PACKAGE_SPEC, "voxcode-mcp"],
                    "env": {"PYTHONUNBUFFERED": "1"},
                }
            }
        },
    )
    _write(
        HOOKS_PATH,
        {
            "hooks": {
                "Stop": [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": f'uvx --from "{PACKAGE_SPEC}" python "${{CLAUDE_PLUGIN_ROOT}}/hooks/summarize_stop.py"',
                            }
                        ],
                    }
                ]
            }
        },
    )
    MARKER.unlink(missing_ok=True)
    print("dev mode off")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("on", "off"))
    args = parser.parse_args()
    (on if args.action == "on" else off)()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
