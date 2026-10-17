import pytest

from voxcode.audio import list_devices
from voxcode.config import load_config
from voxcode.core import doctor, listen, speak
from voxcode.ptt import ptt_readiness


@pytest.mark.hardware
def test_real_audio_devices() -> None:
    devices = list_devices()
    assert devices


@pytest.mark.hardware
def test_real_tts_probe() -> None:
    result = speak("voxcode hardware test")
    assert result.engine


@pytest.mark.hardware
def test_real_doctor() -> None:
    checks = doctor(load_config())
    assert checks


@pytest.mark.hardware
def test_real_listen() -> None:
    result = listen(load_config())
    assert result.transcript is not None


@pytest.mark.hardware
def test_real_vad_listen() -> None:
    import numpy as np
    import sounddevice as sd

    config = load_config()
    input_device = config.input_device
    if input_device is None:
        input_device = sd.default.device[0]
    try:
        sample_rate = int(float(sd.query_devices(input_device, "input")["default_samplerate"]))
        sample = sd.rec(
            max(1, int(sample_rate * 0.3)),
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=input_device,
        )
        sd.wait()
    except Exception as exc:
        pytest.skip(f"could not measure ambient noise floor: {exc}")
    noise_floor = float(np.sqrt(np.mean(np.asarray(sample) ** 2)))
    if noise_floor >= config.silence_threshold:
        pytest.skip(
            f"ambient noise floor {noise_floor:.5f} exceeds silence threshold "
            f"{config.silence_threshold:.5f}"
        )
    config = config.__class__(**{**config.__dict__, "fixed_seconds": 15.0, "vad_mode": "auto"})
    result = listen(config)
    assert result.record_seconds < config.fixed_seconds


@pytest.mark.hardware
def test_real_ptt_hotkey_readiness() -> None:
    ok, detail = ptt_readiness(load_config())
    assert ok, detail
