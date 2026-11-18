# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Framework-agnostic type definitions for agent request/response processing."""

import json
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, field_serializer, field_validator

from foundry_agent_core.masking import mask_session_id

# Field bounds (STIG V-222612 / CCI-002824): every request and response field has a
# size limit, so oversized values fail Pydantic validation.
# _MAX_QUERY_LEN/_MAX_DICT_BYTES were later raised to
# accommodate frontier model context windows. These constants are re-exported from
# foundry_agent_core's package root (see __init__.py's __all__) rather than only
# module-private: downstream packages import from there instead of re-declaring their
# own literals, so raising a bound here takes effect at every layer that checks it.
_MAX_QUERY_LEN = 2_097_152  # 2 MiB (~524K tokens at ~4:1 char:token ratio)
_MAX_CONTENT_LEN = 524_288  # 4 * max_tokens ceiling (131,072) at ~4:1 char:token ratio
_MAX_SESSION_ID_LEN = 128
_MAX_DICT_KEYS = 32
_MAX_DICT_KEY_LEN = 128
_MAX_DICT_BYTES = 4_194_304  # 4 MiB
_MAX_PROCESSING_TIME_MS = 86_400_000  # 24h
_MAX_RESULTS = 100  # canonical ceiling for result-count fields (e.g. RAG max_results)


_BoundedQuery = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_QUERY_LEN, strip_whitespace=True)]
_BoundedContent = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_CONTENT_LEN, strip_whitespace=True)]
_BoundedSessionId = Annotated[
    str,
    StringConstraints(min_length=8, max_length=_MAX_SESSION_ID_LEN, pattern=r"^[A-Za-z0-9_-]+$", strip_whitespace=True),
]


def _json_utf8_size(value: Any) -> int:
    r"""Return the UTF-8 byte size of ``value``'s JSON form, as the byte caps measure it.

    Encodes the ``ensure_ascii=False`` JSON form, so non-ASCII text counts its real bytes
    rather than ``\uXXXX`` escapes. ``default=str`` stringifies values JSON can't encode, and
    ``surrogatepass`` sizes a lone surrogate (which JSON input can carry) instead of failing.
    """
    return len(json.dumps(value, default=str, ensure_ascii=False).encode("utf-8", "surrogatepass"))


def validate_bounded_dict(
    value: object,
    *,
    max_keys: int = _MAX_DICT_KEYS,
    max_key_len: int = _MAX_DICT_KEY_LEN,
    max_bytes: int = _MAX_DICT_BYTES,
    label: str = "dict",
) -> dict[str, Any] | None:
    """Bound a dict's top-level key count, key length, and UTF-8 JSON size (STIG V-222612).

    The size is measured with :func:`_json_utf8_size`.

    Raises:
        ValueError: If ``value`` isn't a dict, a key isn't a string, the dict isn't
            JSON-serializable, or a bound is exceeded. Messages start with ``label``.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a dictionary")
    if len(value) > max_keys:
        raise ValueError(f"{label} exceeds {max_keys} top-level keys")
    for key in value:
        if not isinstance(key, str):
            raise ValueError(f"{label} keys must be strings")
        if len(key) > max_key_len:
            raise ValueError(f"{label} key exceeds {max_key_len} characters")
    try:
        size = _json_utf8_size(value)
    except (TypeError, ValueError, RecursionError) as e:
        raise ValueError(f"{label} is not JSON-serializable") from e
    if size > max_bytes:
        raise ValueError(f"{label} serializes above {max_bytes} bytes")
    return value


# Private name kept as an alias for existing importers; use validate_bounded_dict.
_validate_bounded_dict = validate_bounded_dict


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
        return validate_bounded_dict(v)


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
        return validate_bounded_dict(v)


# Type aliases for common patterns
ContentId = str
ChunkId = str
RelevanceScore = float
ConfidenceScore = float
