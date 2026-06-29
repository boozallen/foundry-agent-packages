# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for foundry_agent_core.masking — mask_session_id (STIG V-222577)."""

import pytest

from foundry_agent_core.masking import mask_session_id, redact_session_ids


class TestMaskSessionId:
    """Test the mask_session_id utility."""

    def test_deterministic_for_same_input(self):
        """Same input yields the same masked token."""
        assert mask_session_id("session-123") == mask_session_id("session-123")

    def test_differs_for_different_inputs(self):
        """Distinct session IDs produce distinct tokens."""
        assert mask_session_id("session-123") != mask_session_id("session-456")

    def test_non_reversible_raw_value_absent(self):
        """The raw identifier must not appear in the masked output."""
        raw = "super-secret-session-id"
        masked = mask_session_id(raw)
        assert raw not in masked

    def test_masked_format(self):
        """Masked token uses the recognizable sid: prefix."""
        masked = mask_session_id("session-123")
        assert masked.startswith("sid:")
        # sid: + 12 hex chars
        assert len(masked) == len("sid:") + 12

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_placeholder_for_none_or_empty(self, value):
        """None / empty / whitespace-only returns a stable placeholder, never raises."""
        assert mask_session_id(value) == "sid:<none>"


class TestRedactSessionIds:
    """Test the redact_session_ids blob sanitization utility."""

    def test_redact_json_blob(self):
        """Redact session_id in a JSON string."""
        blob = '{"session_id": "abc123", "query": "test"}'
        result = redact_session_ids(blob)
        assert "abc123" not in result
        assert "sid:" in result

    def test_redact_repr_blob(self):
        """Redact session_id in a Python repr string."""
        blob = "{'session_id': 'xyz789', 'other': 'data'}"
        result = redact_session_ids(blob)
        assert "xyz789" not in result
        assert "sid:" in result

    def test_no_match_returns_unchanged(self):
        """Blob without session_id is returned unchanged."""
        blob = '{"query": "test", "other": "data"}'
        assert redact_session_ids(blob) == blob
