# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Additional orchestrator tests for coverage."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from foundry_agent_core import AgentRequest, AgentResponse, QueryProcessingError
from foundry_strands_agent.orchestrator import QueryOrchestrator, create_query_processor
from foundry_strands_agent.types import QueryRequest


@pytest.fixture
def orchestrator():
    config = MagicMock()
    config.max_query_length = 2000
    config.default_similarity_threshold = 0.7
    config.max_response_time_ms = 30000

    container = MagicMock()
    container.resolve.return_value = config
    factory = MagicMock()
    tool_registry = MagicMock()
    response_processor = MagicMock()

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

    @pytest.mark.asyncio
    async def test_process_query_start_log_has_no_raw_query_text(self, orchestrator, caplog):
        mock_agent = MagicMock()
        mock_agent.invoke_async = AsyncMock(return_value="Agent response text")
        mock_agent.close = AsyncMock()

        orchestrator._agent_factory.create_agent_with_tool_registry = AsyncMock(return_value=mock_agent)
        orchestrator._response_processor.process_response = AsyncMock(
            return_value=AgentResponse(content="processed", processing_time_ms=10.0)
        )

        query_text = "what is the secret launch code"
        request = AgentRequest(query=query_text)
        with caplog.at_level("INFO"):
            await orchestrator.process_query(request)

        start_records = [r for r in caplog.records if r.getMessage() == "Starting query processing"]
        assert start_records
        for record in start_records:
            assert query_text not in str(record.__dict__)
            assert getattr(record, "query_length", None) == len(query_text)

    @pytest.mark.asyncio
    async def test_query_timeout_context_has_no_raw_query_text(self, orchestrator):
        mock_agent = MagicMock()
        mock_agent.invoke_async = AsyncMock(side_effect=TimeoutError("timed out"))
        mock_agent.close = AsyncMock()

        orchestrator._agent_factory.create_agent_with_tool_registry = AsyncMock(return_value=mock_agent)

        query_text = "what is the secret launch code"
        request = AgentRequest(query=query_text)
        # _create_agent_context's `except Exception` re-wraps whatever is
        # raised while the agent is in use (including QueryTimeoutError)
        # into a QueryProcessingError - pre-existing behavior, out of scope
        # for this change. What matters here is that the raw query text
        # does not leak into that wrapped exception either.
        with pytest.raises(QueryProcessingError) as exc_info:
            await orchestrator.process_query(request)

        assert query_text not in str(exc_info.value)
        assert query_text not in str(exc_info.value.context)


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

    @pytest.mark.asyncio
    async def test_max_results_not_reclamped_below_canonical_bound(self, orchestrator):
        """Orchestrator no longer applies its own hardcoded clamp."""
        from foundry_agent_core import _MAX_RESULTS

        orchestrator._config.max_query_length = 2000
        orchestrator._config.default_similarity_threshold = 0.7
        request = QueryRequest(query="hello", max_results=_MAX_RESULTS)
        result = await orchestrator._preprocess_query(request, "q1")
        assert result.max_results == _MAX_RESULTS

    @pytest.mark.asyncio
    async def test_query_between_old_and_new_bound_not_short_circuited(self, orchestrator):
        """A query beyond the old 8,192-char bound passes end to end."""
        orchestrator._config.max_query_length = 100_000
        request = QueryRequest(query="a" * 50_000)
        result = await orchestrator._preprocess_query(request, "q1")
        assert len(result.query) == 50_000


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
        container = MagicMock()
        container.resolve.return_value = MagicMock()
        processor = create_query_processor(container, MagicMock(), MagicMock(), MagicMock())
        assert isinstance(processor, QueryOrchestrator)


class TestConfigResolvedFromContainer:
    @pytest.mark.asyncio
    async def test_max_query_length_from_container_config(self):
        """Config loaded via container (e.g. from_yaml) is respected at runtime."""
        from foundry_strands_agent.config.models import StrandsAgentConfig
        from foundry_strands_agent.types import QueryRequest

        config = MagicMock(spec=StrandsAgentConfig)
        config.max_query_length = 5000
        config.default_similarity_threshold = 0.7
        config.max_response_time_ms = 30000

        container = MagicMock()
        container.resolve.return_value = config

        orch = QueryOrchestrator(container, MagicMock(), MagicMock(), MagicMock())

        # A query of 3000 chars should pass with limit=5000
        request = QueryRequest(query="a" * 3000)
        result = await orch._preprocess_query(request, "q1")
        assert len(result.query) == 3000

        # A query of 6000 chars should fail with limit=5000
        long_request = QueryRequest(query="b" * 6000)
        with pytest.raises(QueryProcessingError, match="exceeds maximum length"):
            await orch._preprocess_query(long_request, "q2")
