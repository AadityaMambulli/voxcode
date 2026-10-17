import json
import subprocess
import sys
from pathlib import Path

import pytest


HOOK = Path(__file__).parents[1] / "plugins" / "voxcode" / "hooks" / "summarize_stop.py"


def _load_hook():
    namespace = {"__name__": "hook_test"}
    exec(HOOK.read_text(encoding="utf-8"), namespace)
    return namespace


@pytest.mark.fake
def test_hook_summary_uses_first_paragraph_and_skips_labels() -> None:
    hook = _load_hook()
    text = (
        "Implemented the requested change. Added tests and verified the behavior.\n\n"
        "Skipped: unrelated cleanup\nRisk: none\nNext: review the diff"
    )
    summary = hook["_redact"](text)
    assert summary == "Implemented the requested change. Added tests and verified the behavior."


@pytest.mark.fake
def test_hook_summary_respects_configured_labels() -> None:
    hook = _load_hook()
    text = "Completed the fix.\n\nCustom: do not speak this\nNext: also omit this"
    assert hook["_redact"](text, ["Custom", "Next"]) == "Completed the fix."


@pytest.mark.fake
def test_hook_logs_metadata_without_message(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[voxcode]\nvoice_enabled = false\n", encoding="utf-8")
    log = tmp_path / "hook.jsonl"
    environment = {
        **__import__("os").environ,
        "VOXCODE_CONFIG": str(config),
        "VOXCODE_HOOK_LOG": str(log),
    }
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"session_id": "secret", "transcript_path": "missing"}),
        text=True,
        capture_output=True,
        env=environment,
        check=True,
    )
    assert result.returncode == 0
    entry = json.loads(log.read_text(encoding="utf-8"))
    assert entry["stdin_keys"] == ["session_id", "transcript_path"]
    assert entry["voice_enabled"] is False
    assert "secret" not in log.read_text(encoding="utf-8")
