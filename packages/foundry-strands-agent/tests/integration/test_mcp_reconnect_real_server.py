# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""ReconnectingMCPClient against a real MCP server that restarts.

After a real server restart with mcp 1.30.0, the old connection still looks
running, and every call fails with McpError "Session terminated". The call that
fails is not re-sent, and the next call reconnects.

A call made while the server is down is not tested: it hangs with or without
reconnects, because agents send MCP calls with no read timeout.
"""

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.models import BedrockModel

from foundry_strands_agent.mcp_reconnect import ReconnectingMCPClient

_SERVER_SCRIPT = Path(__file__).with_name("_mcp_echo_server.py")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _EchoServer:
    def __init__(self, port: int) -> None:
        self.port = port
        self.url = f"http://127.0.0.1:{port}/mcp"
        self._process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        self._process = subprocess.Popen(  # noqa: S603 - fixed interpreter and test-owned script
            [sys.executable, str(_SERVER_SCRIPT), str(self.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                httpx.get(self.url, timeout=0.5)
                return
            except httpx.TransportError:
                time.sleep(0.1)
        raise RuntimeError("MCP echo server did not start")

    def stop(self) -> None:
        if self._process is not None:
            self._process.terminate()
            self._process.wait(timeout=10)
            self._process = None


@pytest.fixture
def server() -> Iterator[_EchoServer]:
    echo_server = _EchoServer(_free_port())
    echo_server.start()
    yield echo_server
    echo_server.stop()


def _agents_sharing(client: ReconnectingMCPClient, count: int) -> list[Agent]:
    # The model is never called; direct tool calls go straight to the tool.
    model = BedrockModel(region_name="us-east-1")
    return [Agent(model=model, tools=[client], callback_handler=None) for _ in range(count)]


def _echo(agent: Agent, text: str) -> dict:
    return agent.tool.echo(text=text, record_direct_tool_call=False)


def _client_for(server: _EchoServer) -> ReconnectingMCPClient:
    return ReconnectingMCPClient(
        lambda: streamablehttp_client(url=server.url),
        server_name="echo",
        destination_host=f"http://127.0.0.1:{server.port}",
    )


def test_cached_agents_recover_after_fast_restart(server: _EchoServer) -> None:
    client = _client_for(server)
    first, second = _agents_sharing(client, 2)
    assert _echo(first, "before")["status"] == "success"

    server.stop()
    server.start()

    # The server forgot the connection id. This call fails and is not re-sent.
    assert _echo(first, "lost")["status"] == "error"
    # The next call, from any agent sharing the client, reconnects first.
    result = _echo(second, "after")
    assert result["status"] == "success"
    assert result["content"][0]["text"] == "after"
    assert _echo(first, "again")["status"] == "success"
