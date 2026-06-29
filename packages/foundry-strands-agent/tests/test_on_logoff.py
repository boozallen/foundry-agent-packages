# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for on_logoff lifecycle entry point (STIG V-222578, CCI-001185)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from strands.session import FileSessionManager
from strands.session.file_session_manager import SESSION_PREFIX as FILE_SESSION_PREFIX
from strands.types.exceptions import SessionException

from foundry_agent_core import QueryProcessingError
from foundry_strands_agent.chat_historian import ChatHistorian
from foundry_strands_agent.protocols.chat_history_manager import ChatHistoryManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_factory():
    factory = MagicMock()
    factory.create_session_repository.return_value = None
    return factory


@pytest.fixture
def historian(mock_factory):
    with patch("foundry_strands_agent.chat_historian.StrandsAgentConfig.from_env") as m:
        m.return_value = MagicMock()
        return ChatHistorian(agent_factory=mock_factory)


def _make_session_dir(storage_dir: Path, session_id: str) -> Path:
    """Create a minimal session directory with session.json so FileSessionManager recognises it."""
    session_dir = storage_dir / f"{FILE_SESSION_PREFIX}{session_id}"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_data = {
        "session_id": session_id,
        "session_type": "agent",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    (session_dir / "session.json").write_text(json.dumps(session_data))
    return session_dir


# ---------------------------------------------------------------------------
# Protocol contract
# ---------------------------------------------------------------------------


class TestOnLogoffProtocolContract:
    def test_on_logoff_declared_on_protocol(self):
        assert hasattr(ChatHistoryManager, "on_logoff")

    def test_on_logoff_declared_on_historian(self):
        assert hasattr(ChatHistorian, "on_logoff")

    def test_historian_satisfies_protocol(self):
        """ChatHistorian must structurally satisfy ChatHistoryManager Protocol."""
        # Runtime check: all abstractmethods of Protocol are implemented
        assert not getattr(ChatHistorian, "__abstractmethods__", set())


# ---------------------------------------------------------------------------
# Unit tests — mock repository
# ---------------------------------------------------------------------------


class TestOnLogoffUnit:
    @pytest.mark.asyncio
    async def test_delegates_to_delete_chat_session_messages_history(self, historian):
        historian.delete_chat_session_messages_history = AsyncMock()
        await historian.on_logoff("test-session-123")
        historian.delete_chat_session_messages_history.assert_awaited_once_with("test-session-123")

    @pytest.mark.asyncio
    async def test_nonexistent_session_does_not_raise(self, historian, mock_factory):
        """Non-existent session is silently ignored (mirrors delete behavior)."""
        mock_repo = MagicMock(spec=FileSessionManager)
        mock_repo.storage_dir = "/tmp/fake"
        mock_repo.delete_session.side_effect = SessionException("Session does not exist")
        mock_factory.create_session_repository.return_value = mock_repo
        # Should not raise
        await historian.on_logoff("no-such-session")

    @pytest.mark.asyncio
    async def test_session_repository_disabled_does_not_raise_for_logoff(self, historian, mock_factory):
        """When session repo is disabled (None), on_logoff propagates QueryProcessingError.

        (Same as delete_chat_session_messages_history.)
        """
        mock_factory.create_session_repository.return_value = None
        with pytest.raises(QueryProcessingError, match="Chat session history is disabled"):
            await historian.on_logoff("some-session")

    @pytest.mark.asyncio
    async def test_on_logoff_calls_through_file_storage_path(self, historian, mock_factory, tmp_path):
        mock_repo = MagicMock(spec=FileSessionManager)
        mock_repo.storage_dir = str(tmp_path)
        mock_factory.create_session_repository.return_value = mock_repo
        await historian.on_logoff("sess-abc")
        mock_repo.delete_session.assert_called_once_with(session_id="sess-abc")

    @pytest.mark.asyncio
    async def test_propagates_unexpected_exception(self, historian, mock_factory, tmp_path):
        """Unexpected errors (not 'does not exist') surface as QueryProcessingError."""
        mock_repo = MagicMock(spec=FileSessionManager)
        mock_repo.storage_dir = str(tmp_path)
        mock_repo.delete_session.side_effect = SessionException("Storage I/O error")
        mock_factory.create_session_repository.return_value = mock_repo
        with pytest.raises(QueryProcessingError, match="Error deleting chat session history"):
            await historian.on_logoff("sess-io-fail")


# ---------------------------------------------------------------------------
# Integration tests — real FileSessionManager with tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture
def file_historian(mock_factory):
    """ChatHistorian for integration tests; inject tmp_path per-test via pytest."""
    with patch("foundry_strands_agent.chat_historian.StrandsAgentConfig.from_env") as m:
        m.return_value = MagicMock()
        return ChatHistorian(agent_factory=mock_factory)


class TestOnLogoffIntegration:
    @pytest.mark.asyncio
    async def test_logoff_destroys_session_directory(self, file_historian, mock_factory, tmp_path):
        """Core STIG requirement: logoff removes all persisted state from disk."""
        session_id = "integ-session-001"
        session_dir = _make_session_dir(tmp_path, session_id)
        assert session_dir.exists()

        real_repo = FileSessionManager(session_id=session_id, storage_dir=str(tmp_path))
        mock_factory.create_session_repository.return_value = real_repo

        await file_historian.on_logoff(session_id)

        assert not session_dir.exists(), "Session directory should be removed after on_logoff"

    @pytest.mark.asyncio
    async def test_logoff_only_removes_target_session(self, file_historian, mock_factory, tmp_path):
        """on_logoff MUST NOT destroy other sessions' data."""
        target_id = "target-session"
        bystander_id = "bystander-session"

        target_dir = _make_session_dir(tmp_path, target_id)
        bystander_dir = _make_session_dir(tmp_path, bystander_id)

        real_repo = FileSessionManager(session_id=target_id, storage_dir=str(tmp_path))
        mock_factory.create_session_repository.return_value = real_repo

        await file_historian.on_logoff(target_id)

        assert not target_dir.exists(), "Target session directory should be removed"
        assert bystander_dir.exists(), "Bystander session directory must be untouched"

    @pytest.mark.asyncio
    async def test_logoff_nonexistent_session_is_silent(self, file_historian, mock_factory, tmp_path):
        """on_logoff with a session that never existed must not raise."""
        real_repo = FileSessionManager(session_id="ghost-session", storage_dir=str(tmp_path))
        mock_factory.create_session_repository.return_value = real_repo

        # Should not raise
        await file_historian.on_logoff("ghost-session")

    @pytest.mark.asyncio
    async def test_logoff_idempotent(self, file_historian, mock_factory, tmp_path):
        """Calling on_logoff twice for the same session must not raise on the second call."""
        session_id = "idempotent-session"
        _make_session_dir(tmp_path, session_id)

        real_repo = FileSessionManager(session_id=session_id, storage_dir=str(tmp_path))
        mock_factory.create_session_repository.return_value = real_repo

        await file_historian.on_logoff(session_id)
        # Second call: session already gone — should be silent
        await file_historian.on_logoff(session_id)
