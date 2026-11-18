# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Utility functions for authentication flows."""

import base64
import hashlib
import secrets
import urllib.parse


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge pair.

    Returns:
        Tuple of (verifier, challenge) for OAuth PKCE flow
    """
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def sanitize_redirect_path(p: str | None) -> str:
    """Only allow relative paths to avoid open-redirects.

    Args:
        p: Path to sanitize

    Returns:
        Sanitized relative path starting with /
    """
    if not p:
        return "/"
    # Reject control characters outright rather than relying on urlsplit's
    # internal whitespace-stripping, which only affects scheme/netloc
    # detection and does not remove them from the returned path.
    if any(c in p for c in ("\r", "\n", "\x00")):
        return "/"
    # Browsers fold backslashes in URLs into forward slashes, so /\evil.com is
    # //evil.com in disguise; normalize first so the netloc check below sees it.
    p = p.replace("\\", "/")
    # Disallow absolute URLs, javascript:, and protocol-relative URLs
    stripped = p.lstrip("/")
    for candidate in (p, stripped):
        parsed = urllib.parse.urlsplit(candidate)
        if parsed.scheme or parsed.netloc:
            return "/"
    return "/" + stripped


def redact_sid(sid: str | None) -> str:
    """Redact a session ID for safe logging.

    Args:
        sid: Session ID to redact (may be None)

    Returns:
        Redacted form, e.g. "AbCdEfGh..." for a real sid
    """
    if not sid:
        return "<none>"
    if len(sid) <= 8:
        return "********"
    return f"{sid[:8]}..."
