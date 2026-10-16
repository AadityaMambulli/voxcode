"""Text-to-speech engine selection and fallback."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass


_active_process: subprocess.Popen[str] | None = None


@dataclass(frozen=True)
class TtsResult:
    engine: str
    detail: str


class TtsEngine:
    name = "unknown"

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def speak(self, text: str) -> TtsResult:
        raise NotImplementedError

    def stop(self) -> bool:
        return False


class PiperEngine(TtsEngine):
    name = "Piper"

    def available(self) -> tuple[bool, str]:
        path = shutil.which("piper")
        return (True, path or "piper") if path else (False, "piper executable not found")

    def speak(self, text: str) -> TtsResult:
        raise RuntimeError("Piper is detected but no voice model is configured")


class SapiEngine(TtsEngine):
    name = "Windows SAPI"

    def available(self) -> tuple[bool, str]:
        if platform.system() != "Windows":
            return False, "Windows SAPI is only available on Windows"
        return (True, "System.Speech.Synthesis available")

    def speak(self, text: str) -> TtsResult:
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Speak([Console]::In.ReadToEnd())"
        )
        try:
            process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            global _active_process
            _active_process = process
            process.communicate(text)
            if process.returncode:
                raise RuntimeError(f"Windows SAPI exited with code {process.returncode}")
        except OSError as exc:
            raise RuntimeError(f"Windows SAPI failed: {exc}") from exc
        finally:
            _active_process = None
        return TtsResult(self.name, "System.Speech.Synthesis")


class MacSayEngine(TtsEngine):
    name = "macOS say"

    def available(self) -> tuple[bool, str]:
        path = shutil.which("say")
        return (True, path or "say") if platform.system() == "Darwin" and path else (
            False,
            "macOS say is unavailable",
        )

    def speak(self, text: str) -> TtsResult:
        try:
            _run_process(["say", text])
        except OSError as exc:
            raise RuntimeError(f"macOS say failed: {exc}") from exc
        return TtsResult(self.name, "say")


class EspeakEngine(TtsEngine):
    name = "espeak-ng"

    def available(self) -> tuple[bool, str]:
        path = shutil.which("espeak-ng") or shutil.which("espeak")
        return (True, path) if path else (False, "espeak-ng/espeak executable not found")

    def speak(self, text: str) -> TtsResult:
        executable = shutil.which("espeak-ng") or shutil.which("espeak")
        if not executable:
            raise RuntimeError("espeak-ng/espeak executable not found")
        try:
            _run_process([executable, text])
        except OSError as exc:
            raise RuntimeError(f"espeak-ng failed: {exc}") from exc
        return TtsResult(self.name, executable)


def engines() -> list[TtsEngine]:
    return [PiperEngine(), SapiEngine(), MacSayEngine(), EspeakEngine()]


def choose_engine() -> tuple[TtsEngine | None, list[str]]:
    reasons: list[str] = []
    for engine in engines():
        available, detail = engine.available()
        if available:
            return engine, reasons
        reasons.append(f"{engine.name}: {detail}")
    return None, reasons


def speak(text: str) -> TtsResult:
    if not text.strip():
        raise ValueError("text must not be empty")
    engine, reasons = choose_engine()
    if engine is None:
        raise RuntimeError("No TTS engine available: " + "; ".join(reasons))
    return engine.speak(text)


def _run_process(command: list[str]) -> None:
    global _active_process
    process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _active_process = process
    try:
        _stdout, _stderr = process.communicate()
        if process.returncode:
            raise OSError(f"process exited with code {process.returncode}")
    finally:
        _active_process = None


def stop_speaking() -> bool:
    if _active_process is None or _active_process.poll() is not None:
        return False
    _active_process.terminate()
    return True
