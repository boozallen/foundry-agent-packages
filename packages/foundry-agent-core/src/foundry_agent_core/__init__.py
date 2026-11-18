# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""foundry-agent-core — Framework-agnostic agent infrastructure.

DI container, protocol definitions, exception hierarchy, lifecycle primitives,
and the AgentBackend protocol. Zero coupling to any agent framework.
"""

from foundry_agent_core.container import FunctionalDependencyContainer, create_dependency_container
from foundry_agent_core.encryption import decrypt, encrypt, is_encrypted, load_encryption_key
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
from foundry_agent_core.types import (
    _MAX_CONTENT_LEN,
    _MAX_DICT_BYTES,
    _MAX_DICT_KEY_LEN,
    _MAX_DICT_KEYS,
    _MAX_QUERY_LEN,
    _MAX_RESULTS,
    AgentRequest,
    AgentResponse,
    validate_bounded_dict,
)

__all__ = [
    # Core types
    "AgentRequest",
    "AgentResponse",
    # Bound validator (STIG V-222612 / CCI-002824)
    "validate_bounded_dict",
    # Bound constants (STIG V-222612 / CCI-002824) — canonical source
    "_MAX_CONTENT_LEN",
    "_MAX_DICT_BYTES",
    "_MAX_DICT_KEY_LEN",
    "_MAX_DICT_KEYS",
    "_MAX_QUERY_LEN",
    "_MAX_RESULTS",
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
    # Encryption
    "encrypt",
    "decrypt",
    "load_encryption_key",
    "is_encrypted",
]
