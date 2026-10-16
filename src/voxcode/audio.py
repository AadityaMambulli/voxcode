"""Audio device enumeration and microphone capture."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    hostapi: str
    is_default_input: bool = False
    is_default_output: bool = False


def _sounddevice() -> Any:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            "sounddevice is not installed; install with `pip install -e .[audio]`"
        ) from exc
    return sd


def list_devices() -> list[AudioDevice]:
    sd = _sounddevice()
    default = sd.default.device
    hostapis = sd.query_hostapis()
    preferred_hostapi = None
    if __import__("platform").system() == "Windows":
        preferred_hostapi = next(
            (
                index
                for index, hostapi in enumerate(hostapis)
                if "WASAPI" in str(hostapi["name"]).upper()
            ),
            None,
        )
    default_input = default[0] if default is not None else None
    default_output = default[1] if default is not None else None
    raw_devices = list(sd.query_devices())
    default_input_name = (
        str(raw_devices[default_input]["name"])
        if isinstance(default_input, int) and 0 <= default_input < len(raw_devices)
        else None
    )
    default_output_name = (
        str(raw_devices[default_output]["name"])
        if isinstance(default_output, int) and 0 <= default_output < len(raw_devices)
        else None
    )
    devices: list[AudioDevice] = []
    for index, raw in enumerate(raw_devices):
        hostapi_index = int(raw["hostapi"])
        if preferred_hostapi is not None and hostapi_index != preferred_hostapi:
            continue
        devices.append(
            AudioDevice(
                index=index,
                name=str(raw["name"]),
                max_input_channels=int(raw["max_input_channels"]),
                max_output_channels=int(raw["max_output_channels"]),
                hostapi=str(hostapis[hostapi_index]["name"]),
                is_default_input=index == default_input or str(raw["name"]) == default_input_name,
                is_default_output=index == default_output or str(raw["name"]) == default_output_name,
            )
        )
    return devices


def selected_device(configured: int | str | None, direction: str) -> AudioDevice | None:
    devices = list_devices()
    if configured is None:
        return next(
            (
                device
                for device in devices
                if (device.is_default_input if direction == "input" else device.is_default_output)
            ),
            None,
        )
    for device in devices:
        if device.index == configured or device.name == configured:
            return device
    raise ValueError(f"Configured {direction} device was not found: {configured!r}")


def record(
    seconds: float,
    sample_rate: int,
    channels: int,
    device: int | str | None,
    progress: Callable[[str], None] = print,
) -> tuple[Any, int]:
    sd = _sounddevice()
    actual_sample_rate = sample_rate
    try:
        sd.check_input_settings(
            device=device,
            samplerate=sample_rate,
            channels=channels,
        )
    except Exception:
        device_info = sd.query_devices(device, "input")
        actual_sample_rate = int(float(device_info["default_samplerate"]))
        progress(
            f"sample rate {sample_rate}Hz is unsupported; "
            f"using device default {actual_sample_rate}Hz"
        )
    progress(f"recording... ({seconds:g}s)")
    started = time.perf_counter()
    try:
        audio = sd.rec(
            int(seconds * actual_sample_rate),
            samplerate=actual_sample_rate,
            channels=channels,
            dtype="float32",
            device=device,
        )
        sd.wait()
    except Exception as exc:
        raise RuntimeError(f"microphone recording failed: {exc}") from exc
    progress(f"recorded {seconds:g}s in {time.perf_counter() - started:.2f}s")
    return audio, actual_sample_rate
