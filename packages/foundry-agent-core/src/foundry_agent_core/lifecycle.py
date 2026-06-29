# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Request lifecycle management for agent execution.

This module provides infrastructure for managing individual request lifecycles,
including execution context tracking, timeout monitoring, and optional retry
logic for external system failures.

Note: This is NOT workflow orchestration. For multi-step workflows, sagas,
or durable execution, use Temporal (see foundry-temporal package).
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from foundry_agent_core.exceptions import QueryProcessingError, QueryTimeoutError
from foundry_agent_core.masking import mask_session_id
from foundry_agent_core.protocols import DependencyContainer
from foundry_agent_core.types import AgentRequest

logger = logging.getLogger(__name__)


class ExecutionStrategy(Enum):
    """Execution strategy for agent workflow processing."""

    STANDARD = "standard"
    RESILIENT = "resilient"
    HIGH_AVAILABILITY = "high_availability"


class RetryPolicy(Enum):
    """Retry policy for external system failures."""

    NONE = "none"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    CIRCUIT_BREAKER = "circuit_breaker"


@dataclass
class ExecutionContext:
    """Context for tracking agent execution state and resources.

    This context provides infrastructure support for autonomous agent execution
    while maintaining agent autonomy over tool selection and usage decisions.
    """

    session_id: str | None
    query_id: str
    request: AgentRequest | None
    start_time: float
    strategy: ExecutionStrategy = ExecutionStrategy.STANDARD
    retry_policy: RetryPolicy = RetryPolicy.EXPONENTIAL
    max_retries: int = 3
    timeout_ms: int = 30000
    metadata: dict[str, Any] = field(default_factory=dict)
    resource_usage: dict[str, Any] = field(default_factory=dict)
    external_service_states: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize execution context with default metadata."""
        if "created_at" not in self.metadata:
            self.metadata["created_at"] = self.start_time
        if "execution_strategy" not in self.metadata:
            self.metadata["execution_strategy"] = self.strategy.value
        if "retry_policy" not in self.metadata:
            self.metadata["retry_policy"] = self.retry_policy.value

    @property
    def elapsed_time_ms(self) -> float:
        """Calculate elapsed time since execution started."""
        return (time.time() - self.start_time) * 1000

    @property
    def remaining_time_ms(self) -> float:
        """Calculate remaining time before timeout."""
        return max(0, self.timeout_ms - self.elapsed_time_ms)

    @property
    def is_timeout_exceeded(self) -> bool:
        """Check if execution has exceeded the timeout."""
        return self.elapsed_time_ms >= self.timeout_ms

    def update_resource_usage(self, resource_type: str, usage_data: Any) -> None:
        """Update resource usage tracking."""
        self.resource_usage[resource_type] = {
            "data": usage_data,
            "timestamp": time.time(),
        }

    def update_external_service_state(self, service_name: str, state: str) -> None:
        """Update external service state tracking."""
        self.external_service_states[service_name] = state
        self.metadata[f"{service_name}_last_update"] = time.time()


@dataclass
class RetryContext:
    """Context for retry operations with external systems."""

    attempt: int = 0
    max_attempts: int = 3
    base_delay_ms: int = 1000
    max_delay_ms: int = 10000
    backoff_multiplier: float = 2.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_reset_timeout_ms: int = 60000
    last_failure_time: float | None = None
    consecutive_failures: int = 0

    @property
    def should_retry(self) -> bool:
        """Determine if another retry attempt should be made."""
        return self.attempt < self.max_attempts

    @property
    def delay_ms(self) -> int:
        """Calculate delay for exponential backoff."""
        if self.attempt == 0:
            return 0

        delay = min(
            self.base_delay_ms * (self.backoff_multiplier ** (self.attempt - 1)),
            self.max_delay_ms,
        )
        return int(delay)

    @property
    def is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker should be open."""
        if self.consecutive_failures < self.circuit_breaker_threshold:
            return False

        if self.last_failure_time is None:
            return True

        time_since_failure = (time.time() - self.last_failure_time) * 1000
        return time_since_failure < self.circuit_breaker_reset_timeout_ms

    def record_failure(self) -> None:
        """Record a failure for circuit breaker tracking."""
        self.consecutive_failures += 1
        self.last_failure_time = time.time()

    def record_success(self) -> None:
        """Record a success, resetting failure tracking."""
        self.consecutive_failures = 0
        self.last_failure_time = None

    def increment_attempt(self) -> None:
        """Increment the retry attempt counter."""
        self.attempt += 1


class RequestLifecycleManager:
    """Manager for request lifecycle and execution context.

    This class provides infrastructure for request lifecycle management:
    - Execution context creation and tracking
    - Timeout monitoring
    - Optional retry with exponential backoff and circuit breaker

    Note: This is NOT workflow orchestration (use Temporal for that).
    This manages the lifecycle of individual requests within the agent.
    """

    def __init__(self, container: DependencyContainer) -> None:
        """Initialize request lifecycle manager with dependency container.

        Args:
            container: Dependency injection container for infrastructure components
        """
        self._container = container
        self._active_contexts: dict[str, ExecutionContext] = {}
        self._retry_contexts: dict[str, RetryContext] = {}

    @asynccontextmanager
    async def create_execution_context(
        self,
        request: AgentRequest | None = None,
        strategy: ExecutionStrategy = ExecutionStrategy.STANDARD,
        timeout_ms: int = 30000,
    ) -> AsyncGenerator[ExecutionContext]:
        """Create and manage execution context for agent processing.

        Args:
            request: Query request to process
            strategy: Execution strategy to use
            timeout_ms: Maximum execution time in milliseconds

        Yields:
            ExecutionContext for tracking agent execution

        Raises:
            QueryProcessingError: If context creation fails
        """
        session_id = request.session_id if request else None
        query_id = f"query_{int(time.time() * 1000)}"
        start_time = time.time()

        context = ExecutionContext(
            session_id=session_id,
            query_id=query_id,
            request=request,
            start_time=start_time,
            strategy=strategy,
            timeout_ms=timeout_ms,
        )

        try:
            logger.info(
                "Creating execution context for agent processing",
                extra={
                    "session_id": mask_session_id(session_id),
                    "query_id": query_id,
                    "strategy": strategy.value,
                    "timeout_ms": timeout_ms,
                },
            )

            # Register context as active
            self._active_contexts[query_id] = context

            # Initialize retry context if needed
            if strategy in [
                ExecutionStrategy.RESILIENT,
                ExecutionStrategy.HIGH_AVAILABILITY,
            ]:
                max_retries = 5 if strategy == ExecutionStrategy.HIGH_AVAILABILITY else 3
                self._retry_contexts[query_id] = RetryContext(max_attempts=max_retries)

            yield context

            logger.info(
                "Execution context completed successfully",
                extra={
                    "session_id": mask_session_id(session_id),
                    "query_id": query_id,
                    "elapsed_time_ms": context.elapsed_time_ms,
                },
            )

        except Exception as e:
            logger.error(
                "Execution context failed",
                extra={
                    "session_id": mask_session_id(session_id),
                    "query_id": query_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "elapsed_time_ms": context.elapsed_time_ms,
                },
            )
            raise QueryProcessingError(
                f"Execution context failed: {e}",
                context={
                    "session_id": session_id,
                    "query_id": query_id,
                    "error": str(e),
                    "elapsed_time_ms": context.elapsed_time_ms,
                },
            ) from e
        finally:
            # Clean up context tracking
            self._active_contexts.pop(query_id, None)
            self._retry_contexts.pop(query_id, None)

            logger.debug(
                "Execution context cleanup completed",
                extra={"session_id": mask_session_id(session_id), "query_id": query_id},
            )

    # TODO(dead-code): no live callers — candidate for removal, see fix-session-id-log-masking design.md D4
    async def execute_with_retry(
        self,
        context: ExecutionContext,
        operation: Any,
        operation_name: str,
    ) -> Any:
        """Execute operation with retry logic for external system failures.

        This method provides infrastructure retry support while maintaining
        agent autonomy. It only retries infrastructure and external system
        failures, not agent decision-making processes.

        Args:
            context: Execution context for the operation
            operation: Async callable to execute with retry
            operation_name: Name of the operation for logging

        Returns:
            Result of the successful operation

        Raises:
            QueryProcessingError: If all retry attempts fail
            QueryTimeoutError: If operation exceeds context timeout
        """
        retry_context = self._retry_contexts.get(context.query_id, RetryContext())

        while retry_context.should_retry:
            try:
                # Check timeout before attempting operation
                if context.is_timeout_exceeded:
                    raise QueryTimeoutError(
                        context.timeout_ms,
                        context={
                            "session_id": context.session_id,
                            "query_id": context.query_id,
                            "operation": operation_name,
                            "elapsed_time_ms": context.elapsed_time_ms,
                        },
                    )

                # Check circuit breaker
                if retry_context.is_circuit_breaker_open:
                    logger.warning(
                        "Circuit breaker is open, operation blocked",
                        extra={
                            "session_id": mask_session_id(context.session_id),
                            "query_id": context.query_id,
                            "operation": operation_name,
                            "consecutive_failures": retry_context.consecutive_failures,
                        },
                    )
                    raise QueryProcessingError(
                        f"Circuit breaker open for {operation_name}",
                        context={
                            "session_id": context.session_id,
                            "query_id": context.query_id,
                            "operation": operation_name,
                            "consecutive_failures": retry_context.consecutive_failures,
                        },
                    )

                # Apply delay for retry attempts
                if retry_context.attempt > 0:
                    delay_ms = retry_context.delay_ms
                    logger.debug(
                        "Applying retry delay",
                        extra={
                            "session_id": mask_session_id(context.session_id),
                            "query_id": context.query_id,
                            "operation": operation_name,
                            "attempt": retry_context.attempt,
                            "delay_ms": delay_ms,
                        },
                    )
                    await asyncio.sleep(delay_ms / 1000.0)

                # Execute operation with timeout
                remaining_time_s = context.remaining_time_ms / 1000.0
                result = await asyncio.wait_for(operation(), timeout=remaining_time_s)

                # Record success
                retry_context.record_success()
                logger.debug(
                    "Operation completed successfully",
                    extra={
                        "session_id": mask_session_id(context.session_id),
                        "query_id": context.query_id,
                        "operation": operation_name,
                        "attempt": retry_context.attempt + 1,
                    },
                )

                return result

            except TimeoutError as timeout_err:
                raise QueryTimeoutError(
                    context.timeout_ms,
                    context={
                        "session_id": context.session_id,
                        "query_id": context.query_id,
                        "operation": operation_name,
                        "attempt": retry_context.attempt + 1,
                    },
                ) from timeout_err

            except Exception as e:
                retry_context.increment_attempt()
                retry_context.record_failure()

                logger.warning(
                    "Operation attempt failed",
                    extra={
                        "session_id": mask_session_id(context.session_id),
                        "query_id": context.query_id,
                        "operation": operation_name,
                        "attempt": retry_context.attempt,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )

                # If this was the last attempt, raise the error
                if not retry_context.should_retry:
                    raise QueryProcessingError(
                        f"Operation {operation_name} failed after {retry_context.attempt} attempts: {e}",
                        context={
                            "session_id": context.session_id,
                            "query_id": context.query_id,
                            "operation": operation_name,
                            "attempts": retry_context.attempt,
                            "final_error": str(e),
                        },
                    ) from e

        # Should not reach here, but added for completeness
        raise QueryProcessingError(
            f"Retry logic error for operation {operation_name}",
            context={
                "session_id": context.session_id,
                "query_id": context.query_id,
                "operation": operation_name,
            },
        )

    # TODO(dead-code): no live callers — candidate for removal, see fix-session-id-log-masking design.md D4
    def get_active_contexts(self) -> dict[str, ExecutionContext]:
        """Get currently active execution contexts.

        Returns:
            Dictionary of active execution contexts by query ID
        """
        return self._active_contexts.copy()

    # TODO(dead-code): no live callers — candidate for removal, see fix-session-id-log-masking design.md D4
    def get_retry_statistics(self) -> dict[str, dict[str, Any]]:
        """Get retry statistics for all contexts.

        Returns:
            Dictionary of retry statistics by query ID
        """
        return {
            query_id: {
                "attempt": retry_ctx.attempt,
                "consecutive_failures": retry_ctx.consecutive_failures,
                "circuit_breaker_open": retry_ctx.is_circuit_breaker_open,
                "last_failure_time": retry_ctx.last_failure_time,
            }
            for query_id, retry_ctx in self._retry_contexts.items()
        }


def create_request_lifecycle_manager(container: DependencyContainer) -> RequestLifecycleManager:
    """Factory function to create RequestLifecycleManager instance.

    Args:
        container: Dependency injection container

    Returns:
        Configured RequestLifecycleManager implementation
    """
    return RequestLifecycleManager(container)
