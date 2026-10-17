"""Speak a redacted final assistant message when voice mode is enabled."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

PACKAGE_SPEC = (
    "voxcode[audio,stt,vad,mcp] @ "
    "git+https://github.com/__GITHUB_OWNER__/voxcode.git"
)


def _last_assistant_text(transcript_path: str) -> str:
    last = ""
    with Path(transcript_path).open(encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "assistant":
                continue
            message = event.get("message", {})
            content = message.get("content", [])
            if isinstance(content, str):
                last = content
                continue
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            if parts:
                last = " ".join(parts)
    return last


def _voice_enabled() -> bool:
    override = os.getenv("VOXCODE_VOICE_ENABLED")
    if override is not None:
        return override.lower() in {"1", "true", "yes", "on"}
    config_override = os.getenv("VOXCODE_CONFIG")
    if config_override:
        path = Path(config_override)
    elif os.name == "nt":
        path = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "voxcode" / "config.toml"
    elif sys.platform == "darwin":
        path = Path.home() / "Library/Application Support" / "voxcode" / "config.toml"
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "voxcode" / "config.toml"
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle).get("voxcode", {})
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return bool(data.get("voice_enabled", False))


def _redact(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"https?://\S+|(?:[A-Za-z]:\\|/)[^\s]+", " ", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|password|secret)\b\s*[:=]\s*\S+",
        r"\1 redacted",
        text,
    )
    text = re.sub(r"[*_>#\-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:400]


def main() -> int:
    try:
        hook_input: dict[str, Any] = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"voxcode Stop hook could not read hook input: {exc}", file=sys.stderr)
        return 1
    if hook_input.get("stop_hook_active"):
        return 0
    if not _voice_enabled():
        return 0
    transcript_path = hook_input.get("transcript_path")
    if not isinstance(transcript_path, str):
        print("voxcode Stop hook: transcript_path was not provided", file=sys.stderr)
        return 0
    try:
        summary = _redact(_last_assistant_text(transcript_path))
    except OSError as exc:
        print(f"voxcode Stop hook could not read transcript: {exc}", file=sys.stderr)
        return 1
    if not summary:
        return 0
    if "--dev" in sys.argv:
        command = [sys.executable, "-m", "voxcode.cli", "speak", summary]
    else:
        command = ["uvx", "--from", PACKAGE_SPEC, "voxcode", "speak", summary]
    env = dict(os.environ)
    try:
        subprocess.run(command, check=True, env=env)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"voxcode Stop hook could not speak summary: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
