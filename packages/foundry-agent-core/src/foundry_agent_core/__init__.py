# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""foundry-agent-core — Framework-agnostic agent infrastructure.

DI container, protocol definitions, exception hierarchy, lifecycle primitives,
and the AgentBackend protocol. Zero coupling to any agent framework.
"""

from foundry_agent_core.container import FunctionalDependencyContainer, create_dependency_container
from foundry_agent_core.exceptions import (
    AgentCreationError,
    AgentError,
    ConfigurationError,
    DomainError,
    ExternalServiceError,
    InvalidConfigurationError,
    QueryProcessingError,
    QueryTimeoutError,
    ResourceNotFoundError,
    ToolExecutionError,
    ToolLoadingError,
    ToolRegistrationError,
    ValidationError,
)
from foundry_agent_core.masking import mask_session_id, redact_session_ids
from foundry_agent_core.protocols import (
    AgentBackend,
    DependencyContainer,
    ErrorTranslator,
    QueryProcessor,
    ResponseProcessor,
    SessionDestruction,
)
from foundry_agent_core.types import AgentRequest, AgentResponse

__all__ = [
    # Core types
    "AgentRequest",
    "AgentResponse",
    # Protocols
    "AgentBackend",
    "DependencyContainer",
    "ErrorTranslator",
    "QueryProcessor",
    "ResponseProcessor",
    "SessionDestruction",
    # DI Container
    "FunctionalDependencyContainer",
    "create_dependency_container",
    # Exceptions
    "DomainError",
    "ExternalServiceError",
    "ResourceNotFoundError",
    "ToolExecutionError",
    "ConfigurationError",
    "InvalidConfigurationError",
    "AgentError",
    "AgentCreationError",
    "ToolRegistrationError",
    "ToolLoadingError",
    "QueryProcessingError",
    "ValidationError",
    "QueryTimeoutError",
    # Utilities
    "mask_session_id",
    "redact_session_ids",
]
