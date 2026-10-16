import asyncio
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from voxcode.mcp_server import create_server


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
            self.calls = 0

        def transcribe(self, audio, sample_rate, language=None):
            self.calls += 1
            return "fake", 0.001

    engine = CountingStt()
    server = create_server(fake=True, stt_engine=engine)
    listen_tool = server._tool_manager._tools["listen"].fn
    listen_tool(timeout_s=1)
    listen_tool(timeout_s=1)
    assert engine.calls == 2


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
