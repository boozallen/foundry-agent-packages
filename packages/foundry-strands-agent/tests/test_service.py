# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for AgentService — boost coverage on service lifecycle."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundry_agent_core import AgentRequest, AgentResponse
from foundry_strands_agent.exceptions import (
    AgentServiceError,
    AgentServiceInitializationError,
)
from foundry_strands_agent.service import AgentService, create_agent_service


@pytest.fixture
def service():
    container = MagicMock()
    agent_factory = MagicMock()
    tool_registry = MagicMock()
    query_processor = AsyncMock()
    chat_historian = AsyncMock()
    response_processor = AsyncMock()

    with patch("foundry_strands_agent.service.create_request_lifecycle_manager") as mock_lm:
        mock_lm.return_value = MagicMock()
        svc = AgentService(
            container=container,
            agent_factory=agent_factory,
            tool_registry=tool_registry,
            query_processor=query_processor,
            chat_historian=chat_historian,
            response_processor=response_processor,
        )
    return svc


class TestAgentServiceInit:
    def test_not_initialized(self, service):
        assert service._initialized is False

    def test_shutdown_event_not_set(self, service):
        assert not service._shutdown_event.is_set()


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_succeeds(self, service):
        service._agent_factory.load_configured_tools = AsyncMock()
        service._container.resolve.return_value = MagicMock()

        with patch.object(service._agent_factory, "load_configured_tools", new_callable=AsyncMock):
            # Cast the factory to avoid the attribute check
            from foundry_strands_agent.factory import StrandsAgentFactory

            mock_factory = MagicMock(spec=StrandsAgentFactory)
            mock_factory.load_configured_tools = AsyncMock()
            service._agent_factory = mock_factory

            await service.initialize()
            assert service._initialized is True

    @pytest.mark.asyncio
    async def test_double_initialize_warns(self, service):
        service._initialized = True
        await service.initialize()  # should just warn

    @pytest.mark.asyncio
    async def test_initialize_failure_raises(self, service):
        mock_factory = MagicMock()
        mock_factory.load_configured_tools = AsyncMock(side_effect=RuntimeError("boom"))
        service._agent_factory = mock_factory

        with pytest.raises(AgentServiceInitializationError):
            await service.initialize()


class TestProcessQuery:
    @pytest.mark.asyncio
    async def test_not_initialized_raises(self, service):
        request = AgentRequest(query="hello")
        with pytest.raises(AgentServiceError, match="not initialized"):
            await service.process_query(request)

    @pytest.mark.asyncio
    async def test_shutting_down_raises(self, service):
        service._initialized = True
        service._shutdown_event.set()
        request = AgentRequest(query="hello")
        with pytest.raises(AgentServiceError, match="shutting down"):
            await service.process_query(request)

    @pytest.mark.asyncio
    async def test_delegates_to_query_processor(self, service):
        service._initialized = True
        service._lifecycle_manager.create_execution_context = MagicMock()

        mock_response = AgentResponse(content="answer", processing_time_ms=5.0)
        service._query_orchestrator.process_query = AsyncMock(return_value=mock_response)

        # Mock the lifecycle context manager
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_context(**kwargs):
            yield MagicMock()

        service._lifecycle_manager.create_execution_context = fake_context

        request = AgentRequest(query="hello")
        result = await service.process_query(request)
        assert result.content == "answer"


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_not_initialized(self, service):
        await service.shutdown()  # should just warn, not raise

    @pytest.mark.asyncio
    async def test_shutdown_cleans_up(self, service):
        service._initialized = True
        await service.shutdown()
        assert service._initialized is False
        assert service._shutdown_event.is_set()


class TestGetServiceHealth:
    @pytest.mark.asyncio
    async def test_not_initialized_health(self, service):
        health = await service.get_service_health()
        assert health["service_initialized"] is False

    @pytest.mark.asyncio
    async def test_initialized_health(self, service):
        service._initialized = True
        health = await service.get_service_health()
        assert health["service_initialized"] is True
        assert "components" in health


class TestChatHistoryProperty:
    def test_not_initialized_raises(self, service):
        with pytest.raises(AgentServiceError, match="not initialized"):
            _ = service.chat_history

    def test_shutting_down_raises(self, service):
        service._initialized = True
        service._shutdown_event.set()
        with pytest.raises(AgentServiceError, match="shutting down"):
            _ = service.chat_history

    def test_returns_historian(self, service):
        service._initialized = True
        result = service.chat_history
        assert result is service._chat_historian


class TestCreateAgentService:
    def test_factory_function(self):
        container = MagicMock()
        with patch("foundry_strands_agent.service.create_request_lifecycle_manager") as mock_lm:
            mock_lm.return_value = MagicMock()
            svc = create_agent_service(container)
        assert isinstance(svc, AgentService)
