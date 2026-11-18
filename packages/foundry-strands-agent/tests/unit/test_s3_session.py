# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for GuardedS3SessionManager."""

from unittest.mock import patch

import pytest
from strands.session import S3SessionManager

from foundry_agent_core import AgentCreationError
from foundry_strands_agent.s3_session import GuardedS3SessionManager


def _dangling_tool_use_messages() -> list[dict]:
    return [
        {"role": "user", "content": [{"text": "do something"}]},
        {
            "role": "assistant",
            "content": [{"toolUse": {"toolUseId": "tool-1", "name": "some_tool", "input": {}}}],
        },
    ]


class TestGuardedS3SessionManager:
    """Construction is patched to avoid a real boto3/S3 dependency - only the guard is exercised."""

    def test_is_an_s3_session_manager(self):
        with patch.object(S3SessionManager, "__init__", return_value=None):
            mgr = GuardedS3SessionManager(session_id="test", bucket="test-bucket")
        assert isinstance(mgr, S3SessionManager)

    def test_dangling_last_message_tool_use_is_resolved(self):
        with patch.object(S3SessionManager, "__init__", return_value=None):
            mgr = GuardedS3SessionManager(session_id="test", bucket="test-bucket")
        mgr.session_id = "test"

        result = mgr._fix_broken_tool_use(_dangling_tool_use_messages())

        assert result[-1]["role"] == "user"
        assert any("toolResult" in block for block in result[-1]["content"])

    def test_reject_mode_raises(self):
        with patch.object(S3SessionManager, "__init__", return_value=None):
            mgr = GuardedS3SessionManager(session_id="test", bucket="test-bucket", dangling_tool_use_mode="reject")
        mgr.session_id = "test"

        with pytest.raises(AgentCreationError):
            mgr._fix_broken_tool_use(_dangling_tool_use_messages())

    def test_default_mode_is_sanitize(self):
        with patch.object(S3SessionManager, "__init__", return_value=None):
            mgr = GuardedS3SessionManager(session_id="test", bucket="test-bucket")
        assert mgr._dangling_tool_use_mode == "sanitize"
