"""Speech-to-text engine interface."""

from __future__ import annotations

import time
import os
import inspect
from pathlib import Path
from typing import Any, Callable


class SttEngine:
    def __init__(
        self,
        model: str = "small",
        compute_type: str = "int8",
        progress: Callable[[str], None] = print,
        verbose: bool = False,
    ) -> None:
        self.model_name = model
        self.compute_type = compute_type
        self.progress = progress
        self.verbose = verbose
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper is not installed; install with `pip install -e .[stt]`"
                ) from exc
            model_path = _cached_model_path(self.model_name)
            if model_path is None:
                self.progress(
                    f"downloading faster-whisper model {self.model_name!r} "
                    f"(compute_type={self.compute_type})"
                )
                model_path = _download_model(self.model_name)
            elif self.verbose:
                self.progress(f"loading cached model {self.model_name!r}")
            started = time.perf_counter()
            self._model = WhisperModel(
                str(model_path),
                device="cpu",
                compute_type=self.compute_type,
            )
            if self.verbose:
                self.progress(f"model ready in {time.perf_counter() - started:.2f}s")
        return self._model

    def transcribe(
        self, audio: Any, sample_rate: int, language: str | None = None
    ) -> tuple[str, float]:
        model = self._load()
        audio = _prepare_audio(audio, sample_rate)
        started = time.perf_counter()
        kwargs: dict[str, Any] = {"language": language}
        try:
            parameters = inspect.signature(model.transcribe).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "vad_filter" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            kwargs.update(
                vad_filter=True,
                vad_parameters={"threshold": 0.5},
                no_speech_threshold=0.6,
            )
        segments, _info = model.transcribe(audio, **kwargs)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text, time.perf_counter() - started


def _prepare_audio(audio: Any, sample_rate: int) -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "numpy is required for audio transcription; install with `pip install -e .[audio]`"
        ) from exc
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    if samples.ndim != 1:
        raise ValueError(f"audio must be one-dimensional or mono, got shape {samples.shape}")
    target_rate = 16000
    if sample_rate != target_rate and len(samples):
        target_length = max(1, round(len(samples) * target_rate / sample_rate))
        source_positions = np.linspace(0, len(samples) - 1, num=len(samples))
        target_positions = np.linspace(0, len(samples) - 1, num=target_length)
        samples = np.interp(target_positions, source_positions, samples).astype(np.float32)
    return samples


def _cached_model_path(model: str) -> Path | None:
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    cache = hf_home / "hub"
    snapshots = cache / f"models--Systran--faster-whisper-{model}" / "snapshots"
    if not snapshots.exists():
        return None
    candidates = [path for path in snapshots.iterdir() if path.is_dir()]
    return candidates[0] if candidates else None


def _download_model(model: str) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface-hub is required to download STT models; install `pip install -e .[stt]`"
        ) from exc
    try:
        return Path(snapshot_download(f"Systran/faster-whisper-{model}"))
    except Exception as exc:
        raise RuntimeError(f"failed to download faster-whisper model: {exc}") from exc
