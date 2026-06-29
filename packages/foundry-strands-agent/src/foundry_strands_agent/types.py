# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Core domain value objects and type definitions for agent query processing.

Strands-specific types (QueryRequest, SearchResult, DocumentChunk, QueryResponse).
Framework-agnostic types (AgentRequest, AgentResponse) live in foundry-agent-core.
"""

import json
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, field_serializer, field_validator

from foundry_agent_core import mask_session_id

_MAX_QUERY_LEN = 8192
_MAX_SESSION_ID_LEN = 128
_MAX_RESULTS = 100
_MAX_DOC_ID_LEN = 256
_MAX_CHUNK_ID_LEN = 128
_MAX_CONTENT_PREVIEW_LEN = 4096
_MAX_CHUNK_CONTENT_LEN = 131072
_MAX_RESPONSE_TEXT_LEN = 131072
_MAX_SOURCES = 100
_MAX_CHUNKS_USED = 100
_MAX_PROCESSING_TIME_MS = 86_400_000  # 24h
_MAX_CONTEXT_KEYS = 32
_MAX_CONTEXT_KEY_LEN = 128
_MAX_CONTEXT_BYTES = 16384
_MAX_METADATA_KEYS = 64
_MAX_METADATA_KEY_LEN = 128
_MAX_METADATA_BYTES = 32768


_BoundedQuery = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_QUERY_LEN)]
_BoundedSessionId = Annotated[
    str,
    StringConstraints(min_length=8, max_length=_MAX_SESSION_ID_LEN, pattern=r"^[A-Za-z0-9_-]+$", strip_whitespace=True),
]
_BoundedDocumentId = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_DOC_ID_LEN, strip_whitespace=True)]
_BoundedChunkId = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_CHUNK_ID_LEN, strip_whitespace=True)]
_BoundedContentPreview = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_CONTENT_PREVIEW_LEN)]
_BoundedChunkContent = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_CHUNK_CONTENT_LEN)]
_BoundedResponseText = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_RESPONSE_TEXT_LEN)]


def _validate_bounded_map(
    value: dict[str, Any] | None, *, max_keys: int, max_key_len: int, max_bytes: int
) -> dict[str, Any] | None:
    if value is None:
        return None
    if len(value) > max_keys:
        raise ValueError(f"dictionary exceeds {max_keys} top-level keys")
    for key in value:
        if len(key) > max_key_len:
            raise ValueError(f"dictionary key exceeds {max_key_len} characters")
    serialized_size = len(json.dumps(value, default=str))
    if serialized_size > max_bytes:
        raise ValueError(f"dictionary serializes above {max_bytes} bytes")
    return value


class QueryRequest(BaseModel):
    """Represents a user's query that the agent will process.

    This is the input to the agent system, containing the user's question
    and any additional context or parameters needed for processing.
    """

    model_config = {"frozen": True}

    session_id: _BoundedSessionId | None = None
    query: _BoundedQuery
    context: dict[str, Any] | None = None
    max_results: int = Field(default=10, ge=1, le=_MAX_RESULTS)
    similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=datetime.now)

    @field_serializer("session_id")
    def _redact_session_id(self, v: str | None) -> str | None:
        """Mask the session ID on serialization (STIG V-222577).

        Serialized output (``model_dump``/``model_dump_json``) is used for log
        emission, so the identifier is masked here. The in-memory attribute is
        unchanged and remains available for runtime session use.
        """
        if v is None:
            return None
        return mask_session_id(v)

    @field_validator("query")
    @classmethod
    def validate_query_not_empty(cls, v: str) -> str:
        """Ensure query is not empty or just whitespace."""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty or whitespace only")
        return v.strip()

    @field_validator("context", mode="after")
    @classmethod
    def validate_context_bounds(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_bounded_map(
            v,
            max_keys=_MAX_CONTEXT_KEYS,
            max_key_len=_MAX_CONTEXT_KEY_LEN,
            max_bytes=_MAX_CONTEXT_BYTES,
        )


class SearchResult(BaseModel):
    """Represents a single result from agent tool execution with content and metadata."""

    model_config = {"frozen": True}

    document_id: _BoundedDocumentId
    content_preview: _BoundedContentPreview
    similarity_score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any]

    @field_validator("document_id")
    @classmethod
    def validate_document_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("document_id cannot be empty")
        return v.strip()

    @field_validator("metadata", mode="after")
    @classmethod
    def validate_metadata_bounds(cls, v: dict[str, Any]) -> dict[str, Any]:
        bounded = _validate_bounded_map(
            v,
            max_keys=_MAX_METADATA_KEYS,
            max_key_len=_MAX_METADATA_KEY_LEN,
            max_bytes=_MAX_METADATA_BYTES,
        )
        return bounded or {}


class DocumentChunk(BaseModel):
    """Represents a piece of content with metadata and source information."""

    model_config = {"frozen": True}

    chunk_id: _BoundedChunkId
    content: _BoundedChunkContent
    metadata: dict[str, Any]
    source_document_id: _BoundedDocumentId
    chunk_index: int = Field(ge=0, le=10_000_000)
    character_start: int = Field(ge=0, le=10_000_000)
    character_end: int = Field(ge=0, le=10_000_000)

    @field_validator("chunk_id")
    @classmethod
    def validate_chunk_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("chunk_id cannot be empty")
        return v.strip()

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("content cannot be empty")
        return v

    @field_validator("metadata", mode="after")
    @classmethod
    def validate_metadata_bounds(cls, v: dict[str, Any]) -> dict[str, Any]:
        bounded = _validate_bounded_map(
            v,
            max_keys=_MAX_METADATA_KEYS,
            max_key_len=_MAX_METADATA_KEY_LEN,
            max_bytes=_MAX_METADATA_BYTES,
        )
        return bounded or {}

    @field_validator("character_end")
    @classmethod
    def validate_character_positions(cls, v: int, info: Any) -> int:
        if hasattr(info, "data") and "character_start" in info.data:
            if v <= info.data["character_start"]:
                raise ValueError("character_end must be greater than character_start")
        return v


class QueryResponse(BaseModel):
    """Represents the agent's complete answer with sources and metadata."""

    model_config = {"frozen": True}

    response_text: _BoundedResponseText
    sources: list[SearchResult] = Field(max_length=_MAX_SOURCES)
    chunks_used: list[DocumentChunk] = Field(max_length=_MAX_CHUNKS_USED)
    confidence_score: float = Field(ge=0.0, le=1.0)
    processing_time_ms: float = Field(ge=0.0, le=_MAX_PROCESSING_TIME_MS)
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] | None = None

    @field_validator("response_text")
    @classmethod
    def validate_response_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("response_text cannot be empty")
        return v

    @field_validator("metadata", mode="after")
    @classmethod
    def validate_metadata_bounds(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_bounded_map(
            v,
            max_keys=_MAX_METADATA_KEYS,
            max_key_len=_MAX_METADATA_KEY_LEN,
            max_bytes=_MAX_METADATA_BYTES,
        )


ContentId = str
ChunkId = str
RelevanceScore = float
ConfidenceScore = float
