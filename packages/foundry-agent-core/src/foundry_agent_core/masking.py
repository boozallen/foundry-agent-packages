# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Session-ID masking for log and serialization boundaries.

STIG V-222577 (CCI-001184, SRG-APP-000219) requires that the application not
expose session IDs. Raw ``session_id`` values must never reach a log record or
serialized model output. :func:`mask_session_id` produces a deterministic,
non-reversible token so that emissions can still correlate a session across log
lines without disclosing the identifier.

The mask is ``sha256(salt + session_id)`` rendered as a short hex prefix, using
a fixed built-in salt so it works with no configuration.
"""

import hashlib
import re

# Length of the hex digest prefix used in the masked token. 12 hex chars
# (48 bits) is ample to keep distinct sessions distinguishable in logs while
# keeping the token short.
_DIGEST_PREFIX_LEN = 12

# Token prefix so masked values are recognizable in logs and never mistaken
# for a raw identifier.
_MASK_PREFIX = "sid"

# Placeholder emitted when there is no session identifier to mask.
_NONE_PLACEHOLDER = f"{_MASK_PREFIX}:<none>"

# Fixed built-in salt mixed into the session-ID hash. Keeping it non-empty
# ensures the hash is always salted; it requires no configuration.
_SALT = b"foundry-agent-core:v-222577:session-id-salt"


def mask_session_id(value: str | None) -> str:
    """Mask a session ID for safe emission to logs or serialized output.

    Returns a deterministic, non-reversible token of the form ``sid:<hex>``.
    The same input yields the same token within a process; the raw identifier
    cannot be recovered from the token. ``None`` or empty/whitespace-only input
    returns a stable placeholder rather than raising.

    Args:
        value: The raw session identifier, or ``None``.

    Returns:
        A masked token safe to log or serialize.
    """
    if value is None or not value.strip():
        return _NONE_PLACEHOLDER
    digest = hashlib.sha256(_SALT + value.encode("utf-8")).hexdigest()
    return f"{_MASK_PREFIX}:{digest[:_DIGEST_PREFIX_LEN]}"


# Matches a "session_id" key and its string value inside a serialized blob
# (JSON or Python repr), capturing the raw value so it can be replaced with a
# masked token. Handles both ``"session_id": "abc"`` and ``'session_id': 'abc'``.
_SESSION_ID_IN_BLOB = re.compile(r"""(['"]session_id['"]\s*:\s*)(['"])(.*?)\2""")


def redact_session_ids(blob: str) -> str:
    """Mask any ``session_id`` values embedded in a serialized string blob.

    Used when a log emission would otherwise include raw session metadata (a
    JSON string or dict repr) that carries a ``session_id`` field. Each matched
    value is replaced with its :func:`mask_session_id` token.

    Args:
        blob: A serialized representation (JSON text or ``repr``) that may
            contain one or more ``session_id`` fields.

    Returns:
        The blob with every embedded ``session_id`` value masked.
    """

    def _replace(match: re.Match[str]) -> str:
        prefix, quote, raw = match.group(1), match.group(2), match.group(3)
        return f"{prefix}{quote}{mask_session_id(raw)}{quote}"

    return _SESSION_ID_IN_BLOB.sub(_replace, blob)
