# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Error translation protocol for infrastructure exceptions.

This module defines the ErrorTranslator protocol for converting infrastructure-specific
exceptions to domain exceptions while preserving context and semantics.
"""

from abc import abstractmethod
from typing import Any, Protocol

from foundry_agent_core.exceptions import DomainError


class ErrorTranslator(Protocol):
    """Protocol for translating infrastructure errors to domain exceptions.

    Implementations convert provider-specific errors (database, network, etc.)
    into appropriate domain exceptions while preserving context and meaning.
    """

    @abstractmethod
    def translate_error(
        self,
        error: Exception,
        operation_context: dict[str, Any] | None = None,
    ) -> DomainError:
        """Translate an infrastructure error to appropriate domain exception.

        Args:
            error: The original infrastructure exception
            operation_context: Optional context about the failing operation

        Returns:
            Appropriate domain exception with preserved context

        Raises:
            DomainError: Always returns a domain exception, never raises
        """

    @abstractmethod
    def register_error_mapping(
        self,
        infrastructure_error_type: type[Exception],
        domain_error_type: type[DomainError],
    ) -> None:
        """Register a mapping from infrastructure to domain exception.

        Args:
            infrastructure_error_type: Infrastructure exception class to map
            domain_error_type: Domain exception class to map to

        Raises:
            ConfigurationError: If mapping registration fails
        """

    @abstractmethod
    def classify_error(self, error: Exception) -> str:
        """Classify an error as transient or permanent for retry logic.

        Args:
            error: Exception to classify

        Returns:
            Classification: "transient", "permanent", or "unknown"
        """

    @abstractmethod
    def preserve_error_context(
        self,
        original_error: Exception,
        additional_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract and preserve error context for debugging.

        Args:
            original_error: Original exception with context
            additional_context: Additional context to include

        Returns:
            Dictionary with preserved error context
        """

    @abstractmethod
    def should_retry(self, error: Exception) -> tuple[bool, float]:
        """Determine if an error warrants retry and suggest delay.

        Args:
            error: Exception to analyze for retry eligibility

        Returns:
            Tuple of (should_retry, suggested_delay_seconds)
        """
