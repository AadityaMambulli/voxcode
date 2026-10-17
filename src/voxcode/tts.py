"""Text-to-speech engine selection and fallback."""

from __future__ import annotations

import platform
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass


_active_process: subprocess.Popen[str] | None = None
_ACTIVE_FILE = os.path.join(tempfile.gettempdir(), "voxcode-tts-active.json")


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
            _register_process(process)
            process.communicate(text)
            if process.returncode:
                raise RuntimeError(f"Windows SAPI exited with code {process.returncode}")
        except OSError as exc:
            raise RuntimeError(f"Windows SAPI failed: {exc}") from exc
        finally:
            _active_process = None
            _clear_process(process.pid)
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
    stop_speaking()
    engine, reasons = choose_engine()
    if engine is None:
        raise RuntimeError("No TTS engine available: " + "; ".join(reasons))
    return engine.speak(text)


def _run_process(command: list[str]) -> None:
    global _active_process
    process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _active_process = process
    _register_process(process)
    try:
        _stdout, _stderr = process.communicate()
        if process.returncode:
            raise OSError(f"process exited with code {process.returncode}")
    finally:
        _active_process = None
        _clear_process(process.pid)


def _register_process(process: subprocess.Popen[str]) -> None:
    payload = {"pid": process.pid, "started": time.time()}
    try:
        with open(_ACTIVE_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except OSError:
        pass


def _clear_process(pid: int) -> None:
    try:
        with open(_ACTIVE_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("pid") == pid:
            os.unlink(_ACTIVE_FILE)
    except (OSError, ValueError, TypeError):
        pass


def _shared_process() -> tuple[int, float] | None:
    try:
        with open(_ACTIVE_FILE, encoding="utf-8") as handle:
            payload = json.load(handle)
        pid, started = int(payload["pid"]), float(payload["started"])
        if os.name == "nt":
            current = _windows_process_start(pid)
            if current is None or abs(current - started) > 3:
                return None
        return pid, started
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _windows_process_start(pid: int) -> float | None:
    if os.name != "nt":
        return None
    command = (
        f"(Get-Process -Id {pid} -ErrorAction Stop).StartTime.ToUniversalTime()"
        ".Subtract([datetime]'1970-01-01').TotalSeconds"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             f"Get-Process -Id {pid} -ErrorAction SilentlyContinue"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _stop_shared_process(pid: int) -> bool:
    if not _process_exists(pid):
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    try:
        os.killpg(pid, signal.SIGTERM)
    except (NameError, OSError):
        os.kill(pid, signal.SIGTERM)
    return True


def stop_speaking() -> bool:
    stopped = False
    if _active_process is not None and _active_process.poll() is None:
        _active_process.terminate()
        stopped = True
    shared = _shared_process()
    if shared is not None:
        pid, _started = shared
        stopped = _stop_shared_process(pid) or stopped
        if not _process_exists(pid):
            try:
                os.unlink(_ACTIVE_FILE)
            except OSError:
                pass
    return stopped
