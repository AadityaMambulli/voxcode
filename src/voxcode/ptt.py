"""Push-to-talk capture and Windows foreground typing."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

from .audio import record_until_stopped, select_device
from .config import Config
from .stt import SttEngine, _cached_model_path, download_model, model_size_mb

_KEY_CODES = {f"F{number}": 0x6F + number for number in range(1, 25)}
_WM_HOTKEY = 0x0312
_PM_REMOVE = 0x0001
_INPUT_KEYBOARD = 1
_KEYEVENTF_UNICODE = 0x0004
_KEYEVENTF_KEYUP = 0x0002
_VK_RETURN = 0x0D
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_GMEM_ZEROINIT = 0x0040
_cue_lock = threading.Lock()
_cue_failures = 0
_cue_disabled = False
_CUE_FAILURE_LIMIT = 2


def key_code(name: str) -> int:
    normalized = name.strip().upper()
    if normalized not in _KEY_CODES:
        raise ValueError(
            "ptt_key must be a function key name F1-F24; bare letter keys are not allowed"
        )
    return _KEY_CODES[normalized]


def sanitize_transcript(text: str, max_chars: int) -> str:
    cleaned = "".join(" " if char in "\r\n\t" else char for char in text)
    cleaned = "".join(char for char in cleaned if ord(char) >= 32)
    return re.sub(r" {2,}", " ", cleaned).strip()[:max_chars]


_ULONG_PTR = ctypes.c_void_p


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.wintypes.DWORD),
        ("wParamL", ctypes.wintypes.WORD),
        ("wParamH", ctypes.wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.wintypes.DWORD), ("u", _INPUTUNION)]


def _send_input_events(inputs: list[_INPUT]) -> int:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    send_input = user32.SendInput
    send_input.argtypes = (
        ctypes.wintypes.UINT,
        ctypes.POINTER(_INPUT),
        ctypes.c_int,
    )
    send_input.restype = ctypes.wintypes.UINT
    input_array = (_INPUT * len(inputs))(*inputs)
    return int(send_input(len(inputs), input_array, ctypes.sizeof(_INPUT)))


def type_text(text: str, auto_submit: bool = False) -> None:
    if sys.platform != "win32":
        raise RuntimeError("foreground typing is not supported on this platform yet")
    inputs: list[_INPUT] = []
    for char in text:
        inputs.append(
            _INPUT(
                type=_INPUT_KEYBOARD,
                ki=_KEYBDINPUT(
                    wVk=0,
                    wScan=ord(char),
                    dwFlags=_KEYEVENTF_UNICODE,
                    time=0,
                    dwExtraInfo=None,
                ),
            )
        )
        inputs.append(
            _INPUT(
                type=_INPUT_KEYBOARD,
                ki=_KEYBDINPUT(
                    wVk=0,
                    wScan=ord(char),
                    dwFlags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP,
                    time=0,
                    dwExtraInfo=None,
                ),
            )
        )
    if auto_submit:
        inputs.extend(
            [
                _INPUT(
                    type=_INPUT_KEYBOARD,
                    ki=_KEYBDINPUT(wVk=_VK_RETURN),
                ),
                _INPUT(
                    type=_INPUT_KEYBOARD,
                    ki=_KEYBDINPUT(wVk=_VK_RETURN, dwFlags=_KEYEVENTF_KEYUP),
                ),
            ]
        )
    if inputs:
        sent = _send_input_events(inputs)
        if sent != len(inputs):
            error = ctypes.get_last_error()
            raise RuntimeError(
                f"SendInput typed {sent} of {len(inputs)} keyboard events "
                f"(WinError {error}: {ctypes.WinError(error)})"
            )


def copy_to_clipboard(text: str) -> None:
    if sys.platform != "win32":
        raise RuntimeError("clipboard fallback is not supported on this platform yet")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
    kernel32.GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = ctypes.wintypes.HGLOBAL
    user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
    user32.OpenClipboard.restype = ctypes.wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
    user32.SetClipboardData.argtypes = [
        ctypes.wintypes.UINT,
        ctypes.wintypes.HANDLE,
    ]
    user32.SetClipboardData.restype = ctypes.wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.wintypes.BOOL
    encoded = (text + "\x00").encode("utf-16-le")
    memory = kernel32.GlobalAlloc(_GMEM_MOVEABLE | _GMEM_ZEROINIT, len(encoded))
    if not memory:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        locked = kernel32.GlobalLock(memory)
        if not locked:
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(locked, encoded, len(encoded))
        kernel32.GlobalUnlock(memory)
        if not user32.OpenClipboard(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not user32.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            if not user32.SetClipboardData(_CF_UNICODETEXT, memory):
                raise ctypes.WinError(ctypes.get_last_error())
            memory = None
        finally:
            user32.CloseClipboard()
    finally:
        if memory:
            kernel32.GlobalFree(memory)


class WindowsHotkey:
    name: str
    virtual_key: int
    _id: int

    def __init__(self, name: str) -> None:
        if sys.platform != "win32":
            raise RuntimeError("PTT hotkeys are not supported on this platform yet")
        self.name = name
        self.virtual_key = key_code(name)
        self._id = 0x5643

    def register(self) -> None:
        if not ctypes.windll.user32.RegisterHotKey(None, self._id, 0, self.virtual_key):
            raise RuntimeError(
                f"could not register global hotkey {self.name}; it may be in use"
            )

    def unregister(self) -> None:
        ctypes.windll.user32.UnregisterHotKey(None, self._id)

    def events(self, mode: str) -> Iterator[str]:
        if mode not in {"hold", "toggle"}:
            raise ValueError("ptt_mode must be 'hold' or 'toggle'")
        self.register()
        try:
            while True:
                message = ctypes.wintypes.MSG()
                while not ctypes.windll.user32.PeekMessageW(
                    ctypes.byref(message), None, 0, 0, _PM_REMOVE
                ):
                    time.sleep(0.02)
                if message.message != _WM_HOTKEY:
                    continue
                yield "press"
                if mode == "hold":
                    while ctypes.windll.user32.GetAsyncKeyState(self.virtual_key) & 0x8000:
                        time.sleep(0.02)
                    yield "release"
        finally:
            self.unregister()


def ptt_readiness(config: Config) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "not supported on this platform yet (Windows only)"
    try:
        hotkey = WindowsHotkey(config.ptt_key)
        hotkey.register()
        hotkey.unregister()
    except (OSError, RuntimeError, ValueError) as exc:
        return False, str(exc)
    return True, f"{config.ptt_key} can be registered without administrator rights"


class PttListener:
    def __init__(
        self,
        config: Config,
        stt: Any,
        hotkey: Any | None = None,
        recorder: Callable[..., tuple[Any, int]] = record_until_stopped,
        typer: Callable[[str, bool], None] = type_text,
        progress: Callable[[str], None] = print,
        model_ready: Callable[[], bool] | None = None,
        hosted: bool = False,
        on_transcript: Callable[[str], None] | None = None,
        device_selector: Callable[..., tuple[Any, str]] = select_device,
    ) -> None:
        self.config = config
        self.stt = stt
        self.hotkey = hotkey or WindowsHotkey(config.ptt_key)
        self.recorder = recorder
        self.typer = typer
        self.progress = progress
        self.model_ready = model_ready or (lambda: True)
        self.hosted = hosted
        self.on_transcript = on_transcript
        self.device_selector = device_selector
        self.status = "disabled"
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture_stop: threading.Event | None = None
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        if sys.platform != "win32" and isinstance(self.hotkey, WindowsHotkey):
            self.status = "unsupported_platform"
            return
        self.status = "active" if self.model_ready() else "waiting_for_model"
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._capture_stop is not None:
            self._capture_stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._worker is not None:
            self._worker.join(timeout=5)
        if self.status == "active":
            self.status = "disabled"

    def _run(self) -> None:
        try:
            active = False
            for event in self.hotkey.events(self.config.ptt_mode):
                if self._stop.is_set():
                    break
                if event == "press":
                    if not self.model_ready():
                        self.status = "waiting_for_model"
                        _cue(440)
                        continue
                    if self.config.ptt_mode == "toggle" and active:
                        self._finish_capture()
                        active = False
                    else:
                        active = True
                        self.status = "active"
                        self._start_capture()
                elif event == "release" and active:
                    active = False
                    self._finish_capture()
        except RuntimeError as exc:
            self.error = str(exc)
            self.status = (
                "owned_by_another_process"
                if "in use" in str(exc).lower() or "register" in str(exc).lower()
                else "error"
            )
            self._report(
                "PTT unavailable: plugin listener or another process already owns "
                f"{self.config.ptt_key}"
                if self.status == "owned_by_another_process"
                else f"PTT error: {exc}"
            )
        except Exception as exc:
            self.error = str(exc)
            self.status = "error"
            self._report(f"PTT listener error: {exc}")

    def _start_capture(self) -> None:
        self._capture_stop = threading.Event()
        self._worker = threading.Thread(
            target=self._process_capture,
            args=(self._capture_stop,),
            daemon=True,
        )
        self._worker.start()

    def _finish_capture(self) -> None:
        if self._capture_stop is not None:
            self._capture_stop.set()
        if self._worker is not None:
            self._worker.join(timeout=5)

    def _process_capture(self, capture_stop: threading.Event) -> None:
        try:
            if self.config.ptt_beep:
                _cue(880)
            self._report("recording...")
            audio, sample_rate = self.recorder(
                sample_rate=self.config.sample_rate,
                channels=self.config.channels,
                device=self._device().index,
                stop_event=capture_stop,
                max_seconds=60.0,
                progress=self.progress,
            )
            if self.config.ptt_beep:
                _cue(660)
            self._report("transcribing...")
            transcript, _seconds = self.stt.transcribe(
                audio, sample_rate, self.config.language
            )
            text = sanitize_transcript(transcript, self.config.ptt_max_chars)
            if not text:
                self._report("empty transcript; nothing typed")
                return
            if self.on_transcript is not None:
                self.on_transcript(text)
            self._report(f"transcript: {text}")
            try:
                self.typer(text, self.config.ptt_auto_submit)
            except Exception as exc:
                self._report(f"typing failed: {exc}")
                try:
                    copy_to_clipboard(text)
                except Exception as clipboard_exc:
                    self._report(f"clipboard fallback failed: {clipboard_exc}")
                else:
                    self._report(
                        "typing failed; text copied to clipboard, press Ctrl+V"
                    )
            else:
                self._report(f"typed {len(text)} characters")
        except Exception as exc:
            self.error = str(exc)
            self.status = "error"
            self._report(f"PTT capture failed: {exc}")
            if self.config.ptt_beep:
                _cue(440)

    def _report(self, message: str) -> None:
        try:
            self.progress(message)
        except Exception as exc:
            print(f"PTT progress reporting failed: {exc}", file=sys.stderr, flush=True)

    def _device(self) -> Any:
        selected, _reason = self.device_selector(
            self.config.input_device_name or self.config.input_device,
            "input",
            self.config.input_device_hostapi,
        )
        if selected is None:
            raise RuntimeError("No input device is available for PTT")
        return selected


def run_ptt(
    config: Config,
    stt: Any | None = None,
    hotkey: Any | None = None,
    recorder: Callable[..., tuple[Any, int]] = record_until_stopped,
    typer: Callable[[str, bool], None] = type_text,
    progress: Callable[[str], None] = print,
    download_yes: bool = False,
) -> int:
    injected_backend = (
        hotkey is not None
        or stt is not None
        or recorder is not record_until_stopped
        or typer is not type_text
    )
    if sys.platform != "win32" and not injected_backend:
        progress("[FAIL] PTT is not supported on this platform yet (Windows only)")
        return 1
    key_code(config.ptt_key)
    if config.ptt_mode not in {"hold", "toggle"}:
        raise ValueError("ptt_mode must be 'hold' or 'toggle'")
    selected, reason = select_device(
        config.input_device_name or config.input_device,
        "input",
        config.input_device_hostapi,
    )
    if selected is None:
        raise RuntimeError("No input device is available for PTT; run `voxcode devices`")
    engine = stt or SttEngine(
        config.model,
        config.compute_type,
        progress,
        local_only=True,
    )
    if stt is None and _cached_model_path(config.model) is None:
        if not download_yes:
            answer = input(
                f"Download speech model {config.model!r} "
                f"(~{model_size_mb(config.model)} MB)? [Y/n] "
            ).strip().lower()
            if answer not in {"", "y", "yes"}:
                progress("PTT cancelled; speech model was not downloaded")
                return 1
        try:
            download_model(config.model, progress=progress)
        except RuntimeError as exc:
            progress(
                f"PTT model download failed: {exc}. Retry with the full command: "
                'uvx --from "voxcode[audio,stt,vad,mcp] @ '
                'git+https://github.com/AadityaMambulli/voxcode.git" '
                f"voxcode ptt --yes"
            )
            return 1
    preload = getattr(engine, "preload", None)
    if preload is not None:
        preload(local_only=True)
    progress(
        f"PTT ready: hold {config.ptt_key} to dictate "
        f"(mode={config.ptt_mode}, input={selected.name}, chosen by {reason})"
    )
    progress("Press Ctrl+C to stop.")
    listener = PttListener(
        config, engine, hotkey, recorder, typer, progress, hosted=False
    )
    try:
        listener.start()
        if listener._thread is not None:
            listener._thread.join()
    except KeyboardInterrupt:
        listener.stop()
        progress("PTT stopped")
    if listener.status in {"owned_by_another_process", "error"}:
        return 1
    return 0


def _beep(frequency: int) -> None:
    global _cue_disabled, _cue_failures
    with _cue_lock:
        if _cue_disabled:
            return
    try:
        if sys.platform == "win32":
            import winsound

            winsound.Beep(frequency, 80)
    except BaseException as exc:
        with _cue_lock:
            _cue_failures += 1
            if _cue_failures >= _CUE_FAILURE_LIMIT:
                _cue_disabled = True
            should_log = _cue_failures == 1
        if should_log:
            print(
                f"PTT audio cue disabled after failure: {exc}",
                file=sys.stderr,
                flush=True,
            )


def _cue(frequency: int) -> None:
    try:
        thread = threading.Thread(target=_beep, args=(frequency,), daemon=True)
        thread.start()
    except BaseException as exc:
        print(f"PTT audio cue could not start: {exc}", file=sys.stderr, flush=True)
