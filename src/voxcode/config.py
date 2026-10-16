"""Configuration loading and persistence."""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


def config_path() -> Path:
    override = os.getenv("VOXCODE_CONFIG")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "voxcode" / "config.toml"


@dataclass(frozen=True)
class Config:
    input_device: int | str | None = None
    output_device: int | str | None = None
    input_device_name: str | None = None
    input_device_hostapi: str | None = None
    output_device_name: str | None = None
    output_device_hostapi: str | None = None
    sample_rate: int = 16000
    channels: int = 1
    model: str = "small"
    compute_type: str = "int8"
    vad_mode: str = "auto"
    fixed_seconds: float = 4.0
    silence_seconds: float = 1.0
    voice_enabled: bool = False
    language: str | None = None
    vad_aggressiveness: int = 2
    silence_threshold: float = 0.01
    config_version: int = 1
    legacy_ignored: bool = field(default=False, compare=False, repr=False)
    sources: dict[str, str] = field(default_factory=dict, compare=False, repr=False)


def _value(data: dict[str, Any], key: str, default: Any) -> Any:
    value = data.get(key, default)
    if value == "" and default is None:
        return None
    if isinstance(value, str) and value.isdigit() and key.endswith("device"):
        return int(value)
    return value


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    data: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as handle:
            parsed = tomllib.load(handle)
        data = parsed.get("voxcode", parsed)
    legacy = path.exists() and "config_version" not in data
    allowed_legacy = {"language", "voice_enabled"}
    keys = set(data) if not legacy else allowed_legacy
    defaults = Config()
    values: dict[str, Any] = {}
    for key in (
        "input_device_name", "input_device_hostapi", "output_device_name",
        "output_device_hostapi", "sample_rate", "channels", "model",
        "compute_type", "vad_mode", "fixed_seconds", "silence_seconds",
        "voice_enabled", "language", "vad_aggressiveness", "silence_threshold",
    ):
        if key in keys and key in data:
            values[key] = _value(data, key, getattr(defaults, key))
    if not legacy and "input_device" in keys:
        values["input_device"] = _value(data, "input_device", None)
    if not legacy and "output_device" in keys:
        values["output_device"] = _value(data, "output_device", None)
    config = replace(defaults, **values, config_version=int(data.get("config_version", 1)))
    sources = {key: "file" for key in values}
    if legacy:
        config = replace(config, input_device=None, output_device=None, legacy_ignored=True)
    env = {
        "input_device": os.getenv("VOXCODE_INPUT_DEVICE"),
        "output_device": os.getenv("VOXCODE_OUTPUT_DEVICE"),
        "sample_rate": os.getenv("VOXCODE_SAMPLE_RATE"),
        "channels": os.getenv("VOXCODE_CHANNELS"),
        "model": os.getenv("VOXCODE_MODEL"),
        "compute_type": os.getenv("VOXCODE_COMPUTE_TYPE"),
        "vad_mode": os.getenv("VOXCODE_VAD_MODE"),
        "fixed_seconds": os.getenv("VOXCODE_FIXED_SECONDS"),
        "silence_seconds": os.getenv("VOXCODE_SILENCE_SECONDS"),
        "voice_enabled": os.getenv("VOXCODE_VOICE_ENABLED"),
        "language": os.getenv("VOXCODE_LANGUAGE"),
        "vad_aggressiveness": os.getenv("VOXCODE_VAD_AGGRESSIVENESS"),
        "silence_threshold": os.getenv("VOXCODE_SILENCE_THRESHOLD"),
    }
    for key, value in env.items():
        if value is not None:
            if key.endswith("device") and value.isdigit():
                value = int(value)
            elif key in {"sample_rate", "channels"}:
                value = int(value)
            elif key in {"fixed_seconds", "silence_seconds"}:
                value = float(value)
            elif key == "voice_enabled":
                value = value.lower() in {"1", "true", "yes", "on"}
            elif key == "vad_aggressiveness":
                value = int(value)
            elif key == "silence_threshold":
                value = float(value)
            config = replace(config, **{key: value})
            sources[key] = "environment"
    config = replace(config, sources=sources)
    for key in config.__dataclass_fields__:
        if key not in {"legacy_ignored", "sources", "config_version"}:
            config.sources.setdefault(key, "default")
    return config


def save_config(
    config: Config,
    path: Path | None = None,
    fields: set[str] | None = None,
) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        defaults = Config()
        fields = {
            key
            for key in (
                "input_device_name", "input_device_hostapi",
                "output_device_name", "output_device_hostapi", "sample_rate",
                "channels", "model", "compute_type", "vad_mode",
                "fixed_seconds", "silence_seconds", "voice_enabled",
                "language", "vad_aggressiveness", "silence_threshold",
            )
            if getattr(config, key) != getattr(defaults, key)
        }
    lines = ["[voxcode]", "config_version = 1"]
    for key in (
        "input_device_name", "input_device_hostapi", "output_device_name",
        "output_device_hostapi", "sample_rate", "channels", "model",
        "compute_type", "vad_mode", "fixed_seconds", "silence_seconds",
        "voice_enabled", "language", "vad_aggressiveness", "silence_threshold",
    ):
        if key in fields:
            value = getattr(config, key)
            lines.append(f"{key} = {_toml_value(value)}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _toml_value(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)
