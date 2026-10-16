import types

import numpy as np
import pytest

from voxcode.audio import _record_with_vad


@pytest.mark.fake
def test_vad_stops_after_speech_and_silence(monkeypatch) -> None:
    class FakeVad:
        def __init__(self, mode):
            pass

        def is_speech(self, pcm, sample_rate):
            return float(np.frombuffer(pcm, dtype=np.int16).max()) > 1000

    monkeypatch.setitem(__import__("sys").modules, "webrtcvad", types.SimpleNamespace(Vad=FakeVad))

    class Stream:
        def __init__(self, *args, **kwargs):
            self.frame = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, frame_samples):
            self.frame += 1
            value = 0.2 if self.frame <= 3 else 0.0
            return np.full((frame_samples, 1), value, dtype=np.float32), False

    fake_sd = types.SimpleNamespace(InputStream=Stream)
    result, rate = _record_with_vad(
        fake_sd,
        max_seconds=10,
        sample_rate=16000,
        channels=1,
        device=0,
        silence_seconds=0.09,
        progress=lambda _: None,
    )
    assert rate == 16000
    assert len(result) == 6 * 480


@pytest.mark.fake
def test_vad_stops_initial_silence(monkeypatch) -> None:
    class FakeVad:
        def __init__(self, mode):
            pass

        def is_speech(self, pcm, sample_rate):
            return False

    import sys
    monkeypatch.setitem(sys.modules, "webrtcvad", types.SimpleNamespace(Vad=FakeVad))

    class Stream:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, frame_samples):
            return np.zeros((frame_samples, 1), dtype=np.float32), False

    result, _ = _record_with_vad(
        types.SimpleNamespace(InputStream=Stream),
        max_seconds=10,
        sample_rate=16000,
        channels=1,
        device=0,
        silence_seconds=0.09,
        progress=lambda _: None,
    )
    assert len(result) == 6 * 480
