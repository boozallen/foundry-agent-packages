# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""HTTP-specific response models for the FastAPI interface.

Lean API response models without RAG-specific fields. RAG fields (sources,
chunks_used, confidence_score) stay in the Strands adapter layer.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

_MAX_CONTENT_LEN = 131072
_MAX_SESSION_ID_LEN = 128
_MAX_PROCESSING_TIME_MS = 86_400_000  # 24h
_MAX_ERROR_CODE_LEN = 64
_MAX_MESSAGE_LEN = 4096
_MAX_CORRELATION_ID_LEN = 128
_MAX_API_VERSION_LEN = 16


class QueryAPIResponse(BaseModel):
    """HTTP API response for agent query results.

    Lean response matching AgentResponse fields — no RAG-specific types.
    """

    content: str = Field(
        ...,
        description="Agent-generated response content",
        min_length=1,
        max_length=_MAX_CONTENT_LEN,
    )

    session_id: str | None = Field(
        default=None,
        description="Chat session identifier",
        min_length=3,
        max_length=_MAX_SESSION_ID_LEN,
    )

    processing_time_ms: float = Field(
        ...,
        ge=0.0,
        le=_MAX_PROCESSING_TIME_MS,
        description="Total query processing time in milliseconds",
    )

    timestamp: datetime = Field(
        ...,
        description="Response generation timestamp in ISO 8601 format",
    )

    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Additional response metadata",
    )

    correlation_id: str | None = Field(
        default=None,
        description="Request correlation ID for distributed tracing",
        min_length=1,
        max_length=_MAX_CORRELATION_ID_LEN,
    )

    api_version: str = Field(
        default="1.0",
        description="API version for response format tracking",
        min_length=1,
        max_length=_MAX_API_VERSION_LEN,
    )


class ErrorResponse(BaseModel):
    """Standardized API error response."""

    error: str = Field(
        ...,
        description="Error type or category",
        min_length=1,
        max_length=_MAX_ERROR_CODE_LEN,
    )

    message: str = Field(
        ...,
        description="Human-readable error description",
        min_length=1,
        max_length=_MAX_MESSAGE_LEN,
    )

    details: dict[str, Any] | None = Field(
        default=None,
        description="Additional error details for debugging",
    )

    correlation_id: str | None = Field(
        default=None,
        description="Request correlation ID for tracing",
        min_length=1,
        max_length=_MAX_CORRELATION_ID_LEN,
    )

    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Error timestamp",
    )
