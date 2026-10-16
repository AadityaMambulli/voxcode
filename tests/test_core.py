import pytest

from voxcode.config import Config
from voxcode.core import listen


class FakeStt:
    def transcribe(self, audio, sample_rate):
        assert audio == "audio"
        assert sample_rate == 16000
        return "hello terminal", 0.25


@pytest.mark.fake
def test_listen_routes_audio_to_stt(monkeypatch) -> None:
    class Device:
        index = 7
        name = "fake mic"

    monkeypatch.setattr(
        "voxcode.core.selected_device",
        lambda configured, direction: Device(),
    )
    monkeypatch.setattr(
        "voxcode.core.record",
        lambda **kwargs: ("audio", 16000),
    )
    result = listen(Config(), progress=lambda _: None, stt=FakeStt())
    assert result.transcript == "hello terminal"
    assert result.record_seconds >= 0
    assert result.transcription_seconds == 0.25
