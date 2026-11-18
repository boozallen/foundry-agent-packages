# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for utility functions."""

import urllib.parse

from foundry_auth.utils import generate_pkce_pair, redact_sid, sanitize_redirect_path


def test_generate_pkce_pair():
    """Test PKCE pair generation."""
    verifier, challenge = generate_pkce_pair()

    assert isinstance(verifier, str)
    assert isinstance(challenge, str)
    assert len(verifier) > 0
    assert len(challenge) > 0
    assert verifier != challenge


def test_generate_pkce_pair_unique():
    """Test PKCE pairs are unique."""
    v1, c1 = generate_pkce_pair()
    v2, c2 = generate_pkce_pair()

    assert v1 != v2
    assert c1 != c2


def test_sanitize_redirect_path_none():
    """Test sanitize with None returns /."""
    assert sanitize_redirect_path(None) == "/"


def test_sanitize_redirect_path_empty():
    """Test sanitize with empty string returns /."""
    assert sanitize_redirect_path("") == "/"


def test_sanitize_redirect_path_relative():
    """Test sanitize with relative path."""
    assert sanitize_redirect_path("dashboard") == "/dashboard"
    assert sanitize_redirect_path("/dashboard") == "/dashboard"


def test_sanitize_redirect_path_blocks_http():
    """Test sanitize blocks http URLs."""
    assert sanitize_redirect_path("http://evil.com") == "/"


def test_sanitize_redirect_path_blocks_https():
    """Test sanitize blocks https URLs."""
    assert sanitize_redirect_path("https://evil.com") == "/"


def test_sanitize_redirect_path_blocks_javascript():
    """Test sanitize blocks javascript: URLs."""
    assert sanitize_redirect_path("javascript:alert(1)") == "/"


def test_sanitize_redirect_path_blocks_backslash_variants():
    """Backslash forms of protocol-relative URLs sanitize to /.

    Browsers fold backslashes into forward slashes, so these are
    //evil.com in disguise.
    """
    assert sanitize_redirect_path("/\\evil.com") == "/"
    assert sanitize_redirect_path("\\/evil.com") == "/"
    # /\/ folds to ///, which parses as a netloc-less path: the result is a
    # same-origin path, not a redirect off-origin.
    assert sanitize_redirect_path("/\\/evil.com") == "/evil.com"


def test_sanitize_redirect_path_blocks_protocol_relative():
    """Test sanitize blocks protocol-relative URLs."""
    assert sanitize_redirect_path("//evil.com") == "/"
    assert sanitize_redirect_path("//evil.com/path") == "/"


def test_sanitize_redirect_path_blocks_case_variants():
    """Test sanitize blocks scheme case variants and slash-prefixed schemes."""
    assert sanitize_redirect_path("Https://evil.com") == "/"
    assert sanitize_redirect_path("HTTPS://evil.com") == "/"
    assert sanitize_redirect_path("JavaScript:alert(1)") == "/"
    assert sanitize_redirect_path("/https://evil.com") == "/"


def test_sanitize_redirect_path_blocks_control_characters():
    """Control characters must not survive into the returned path.

    Plain payloads with no scheme-like substring, so this fails if the
    control-character check is ever removed and someone mistakes an
    unrelated coincidence (e.g. a scheme-shaped test string) for coverage.
    """
    assert sanitize_redirect_path("/a\nb") == "/"
    assert sanitize_redirect_path("/a\rb") == "/"
    assert sanitize_redirect_path("/a\r\nb") == "/"
    assert sanitize_redirect_path("/path\r\n\r\n<script>evil</script>") == "/"
    assert sanitize_redirect_path("/a\x00b") == "/"


def test_sanitize_redirect_path_url_encoded_stays_same_origin():
    """URL-encoded protocol-relative/scheme bypass attempts stay same-origin.

    urlsplit() never percent-decodes, so %2F is never read as a literal /:
    the result keeps one real leading / and is a same-origin path reference,
    not a decoded //evil.com in disguise. The encoding is preserved, not
    stripped - a browser resolves the result against the current origin.
    """
    assert sanitize_redirect_path("%2F%2Fevil.com") == "/%2F%2Fevil.com"
    assert sanitize_redirect_path("%68ttps://evil.com") == "/%68ttps://evil.com"

    # Same join as the auth callback in routers.py.
    frontend_url = "https://app.example.com"
    for path in ("%2F%2Fevil.com", "/%2F%2Fevil.com", "%68ttps://evil.com"):
        return_to = sanitize_redirect_path(path)
        target = urllib.parse.urljoin(frontend_url.rstrip("/") + "/", return_to.lstrip("/"))
        assert urllib.parse.urlsplit(target).netloc == "app.example.com"


def test_redact_sid_full_length():
    """Test redact_sid masks a real-length session ID."""
    sid = "A" * 43
    assert redact_sid(sid) == "AAAAAAAA..."
    assert sid not in redact_sid(sid)


def test_redact_sid_none_and_short():
    """Test redact_sid handles None and degenerate short values."""
    assert redact_sid(None) == "<none>"
    assert redact_sid("") == "<none>"
    assert redact_sid("abc") == "********"
