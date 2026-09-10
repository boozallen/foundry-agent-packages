# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for StrandsAgentBackend — boost coverage."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundry_agent_core import AgentRequest, AgentResponse, QueryProcessingError
from foundry_strands_agent.backend import StrandsAgentBackend


class TestStrandsAgentBackendInit:
    def test_init_resolves_config_and_factories(self):
        container = MagicMock()
        mock_config = MagicMock()
        mock_config.agent_name = "test-agent"
        mock_config.agent_description = "A test agent"

        container.resolve.side_effect = lambda t: {
            MagicMock: mock_config,  # fallback
        }.get(t, mock_config)

        with patch("foundry_strands_agent.backend.create_query_processor") as mock_qp:
            with patch("foundry_strands_agent.backend.create_response_processor") as mock_rp:
                mock_qp.return_value = MagicMock()
                mock_rp.return_value = MagicMock()
                backend = StrandsAgentBackend(container, agent_name="override-name")

        assert backend.name == "override-name"

    def test_init_uses_config_name_when_no_override(self):
        container = MagicMock()
        mock_config = MagicMock()
        mock_config.agent_name = "config-agent"
        mock_config.agent_description = "Config description"
        container.resolve.return_value = mock_config

        with patch("foundry_strands_agent.backend.create_query_processor") as mock_qp:
            with patch("foundry_strands_agent.backend.create_response_processor") as mock_rp:
                mock_qp.return_value = MagicMock()
                mock_rp.return_value = MagicMock()
                backend = StrandsAgentBackend(container)

        assert backend.name == "config-agent"
        assert backend.description == "Config description"


class TestProcessMessage:
    @pytest.mark.asyncio
    async def test_delegates_to_query_processor(self):
        container = MagicMock()
        mock_config = MagicMock()
        mock_config.agent_name = "test"
        mock_config.agent_description = "test"
        container.resolve.return_value = mock_config

        mock_processor = AsyncMock()
        mock_response = AgentResponse(content="hello", processing_time_ms=10.0)
        mock_processor.process_query.return_value = mock_response

        with patch("foundry_strands_agent.backend.create_query_processor") as mock_qp:
            with patch("foundry_strands_agent.backend.create_response_processor"):
                mock_qp.return_value = mock_processor
                backend = StrandsAgentBackend(container)

        request = AgentRequest(query="test query")
        result = await backend.process_message(request)

        assert result.content == "hello"
        mock_processor.process_query.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_wraps_unexpected_exception(self):
        container = MagicMock()
        mock_config = MagicMock()
        mock_config.agent_name = "test"
        mock_config.agent_description = "test"
        container.resolve.return_value = mock_config

        mock_processor = AsyncMock()
        mock_processor.process_query.side_effect = RuntimeError("unexpected")

        with patch("foundry_strands_agent.backend.create_query_processor") as mock_qp:
            with patch("foundry_strands_agent.backend.create_response_processor"):
                mock_qp.return_value = mock_processor
                backend = StrandsAgentBackend(container)

        request = AgentRequest(query="test")
        with pytest.raises(QueryProcessingError, match="StrandsAgentBackend processing failed"):
            await backend.process_message(request)

    @pytest.mark.asyncio
    async def test_reraises_query_processing_error(self):
        container = MagicMock()
        mock_config = MagicMock()
        mock_config.agent_name = "test"
        mock_config.agent_description = "test"
        container.resolve.return_value = mock_config

        mock_processor = AsyncMock()
        mock_processor.process_query.side_effect = QueryProcessingError("pipeline failed")

        with patch("foundry_strands_agent.backend.create_query_processor") as mock_qp:
            with patch("foundry_strands_agent.backend.create_response_processor"):
                mock_qp.return_value = mock_processor
                backend = StrandsAgentBackend(container)

        request = AgentRequest(query="test")
        with pytest.raises(QueryProcessingError, match="pipeline failed"):
            await backend.process_message(request)
