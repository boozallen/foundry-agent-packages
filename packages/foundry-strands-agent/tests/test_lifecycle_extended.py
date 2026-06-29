# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Extended tests for lifecycle module to improve coverage."""

import time

from foundry_agent_core import AgentRequest
from foundry_strands_agent.lifecycle import (
    ExecutionContext,
    ExecutionStrategy,
    RetryPolicy,
)


class TestExecutionContext:
    """Test ExecutionContext data class."""

    def test_execution_context_defaults(self):
        """Test ExecutionContext with default values."""
        ctx = ExecutionContext(
            session_id="test-session",
            query_id="test-query",
            request=None,
            start_time=time.time(),
        )

        assert ctx.strategy == ExecutionStrategy.STANDARD
        assert ctx.retry_policy == RetryPolicy.EXPONENTIAL
        assert ctx.max_retries == 3
        assert ctx.timeout_ms == 30000
        assert isinstance(ctx.metadata, dict)
        assert isinstance(ctx.resource_usage, dict)
        assert isinstance(ctx.external_service_states, dict)

    def test_execution_context_post_init(self):
        """Test that __post_init__ sets metadata correctly."""
        start = time.time()
        ctx = ExecutionContext(
            session_id="test-123",
            query_id="query-1",
            request=None,
            start_time=start,
        )

        assert "created_at" in ctx.metadata
        assert ctx.metadata["created_at"] == start
        assert ctx.metadata["execution_strategy"] == "standard"
        assert ctx.metadata["retry_policy"] == "exponential"

    def test_execution_context_custom_strategy(self):
        """Test ExecutionContext with custom strategy."""
        ctx = ExecutionContext(
            session_id="test-123",
            query_id="query-2",
            request=None,
            start_time=time.time(),
            strategy=ExecutionStrategy.RESILIENT,
            retry_policy=RetryPolicy.LINEAR,
            max_retries=5,
            timeout_ms=60000,
        )

        assert ctx.strategy == ExecutionStrategy.RESILIENT
        assert ctx.retry_policy == RetryPolicy.LINEAR
        assert ctx.max_retries == 5
        assert ctx.timeout_ms == 60000
        assert ctx.metadata["execution_strategy"] == "resilient"
        assert ctx.metadata["retry_policy"] == "linear"

    def test_elapsed_time_ms(self):
        """Test elapsed time calculation."""
        start = time.time() - 0.5  # 500ms ago
        ctx = ExecutionContext(
            session_id="test-123",
            query_id="query-3",
            request=None,
            start_time=start,
        )

        elapsed = ctx.elapsed_time_ms
        assert elapsed >= 500
        assert elapsed < 2000  # Should be around 500ms

    def test_remaining_time_ms(self):
        """Test remaining time calculation."""
        start = time.time() - 0.5  # 500ms ago
        ctx = ExecutionContext(
            session_id="test-123",
            query_id="query-4",
            request=None,
            start_time=start,
            timeout_ms=1000,
        )

        remaining = ctx.remaining_time_ms
        assert remaining <= 500
        assert remaining > 400  # Should be around 500ms

    def test_execution_context_with_request(self):
        """Test ExecutionContext with an AgentRequest."""
        request = AgentRequest(
            query="Test query",
            session_id="req-session",
        )
        ctx = ExecutionContext(
            session_id="test-123",
            query_id="query-5",
            request=request,
            start_time=time.time(),
        )

        assert ctx.request == request
        assert ctx.request.query == "Test query"

    def test_execution_context_resource_usage(self):
        """Test resource_usage dictionary."""
        ctx = ExecutionContext(
            session_id="test-123",
            query_id="query-6",
            request=None,
            start_time=time.time(),
        )

        # Modify resource_usage
        ctx.resource_usage["tokens_used"] = 150
        ctx.resource_usage["api_calls"] = 3

        assert ctx.resource_usage["tokens_used"] == 150
        assert ctx.resource_usage["api_calls"] == 3

    def test_execution_context_external_service_states(self):
        """Test external_service_states dictionary."""
        ctx = ExecutionContext(
            session_id="test-123",
            query_id="query-7",
            request=None,
            start_time=time.time(),
        )

        # Track external service states
        ctx.external_service_states["database"] = "connected"
        ctx.external_service_states["cache"] = "healthy"

        assert ctx.external_service_states["database"] == "connected"
        assert ctx.external_service_states["cache"] == "healthy"

    def test_execution_context_metadata_override(self):
        """Test that pre-existing metadata is preserved."""
        start = time.time()
        ctx = ExecutionContext(
            session_id="test-123",
            query_id="query-8",
            request=None,
            start_time=start,
            metadata={"created_at": 12345, "custom_field": "value"},
        )

        # Should preserve the custom created_at
        assert ctx.metadata["created_at"] == 12345
        assert ctx.metadata["custom_field"] == "value"
        # Should still add strategy and policy
        assert "execution_strategy" in ctx.metadata


class TestExecutionStrategy:
    """Test ExecutionStrategy enum."""

    def test_execution_strategy_values(self):
        """Test all ExecutionStrategy enum values."""
        assert ExecutionStrategy.STANDARD.value == "standard"
        assert ExecutionStrategy.RESILIENT.value == "resilient"
        assert ExecutionStrategy.HIGH_AVAILABILITY.value == "high_availability"

    def test_execution_strategy_from_string(self):
        """Test creating ExecutionStrategy from string."""
        strategy = ExecutionStrategy("standard")
        assert strategy == ExecutionStrategy.STANDARD


class TestRetryPolicy:
    """Test RetryPolicy enum."""

    def test_retry_policy_values(self):
        """Test all RetryPolicy enum values."""
        assert RetryPolicy.NONE.value == "none"
        assert RetryPolicy.LINEAR.value == "linear"
        assert RetryPolicy.EXPONENTIAL.value == "exponential"
        assert RetryPolicy.CIRCUIT_BREAKER.value == "circuit_breaker"

    def test_retry_policy_from_string(self):
        """Test creating RetryPolicy from string."""
        policy = RetryPolicy("exponential")
        assert policy == RetryPolicy.EXPONENTIAL


# Factory tests removed - DependencyContainer is abstract and needs concrete implementation


class TestExecutionContextWithNoneSession:
    """Test ExecutionContext with None session_id."""

    def test_none_session_id(self):
        """Test ExecutionContext works with None session_id."""
        ctx = ExecutionContext(
            session_id=None,
            query_id="query-9",
            request=None,
            start_time=time.time(),
        )

        assert ctx.session_id is None
        assert ctx.query_id == "query-9"


class TestExecutionContextEdgeCases:
    """Test edge cases for ExecutionContext."""

    def test_very_large_timeout(self):
        """Test ExecutionContext with very large timeout."""
        ctx = ExecutionContext(
            session_id="test-123",
            query_id="query-11",
            request=None,
            start_time=time.time(),
            timeout_ms=1000000,
        )

        assert ctx.timeout_ms == 1000000
        assert ctx.remaining_time_ms > 900000
