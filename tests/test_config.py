from pathlib import Path

import pytest

from voxcode.config import Config, load_config, save_config


@pytest.mark.fake
def test_config_round_trip(tmp_path: Path) -> None:
    original = Config(
        input_device_name="USB mic",
        input_device_hostapi="WASAPI",
        output_device_name="USB speaker",
        output_device_hostapi="WASAPI",
        fixed_seconds=2.5,
    )
    path = tmp_path / "config.toml"
    save_config(original, path)
    assert load_config(path) == original


@pytest.mark.fake
def test_legacy_config_ignores_saved_defaults(tmp_path: Path) -> None:
    path = tmp_path / "legacy.toml"
    path.write_text(
        "[voxcode]\n"
        "input_device = 14\noutput_device = 13\nsample_rate = 16000\n"
        "vad_mode = 'fixed'\nfixed_seconds = 4.0\nsilence_seconds = 1.0\n"
        "model = 'small'\ncompute_type = 'int8'\nvoice_enabled = true\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.legacy_ignored
    assert config.vad_mode == "auto"
    assert config.input_device is None
    assert config.voice_enabled is True


@pytest.mark.fake
def test_save_config_only_writes_explicit_fields(tmp_path: Path) -> None:
    path = tmp_path / "sparse.toml"
    save_config(Config(language="en"), path, fields={"language"})
    text = path.read_text(encoding="utf-8")
    assert "language = \"en\"" in text
    assert "vad_mode" not in text
    assert "sample_rate" not in text


@pytest.mark.fake
def test_environment_value_has_environment_provenance(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.toml"
    monkeypatch.setenv("VOXCODE_CONFIG", str(path))
    monkeypatch.setenv("VOXCODE_LANGUAGE", "en")
    config = load_config()
    assert config.language == "en"
    assert config.sources["language"] == "environment"


@pytest.mark.fake
def test_config_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "bom.toml"
    path.write_bytes(b"\xef\xbb\xbf[voxcode]\nlanguage = 'en'\n")
    assert load_config(path).language == "en"


@pytest.mark.fake
def test_config_round_trips_hook_skip_labels(tmp_path: Path) -> None:
    path = tmp_path / "hook-labels.toml"
    save_config(Config(hook_skip_labels=["Custom", "Next"]), path)
    assert load_config(path).hook_skip_labels == ["Custom", "Next"]


@pytest.mark.fake
def test_config_round_trips_ptt_settings(tmp_path: Path) -> None:
    path = tmp_path / "ptt.toml"
    original = Config(
        ptt_key="F10",
        ptt_mode="toggle",
        ptt_auto_submit=True,
        ptt_beep=True,
        ptt_max_chars=500,
    )
    save_config(original, path)
    assert load_config(path) == original


@pytest.mark.fake
def test_config_parse_error_names_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("[voxcode\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="broken\\.toml"):
        load_config(path)
