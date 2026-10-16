"""Configuration loading and persistence."""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


def config_path() -> Path:
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
    sample_rate: int = 16000
    channels: int = 1
    model: str = "small"
    compute_type: str = "int8"
    vad_mode: str = "fixed"
    fixed_seconds: float = 4.0
    silence_seconds: float = 1.0
    voice_enabled: bool = False


def _value(data: dict[str, Any], key: str, default: Any) -> Any:
    value = data.get(key, default)
    if key.endswith("device") and value == "":
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
    config = Config(
        input_device=_value(data, "input_device", None),
        output_device=_value(data, "output_device", None),
        sample_rate=int(_value(data, "sample_rate", 16000)),
        channels=int(_value(data, "channels", 1)),
        model=str(_value(data, "model", "small")),
        compute_type=str(_value(data, "compute_type", "int8")),
        vad_mode=str(_value(data, "vad_mode", "fixed")),
        fixed_seconds=float(_value(data, "fixed_seconds", 4.0)),
        silence_seconds=float(_value(data, "silence_seconds", 1.0)),
        voice_enabled=bool(_value(data, "voice_enabled", False)),
    )
    env = {
        "input_device": os.getenv("VOXCODE_INPUT_DEVICE"),
        "output_device": os.getenv("VOXCODE_OUTPUT_DEVICE"),
        "model": os.getenv("VOXCODE_MODEL"),
        "compute_type": os.getenv("VOXCODE_COMPUTE_TYPE"),
        "vad_mode": os.getenv("VOXCODE_VAD_MODE"),
    }
    for key, value in env.items():
        if value is not None:
            if key.endswith("device") and value.isdigit():
                value = int(value)
            config = replace(config, **{key: value})
    return config


def save_config(config: Config, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[voxcode]",
        f"input_device = {_toml_value(config.input_device)}",
        f"output_device = {_toml_value(config.output_device)}",
        f"sample_rate = {config.sample_rate}",
        f"channels = {config.channels}",
        f"model = {_toml_value(config.model)}",
        f"compute_type = {_toml_value(config.compute_type)}",
        f"vad_mode = {_toml_value(config.vad_mode)}",
        f"fixed_seconds = {config.fixed_seconds}",
        f"silence_seconds = {config.silence_seconds}",
        f"voice_enabled = {'true' if config.voice_enabled else 'false'}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _toml_value(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)
