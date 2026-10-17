"""stdio MCP server exposing the shared voxcode voice operations."""

from __future__ import annotations

import argparse
import sys
import threading
from dataclasses import replace
from typing import Any

from mcp.server.fastmcp import FastMCP


def create_server(fake: bool = False, stt_engine: Any | None = None) -> FastMCP:
    from . import core
    from .audio import AudioDevice
    from .config import load_config, save_config
    from .stt import SttEngine
    from .tts import TtsResult, speak as tts_speak

    config = load_config()
    mcp = FastMCP("voxcode")
    shared_stt = stt_engine or (
        None
        if fake
        else SttEngine(
            config.model,
            config.compute_type,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
    )

    def preload_model() -> None:
        if shared_stt is not None:
            try:
                shared_stt._load()
            except RuntimeError as exc:
                print(f"model preload failed: {exc}", file=sys.stderr, flush=True)
    fake_device = AudioDevice(0, "fake microphone", 1, 0, "fake", True, False)

    def fake_select(_configured: Any, _direction: str) -> tuple[AudioDevice, str]:
        return fake_device, "explicit fake backend"

    def fake_record(**_kwargs: Any) -> tuple[str, int]:
        return "fake audio", 16000

    class FakeStt:
        def transcribe(self, audio: Any, sample_rate: int) -> tuple[str, float]:
            return f"fake transcript ({audio}, {sample_rate}Hz)", 0.001

    def fake_speak(text: str) -> TtsResult:
        return TtsResult("fake", text)

    @mcp.tool()
    def listen(timeout_s: float = 4.0) -> dict[str, Any]:
        """Record and transcribe speech for at most timeout_s seconds."""
        active_config = replace(config, fixed_seconds=timeout_s)
        result = core.listen(
            active_config,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
            stt=shared_stt if shared_stt is not None else FakeStt(),
            device_selector=fake_select if fake else core.select_device,
            recorder=fake_record if fake else core.record,
        )
        return {
            "transcript": result.transcript,
            "record_seconds": result.record_seconds,
            "transcription_seconds": result.transcription_seconds,
        }

    @mcp.tool()
    def speak(text: str, interrupt: bool = False) -> dict[str, Any]:
        """Speak text using the configured local TTS fallback."""
        if interrupt:
            core.stop_speaking()
        result = core.speak(text, fake_speak if fake else tts_speak)
        return {"engine": result.engine, "detail": result.detail}

    @mcp.tool()
    def stop_speaking() -> dict[str, bool]:
        """Stop active speech if the selected TTS backend supports interruption."""
        return {"stopped": core.stop_speaking()}

    @mcp.tool()
    def voice_status() -> dict[str, Any]:
        """Return current voice mode configuration and backend status."""
        engine, reasons = core.choose_engine()
        return {
            "enabled": config.voice_enabled,
            "input_device": config.input_device,
            "output_device": config.output_device,
            "language": config.language,
            "tts_engine": "fake" if fake else (engine.name if engine else None),
            "tts_reasons": reasons,
        }

    @mcp.tool()
    def voice_config(
        input_device: int | str | None = None,
        output_device: int | str | None = None,
        input_device_name: str | None = None,
        output_device_name: str | None = None,
        input_device_hostapi: str | None = None,
        output_device_hostapi: str | None = None,
        vad_mode: str | None = None,
        fixed_seconds: float | None = None,
        silence_seconds: float | None = None,
        voice_enabled: bool | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        """Update and persist provided voice configuration values."""
        nonlocal config
        updates = {
            key: value
            for key, value in {
                "input_device": input_device,
                "output_device": output_device,
                "vad_mode": vad_mode,
                "fixed_seconds": fixed_seconds,
                "silence_seconds": silence_seconds,
                "voice_enabled": voice_enabled,
                "language": language,
            }.items()
            if value is not None
        }
        if input_device is not None and input_device_name is None:
            selected, _reason = (fake_select if fake else core.select_device)(
                input_device, "input"
            )
            if selected is not None:
                updates.update(
                    input_device_name=selected.name,
                    input_device_hostapi=selected.hostapi,
                )
                updates.pop("input_device", None)
        if output_device is not None and output_device_name is None:
            selected, _reason = (fake_select if fake else core.select_device)(
                output_device, "output"
            )
            if selected is not None:
                updates.update(
                    output_device_name=selected.name,
                    output_device_hostapi=selected.hostapi,
                )
                updates.pop("output_device", None)
        config = replace(config, **updates)
        if config.voice_enabled and not fake:
            threading.Thread(target=preload_model, daemon=True).start()
        path = save_config(
            config,
            fields=set(updates),
        )
        return {"saved": str(path), "config": config.__dict__}

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voxcode-mcp")
    parser.add_argument("--fake", action="store_true", help="use explicit fake backends")
    args = parser.parse_args(argv)
    create_server(args.fake).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
