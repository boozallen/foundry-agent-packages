# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for session store factory."""

import pytest

from foundry_auth.session import SQLiteSessionStore
from foundry_auth.stores import get_session_store


def test_get_session_store_default_sqlite(monkeypatch, tmp_path):
    """Test get_session_store returns SQLite by default."""
    monkeypatch.setenv("SESSION_STORE_PATH", str(tmp_path / "test.db"))

    store = get_session_store()
    try:
        assert isinstance(store, SQLiteSessionStore)
    finally:
        store.close()


def test_get_session_store_sqlite_explicit(monkeypatch, tmp_path):
    """Test get_session_store with explicit sqlite type."""
    monkeypatch.setenv("SESSION_STORE_TYPE", "sqlite")
    monkeypatch.setenv("SESSION_STORE_PATH", str(tmp_path / "test.db"))

    store = get_session_store()
    try:
        assert isinstance(store, SQLiteSessionStore)
    finally:
        store.close()


def test_get_session_store_redis_raises(monkeypatch):
    """Test get_session_store with redis type raises NotImplementedError."""
    monkeypatch.setenv("SESSION_STORE_TYPE", "redis")

    with pytest.raises(NotImplementedError):
        get_session_store()


def test_get_session_store_invalid_type_raises(monkeypatch):
    """Test get_session_store with invalid type raises ValueError."""
    monkeypatch.setenv("SESSION_STORE_TYPE", "invalid")

    with pytest.raises(ValueError, match="Unsupported SESSION_STORE_TYPE"):
        get_session_store()


def test_get_session_store_with_prefix(monkeypatch, tmp_path):
    """Test get_session_store with prefix."""
    monkeypatch.setenv("API_SESSION_STORE_TYPE", "sqlite")
    monkeypatch.setenv("API_SESSION_STORE_PATH", str(tmp_path / "api.db"))

    store = get_session_store(prefix="API_")
    try:
        assert isinstance(store, SQLiteSessionStore)
    finally:
        store.close()


def test_get_session_store_missing_encryption_key_raises(monkeypatch, tmp_path):
    """Test get_session_store raises when FOUNDRY_AUTH_TOKEN_ENCRYPTION_KEY is unset."""
    monkeypatch.setenv("SESSION_STORE_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("FOUNDRY_AUTH_TOKEN_ENCRYPTION_KEY", raising=False)

    from foundry_agent_core.exceptions import AgentCreationError

    with pytest.raises(AgentCreationError):
        get_session_store()
