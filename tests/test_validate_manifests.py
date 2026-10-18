import importlib.util
from pathlib import Path

import pytest


def _validator():
    path = Path(__file__).parents[1] / "scripts" / "validate_manifests.py"
    spec = importlib.util.spec_from_file_location("validate_manifests", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.fake
def test_validator_skips_missing_claude_cli(monkeypatch, capsys) -> None:
    validator = _validator()
    monkeypatch.setattr(validator.shutil, "which", lambda name: None)
    monkeypatch.setattr(validator, "ROOT", Path(__file__).parents[1])

    assert validator.main([]) == 0
    assert "Claude CLI check skipped" in capsys.readouterr().out


@pytest.mark.fake
def test_validator_requires_claude_when_requested(monkeypatch, capsys) -> None:
    validator = _validator()
    monkeypatch.setattr(validator.shutil, "which", lambda name: None)
    monkeypatch.setattr(validator, "ROOT", Path(__file__).parents[1])

    assert validator.main(["--require-claude"]) == 1
    assert "--require-claude" in capsys.readouterr().out
