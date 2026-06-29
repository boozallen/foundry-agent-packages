# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Additional orchestrator tests for coverage."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundry_agent_core import AgentRequest, AgentResponse, QueryProcessingError
from foundry_strands_agent.orchestrator import QueryOrchestrator, create_query_processor
from foundry_strands_agent.types import QueryRequest


@pytest.fixture
def orchestrator():
    container = MagicMock()
    factory = MagicMock()
    tool_registry = MagicMock()
    response_processor = MagicMock()

    with patch("foundry_strands_agent.orchestrator.StrandsAgentConfig.from_env") as mock_config:
        config = MagicMock()
        config.max_query_length = 2000
        config.default_similarity_threshold = 0.7
        mock_config.return_value = config
        orch = QueryOrchestrator(container, factory, tool_registry, response_processor)
    return orch


class TestQueryOrchestratorProcessQuery:
    @pytest.mark.asyncio
    async def test_process_query_full_pipeline(self, orchestrator):
        mock_agent = MagicMock()
        mock_agent.invoke_async = AsyncMock(return_value="Agent response text")
        mock_agent.close = AsyncMock()

        orchestrator._agent_factory.create_agent_with_tool_registry = AsyncMock(return_value=mock_agent)
        orchestrator._response_processor.process_response = AsyncMock(
            return_value=AgentResponse(content="processed", processing_time_ms=10.0)
        )

        request = AgentRequest(query="hello world")
        result = await orchestrator.process_query(request)

        assert result.content == "processed"
        orchestrator._response_processor.process_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_query_reraises_query_processing_error(self, orchestrator):
        orchestrator._agent_factory.create_agent_with_tool_registry = AsyncMock(
            side_effect=QueryProcessingError("agent failed")
        )

        request = AgentRequest(query="hello")
        with pytest.raises(QueryProcessingError, match="agent failed"):
            await orchestrator.process_query(request)

    @pytest.mark.asyncio
    async def test_process_query_wraps_unexpected_error(self, orchestrator):
        orchestrator._agent_factory.create_agent_with_tool_registry = AsyncMock(side_effect=RuntimeError("unexpected"))

        request = AgentRequest(query="hello")
        with pytest.raises(QueryProcessingError):
            await orchestrator.process_query(request)


class TestPreprocessQuery:
    @pytest.mark.asyncio
    async def test_query_too_long_raises(self, orchestrator):
        orchestrator._config.max_query_length = 10
        request = QueryRequest(query="a" * 100)
        with pytest.raises(QueryProcessingError, match="exceeds maximum length"):
            await orchestrator._preprocess_query(request, "q1")

    @pytest.mark.asyncio
    async def test_normalizes_query(self, orchestrator):
        orchestrator._config.max_query_length = 2000
        orchestrator._config.default_similarity_threshold = 0.8
        request = QueryRequest(query="  hello  ", similarity_threshold=0.9)
        result = await orchestrator._preprocess_query(request, "q1")
        assert result.query == "hello"
        assert result.similarity_threshold == 0.9

    @pytest.mark.asyncio
    async def test_default_similarity_threshold_applied(self, orchestrator):
        orchestrator._config.max_query_length = 2000
        orchestrator._config.default_similarity_threshold = 0.8
        request = QueryRequest(query="hello")
        result = await orchestrator._preprocess_query(request, "q1")
        assert result.similarity_threshold == 0.7  # QueryRequest default, not config default


class TestToInternalRequest:
    def test_maps_all_fields(self, orchestrator):
        request = AgentRequest(query="test", session_id="session1", context={"k": "v"})
        internal = orchestrator._to_internal_request(request)
        assert internal.query == "test"
        assert internal.session_id == "session1"
        assert internal.context == {"k": "v"}


class TestExtractResultText:
    def test_none_returns_empty(self, orchestrator):
        assert orchestrator._extract_result_text(None) == ""

    def test_string_passthrough(self, orchestrator):
        assert orchestrator._extract_result_text("hello") == "hello"

    def test_object_with_text_attr(self, orchestrator):
        obj = MagicMock()
        obj.text = "from text"
        del obj.content
        del obj.output
        assert orchestrator._extract_result_text(obj) == "from text"

    def test_object_with_content_attr(self, orchestrator):
        obj = MagicMock()
        obj.content = "from content"
        assert orchestrator._extract_result_text(obj) == "from content"

    def test_fallback_to_str(self, orchestrator):
        result = orchestrator._extract_result_text(42)
        assert result == "42"


class TestCreateQueryProcessor:
    def test_returns_orchestrator(self):
        with patch("foundry_strands_agent.orchestrator.StrandsAgentConfig.from_env") as mock_config:
            mock_config.return_value = MagicMock()
            processor = create_query_processor(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        assert isinstance(processor, QueryOrchestrator)
