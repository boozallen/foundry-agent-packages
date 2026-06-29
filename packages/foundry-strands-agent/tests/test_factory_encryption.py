# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for factory encryption integration."""

import secrets

import pytest

from foundry_agent_core import AgentCreationError
from foundry_strands_agent.encrypted_session import EncryptedFileSessionManager
from foundry_strands_agent.factory import _default_file_session_manager, _default_s3_session_manager


class TestFileSessionManagerFactory:
    def test_creates_encrypted_manager_when_key_set(self, monkeypatch, tmp_path):
        hex_key = secrets.token_hex(32)
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", hex_key)
        mgr = _default_file_session_manager(session_id="test", storage_dir=str(tmp_path))
        assert isinstance(mgr, EncryptedFileSessionManager)

    def test_raises_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("SESSION_ENCRYPTION_KEY", raising=False)
        with pytest.raises(AgentCreationError, match="required but not set"):
            _default_file_session_manager(session_id="test", storage_dir="/tmp")

    def test_raises_when_key_invalid(self, monkeypatch):
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "not-valid-hex")
        with pytest.raises(AgentCreationError):
            _default_file_session_manager(session_id="test", storage_dir="/tmp")


class TestS3SessionManagerFactory:
    def test_s3_unaffected_by_encryption_key(self, monkeypatch):
        hex_key = secrets.token_hex(32)
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", hex_key)
        from unittest.mock import patch

        from strands.session import S3SessionManager

        with patch.object(S3SessionManager, "__init__", return_value=None):
            mgr = _default_s3_session_manager(
                session_id="test",
                s3_bucket="test-bucket",
                s3_prefix="prefix/",
                s3_region="us-east-1",
            )
        assert isinstance(mgr, S3SessionManager)
        assert not isinstance(mgr, EncryptedFileSessionManager)
