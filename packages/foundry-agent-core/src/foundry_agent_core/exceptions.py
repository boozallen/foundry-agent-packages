# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Domain-specific exception hierarchy for agent query processing.

This module defines a focused exception hierarchy for agent-based query processing,
following Python exception best practices with clear error messages and
context information for debugging and user feedback.

Note: This project focuses on agent orchestration and infrastructure support.
Agent tool selection and execution remain autonomous within Strands framework.
"""

import warnings
from typing import Any


class DomainError(Exception):
    """Base exception for all domain-related errors.

    This is the root of the domain exception hierarchy. All domain-specific
    exceptions should inherit from this class to enable clean error handling
    at the application boundaries.
    """

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        """Initialize domain error with message and optional context.

        Args:
            message: Human-readable error description
            context: Optional dictionary with error context for debugging
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        """Return formatted error message with context if available."""
        if self.context:
            context_str = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{self.message} (context: {context_str})"
        return self.message


# External Service Integration Exceptions
class ExternalServiceError(DomainError):
    """Base exception for external service integration operations.

    Raised when external API or service operations fail, including connection
    issues, authentication failures, or service unavailability.
    """

    pass


class ResourceNotFoundError(ExternalServiceError):
    """Raised when requested resources cannot be found in external services.

    This typically occurs when trying to retrieve resources by ID that
    either don't exist or are inaccessible.
    """

    def __init__(self, resource_ids: list[str], *, context: dict[str, Any] | None = None) -> None:
        """Initialize with missing resource IDs.

        Args:
            resource_ids: List of resource IDs that were not found
            context: Optional error context
        """
        ids_str = ", ".join(resource_ids)
        message = f"Resources not found: {ids_str}"
        super().__init__(message, context=context)
        self.resource_ids = resource_ids


class ToolExecutionError(DomainError):
    """Raised when agent tool execution operations fail.

    This can occur due to malformed tool parameters, execution timeouts,
    or internal tool errors during autonomous agent execution.
    """

    pass


# Configuration Exceptions
class ConfigurationError(DomainError):
    """Base exception for configuration-related errors.

    Raised when application configuration is missing, invalid, or cannot
    be loaded from the configured sources.
    """

    pass


class InvalidConfigurationError(ConfigurationError):
    """Raised when configuration values are present but invalid.

    This occurs when configuration values fail validation rules,
    such as invalid URLs, out-of-range numbers, or malformed data.
    """

    def __init__(
        self,
        config_key: str,
        config_value: Any,
        reason: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize with invalid configuration details.

        Args:
            config_key: The configuration key that is invalid
            config_value: The invalid value that was provided
            reason: Explanation of why the value is invalid
            context: Optional error context
        """
        message = f"Invalid configuration '{config_key}': {reason} (got: {config_value!r})"
        super().__init__(message, context=context)
        self.config_key = config_key
        self.config_value = config_value
        self.reason = reason


# Agent and Tool Exceptions
class AgentError(DomainError):
    """Base exception for Strands Agent operations.

    Raised when agent creation, configuration, or execution fails.
    """

    pass


class AgentCreationError(AgentError):
    """Raised when creating or configuring Strands Agent instances fails.

    This can occur due to invalid model configuration, missing tools,
    or framework initialization problems.
    """

    pass


class ToolRegistrationError(AgentError):
    """Raised when registering tools with the agent system fails.

    This typically occurs when tool functions don't meet the required
    interface or when tool metadata is invalid.
    """

    def __init__(self, tool_name: str, reason: str, *, context: dict[str, Any] | None = None) -> None:
        """Initialize with tool registration failure details.

        Args:
            tool_name: Name of the tool that failed to register
            reason: Explanation of the registration failure
            context: Optional error context
        """
        message = f"Failed to register tool '{tool_name}': {reason}"
        super().__init__(message, context=context)
        self.tool_name = tool_name
        self.reason = reason


class ToolLoadingError(AgentError):
    """Raised when loading tools from directory fails.

    This occurs when tool discovery fails, tool files are malformed,
    or there are import/syntax errors in tool definitions.
    """

    pass


# Query Processing Exceptions
class QueryProcessingError(DomainError):
    """Base exception for agent query processing failures.

    This is the main exception for end-to-end query processing issues
    that don't fall into more specific categories.
    """

    pass


class ValidationError(DomainError):
    """Raised when input validation fails for domain objects.

    This occurs when user input or data doesn't meet the validation
    rules defined in domain value objects.
    """

    def __init__(
        self,
        field_name: str,
        field_value: Any,
        validation_rule: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize with validation failure details.

        Args:
            field_name: Name of the field that failed validation
            field_value: The value that failed validation
            validation_rule: Description of the validation rule that failed
            context: Optional error context
        """
        message = f"Validation failed for '{field_name}': {validation_rule} (got: {field_value!r})"
        super().__init__(message, context=context)
        self.field_name = field_name
        self.field_value = field_value
        self.validation_rule = validation_rule


class QueryTimeoutError(QueryProcessingError):
    """Raised when query processing exceeds the allowed time limit.

    This occurs when agent query processing takes longer than the configured
    timeout threshold, helping maintain system responsiveness.
    """

    def __init__(self, timeout_ms: float, *, context: dict[str, Any] | None = None) -> None:
        """Initialize with timeout details.

        Args:
            timeout_ms: The timeout threshold that was exceeded (in milliseconds)
            context: Optional error context
        """
        message = f"Query processing timed out after {timeout_ms}ms"
        super().__init__(message, context=context)
        self.timeout_ms = timeout_ms


# Deprecated aliases for backward compatibility
# These will be removed in a future version
_DEPRECATED_ALIASES: dict[str, tuple[type, str]] = {
    "MissingConfigurationError": (
        ConfigurationError,
        "MissingConfigurationError is deprecated, use ConfigurationError with context['key'] instead",
    ),
    "MCPConnectionError": (
        ExternalServiceError,
        "MCPConnectionError is deprecated, use ExternalServiceError with context['service_type']='mcp' instead",
    ),
}


def __getattr__(name: str) -> type:
    """Emit deprecation warnings for deprecated exception aliases."""
    if name in _DEPRECATED_ALIASES:
        replacement, message = _DEPRECATED_ALIASES[name]
        warnings.warn(message, DeprecationWarning, stacklevel=2)
        return replacement
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
