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
from .stt import SttEngine

_KEY_CODES = {f"F{number}": 0x6F + number for number in range(1, 25)}
_WM_HOTKEY = 0x0312
_PM_REMOVE = 0x0001
_INPUT_KEYBOARD = 1
_KEYEVENTF_UNICODE = 0x0004
_KEYEVENTF_KEYUP = 0x0002
_VK_RETURN = 0x0D


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


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


def type_text(text: str, auto_submit: bool = False) -> None:
    if sys.platform != "win32":
        raise RuntimeError("foreground typing is not supported on this platform yet")
    user32 = ctypes.windll.user32
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
        sent = user32.SendInput(
            len(inputs), (_INPUT * len(inputs))(*inputs), ctypes.sizeof(_INPUT)
        )
        if sent != len(inputs):
            raise RuntimeError(f"SendInput typed {sent} of {len(inputs)} keyboard events")


class WindowsHotkey:
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


def run_ptt(
    config: Config,
    stt: Any | None = None,
    hotkey: Any | None = None,
    recorder: Callable[..., tuple[Any, int]] = record_until_stopped,
    typer: Callable[[str, bool], None] = type_text,
    progress: Callable[[str], None] = print,
) -> int:
    if sys.platform != "win32":
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
    engine = stt or SttEngine(config.model, config.compute_type, progress)
    preload = getattr(engine, "preload", None)
    if preload is not None:
        preload(local_only=True)
    progress(
        f"PTT ready: hold {config.ptt_key} to dictate "
        f"(mode={config.ptt_mode}, input={selected.name}, chosen by {reason})"
    )
    progress("Press Ctrl+C to stop.")
    backend = hotkey or WindowsHotkey(config.ptt_key)
    stop_event: threading.Event | None = None
    worker: threading.Thread | None = None

    def start_capture() -> None:
        nonlocal stop_event, worker
        if worker is not None and worker.is_alive():
            return
        stop_event = threading.Event()
        worker = threading.Thread(target=process_capture, args=(stop_event,), daemon=True)
        worker.start()

    def process_capture(capture_stop: threading.Event) -> None:
        if config.ptt_beep:
            _beep(880)
        progress("recording...")
        audio, sample_rate = recorder(
            sample_rate=config.sample_rate,
            channels=config.channels,
            device=selected.index,
            stop_event=capture_stop,
            max_seconds=60.0,
            progress=progress,
        )
        progress("transcribing...")
        transcript, _seconds = engine.transcribe(audio, sample_rate, config.language)
        text = sanitize_transcript(transcript, config.ptt_max_chars)
        if text:
            typer(text, config.ptt_auto_submit)
            progress(f"typed {len(text)} characters")
        else:
            progress("empty transcript; nothing typed")
        if config.ptt_beep:
            _beep(660)

    try:
        active = False
        for event in backend.events(config.ptt_mode):
            if config.ptt_mode == "hold":
                if event == "press":
                    active = True
                    start_capture()
                elif event == "release" and active:
                    active = False
                    if stop_event is not None:
                        stop_event.set()
            elif event == "press":
                if active:
                    if stop_event is not None:
                        stop_event.set()
                    active = False
                else:
                    active = True
                    start_capture()
        if worker is not None:
            worker.join(timeout=5)
    except KeyboardInterrupt:
        if stop_event is not None:
            stop_event.set()
        if worker is not None:
            worker.join(timeout=5)
        progress("PTT stopped")
    return 0


def _beep(frequency: int) -> None:
    if sys.platform == "win32":
        import winsound

        winsound.Beep(frequency, 80)
