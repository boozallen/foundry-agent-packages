# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""HTTP-specific request models for the FastAPI interface.

Implements API request models with HTTP-specific validation concerns,
OpenAPI documentation, and clean separation from domain models.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_MAX_SESSION_ID_LEN = 128
_MAX_QUERY_LEN = 8192
_MAX_CONTEXT_KEYS = 32
_MAX_CONTEXT_KEY_LEN = 128
_MAX_CONTEXT_BYTES = 16384


class QueryAPIRequest(BaseModel):
    """HTTP API request model for agent query processing.

    Handles HTTP-specific validation, serialization, and OpenAPI documentation
    for query requests. This model is independent of domain models and focuses
    on API layer concerns like Content-Type validation and HTTP semantics.
    """

    model_config = ConfigDict(
        extra="ignore",
        use_enum_values=True,
        json_schema_extra={
            "examples": [
                {
                    "query": "What are the main features of this system?",
                    "context": {"user_id": "12345", "source": "web"},
                    "max_results": 10,
                    "similarity_threshold": 0.8,
                }
            ]
        },
    )

    session_id: str | None = Field(
        default=None,
        description="Unique identifier for the chat session",
        min_length=8,
        max_length=_MAX_SESSION_ID_LEN,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    query: str = Field(
        ...,
        description="The user's question or query to be processed by the agent",
        min_length=1,
        max_length=_MAX_QUERY_LEN,
        examples=[
            "What are the key features of this project?",
            "How do I configure the agent settings?",
            "Explain the architecture of the system",
        ],
    )

    context: dict[str, Any] | None = Field(
        default=None,
        description="Optional context information to help with query processing",
        examples=[
            {"source": "web", "user_id": "12345"},
            {"session_id": "abc-123", "previous_queries": ["hello", "help"]},
        ],
    )

    max_results: int = Field(
        default=10,
        description="Maximum number of results to return",
        ge=1,
        le=100,
        examples=[5, 10, 25],
    )

    similarity_threshold: float = Field(
        default=0.7,
        description="Minimum similarity threshold for results (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
        examples=[0.5, 0.7, 0.9],
    )

    @field_validator("session_id", mode="before")
    @classmethod
    def strip_session_id(cls, v: str | None) -> str | None:
        """Strip whitespace from session_id to match core/strands behavior.

        Args:
            v: Session ID string to strip

        Returns:
            Stripped session ID or None
        """
        if v is None:
            return None
        return v.strip() if isinstance(v, str) else v

    @field_validator("query")
    @classmethod
    def validate_query_not_empty(cls, v: str) -> str:
        """Ensure query is not empty or just whitespace.

        Args:
            v: Query string to validate

        Returns:
            Stripped query string

        Raises:
            ValueError: If query is empty or only whitespace
        """
        if not v or not v.strip():
            raise ValueError("Query cannot be empty or whitespace only")
        return v.strip()

    @field_validator("context", mode="before")
    @classmethod
    def validate_context_serializable(cls, v: Any) -> dict[str, Any] | None:
        """Ensure context is JSON-serializable for HTTP transport.

        Args:
            v: Context value to validate

        Returns:
            Validated context dictionary or None

        Raises:
            ValueError: If context is not JSON-serializable
        """
        if v is None:
            return None

        if not isinstance(v, dict):
            raise ValueError("Context must be a dictionary")

        # Validate that all keys are strings (required for JSON)
        for key in v.keys():
            if not isinstance(key, str):
                raise ValueError("All context keys must be strings")
            if len(key) > _MAX_CONTEXT_KEY_LEN:
                raise ValueError(f"Context key exceeds {_MAX_CONTEXT_KEY_LEN} characters")

        if len(v) > _MAX_CONTEXT_KEYS:
            raise ValueError(f"Context exceeds {_MAX_CONTEXT_KEYS} top-level keys")

        serialized_size = len(json.dumps(v, default=str))
        if serialized_size > _MAX_CONTEXT_BYTES:
            raise ValueError(f"Context serializes above {_MAX_CONTEXT_BYTES} bytes")

        return v
