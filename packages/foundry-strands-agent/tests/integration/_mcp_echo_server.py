# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Minimal streamable-HTTP MCP server for the reconnect integration test. Usage: python _mcp_echo_server.py PORT."""

import sys

from mcp.server.fastmcp import FastMCP

server = FastMCP("echo", host="127.0.0.1", port=int(sys.argv[1]))


@server.tool()
def echo(text: str) -> str:
    """Return text unchanged."""
    return text


server.run(transport="streamable-http")
