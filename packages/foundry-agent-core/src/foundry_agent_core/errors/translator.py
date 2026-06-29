# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Error translation from infrastructure to domain exceptions.

This module implements the ErrorTranslator protocol for converting
infrastructure-specific exceptions into appropriate domain exceptions.

Usage:
    translator = create_error_translator()
    domain_error = translator.translate_error(infra_error)

Retry Logic:
    should_retry, delay = translator.should_retry(error)
    if should_retry:
        await asyncio.sleep(delay)

Custom Mappings:
    translator.register_error_mapping(MyInfraError, MyDomainError)
"""

import re
import time
from typing import Any

from foundry_agent_core.exceptions import (
    ConfigurationError,
    DomainError,
    ExternalServiceError,
    QueryProcessingError,
    QueryTimeoutError,
    ToolLoadingError,
)
from foundry_agent_core.protocols import ErrorTranslator


class InfrastructureErrorTranslator(ErrorTranslator):
    """Implementation of ErrorTranslator for converting infrastructure exceptions.

    This translator maps infrastructure-specific errors to appropriate domain exceptions
    while preserving context, supporting custom mappings, and providing retry logic.
    """

    def __init__(self) -> None:
        """Initialize error translator with default mappings."""
        self._error_mappings: dict[type[Exception], type[DomainError]] = {}
        self._transient_patterns: list[str] = []
        self._permanent_patterns: list[str] = []

        # Set up default mappings
        self._setup_default_mappings()
        self._setup_default_patterns()

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
        context = self.preserve_error_context(error, operation_context)

        # Try direct type mappings
        error_type = type(error)
        if error_type in self._error_mappings:
            domain_error_type = self._error_mappings[error_type]
            return self._create_domain_error(domain_error_type, error, context)

        # Check parent classes for inheritance-based mapping
        for base_type in error_type.__mro__[1:]:  # Skip the error type itself
            if base_type in self._error_mappings:
                domain_error_type = self._error_mappings[base_type]
                return self._create_domain_error(domain_error_type, error, context)

        # Default fallback - classify by common patterns
        domain_error_type = self._classify_unknown_error(error)
        return self._create_domain_error(domain_error_type, error, context)

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
        try:
            self._error_mappings[infrastructure_error_type] = domain_error_type

        except Exception as e:
            raise ConfigurationError(
                f"Failed to register error mapping: {e}",
                context={
                    "infrastructure_type": infrastructure_error_type.__name__,
                    "domain_type": domain_error_type.__name__,
                    "error": str(e),
                },
            ) from e

    def classify_error(self, error: Exception) -> str:
        """Classify an error as transient or permanent for retry logic.

        Args:
            error: Exception to classify

        Returns:
            Classification: "transient", "permanent", or "unknown"
        """
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()

        # Check for transient patterns
        for pattern in self._transient_patterns:
            if re.search(pattern, error_str) or re.search(pattern, error_type):
                return "transient"

        # Check for permanent patterns
        for pattern in self._permanent_patterns:
            if re.search(pattern, error_str) or re.search(pattern, error_type):
                return "permanent"

        # Special cases based on error types
        if isinstance(error, ConnectionError | TimeoutError):
            return "transient"

        if isinstance(error, ValueError | TypeError | AttributeError):
            return "permanent"

        # Default to unknown
        return "unknown"

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
        context: dict[str, Any] = {
            "original_error_type": type(original_error).__name__,
            "original_error_message": str(original_error),
            "timestamp": time.time(),
        }

        # Add exception-specific context
        if hasattr(original_error, "__dict__"):
            error_attrs = {
                k: v for k, v in original_error.__dict__.items() if not k.startswith("_") and not callable(v)
            }
            if error_attrs:
                context["error_attributes"] = error_attrs

        # Add traceback info if available
        if hasattr(original_error, "__traceback__") and original_error.__traceback__:
            tb = original_error.__traceback__
            context["traceback_info"] = {
                "filename": tb.tb_frame.f_code.co_filename,
                "line_number": tb.tb_lineno,
                "function_name": tb.tb_frame.f_code.co_name,
            }

        # Add additional context
        if additional_context:
            context.update(additional_context)

        return context

    def should_retry(self, error: Exception) -> tuple[bool, float]:
        """Determine if an error warrants retry and suggest delay.

        Args:
            error: Exception to analyze for retry eligibility

        Returns:
            Tuple of (should_retry, suggested_delay_seconds)
        """
        classification = self.classify_error(error)

        if classification == "permanent":
            return False, 0.0

        if classification == "transient":
            # Base delay on error type
            if isinstance(error, TimeoutError):
                return True, 2.0
            elif isinstance(error, ConnectionError):
                return True, 1.0
            else:
                return True, 0.5

        # Unknown classification - conservative retry with longer delay
        return True, 5.0

    def _setup_default_mappings(self) -> None:
        """Set up default error mappings for common infrastructure exceptions."""
        # Network/Connection errors
        self._error_mappings[ConnectionError] = ExternalServiceError
        self._error_mappings[TimeoutError] = QueryTimeoutError

        # Configuration errors
        self._error_mappings[KeyError] = ConfigurationError
        self._error_mappings[ValueError] = ConfigurationError

        # Import/module errors
        self._error_mappings[ImportError] = ToolLoadingError
        self._error_mappings[ModuleNotFoundError] = ToolLoadingError

    def _setup_default_patterns(self) -> None:
        """Set up default patterns for error classification."""
        # Transient error patterns
        self._transient_patterns.extend(
            [
                r"timeout",
                r"connection.*reset",
                r"connection.*refused",
                r"temporarily unavailable",
                r"service unavailable",
                r"rate limit",
                r"too many requests",
                r"network.*error",
                r"temporary failure",
            ]
        )

        # Permanent error patterns
        self._permanent_patterns.extend(
            [
                r"not found",
                r"invalid.*syntax",
                r"permission denied",
                r"unauthorized",
                r"forbidden",
                r"invalid.*argument",
                r"validation.*error",
                r"schema.*error",
                r"type.*error",
                r"attribute.*error",
            ]
        )

    def _classify_unknown_error(self, error: Exception) -> type[DomainError]:
        """Fallback classification for unmapped errors.

        Returns QueryProcessingError as the default for unmapped exceptions.
        Teams can use register_error_mapping() for custom mappings.
        """
        return QueryProcessingError

    def _create_domain_error(
        self,
        domain_error_type: type[DomainError],
        original_error: Exception,
        context: dict[str, Any],
    ) -> DomainError:
        """Create a domain error instance with proper message and context."""
        # Create meaningful error message
        original_message = str(original_error)
        domain_message = f"Infrastructure error translated to domain: {original_message}"

        # Create the domain error with context
        return domain_error_type(domain_message, context=context)


def create_error_translator() -> ErrorTranslator:
    """Factory function to create a new error translator instance.

    Returns:
        New ErrorTranslator instance ready for error translation
    """
    return InfrastructureErrorTranslator()
