# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for query orchestration — spec: strands-query-orchestration."""

import time
from unittest.mock import MagicMock, patch

import pytest

from foundry_agent_core import AgentRequest, AgentResponse


class TestQueryOrchestratorProtocol:
    """Scenario: QueryOrchestrator implements QueryProcessor protocol."""

    def test_has_process_query(self):
        from foundry_strands_agent.orchestrator import QueryOrchestrator

        assert hasattr(QueryOrchestrator, "process_query")

    def test_has_process_query_stream(self):
        from foundry_strands_agent.orchestrator import QueryOrchestrator

        assert hasattr(QueryOrchestrator, "process_query_stream")

    def test_to_internal_request_mapping(self):
        from foundry_strands_agent.orchestrator import QueryOrchestrator

        container = MagicMock()
        factory = MagicMock()
        tool_registry = MagicMock()
        response_processor = MagicMock()

        with patch("foundry_strands_agent.orchestrator.StrandsAgentConfig.from_env") as mock_config:
            mock_config.return_value = MagicMock()
            orch = QueryOrchestrator(container, factory, tool_registry, response_processor)

        request = AgentRequest(query="hello", session_id="session1", context={"key": "val"})
        internal = orch._to_internal_request(request)

        assert internal.query == "hello"
        assert internal.session_id == "session1"
        assert internal.context == {"key": "val"}

    def test_to_internal_request_no_session(self):
        from foundry_strands_agent.orchestrator import QueryOrchestrator

        container = MagicMock()
        factory = MagicMock()
        tool_registry = MagicMock()
        response_processor = MagicMock()

        with patch("foundry_strands_agent.orchestrator.StrandsAgentConfig.from_env") as mock_config:
            mock_config.return_value = MagicMock()
            orch = QueryOrchestrator(container, factory, tool_registry, response_processor)

        request = AgentRequest(query="hello")
        internal = orch._to_internal_request(request)

        assert internal.query == "hello"
        assert internal.session_id is None


class TestDefaultResponseProcessor:
    """Scenario: Response transformation."""

    @pytest.mark.asyncio
    async def test_process_response_extracts_content(self):
        from foundry_strands_agent.response_processor import DefaultResponseProcessor

        processor = DefaultResponseProcessor()
        raw_response = MagicMock()
        raw_response.content = "Hello world"
        raw_response.sources = []
        raw_response.chunks = []
        raw_response.confidence = None
        raw_response.metadata = {}
        del raw_response.execution_time
        del raw_response.tools_used
        del raw_response.reasoning

        request = AgentRequest(query="test query")
        start_time = time.time()

        result = await processor.process_response(raw_response, request, start_time, "q-1")

        assert isinstance(result, AgentResponse)
        assert result.content == "Hello world"
        assert result.processing_time_ms >= 0

    @pytest.mark.asyncio
    async def test_process_response_with_string_response(self):
        from foundry_strands_agent.response_processor import DefaultResponseProcessor

        processor = DefaultResponseProcessor()
        request = AgentRequest(query="test")
        start_time = time.time()

        result = await processor.process_response("plain string response", request, start_time, "q-2")

        assert result.content == "plain string response"

    @pytest.mark.asyncio
    async def test_confidence_score_range(self):
        from foundry_strands_agent.response_processor import DefaultResponseProcessor

        processor = DefaultResponseProcessor()
        raw = MagicMock()
        raw.content = "Some long response with enough text to get quality bonus"
        raw.sources = [MagicMock(similarity_score=0.9), MagicMock(similarity_score=0.85)]
        raw.chunks = []
        raw.confidence = None
        raw.metadata = {}
        del raw.execution_time
        del raw.tools_used
        del raw.reasoning

        request = AgentRequest(query="test")
        result = await processor.process_response(raw, request, time.time(), "q-3")

        assert result.metadata is not None
        assert 0.0 <= result.metadata["confidence_score"] <= 1.0


class TestRequestLifecycleManager:
    """Scenario: Execution context creation and timeout."""

    @pytest.mark.asyncio
    async def test_create_execution_context(self):
        from foundry_strands_agent.lifecycle import ExecutionStrategy, RequestLifecycleManager

        container = MagicMock()
        manager = RequestLifecycleManager(container)

        request = AgentRequest(query="test", session_id="session1")
        async with manager.create_execution_context(
            request=request,
            strategy=ExecutionStrategy.STANDARD,
            timeout_ms=5000,
        ) as ctx:
            assert ctx.session_id == "session1"
            assert ctx.timeout_ms == 5000
            assert ctx.strategy == ExecutionStrategy.STANDARD
            assert ctx.elapsed_time_ms >= 0
            assert ctx.remaining_time_ms <= 5000

    def test_timeout_exceeded(self):
        from foundry_strands_agent.lifecycle import ExecutionContext

        ctx = ExecutionContext(
            session_id="session1",
            query_id="q1",
            request=None,
            start_time=time.time() - 100,
            timeout_ms=1000,
        )
        assert ctx.is_timeout_exceeded is True
        assert ctx.remaining_time_ms == 0.0

    def test_timeout_not_exceeded(self):
        from foundry_strands_agent.lifecycle import ExecutionContext

        ctx = ExecutionContext(
            session_id="session1",
            query_id="q1",
            request=None,
            start_time=time.time(),
            timeout_ms=60000,
        )
        assert ctx.is_timeout_exceeded is False
        assert ctx.remaining_time_ms > 0

    def test_retry_context_backoff(self):
        from foundry_strands_agent.lifecycle import RetryContext

        ctx = RetryContext(attempt=0, max_attempts=3, base_delay_ms=1000)
        assert ctx.should_retry is True
        assert ctx.delay_ms == 0

        ctx.increment_attempt()
        assert ctx.attempt == 1
        assert ctx.delay_ms == 1000

        ctx.increment_attempt()
        assert ctx.attempt == 2
        assert ctx.delay_ms == 2000

    def test_circuit_breaker(self):
        from foundry_strands_agent.lifecycle import RetryContext

        ctx = RetryContext(circuit_breaker_threshold=3)
        assert ctx.is_circuit_breaker_open is False

        for _ in range(3):
            ctx.record_failure()
        assert ctx.is_circuit_breaker_open is True

        ctx.record_success()
        assert ctx.is_circuit_breaker_open is False
