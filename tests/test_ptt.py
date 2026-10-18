import threading

import pytest

from voxcode.config import Config
from voxcode import ptt
from voxcode.ptt import key_code, run_ptt, sanitize_transcript


@pytest.mark.fake
def test_ptt_rejects_bare_letter_and_sanitizes_text() -> None:
    assert key_code("f9") == 0x78
    with pytest.raises(ValueError, match="function key"):
        key_code("a")
    assert sanitize_transcript(" hello\n\tworld\x00 ", 20) == "hello world"
    assert len(sanitize_transcript("abcdef", 3)) == 3


@pytest.mark.fake
def test_ptt_fake_key_event_types_without_enter(monkeypatch) -> None:
    class Device:
        index = 3
        name = "fake microphone"

    class FakeHotkey:
        def events(self, mode):
            assert mode == "hold"
            yield "press"
            yield "release"

    class FakeStt:
        def __init__(self):
            self.preloaded = False

        def preload(self, local_only=False):
            self.preloaded = local_only

        def transcribe(self, audio, sample_rate, language):
            return "hello\nworld", 0.01

    typed: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "voxcode.ptt.select_device",
        lambda configured, direction, hostapi=None: (Device(), "fake"),
    )
    engine = FakeStt()
    result = run_ptt(
        Config(ptt_auto_submit=False),
        stt=engine,
        hotkey=FakeHotkey(),
        recorder=lambda **kwargs: ("audio", 16000),
        typer=lambda text, submit: typed.append((text, submit)),
        progress=lambda _: None,
    )
    assert result == 0
    assert engine.preloaded is True
    assert typed == [("hello world", False)]


@pytest.mark.fake
def test_ptt_toggle_stops_and_types_once(monkeypatch) -> None:
    class Device:
        index = 3
        name = "fake microphone"

    class FakeHotkey:
        def events(self, mode):
            assert mode == "toggle"
            yield "press"
            yield "press"

    class FakeStt:
        def preload(self, local_only=False):
            pass

        def transcribe(self, audio, sample_rate, language):
            return "one phrase", 0.01

    calls: list[threading.Event] = []
    typed: list[str] = []
    monkeypatch.setattr(
        "voxcode.ptt.select_device",
        lambda configured, direction, hostapi=None: (Device(), "fake"),
    )
    run_ptt(
        Config(ptt_mode="toggle"),
        stt=FakeStt(),
        hotkey=FakeHotkey(),
        recorder=lambda **kwargs: (calls.append(kwargs["stop_event"]) or ("audio", 16000)),
        typer=lambda text, submit: typed.append(text),
        progress=lambda _: None,
    )
    assert typed == ["one phrase"]
    assert calls and calls[0].is_set()


@pytest.mark.fake
def test_ptt_sendinput_failure_copies_transcript(monkeypatch) -> None:
    class Device:
        index = 3
        name = "fake microphone"

    class FakeHotkey:
        def events(self, mode):
            yield "press"
            yield "release"

    class FakeStt:
        def preload(self, local_only=False):
            pass

        def transcribe(self, audio, sample_rate, language):
            return "hello world", 0.01

    messages: list[str] = []
    copied: list[str] = []
    monkeypatch.setattr(
        "voxcode.ptt.select_device",
        lambda configured, direction, hostapi=None: (Device(), "fake"),
    )
    monkeypatch.setattr(ptt, "_send_input_events", lambda inputs: 0)
    monkeypatch.setattr(ptt, "copy_to_clipboard", copied.append)
    run_ptt(
        Config(),
        stt=FakeStt(),
        hotkey=FakeHotkey(),
        recorder=lambda **kwargs: ("audio", 16000),
        typer=ptt.type_text,
        progress=messages.append,
    )
    assert copied == ["hello world"]
    assert "transcript: hello world" in messages
    assert "typing failed; text copied to clipboard, press Ctrl+V" in messages


@pytest.mark.fake
def test_ptt_fakes_run_on_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(ptt.sys, "platform", "linux")
    messages: list[str] = []

    class Device:
        index = 3
        name = "fake microphone"

    class FakeHotkey:
        def events(self, mode):
            yield "press"
            yield "release"

    class FakeStt:
        def preload(self, local_only=False):
            pass

        def transcribe(self, audio, sample_rate, language):
            return "portable fake", 0.01

    monkeypatch.setattr(
        "voxcode.ptt.select_device",
        lambda configured, direction, hostapi=None: (Device(), "fake"),
    )
    typed: list[str] = []
    assert run_ptt(
        Config(),
        stt=FakeStt(),
        hotkey=FakeHotkey(),
        recorder=lambda **kwargs: ("audio", 16000),
        typer=lambda text, submit: typed.append(text),
        progress=messages.append,
    ) == 0
    assert typed == ["portable fake"]


@pytest.mark.fake
def test_ptt_real_path_refuses_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(ptt.sys, "platform", "linux")
    messages: list[str] = []
    assert run_ptt(Config(), progress=messages.append) == 1
    assert messages == ["[FAIL] PTT is not supported on this platform yet (Windows only)"]
