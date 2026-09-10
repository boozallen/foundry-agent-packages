# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for ChatHistorian — spec: strands-chat-history."""

from unittest.mock import MagicMock

import pytest

from foundry_strands_agent.chat_historian import ChatHistorian


@pytest.fixture
def mock_agent_factory():
    factory = MagicMock()
    factory.create_session_repository.return_value = None
    return factory


@pytest.fixture
def mock_config():
    return MagicMock()


@pytest.fixture
def historian(mock_agent_factory, mock_config):
    return ChatHistorian(agent_factory=mock_agent_factory, config=mock_config)


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


class TestConfigReceivedAsParameter:
    """Scenario: Config received as constructor parameter."""

    def test_historian_uses_provided_config(self):
        config = MagicMock()
        config.session_type = "file"
        factory = MagicMock()
        factory.create_session_repository.return_value = None

        historian = ChatHistorian(agent_factory=factory, config=config)
        assert historian._config is config
