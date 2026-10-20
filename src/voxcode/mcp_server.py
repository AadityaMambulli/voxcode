"""stdio MCP server exposing the shared voxcode voice operations."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import replace
from contextlib import asynccontextmanager
from concurrent.futures import TimeoutError
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

DEFAULT_DOWNLOAD_STALL_TIMEOUT_SECONDS = 600

def create_server(fake: bool = False, stt_engine: Any | None = None) -> FastMCP:
    from . import core
    from .audio import AudioDevice, record_until_stopped
    from .config import load_config, save_config
    from .ptt import PttListener
    from .stt import (
        SttEngine,
        _cached_model_path,
        download_model,
        model_size_label,
    )
    from .tts import TtsResult, speak as tts_speak

    config = load_config()
    class FakeStt:
        _model = object()

        def preload(self, local_only: bool = True) -> float:
            return 0.0

        def transcribe(
            self, audio: Any, sample_rate: int, language: str | None = None
        ) -> tuple[str, float]:
            return f"fake transcript ({audio}, {sample_rate}Hz)", 0.001

    shared_stt = stt_engine or (
        FakeStt()
        if fake
        else SttEngine(
            config.model,
            config.compute_type,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
            local_only=True,
        )
    )
    download_lock = threading.Lock()
    ptt_listener: PttListener | None = None
    ptt_timer: threading.Timer | None = None
    ptt_status = "disabled"
    ptt_last_transcript = ""
    download_state: dict[str, str] = {"status": "ready", "detail": ""}
    if not fake and _cached_model_path(config.model) is None:
        download_state = {
            "status": "missing",
            "detail": (
                f"Downloading speech model (~{model_size_label(config.model)}), "
                "try again in a minute"
            ),
        }

    def preload_model() -> None:
        if shared_stt is not None:
            try:
                shared_stt.preload(local_only=True)
            except RuntimeError as exc:
                print(f"model preload failed: {exc}", file=sys.stderr, flush=True)

    def download_in_background() -> None:
        with download_lock:
            if download_state["status"] == "downloading":
                return
            download_state["status"] = "downloading"
            download_state["detail"] = (
                f"Downloading speech model (~{model_size_label(config.model)}), "
                "try again in a minute"
            )
        started = time.perf_counter()
        try:
            stall_timeout = float(
                os.environ.get(
                    "VOXCODE_DOWNLOAD_STALL_TIMEOUT_SECONDS",
                    str(DEFAULT_DOWNLOAD_STALL_TIMEOUT_SECONDS),
                )
            )
            if stall_timeout <= 0:
                raise ValueError
        except ValueError:
            with download_lock:
                download_state["status"] = "download_failed"
                download_state["detail"] = (
                    "invalid VOXCODE_DOWNLOAD_STALL_TIMEOUT_SECONDS; "
                    "use a positive number"
                )
            print(download_state["detail"], file=sys.stderr, flush=True)
            return
        last_progress = started
        last_cache_size = 0
        reconstruct_started: float | None = None
        progress_lock = threading.Lock()

        def cache_size() -> int:
            cache_root = Path(
                os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
            )
            model_root = (
                cache_root
                / "hub"
                / f"models--Systran--faster-whisper-{config.model}"
            )
            return sum(
                path.stat().st_size
                for path in model_root.rglob("*")
                if path.is_file()
            )

        def report(message: str) -> None:
            nonlocal last_progress, reconstruct_started
            now = time.perf_counter()
            with progress_lock:
                last_progress = now
                if "Reconstructing" in message and reconstruct_started is None:
                    reconstruct_started = now
            print(message, file=sys.stderr, flush=True)

        executor = ThreadPoolExecutor(max_workers=1)
        download_error: Exception | None = None
        try:
            future = executor.submit(
                download_model,
                config.model,
                report,
            )
            while True:
                try:
                    future.result(timeout=1.0)
                    break
                except FutureTimeoutError:
                    now = time.perf_counter()
                    current_cache_size = cache_size()
                    with progress_lock:
                        if current_cache_size > last_cache_size:
                            last_cache_size = current_cache_size
                            last_progress = now
                        stalled_for = now - last_progress
                    if stalled_for >= stall_timeout:
                        raise RuntimeError(
                            f"speech model download stalled for "
                            f"{stall_timeout:g}s; "
                            "partial files remain resumable"
                        )
            if shared_stt is not None:
                shared_stt.preload(local_only=True)
        except FutureTimeoutError:
            download_error = RuntimeError("speech model download worker timed out")
        except Exception as exc:
            download_error = exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if download_error is not None:
            with download_lock:
                download_state["status"] = "download_failed"
                download_state["detail"] = (
                    f"speech model download failed: {download_error}; "
                    "retry the listen call"
                )
            print(
                f"model download failed after {time.perf_counter() - started:.1f}s: "
                f"{download_error}",
                file=sys.stderr,
                flush=True,
            )
        else:
            completed = time.perf_counter()
            reconstruction_seconds = (
                completed - reconstruct_started
                if reconstruct_started is not None
                else 0.0
            )
            download_seconds = (
                reconstruct_started - started
                if reconstruct_started is not None
                else completed - started
            )
            print(
                f"model download complete: download_seconds={download_seconds:.1f}, "
                f"reconstruct_seconds={reconstruction_seconds:.1f}",
                file=sys.stderr,
                flush=True,
            )
            with download_lock:
                download_state["status"] = "ready"
                download_state["detail"] = ""

    def start_download_if_needed() -> None:
        if fake or _cached_model_path(config.model) is not None:
            return
        with download_lock:
            if download_state["status"] == "ready":
                return
            if download_state["status"] == "downloading":
                return
        threading.Thread(target=download_in_background, daemon=True).start()

    def ptt_progress(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    def ptt_model_ready() -> bool:
        return fake or getattr(shared_stt, "_model", None) is not None

    def start_ptt() -> None:
        nonlocal ptt_listener, ptt_status
        if not config.ptt_autostart or ptt_listener is not None:
            return
        if fake:
            class FakeHotkey:
                def events(self, _mode: str):
                    yield "press"
                    yield "release"

            fake_hotkey: Any = FakeHotkey()
            fake_recorder = fake_record
            def fake_typer(text: str, _submit: bool) -> None:
                nonlocal ptt_last_transcript
                ptt_last_transcript = text
                ptt_progress(f"typed: {text}")
        else:
            fake_hotkey = None
            fake_recorder = core.record_until_stopped
            from .ptt import type_text

            fake_typer = type_text
        listener_config = replace(
            config,
            ptt_beep=config.ptt_beep
            if config.sources.get("ptt_beep") in {"file", "environment"}
            else True,
        )
        ptt_listener = PttListener(
            listener_config,
            shared_stt if shared_stt is not None else FakeStt(),
            hotkey=fake_hotkey,
            recorder=fake_recorder,
            typer=fake_typer,
            progress=ptt_progress,
            model_ready=ptt_model_ready,
            hosted=True,
        )
        ptt_listener.start()
        ptt_status = (
            "waiting_for_model" if not ptt_model_ready() else ptt_listener.status
        )

    def stop_ptt() -> None:
        nonlocal ptt_listener, ptt_status
        if ptt_listener is not None:
            ptt_listener.stop()
            ptt_status = "disabled"
            ptt_listener = None

    def refresh_ptt_status() -> str:
        nonlocal ptt_status
        if ptt_listener is not None:
            ptt_status = ptt_listener.status
            if not ptt_model_ready() and ptt_status in {"active", "disabled"}:
                ptt_status = "waiting_for_model"
        return ptt_status

    @asynccontextmanager
    async def lifespan(_server: FastMCP[Any]):
        nonlocal ptt_timer
        if shared_stt is not None and not fake:
            if _cached_model_path(config.model) is None:
                start_download_if_needed()
            else:
                threading.Thread(target=preload_model, daemon=True).start()
        if config.ptt_autostart:
            ptt_timer = threading.Timer(0.2, start_ptt)
            ptt_timer.daemon = True
            ptt_timer.start()
        yield {}
        if ptt_timer is not None:
            ptt_timer.cancel()
        stop_ptt()

    mcp = FastMCP("voxcode", lifespan=lifespan)
    fake_device = AudioDevice(0, "fake microphone", 1, 0, "fake", True, False)

    def fake_select(
        _configured: Any,
        _direction: str,
        _hostapi: str | None = None,
    ) -> tuple[AudioDevice, str]:
        return fake_device, "explicit fake backend"

    def fake_record(**_kwargs: Any) -> tuple[str, int]:
        return "fake audio", 16000

    def fake_speak(text: str) -> TtsResult:
        return TtsResult("fake", text)

    @mcp.tool()
    def listen(timeout_s: float = 4.0) -> dict[str, Any]:
        """Record and transcribe speech for at most timeout_s seconds."""
        if timeout_s <= 0:
            return {"transcript": "", "error": "timeout_s must be positive"}
        if not fake and _cached_model_path(config.model) is None:
            start_download_if_needed()
            with download_lock:
                status = download_state["status"]
                detail = download_state["detail"]
            if status == "downloading" or status == "missing":
                return {
                    "transcript": "",
                    "error": None,
                    "status": "downloading_model",
                    "detail": detail,
                }
            if status == "download_failed":
                return {
                    "transcript": "",
                    "error": detail,
                    "status": "download_failed",
                    "detail": "Retry the listen call to try the download again",
                }
        active_config = replace(config, fixed_seconds=timeout_s)
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            core.listen,
            active_config,
            lambda message: print(message, file=sys.stderr, flush=True),
            shared_stt if shared_stt is not None else FakeStt(),
            fake_select if fake else core.select_device,
            fake_record if fake else core.record,
        )
        try:
            deadline = max(120.0, timeout_s + 30.0)
            result = future.result(timeout=deadline)
        except TimeoutError:
            future.cancel()
            return {
                "transcript": "",
                "error": f"listen exceeded {deadline:g}s deadline",
            }
        except Exception as exc:
            return {"transcript": "", "error": str(exc)}
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return {
            "transcript": result.transcript,
            "error": None,
            "record_seconds": result.record_seconds,
            "transcription_seconds": result.transcription_seconds,
            "model_load_seconds": result.model_load_seconds,
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
            "ptt": refresh_ptt_status(),
            "ptt_transcript": ptt_last_transcript if fake else None,
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
        ptt_autostart: bool | None = None,
        ptt_beep: bool | None = None,
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
                "ptt_autostart": ptt_autostart,
                "ptt_beep": ptt_beep,
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
        if ptt_autostart is False:
            stop_ptt()
        elif ptt_autostart is True and ptt_listener is None:
            start_ptt()
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
