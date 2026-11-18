# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Agent-specific exception handling extending domain exceptions.

This module defines agent-specific exceptions that extend the base domain
exceptions with additional context and information relevant to agent operations,
workflow management, and service lifecycle.
"""

import logging
import uuid
from typing import Any, NoReturn

from foundry_agent_core import DomainError, QueryProcessingError


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


def raise_with_correlation_id(
    error_cls: type[DomainError],
    log_message: str,
    *,
    logger: logging.Logger,
    context: dict[str, Any] | None = None,
) -> NoReturn:
    """Log full failure detail under a correlation ID, then raise a generic DomainError.

    Must be called from inside an ``except`` block, so ``exc_info=True`` captures the real,
    active exception. Nothing derived from that exception - which might carry a secret an
    underlying library echoed back in its own message - ever reaches the raised exception's
    message or context. The exception chain is deliberately severed (``from None``) so a later
    ``exc_info=True`` log of *this* exception elsewhere (e.g. API middleware) can't render the
    original message either. Full detail is intentionally only ever in the log, tied to the
    correlation_id.

    ``context`` must contain only values safe to raise and log directly (e.g. identifiers like
    a server name/URL), never anything that could itself carry a secret.
    """
    correlation_id = str(uuid.uuid4())
    logger.error(
        "%s (correlation_id=%s, context=%s)",
        log_message,
        correlation_id,
        context or {},
        exc_info=True,
    )
    raise error_cls(
        "Operation failed. See internal logs for this correlation_id.",
        context={**(context or {}), "correlation_id": correlation_id},
    ) from None
