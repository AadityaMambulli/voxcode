from voxcode import tts

import pytest


class FakeEngine(tts.TtsEngine):
    name = "fake"

    def __init__(self, available: bool) -> None:
        self._available = available

    def available(self) -> tuple[bool, str]:
        return self._available, "fake"

    def speak(self, text: str) -> tts.TtsResult:
        return tts.TtsResult(self.name, text)


@pytest.mark.fake
def test_choose_engine_uses_first_available(monkeypatch) -> None:
    second = FakeEngine(True)
    monkeypatch.setattr(tts, "engines", lambda: [FakeEngine(False), second])
    engine, reasons = tts.choose_engine()
    assert engine is second
    assert reasons == ["fake: fake"]


@pytest.mark.fake
def test_speak_stops_previous_audio(monkeypatch) -> None:
    stopped = []
    monkeypatch.setattr(tts, "stop_speaking", lambda: stopped.append(True) or True)
    engine = FakeEngine(True)
    monkeypatch.setattr(tts, "engines", lambda: [engine])
    result = tts.speak("new reply")
    assert result.engine == "fake"
    assert stopped == [True]
