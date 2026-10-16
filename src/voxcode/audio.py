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


def select_device(
    configured: int | str | None,
    direction: str,
    configured_hostapi: str | None = None,
) -> tuple[AudioDevice | None, str]:
    devices = list_devices()
    candidates = [
        device
        for device in devices
        if (device.max_input_channels if direction == "input" else device.max_output_channels)
    ]
    if configured is not None:
        configured_device = next(
            (
                device for device in candidates
                if (device.index == configured or device.name == configured)
                and (configured_hostapi is None or device.hostapi == configured_hostapi)
            ),
            None,
        )
        if configured_device is not None:
            return configured_device, "configured"
    default_device = next(
        (
            device
            for device in candidates
            if (device.is_default_input if direction == "input" else device.is_default_output)
        ),
        None,
    )
    if default_device is not None:
        return default_device, "OS default"
    if candidates:
        return candidates[0], f"fallback: first available {direction}"
    return None, "no available device"


def selected_device(configured: int | str | None, direction: str) -> AudioDevice | None:
    return select_device(configured, direction)[0]


def record(
    seconds: float,
    sample_rate: int,
    channels: int,
    device: int | str | None,
    vad_mode: str = "auto",
    silence_seconds: float = 1.0,
    vad_aggressiveness: int = 2,
    silence_threshold: float = 0.01,
    debug_vad: bool = False,
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
    if vad_mode == "auto":
        try:
            return _record_with_vad(
                sd,
                seconds,
                actual_sample_rate,
                channels,
                device,
                silence_seconds,
                vad_aggressiveness,
                silence_threshold,
                debug_vad,
                progress,
            )
        except RuntimeError as exc:
            progress(f"VAD unavailable ({exc}); falling back to fixed-seconds mode")
    progress(f"recording... (fixed-seconds, max {seconds:g}s)")
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


def _record_with_vad(
    sd: Any,
    max_seconds: float,
    sample_rate: int,
    channels: int,
    device: int | str | None,
    silence_seconds: float,
    vad_aggressiveness: int = 2,
    silence_threshold: float = 0.01,
    debug_vad: bool = False,
    progress: Callable[[str], None] = print,
) -> tuple[Any, int]:
    try:
        import webrtcvad
    except ImportError as exc:
        raise RuntimeError(
            "install `pip install -e .[vad]` for auto-stop VAD"
        ) from exc
    if sample_rate not in (8000, 16000, 32000, 48000):
        raise RuntimeError(f"webrtc VAD does not support {sample_rate}Hz")
    frame_ms = 30
    frame_samples = sample_rate * frame_ms // 1000
    vad = webrtcvad.Vad(vad_aggressiveness)
    chunks: list[Any] = []
    speech_started = False
    silence_frames = 0
    silence_limit = max(1, round(silence_seconds * 1000 / frame_ms))
    initial_silence_limit = silence_limit * 2
    progress(f"recording... (auto-stop, max {max_seconds:g}s)")
    started = time.perf_counter()
    energies: list[float] = []
    noise_floor: float | None = None
    with sd.InputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="float32",
        device=device,
        blocksize=frame_samples,
    ) as stream:
        while time.perf_counter() - started < max_seconds:
            data, _overflowed = stream.read(frame_samples)
            chunks.append(data.copy())
            mono = data[:, 0] if channels > 1 else data[:, 0]
            pcm = (mono * 32767).astype("int16").tobytes()
            energy = float((mono**2).mean() ** 0.5)
            energies.append(energy)
            if len(energies) <= max(1, round(0.3 * 1000 / frame_ms)):
                noise_floor = sum(energies) / len(energies)
            adaptive_threshold = max(
                silence_threshold,
                (noise_floor or silence_threshold) * 2.5,
            )
            vad_speech = vad.is_speech(pcm, sample_rate)
            is_speech = vad_speech and (
                energy + 1e-6 >= adaptive_threshold or speech_started
            )
            if debug_vad:
                progress(
                    f"vad frame={len(chunks)} rms={energy:.5f} "
                    f"noise_floor={noise_floor or 0:.5f} "
                    f"threshold={adaptive_threshold:.5f} speech={is_speech}"
                )
            if is_speech:
                speech_started = True
                silence_frames = 0
            else:
                silence_frames += 1
                limit = silence_limit if speech_started else initial_silence_limit
                if silence_frames >= limit:
                    break
    progress(f"recorded {time.perf_counter() - started:.2f}s with VAD auto-stop")
    if not chunks:
        raise RuntimeError("VAD captured no audio")
    return __import__("numpy").concatenate(chunks, axis=0), sample_rate
