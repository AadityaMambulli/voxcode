import asyncio
import json
import os
import sys
import tempfile
import threading
import ctypes
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from voxcode.config import Config
from voxcode.mcp_server import create_server
from voxcode.ptt import PttListener


def _run_fake_mcp(tmp_path: Path) -> list[str]:
    async def run() -> list[str]:
        env = dict(os.environ)
        env["APPDATA"] = str(tmp_path)
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "voxcode.mcp_server", "--fake"],
            cwd=str(Path(__file__).parents[1]),
            env=env,
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(tool.name for tool in tools.tools)
                await session.call_tool("listen", {"timeout_s": 1})
                listen_result = await session.call_tool("listen", {"timeout_s": 1})
                assert json.loads(listen_result.content[0].text)["error"] is None
                await session.call_tool("speak", {"text": "hello", "interrupt": False})
                await session.call_tool("stop_speaking", {})
                await session.call_tool("voice_status", {})
                await session.call_tool(
                    "voice_config",
                    {"vad_mode": "fixed", "fixed_seconds": 1.0},
                )
                return names

    return asyncio.run(run())


@pytest.mark.fake
def test_stdio_mcp_calls_every_tool(tmp_path: Path) -> None:
    assert _run_fake_mcp(tmp_path) == [
        "listen",
        "speak",
        "stop_speaking",
        "voice_config",
        "voice_status",
    ]


@pytest.mark.fake
def test_mcp_reuses_one_stt_engine() -> None:
    class CountingStt:
        def __init__(self):
            self.loads = 0
            self.calls = 0
            self.model = None

        def _load(self):
            if self.model is None:
                self.loads += 1
                self.model = object()

        def transcribe(self, audio, sample_rate, language=None):
            self._load()
            self.calls += 1
            return "fake", 0.001

    engine = CountingStt()
    server = create_server(fake=True, stt_engine=engine)
    listen_tool = server._tool_manager._tools["listen"].fn
    listen_tool(timeout_s=1)
    listen_tool(timeout_s=1)
    assert engine.loads == 1
    assert engine.calls == 2


@pytest.mark.fake
def test_mcp_tool_progress_does_not_use_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    server = create_server(fake=True)
    listen_tool = server._tool_manager._tools["listen"].fn

    listen_tool(timeout_s=1)

    captured = capsys.readouterr()
    assert captured.out == ""


@pytest.mark.fake
def test_mcp_reports_downloading_model(monkeypatch, tmp_path: Path) -> None:
    class FakeStt:
        def preload(self, local_only=False):
            pass

    monkeypatch.setenv("VOXCODE_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setattr("voxcode.stt._cached_model_path", lambda model: None)
    download_started = threading.Event()
    monkeypatch.setattr(
        "voxcode.stt.download_model",
        lambda model, progress: download_started.set() or threading.Event().wait(1),
    )
    server = create_server(fake=False, stt_engine=FakeStt())
    listen_tool = server._tool_manager._tools["listen"].fn
    result = listen_tool(timeout_s=1)
    assert result["status"] == "downloading_model"
    assert "speech model" in result["detail"].lower()
    assert download_started.wait(1)


@pytest.mark.fake
def test_stdio_mcp_hosted_ptt_types_with_one_stt_engine(tmp_path: Path) -> None:
    async def run() -> dict:
        env = dict(os.environ)
        env["APPDATA"] = str(tmp_path)
        env["VOXCODE_PTT_AUTOSTART"] = "true"
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "voxcode.mcp_server", "--fake"],
            cwd=str(Path(__file__).parents[1]),
            env=env,
        )
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8") as stderr:
            async with stdio_client(parameters, errlog=stderr) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    for _ in range(100):
                        await asyncio.sleep(0.1)
                        result = await session.call_tool("voice_status", {})
                        status = json.loads(result.content[0].text)
                        if status["ptt_transcript"]:
                            return status
            stderr.seek(0)
            raise AssertionError(
                "hosted PTT did not type within 10s; "
                f"final voice_status={json.dumps(status, sort_keys=True)}; "
                f"server stderr={stderr.read()!r}"
            )

    status = asyncio.run(run())
    assert status["ptt_transcript"].startswith("fake transcript")
    assert status["ptt"] in {"active", "disabled"}


@pytest.mark.fake
def test_hosted_ptt_reports_owned_hotkey() -> None:
    class OwnedHotkey:
        def events(self, _mode: str):
            raise RuntimeError("could not register global hotkey F9; it may be in use")
            yield "press"

    listener = PttListener(
        Config(),
        stt=type("Stt", (), {})(),
        hotkey=OwnedHotkey(),
        progress=lambda _message: None,
    )
    listener.start()
    assert listener._thread is not None
    listener._thread.join(1)
    assert listener.status == "owned_by_another_process"


@pytest.mark.hardware
def test_windows_stdio_hosted_ptt_f9_fires(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows F9 integration requires Windows")

    async def run() -> dict:
        env = dict(os.environ)
        env["APPDATA"] = str(tmp_path)
        env["VOXCODE_PTT_AUTOSTART"] = "true"
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "voxcode.mcp_server"],
            cwd=str(Path(__file__).parents[1]),
            env=env,
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await asyncio.sleep(1)
                ctypes.windll.user32.keybd_event(0x78, 0, 0, 0)
                await asyncio.sleep(0.3)
                ctypes.windll.user32.keybd_event(0x78, 0, 2, 0)
                await asyncio.sleep(1)
                result = await session.call_tool("voice_status", {})
                return json.loads(result.content[0].text)

    status = asyncio.run(run())
    assert status["ptt"] in {"active", "waiting_for_model", "error"}


@pytest.mark.hardware
def test_stdio_mcp_real_server_status(tmp_path: Path) -> None:
    async def run() -> str:
        env = dict(os.environ)
        env["APPDATA"] = str(tmp_path)
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "voxcode.mcp_server"],
            cwd=str(Path(__file__).parents[1]),
            env=env,
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("speak", {"text": "voxcode MCP test"})
                return result.content[0].text

    assert "Windows SAPI" in asyncio.run(run())
