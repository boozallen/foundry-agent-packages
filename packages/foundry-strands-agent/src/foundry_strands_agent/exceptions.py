# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Agent-specific exception handling extending domain exceptions.

This module defines agent-specific exceptions that extend the base domain
exceptions with additional context and information relevant to agent operations,
workflow management, and service lifecycle.
"""

from typing import Any

from foundry_agent_core import QueryProcessingError


class AgentServiceError(QueryProcessingError):
    """Base exception for agent service operations.

    Extends QueryProcessingError to provide consistent error handling
    for high-level service operations and lifecycle management.
    """

    def __init__(
        self,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, context=context or {})


class AgentServiceInitializationError(AgentServiceError):
    """Exception raised when agent service initialization fails."""

    def __init__(
        self,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"Service initialization failed: {message}", context=context)


class AgentServiceShutdownError(AgentServiceError):
    """Exception raised when agent service shutdown fails."""

    def __init__(
        self,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"Service shutdown failed: {message}", context=context)
