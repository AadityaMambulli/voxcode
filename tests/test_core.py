import pytest

from voxcode.config import Config
from voxcode.core import listen
from voxcode.audio import AudioDevice, select_device


class FakeStt:
    def transcribe(self, audio, sample_rate, language=None):
        assert audio == "audio"
        assert sample_rate == 16000
        return "hello terminal", 0.25


@pytest.mark.fake
def test_listen_routes_audio_to_stt(monkeypatch) -> None:
    class Device:
        index = 7
        name = "fake mic"

    monkeypatch.setattr(
        "voxcode.core.select_device",
        lambda configured, direction: (Device(), "fake backend"),
    )
    result = listen(
        Config(),
        progress=lambda _: None,
        stt=FakeStt(),
        device_selector=lambda configured, direction: (Device(), "fake backend"),
        recorder=lambda **kwargs: ("audio", 16000),
    )
    assert result.transcript == "hello terminal"
    assert result.record_seconds >= 0
    assert result.transcription_seconds == 0.25


@pytest.mark.fake
def test_listen_falls_back_when_default_is_missing() -> None:
    class Device:
        index = 7
        name = "first available mic"

    result = listen(
        Config(),
        progress=lambda _: None,
        stt=FakeStt(),
        device_selector=lambda configured, direction: (Device(), "first available device"),
        recorder=lambda **kwargs: ("audio", 16000),
    )
    assert result.transcript == "hello terminal"


@pytest.mark.fake
def test_select_device_falls_back_to_first_available(monkeypatch) -> None:
    devices = [
        AudioDevice(4, "first mic", 1, 0, "fake"),
        AudioDevice(5, "speaker", 0, 2, "fake"),
    ]
    monkeypatch.setattr("voxcode.audio.list_devices", lambda: devices)
    selected, reason = select_device(None, "input")
    assert selected == devices[0]
    assert reason == "fallback: first available input"


@pytest.mark.fake
def test_select_device_resolves_saved_name_after_index_shift(monkeypatch) -> None:
    devices = [
        AudioDevice(21, "other mic", 1, 0, "fake"),
        AudioDevice(14, "saved mic", 1, 0, "fake"),
    ]
    monkeypatch.setattr("voxcode.audio.list_devices", lambda: devices)
    selected, reason = select_device("saved mic", "input", "fake")
    assert selected == devices[1]
    assert reason == "configured"
