# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for core type definitions and validation (STIG V-222609)."""

import pytest
from pydantic import ValidationError

from foundry_agent_core.types import AgentRequest, AgentResponse


class TestAgentRequestSessionIdValidation:
    """Test session ID validation for AgentRequest (STIG V-222609 compliance)."""

    def test_agent_request_session_id_valid_patterns(self):
        """Valid session IDs with alphanumeric, hyphens, and underscores are accepted."""
        # Alphanumeric with hyphens
        req1 = AgentRequest(query="test", session_id="session-abc123def456")
        assert req1.session_id == "session-abc123def456"

        # Alphanumeric with underscores
        req2 = AgentRequest(query="test", session_id="user_session_2024_06_23")
        assert req2.session_id == "user_session_2024_06_23"

        # UUID format
        req3 = AgentRequest(query="test", session_id="12345678-1234-5678-1234-567812345678")
        assert req3.session_id == "12345678-1234-5678-1234-567812345678"

        # Mixed case alphanumeric
        req4 = AgentRequest(query="test", session_id="Session-ABC-123")
        assert req4.session_id == "Session-ABC-123"

    def test_agent_request_session_id_boundary_8_chars(self):
        """Session ID with exactly 8 characters (minimum) is accepted."""
        req = AgentRequest(query="test", session_id="abcd1234")
        assert req.session_id == "abcd1234"

    def test_agent_request_session_id_boundary_128_chars(self):
        """Session ID with exactly 128 characters (maximum) is accepted."""
        session_id_128 = "a" * 128
        req = AgentRequest(query="test", session_id=session_id_128)
        assert req.session_id == session_id_128
        assert len(req.session_id) == 128

    def test_agent_request_session_id_too_short_raises(self):
        """Session ID with 7 characters (below minimum) raises ValidationError."""
        with pytest.raises(ValidationError, match="at least 8 characters"):
            AgentRequest(query="test", session_id="test123")

        with pytest.raises(ValidationError):
            AgentRequest(query="test", session_id="x")

    def test_agent_request_session_id_too_long_raises(self):
        """Session ID with 129+ characters (above maximum) raises ValidationError."""
        session_id_129 = "a" * 129
        with pytest.raises(ValidationError, match="at most 128 characters"):
            AgentRequest(query="test", session_id=session_id_129)

        session_id_256 = "a" * 256
        with pytest.raises(ValidationError, match="at most 128 characters"):
            AgentRequest(query="test", session_id=session_id_256)

    def test_agent_request_session_id_sql_injection_blocked(self):
        """SQL injection payloads are rejected with ValidationError."""
        # SQL comment injection
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="admin'--")

        # SQL DROP statement
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="'; DROP TABLE sessions--")

        # SQL UNION injection
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="1' UNION SELECT * FROM users--")

    def test_agent_request_session_id_path_traversal_blocked(self):
        """Path traversal sequences are rejected with ValidationError."""
        # Relative path traversal
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="../../../etc/passwd")

        # Absolute path injection
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="/etc/shadow")

        # Windows path traversal
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="..\\..\\windows\\system32")

    def test_agent_request_session_id_control_chars_blocked(self):
        """Control characters are rejected with ValidationError."""
        # Null byte injection
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="session\x00admin")

        # ANSI escape sequence
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="session\x1b[0m")

        # Newline injection
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="session\ninjected")

    def test_agent_request_session_id_special_chars_blocked(self):
        """Special characters outside whitelist are rejected with ValidationError."""
        # At-sign
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="user@session")

        # Percent-encoding
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="session%20id")

        # Parentheses
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="session(123)")

        # Brackets
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentRequest(query="test", session_id="session[0]")

    def test_agent_request_session_id_strips_whitespace(self):
        """Leading and trailing whitespace is stripped before validation."""
        req1 = AgentRequest(query="test", session_id="  session123")
        assert req1.session_id == "session123"

        req2 = AgentRequest(query="test", session_id="session123  ")
        assert req2.session_id == "session123"

        req3 = AgentRequest(query="test", session_id="  session123  ")
        assert req3.session_id == "session123"

    def test_agent_request_session_id_whitespace_only_raises(self):
        """Whitespace-only session ID raises ValidationError."""
        with pytest.raises(ValidationError):
            AgentRequest(query="test", session_id="   ")

    def test_agent_request_session_id_none_allowed(self):
        """None session_id is accepted (no session context)."""
        req = AgentRequest(query="test", session_id=None)
        assert req.session_id is None

    def test_agent_request_session_id_omitted_defaults_none(self):
        """Omitted session_id defaults to None."""
        req = AgentRequest(query="test")
        assert req.session_id is None


class TestAgentResponseSessionIdValidation:
    """Test that AgentResponse applies same session ID validation."""

    def test_agent_response_session_id_validation_same(self):
        """AgentResponse enforces identical session ID validation as AgentRequest."""
        # Valid 8+ char session ID accepted
        resp1 = AgentResponse(content="response", session_id="session-123", processing_time_ms=100.0)
        assert resp1.session_id == "session-123"

        # 7-char session ID rejected
        with pytest.raises(ValidationError, match="at least 8 characters"):
            AgentResponse(content="response", session_id="sess-1", processing_time_ms=100.0)

        # SQL injection rejected
        with pytest.raises(ValidationError, match="String should match pattern"):
            AgentResponse(content="response", session_id="admin'--", processing_time_ms=100.0)

        # None allowed
        resp2 = AgentResponse(content="response", session_id=None, processing_time_ms=100.0)
        assert resp2.session_id is None
