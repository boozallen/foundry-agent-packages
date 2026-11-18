# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Shared session-identifier masking for request path/query logging.

Used by both the request-logging and error-handling middleware, so a raw
session identifier can't leak through one of them while the other masks it.
"""

from foundry_agent_core import mask_session_id

# Path segments that mark the *next* segment as a session identifier
# (e.g. /sessions/{session_id}/history).
_SESSION_PATH_MARKERS = frozenset({"session", "sessions"})

# Query parameter keys known to carry a session identifier.
_SESSION_ID_QUERY_KEYS = frozenset({"session_id"})


def mask_path(path: str) -> str:
    """Mask the path segment immediately following a session marker segment.

    Masks any non-empty segment after a "session"/"sessions" marker,
    regardless of its shape. Once a segment is positionally known to be the
    identifier, an additional shape requirement only creates a way for a
    real identifier that's short, long, or contains an unexpected character
    to be logged raw instead of masked.
    """
    segments = path.split("/")
    masked_segments = []
    mask_next = False
    for segment in segments:
        if mask_next and segment:
            masked_segments.append(mask_session_id(segment))
        else:
            masked_segments.append(segment)
        mask_next = segment.lower() in _SESSION_PATH_MARKERS
    return "/".join(masked_segments)


def mask_query_params(query_params: dict[str, str]) -> dict[str, str]:
    """Mask the value of any known session-identifier query parameter."""
    return {
        key: (mask_session_id(value) if key in _SESSION_ID_QUERY_KEYS else value) for key, value in query_params.items()
    }
