# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for session destruction (STIG V-222578)."""

import logging
import secrets
from unittest.mock import MagicMock, patch

import pytest
from strands.types.exceptions import SessionException

from foundry_agent_core import AgentCreationError
from foundry_strands_agent.factory import StrandsAgentFactory


@pytest.fixture
def encryption_key(monkeypatch):
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", secrets.token_hex(32))


@pytest.fixture
def factory(encryption_key):
    container = MagicMock()
    return StrandsAgentFactory(container=container)


class TestDestroySession:
    def test_calls_delete_session_on_manager(self, factory, tmp_path, monkeypatch):
        monkeypatch.setenv("STRANDS_SESSION_STORAGE_DIR", str(tmp_path))
        with patch.object(factory, "_create_session_manager") as mock_create:
            mock_manager = MagicMock()
            mock_create.return_value = mock_manager
            factory.destroy_session(session_id="test-session-123")
            mock_manager.delete_session.assert_called_once_with("test-session-123")

    def test_nonexistent_session_raises(self, factory, tmp_path, monkeypatch):
        monkeypatch.setenv("STRANDS_SESSION_STORAGE_DIR", str(tmp_path))
        with patch.object(factory, "_create_session_manager") as mock_create:
            mock_manager = MagicMock()
            mock_manager.delete_session.side_effect = SessionException("Session does not exist")
            mock_create.return_value = mock_manager
            with pytest.raises(AgentCreationError, match="Failed to destroy session"):
                factory.destroy_session(session_id="nonexistent")

    def test_config_overrides_passed_to_session_manager(self, factory):
        with (
            patch.object(factory, "_create_session_manager") as mock_create,
            patch.object(factory, "_get_base_config") as mock_base,
            patch.object(factory, "_merge_config_overrides") as mock_merge,
        ):
            mock_manager = MagicMock()
            mock_create.return_value = mock_manager
            mock_base.return_value = MagicMock()
            mock_merge.return_value = {
                "session_type": "s3",
                "session_storage_dir": None,
                "session_s3_bucket": "my-bucket",
                "session_s3_prefix": "sessions/",
                "session_s3_region": "us-east-1",
            }

            factory.destroy_session(
                session_id="test-session-123",
                config_overrides={"session_type": "s3", "session_s3_bucket": "my-bucket"},
            )

            mock_merge.assert_called_once()
            mock_create.assert_called_once_with(
                session_id="test-session-123",
                session_type="s3",
                storage_dir=None,
                s3_bucket="my-bucket",
                s3_prefix="sessions/",
                s3_region="us-east-1",
            )
            mock_manager.delete_session.assert_called_once_with("test-session-123")

    def test_logs_masked_session_id(self, factory, tmp_path, monkeypatch, caplog):
        monkeypatch.setenv("STRANDS_SESSION_STORAGE_DIR", str(tmp_path))
        with patch.object(factory, "_create_session_manager") as mock_create:
            mock_manager = MagicMock()
            mock_create.return_value = mock_manager
            with caplog.at_level(logging.INFO):
                factory.destroy_session(session_id="secret-session-id-value")
            assert "Session destroyed" in caplog.text
            assert "secret-session-id-value" not in caplog.text
