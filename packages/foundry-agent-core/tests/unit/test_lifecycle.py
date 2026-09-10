# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for lifecycle module."""

import logging
import time

import pytest

from foundry_agent_core.lifecycle import (
    ExecutionContext,
    ExecutionStrategy,
    RequestLifecycleManager,
    RetryContext,
    RetryPolicy,
    create_request_lifecycle_manager,
)
from foundry_agent_core.masking import mask_session_id
from foundry_agent_core.types import AgentRequest


class TestExecutionContext:
    def test_default_initialization(self) -> None:
        ctx = ExecutionContext(
            session_id=None,
            query_id="q1",
            request=None,
            start_time=time.time(),
        )
        assert ctx.query_id == "q1"
        assert ctx.strategy == ExecutionStrategy.STANDARD
        assert ctx.retry_policy == RetryPolicy.EXPONENTIAL
        assert ctx.max_retries == 3
        assert ctx.timeout_ms == 30000

    def test_with_request(self) -> None:
        req = AgentRequest(query="test")
        ctx = ExecutionContext(
            session_id="session1",
            query_id="q1",
            request=req,
            start_time=time.time(),
        )
        assert ctx.request is req
        assert ctx.session_id == "session1"

    def test_elapsed_time(self) -> None:
        ctx = ExecutionContext(
            session_id=None,
            query_id="q1",
            request=None,
            start_time=time.time() - 1.0,
        )
        assert ctx.elapsed_time_ms >= 900

    def test_timeout_exceeded(self) -> None:
        ctx = ExecutionContext(
            session_id=None,
            query_id="q1",
            request=None,
            start_time=time.time() - 35.0,
            timeout_ms=30000,
        )
        assert ctx.is_timeout_exceeded is True

    def test_timeout_not_exceeded(self) -> None:
        ctx = ExecutionContext(
            session_id=None,
            query_id="q1",
            request=None,
            start_time=time.time(),
            timeout_ms=30000,
        )
        assert ctx.is_timeout_exceeded is False

    def test_update_resource_usage(self) -> None:
        ctx = ExecutionContext(session_id=None, query_id="q1", request=None, start_time=time.time())
        ctx.update_resource_usage("memory", {"used": "50MB"})
        assert "memory" in ctx.resource_usage

    def test_update_external_service_state(self) -> None:
        ctx = ExecutionContext(session_id=None, query_id="q1", request=None, start_time=time.time())
        ctx.update_external_service_state("db", "healthy")
        assert ctx.external_service_states["db"] == "healthy"


class TestRetryContext:
    def test_defaults(self) -> None:
        rc = RetryContext()
        assert rc.attempt == 0
        assert rc.max_attempts == 3
        assert rc.should_retry is True

    def test_should_retry_at_limit(self) -> None:
        rc = RetryContext(max_attempts=3)
        rc.attempt = 3
        assert rc.should_retry is False

    def test_delay_exponential(self) -> None:
        rc = RetryContext(base_delay_ms=1000, backoff_multiplier=2.0)
        rc.attempt = 0
        assert rc.delay_ms == 0
        rc.attempt = 1
        assert rc.delay_ms == 1000
        rc.attempt = 2
        assert rc.delay_ms == 2000

    def test_record_failure_and_success(self) -> None:
        rc = RetryContext()
        rc.record_failure()
        assert rc.consecutive_failures == 1
        rc.record_success()
        assert rc.consecutive_failures == 0

    def test_circuit_breaker(self) -> None:
        rc = RetryContext(circuit_breaker_threshold=2)
        rc.record_failure()
        rc.record_failure()
        assert rc.is_circuit_breaker_open is True


class TestRequestLifecycleManager:
    @pytest.mark.asyncio
    async def test_create_execution_context(self) -> None:
        from foundry_agent_core.container import FunctionalDependencyContainer

        container = FunctionalDependencyContainer()
        manager = RequestLifecycleManager(container)
        async with manager.create_execution_context() as ctx:
            assert isinstance(ctx, ExecutionContext)
            assert ctx.query_id is not None

    def test_create_request_lifecycle_manager(self) -> None:
        from foundry_agent_core.container import FunctionalDependencyContainer

        container = FunctionalDependencyContainer()
        manager = create_request_lifecycle_manager(container)
        assert isinstance(manager, RequestLifecycleManager)

    @pytest.mark.asyncio
    async def test_session_id_is_masked_in_log_records(self) -> None:
        """STIG V-222577: raw session ID must not appear in any log record extra.

        Installs a capturing handler on the lifecycle logger, invokes
        create_execution_context with a known session_id, and asserts:
        - At least one record was emitted with a session_id extra field.
        - No record's session_id extra equals the raw input value.
        - Every record's session_id extra matches the <session:…> placeholder.
        """
        from foundry_agent_core.container import FunctionalDependencyContainer

        raw_session_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        expected_masked = mask_session_id(raw_session_id)

        captured: list[logging.LogRecord] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        lifecycle_logger = logging.getLogger("foundry_agent_core.lifecycle")
        handler = CapturingHandler()
        lifecycle_logger.addHandler(handler)
        original_level = lifecycle_logger.level
        lifecycle_logger.setLevel(logging.DEBUG)

        try:
            container = FunctionalDependencyContainer()
            manager = RequestLifecycleManager(container)
            async with manager.create_execution_context(request=AgentRequest(query="test", session_id=raw_session_id)):
                pass
        finally:
            lifecycle_logger.removeHandler(handler)
            lifecycle_logger.setLevel(original_level)

        records_with_session = [r for r in captured if getattr(r, "session_id", None) is not None]
        assert records_with_session, "Expected at least one log record with session_id extra"

        for record in records_with_session:
            assert record.session_id != raw_session_id, f"Raw session ID leaked into log record: {record.session_id!r}"
            assert record.session_id == expected_masked, (
                f"Expected masked placeholder {expected_masked!r}, got {record.session_id!r}"
            )
