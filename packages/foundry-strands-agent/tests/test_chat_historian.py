# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for ChatHistorian — spec: strands-chat-history."""

from unittest.mock import MagicMock, patch

import pytest

from foundry_strands_agent.chat_historian import ChatHistorian


@pytest.fixture
def mock_agent_factory():
    factory = MagicMock()
    factory.create_session_repository.return_value = None
    return factory


@pytest.fixture
def historian(mock_agent_factory):
    with patch("foundry_strands_agent.chat_historian.StrandsAgentConfig.from_env") as mock_config:
        mock_config.return_value = MagicMock()
        return ChatHistorian(agent_factory=mock_agent_factory)


class TestGetChatSessionsHistory:
    """Scenario: Get chat sessions history."""

    @pytest.mark.asyncio
    async def test_raises_when_session_repo_disabled(self, historian):
        from foundry_agent_core import QueryProcessingError

        with pytest.raises(QueryProcessingError, match="Chat session history is disabled"):
            await historian.get_chat_sessions_history()

    @pytest.mark.asyncio
    async def test_invalid_offset_raises(self, historian):
        with pytest.raises(ValueError, match="Offset must be 0 or greater"):
            await historian.get_chat_sessions_history(offset=-1)

    @pytest.mark.asyncio
    async def test_invalid_limit_raises(self, historian):
        with pytest.raises(ValueError, match="Limit must be between 1 and 100"):
            await historian.get_chat_sessions_history(limit=0)

    @pytest.mark.asyncio
    async def test_limit_over_100_raises(self, historian):
        with pytest.raises(ValueError, match="Limit must be between 1 and 100"):
            await historian.get_chat_sessions_history(limit=101)


class TestGetChatSessionMessagesHistory:
    """Scenario: Get chat session messages."""

    @pytest.mark.asyncio
    async def test_raises_when_session_repo_disabled(self, historian):
        from foundry_agent_core import QueryProcessingError

        with pytest.raises(QueryProcessingError, match="Chat session history is disabled"):
            await historian.get_chat_session_messages_history(session_id="test-123")

    @pytest.mark.asyncio
    async def test_invalid_offset_raises(self, historian):
        with pytest.raises(ValueError, match="Offset must be 0 or greater"):
            await historian.get_chat_session_messages_history(session_id="test-123", offset=-1)

    @pytest.mark.asyncio
    async def test_invalid_limit_raises(self, historian):
        with pytest.raises(ValueError, match="Limit must be between 1 and 100"):
            await historian.get_chat_session_messages_history(session_id="test-123", limit=0)


class TestCreateChatSessionMessagesHistory:
    """Scenario: Create chat session."""

    @pytest.mark.asyncio
    async def test_raises_when_session_repo_disabled(self, historian):
        from foundry_agent_core import QueryProcessingError

        with pytest.raises(QueryProcessingError, match="Chat session history is disabled"):
            await historian.create_chat_session_messages_history(session_id="new-session")


class TestDeleteChatSessionMessagesHistory:
    """Scenario: Delete chat session."""

    @pytest.mark.asyncio
    async def test_raises_when_session_repo_disabled(self, historian):
        from foundry_agent_core import QueryProcessingError

        with pytest.raises(QueryProcessingError, match="Chat session history is disabled"):
            await historian.delete_chat_session_messages_history(session_id="old-session")
