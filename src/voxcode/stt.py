"""Speech-to-text engine interface."""

from __future__ import annotations

import time
from typing import Any, Callable


class SttEngine:
    def __init__(
        self,
        model: str = "small",
        compute_type: str = "int8",
        progress: Callable[[str], None] = print,
    ) -> None:
        self.model_name = model
        self.compute_type = compute_type
        self.progress = progress
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper is not installed; install with `pip install -e .[stt]`"
                ) from exc
            self.progress(
                f"loading faster-whisper model {self.model_name!r} "
                f"(first use may download it; compute_type={self.compute_type})"
            )
            started = time.perf_counter()
            self._model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type=self.compute_type,
            )
            self.progress(f"model ready in {time.perf_counter() - started:.2f}s")
        return self._model

    def transcribe(self, audio: Any, sample_rate: int) -> tuple[str, float]:
        model = self._load()
        audio = _prepare_audio(audio, sample_rate)
        started = time.perf_counter()
        segments, _info = model.transcribe(audio, language=None)
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
