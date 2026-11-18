# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for foundry-auth tests."""

import os
from pathlib import Path

import pytest

from foundry_auth.websocket import WebSocketConfig

TEST_ENCRYPTION_KEY_HEX = os.urandom(32).hex()


@pytest.fixture(autouse=True)
def reset_websocket_globals():
    """Reset WebSocket module global state before each test.

    This fixture automatically runs before every test to ensure WebSocket
    global state (_connection_registry, _connection_timestamps, _config)
    doesn't leak between tests.
    """
    from foundry_auth import websocket

    websocket._connection_registry.clear()
    websocket._connection_timestamps.clear()
    websocket._config = WebSocketConfig(
        session_check_interval_seconds=int(os.environ.get("WEBSOCKET_SESSION_CHECK_INTERVAL_SECONDS", "300")),
        max_connection_seconds=int(os.environ.get("WEBSOCKET_MAX_CONNECTION_SECONDS", "3600")),
    )

    yield

    websocket._connection_registry.clear()
    websocket._connection_timestamps.clear()


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path for SQLite session store tests.

    Args:
        tmp_path: pytest's built-in temporary directory fixture

    Returns:
        Path to a temporary database file
    """
    return tmp_path / "test_sessions.db"


@pytest.fixture(autouse=True)
def _auth_encryption_key_env(monkeypatch):
    """Ensure FOUNDRY_AUTH_TOKEN_ENCRYPTION_KEY is set for session store tests."""
    monkeypatch.setenv("FOUNDRY_AUTH_TOKEN_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY_HEX)
