import sys
import types
from pathlib import Path

import pytest

from voxcode.stt import SttEngine, _cached_model_path, _download_model


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


@pytest.mark.fake
def test_stt_cached_preload_is_local_only(monkeypatch, tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    calls = []

    class FakeModel:
        def __init__(self, path, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("voxcode.stt._cached_model_path", lambda model: model_dir)
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeModel),
    )
    engine = SttEngine(progress=lambda _: None)
    engine.preload(local_only=True)
    assert calls == [{"device": "cpu", "compute_type": "int8", "local_files_only": True}]


@pytest.mark.fake
def test_stt_local_only_missing_model_has_context(monkeypatch) -> None:
    monkeypatch.setattr("voxcode.stt._cached_model_path", lambda model: None)
    engine = SttEngine(local_only=True, progress=lambda _: None)
    with pytest.raises(RuntimeError, match="not cached"):
        engine.preload(local_only=True)


@pytest.mark.fake
def test_download_failure_is_clear(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("huggingface_hub.snapshot_download", fail)
    with pytest.raises(RuntimeError, match="failed to download faster-whisper model: offline"):
        _download_model("small", progress=lambda _: None)


@pytest.mark.fake
def test_incomplete_snapshot_is_not_cached(tmp_path: Path, monkeypatch) -> None:
    snapshots = (
        tmp_path
        / "hub"
        / "models--Systran--faster-whisper-small"
        / "snapshots"
        / "revision"
    )
    snapshots.mkdir(parents=True)
    (snapshots / "config.json").write_text("{}", encoding="utf-8")
    (snapshots / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    assert _cached_model_path("small") is None
