# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Framework-agnostic type definitions for agent request/response processing."""

import json
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, field_serializer, field_validator

from foundry_agent_core.masking import mask_session_id

# Field bounds (STIG V-222612 / CCI-002824). See
# openspec/changes/foundry-586-add-pydantic-size-constraints/design.md D1
# for rationale; values are exported as module-private constants so tests and
# adapters can reference the canonical limits.
_MAX_QUERY_LEN = 8192  # 8 KiB
_MAX_CONTENT_LEN = 131072  # 128 KiB
_MAX_SESSION_ID_LEN = 128
_MAX_DICT_KEYS = 32
_MAX_DICT_KEY_LEN = 128
_MAX_DICT_BYTES = 16384  # 16 KiB
_MAX_PROCESSING_TIME_MS = 86_400_000  # 24h


_BoundedQuery = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_QUERY_LEN, strip_whitespace=True)]
_BoundedContent = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_CONTENT_LEN, strip_whitespace=True)]
_BoundedSessionId = Annotated[
    str,
    StringConstraints(min_length=8, max_length=_MAX_SESSION_ID_LEN, pattern=r"^[A-Za-z0-9_-]+$", strip_whitespace=True),
]


def _validate_bounded_dict(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if len(value) > _MAX_DICT_KEYS:
        raise ValueError(f"dict exceeds {_MAX_DICT_KEYS} top-level keys")
    for key in value:
        if len(key) > _MAX_DICT_KEY_LEN:
            raise ValueError(f"dict key exceeds {_MAX_DICT_KEY_LEN} characters")
    if len(json.dumps(value, default=str)) > _MAX_DICT_BYTES:
        raise ValueError(f"dict serializes above {_MAX_DICT_BYTES} bytes")
    return value


class AgentRequest(BaseModel):
    """Framework-agnostic agent request for the AgentBackend protocol surface.

    Lean request type without RAG-specific fields. Used at the protocol boundary;
    framework adapters map this to their internal request types.
    """

    model_config = {"frozen": True}

    query: _BoundedQuery
    session_id: _BoundedSessionId | None = None
    context: dict[str, Any] | None = None

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

    @field_validator("context", mode="after")
    @classmethod
    def _validate_context_bounds(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_bounded_dict(v)


class AgentResponse(BaseModel):
    """Framework-agnostic agent response for the AgentBackend protocol surface.

    Lean response type without RAG-specific fields. Used at the protocol boundary;
    framework adapters map their internal response types to this.
    """

    model_config = {"frozen": True}

    content: _BoundedContent
    session_id: _BoundedSessionId | None = None
    processing_time_ms: float = Field(ge=0, le=_MAX_PROCESSING_TIME_MS)
    metadata: dict[str, Any] | None = None

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

    @field_validator("metadata", mode="after")
    @classmethod
    def _validate_metadata_bounds(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_bounded_dict(v)


# Type aliases for common patterns
ContentId = str
ChunkId = str
RelevanceScore = float
ConfidenceScore = float
