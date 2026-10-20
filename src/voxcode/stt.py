"""Speech-to-text engine interface."""

from __future__ import annotations

import time
import os
import inspect
import threading
from pathlib import Path
from typing import Any, Callable

MODEL_SIZE_BYTES = {
    "tiny": 75_000_000,
    "base": 145_000_000,
    "small": 486_215_847,
    "medium": 1_500_000_000,
    "large-v3": 3_000_000_000,
}


class SttEngine:
    def __init__(
        self,
        model: str = "small",
        compute_type: str = "int8",
        progress: Callable[[str], None] = print,
        verbose: bool = False,
        local_only: bool = False,
    ) -> None:
        self.model_name = model
        self.compute_type = compute_type
        self.progress = progress
        self.verbose = verbose
        self.local_only = local_only
        self._model: Any = None
        self.last_load_seconds = 0.0
        self._load_lock = threading.Lock()

    def _load(self, local_only: bool | None = None) -> Any:
        load_started = time.perf_counter()
        effective_local_only = (
            self.local_only if local_only is None else local_only
        )
        with self._load_lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise RuntimeError(
                        "faster-whisper is not installed; install with `pip install -e .[stt]`"
                    ) from exc
                model_path = _cached_model_path(self.model_name)
                if model_path is None:
                    if effective_local_only:
                        raise RuntimeError(
                            f"faster-whisper model {self.model_name!r} is not cached; "
                            "download the speech model before starting this operation"
                        )
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
                    local_files_only=True,
                )
                self.last_load_seconds = time.perf_counter() - load_started
                if self.verbose:
                    self.progress(f"model ready in {self.last_load_seconds:.2f}s")
        return self._model

    def preload(self, local_only: bool = False) -> float:
        if local_only:
            self.local_only = True
        self._load(local_only=local_only)
        return self.last_load_seconds

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
        if "condition_on_previous_text" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            kwargs["condition_on_previous_text"] = False
        segments, _info = model.transcribe(audio, **kwargs)
        text = _remove_repeated_text(
            " ".join(segment.text.strip() for segment in segments).strip()
        )
        return text, time.perf_counter() - started


def _remove_repeated_text(text: str) -> str:
    words = text.split()
    for size in range(len(words) // 2, 0, -1):
        midpoint = len(words) - size
        if words[midpoint:] == words[midpoint - size : midpoint]:
            return " ".join(words[:midpoint])
    return text


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
    candidates = [
        path
        for path in snapshots.iterdir()
        if path.is_dir()
        and (path / "config.json").is_file()
        and (path / "model.bin").is_file()
        and (path / "tokenizer.json").is_file()
    ]
    return candidates[0] if candidates else None


def model_size_mb(model: str) -> int:
    return round(MODEL_SIZE_BYTES.get(model, MODEL_SIZE_BYTES["small"]) / 1_000_000)


def model_size_label(model: str) -> str:
    size = MODEL_SIZE_BYTES.get(model, MODEL_SIZE_BYTES["small"])
    return f"{size / 1_000_000:.0f} MB / {size / (1024 * 1024):.1f} MiB"


def download_model(
    model: str,
    progress: Callable[[str], None] = print,
) -> Path:
    return _download_model(model, progress)


def _download_model(
    model: str,
    progress: Callable[[str], None] = print,
) -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface-hub is required to download STT models; install `pip install -e .[stt]`"
        ) from exc
    progress(
        f"Downloading speech model {model!r} (~{model_size_mb(model)} MB); "
        "partial files are resumable"
    )

    from tqdm.auto import tqdm

    class ProgressBar(tqdm):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.setdefault("unit", "B")
            kwargs.setdefault("unit_scale", True)
            super().__init__(*args, **kwargs)

        def display(self, msg: str | None = None, pos: int | None = None) -> None:
            progress(
                f"model download: {self.n}/{self.total or '?'} bytes "
                f"({self.desc or 'files'})"
            )

    try:
        path = Path(
            snapshot_download(
                f"Systran/faster-whisper-{model}",
                tqdm_class=ProgressBar,
            )
        )
        size = sum(file.stat().st_size for file in path.rglob("*") if file.is_file())
        progress(f"Downloaded {size / (1024 * 1024):.1f} MB to {path}")
        return path
    except Exception as exc:
        raise RuntimeError(f"failed to download faster-whisper model: {exc}") from exc
