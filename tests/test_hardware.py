import pytest

from voxcode.audio import list_devices
from voxcode.config import load_config
from voxcode.core import doctor, listen, speak


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
