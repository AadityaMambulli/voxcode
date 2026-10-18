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
    "git+https://github.com/AadityaMambulli/voxcode.git"
)
DEFAULT_SKIP_LABELS = ["Skipped", "Risk", "Verified", "Note", "Next"]


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
        data = tomllib.loads(path.read_text(encoding="utf-8-sig")).get("voxcode", {})
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return False
    return bool(data.get("voice_enabled", False))


def _hook_skip_labels() -> list[str]:
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
        value = tomllib.loads(path.read_text(encoding="utf-8-sig")).get(
            "voxcode", {}
        ).get("hook_skip_labels")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return DEFAULT_SKIP_LABELS
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return DEFAULT_SKIP_LABELS
    return value


def _summary(text: str, labels: list[str]) -> str:
    paragraph = re.split(r"\n\s*\n", text.strip(), maxsplit=1)[0]
    label_pattern = "|".join(re.escape(label) for label in labels if label.strip())
    if label_pattern:
        paragraph = re.sub(
            rf"(?im)^\s*(?:{label_pattern})\s*:\s*.*$",
            "",
            paragraph,
        )
    paragraph = re.sub(r"\s+", " ", paragraph).strip()
    if len(paragraph) <= 200:
        return paragraph
    candidate = paragraph[:201]
    boundary = max(
        candidate.rfind(". "),
        candidate.rfind("! "),
        candidate.rfind("? "),
    )
    if boundary >= 40:
        return candidate[: boundary + 1].strip()
    return candidate[:200].rsplit(" ", 1)[0].rstrip(" ,;:") + "."


def _redact(text: str, labels: list[str] | None = None) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"https?://\S+|(?:[A-Za-z]:\\|/)[^\s]+", " ", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|password|secret)\b\s*[:=]\s*\S+",
        r"\1 redacted",
        text,
    )
    text = re.sub(r"[*_>#\-]+", " ", text)
    return _summary(text, labels or DEFAULT_SKIP_LABELS)


def _hook_log(entry: dict[str, Any]) -> None:
    path = os.getenv("VOXCODE_HOOK_LOG")
    if not path:
        return
    from datetime import datetime, timezone

    try:
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"timestamp": datetime.now(timezone.utc).isoformat(), **entry},
                    separators=(",", ":"),
                )
                + "\n"
            )
    except OSError as exc:
        print(f"voxcode Stop hook could not write log: {exc}", file=sys.stderr)


def main() -> int:
    log: dict[str, Any] = {
        "stdin_keys": [],
        "transcript_path_existed": False,
        "voice_enabled": False,
        "summary_length": 0,
        "speech_started": False,
        "speech_finished": False,
        "exception": None,
    }
    dry_run = "--dry-run" in sys.argv
    try:
        hook_input: dict[str, Any] = json.load(sys.stdin)
        log["stdin_keys"] = sorted(hook_input.keys())
    except (json.JSONDecodeError, OSError) as exc:
        log["exception"] = str(exc)
        _hook_log(log)
        print(f"voxcode Stop hook could not read hook input: {exc}", file=sys.stderr)
        return 1
    if hook_input.get("stop_hook_active"):
        _hook_log(log)
        return 0
    log["voice_enabled"] = _voice_enabled()
    if not log["voice_enabled"]:
        _hook_log(log)
        return 0
    transcript_path = hook_input.get("transcript_path")
    if not isinstance(transcript_path, str):
        _hook_log(log)
        print("voxcode Stop hook: transcript_path was not provided", file=sys.stderr)
        return 0
    log["transcript_path_existed"] = Path(transcript_path).exists()
    try:
        summary = _redact(_last_assistant_text(transcript_path), _hook_skip_labels())
    except OSError as exc:
        log["exception"] = str(exc)
        _hook_log(log)
        print(f"voxcode Stop hook could not read transcript: {exc}", file=sys.stderr)
        return 1
    if not summary:
        _hook_log(log)
        return 0
    log["summary_length"] = len(summary)
    if dry_run:
        print(summary)
        _hook_log(log)
        return 0
    if "--dev" in sys.argv:
        command = [sys.executable, "-m", "voxcode.cli", "speak", summary]
    else:
        command = ["uvx", "--from", PACKAGE_SPEC, "voxcode", "speak", summary]
    env = dict(os.environ)
    try:
        log["speech_started"] = True
        subprocess.run(command, check=True, env=env)
        log["speech_finished"] = True
    except (OSError, subprocess.CalledProcessError) as exc:
        log["exception"] = str(exc)
        print(f"voxcode Stop hook could not speak summary: {exc}", file=sys.stderr)
        _hook_log(log)
        return 1
    _hook_log(log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
