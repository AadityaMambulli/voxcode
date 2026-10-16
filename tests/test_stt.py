import sys
import types
from pathlib import Path

import pytest

from voxcode.stt import SttEngine


@pytest.mark.fake
def test_stt_creates_model_once(monkeypatch, tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    calls = []

    class FakeModel:
        def __init__(self, path, **kwargs):
            calls.append((path, kwargs))

        def transcribe(self, audio, language=None):
            segment = types.SimpleNamespace(text="hello")
            return iter([segment]), types.SimpleNamespace()

    monkeypatch.setattr("voxcode.stt._cached_model_path", lambda model: model_dir)
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeModel),
    )
    engine = SttEngine(progress=lambda _: None)
    audio = [0.0] * 16000
    assert engine.transcribe(audio, 16000, "en")[0] == "hello"
    assert engine.transcribe(audio, 16000, "en")[0] == "hello"
    assert len(calls) == 1
