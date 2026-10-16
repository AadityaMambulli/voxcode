from pathlib import Path

import pytest

from voxcode.config import Config, load_config, save_config


@pytest.mark.fake
def test_config_round_trip(tmp_path: Path) -> None:
    original = Config(input_device=3, output_device="USB", fixed_seconds=2.5)
    path = tmp_path / "config.toml"
    save_config(original, path)
    assert load_config(path) == original
