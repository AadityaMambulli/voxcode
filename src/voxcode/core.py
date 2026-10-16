"""Shared voice operations used by the CLI."""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

from .audio import AudioDevice, list_devices, record, select_device
from .config import Config
from .stt import SttEngine
from .tts import TtsResult, choose_engine, speak as speak_text, stop_speaking as stop_tts


@dataclass(frozen=True)
class ListenResult:
    transcript: str
    record_seconds: float
    transcription_seconds: float


def speak(text: str, speak_fn: Callable[[str], TtsResult] = speak_text) -> TtsResult:
    return speak_fn(text)


def stop_speaking() -> bool:
    return stop_tts()


def listen(
    config: Config,
    progress: Callable[[str], None] = print,
    stt: SttEngine | None = None,
    device_selector: Callable[..., tuple[AudioDevice | None, str]] = select_device,
    recorder: Callable[..., tuple[Any, int]] = record,
    language: str | None = None,
    verbose: bool = False,
    debug_vad: bool = False,
) -> ListenResult:
    configured = config.input_device_name or config.input_device
    if config.input_device_hostapi is None:
        input_device, selection_reason = device_selector(configured, "input")
    else:
        input_device, selection_reason = device_selector(
            configured, "input", config.input_device_hostapi
        )
    if input_device is None:
        raise RuntimeError(
            "No input device is available; connect or enable a microphone, "
            "then run `voxcode devices`."
        )
    progress(
        f"input device: {input_device.index} {input_device.name} "
        f"(chosen by {selection_reason})"
    )
    started = time.perf_counter()
    audio, actual_sample_rate = recorder(
        seconds=config.fixed_seconds,
        sample_rate=config.sample_rate,
        channels=config.channels,
        device=input_device.index,
        vad_mode=config.vad_mode,
        silence_seconds=config.silence_seconds,
        vad_aggressiveness=config.vad_aggressiveness,
        silence_threshold=config.silence_threshold,
        debug_vad=debug_vad,
        progress=progress,
    )
    record_seconds = time.perf_counter() - started
    stt_engine = stt or SttEngine(config.model, config.compute_type, progress, verbose)
    transcript, transcription_seconds = stt_engine.transcribe(
        audio, actual_sample_rate, language
    )
    return ListenResult(transcript, record_seconds, transcription_seconds)


def device_summary(config: Config) -> tuple[list[AudioDevice], AudioDevice | None, AudioDevice | None]:
    devices = list_devices()
    return (
        devices,
        select_device(config.input_device_name or config.input_device, "input",
                      config.input_device_hostapi)[0],
        select_device(config.output_device_name or config.output_device, "output",
                      config.output_device_hostapi)[0],
    )


def doctor(config: Config) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    version_ok = sys.version_info >= (3, 10) and sys.version_info < (3, 14)
    version_detail = platform.python_version()
    if not version_ok:
        version_detail += " is unsupported; use Python >=3.10,<3.14"
    checks.append(("Python version", version_ok, version_detail))

    try:
        import sounddevice  # noqa: F401
        devices, input_device, output_device = device_summary(config)
        checks.append(("sounddevice import", True, "imported"))
        checks.append(
            (
                "audio devices",
                bool(devices),
                f"{len(devices)} device(s) enumerated",
            )
        )
        try:
            import webrtcvad  # noqa: F401
        except ImportError as exc:
            checks.append(("VAD auto-stop", False, str(exc)))
        else:
            checks.append(("VAD auto-stop", True, "webrtcvad imported"))
        checks.append(
            (
                "chosen input device",
                input_device is not None,
                _device_detail(input_device, "No input device selected"),
            )
        )
        checks.append(
            (
                "chosen output device",
                output_device is not None,
                _device_detail(output_device, "No output device selected"),
            )
        )
    except Exception as exc:
        checks.append(("sounddevice import/devices", False, str(exc)))

    try:
        import faster_whisper  # noqa: F401
        checks.append(("faster-whisper import", True, "imported"))
    except ImportError as exc:
        checks.append(("faster-whisper import", False, str(exc)))

    engine, reasons = choose_engine()
    if engine is None:
        checks.append(("TTS engine probe", False, "; ".join(reasons)))
    else:
        available, detail = engine.available()
        if not available:
            checks.append(("TTS engine probe", False, f"{engine.name}: {detail}"))
        else:
            try:
                result = engine.speak("voxcode doctor")
            except RuntimeError as exc:
                checks.append(("TTS engine probe", False, str(exc)))
            else:
                checks.append(
                    ("TTS engine probe", True, f"{result.engine}: {result.detail}")
                )
    return checks


def _device_detail(device: AudioDevice | None, missing: str) -> str:
    if device is None:
        return missing
    return f"{device.index}: {device.name} ({device.hostapi})"
