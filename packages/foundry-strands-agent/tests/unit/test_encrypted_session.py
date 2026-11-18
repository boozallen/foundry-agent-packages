# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for EncryptedFileSessionManager."""

import json
import logging
import os
import secrets
import tempfile

import pytest
from strands.session import FileSessionManager

from foundry_agent_core import mask_session_id
from foundry_strands_agent.encrypted_session import EncryptedFileSessionManager


@pytest.fixture
def key() -> bytes:
    return secrets.token_bytes(32)


@pytest.fixture
def storage_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


class TestSdkCouplingGuard:
    def test_write_file_method_exists_on_upstream(self):
        assert hasattr(FileSessionManager, "_write_file")
        assert callable(FileSessionManager._write_file)

    def test_read_file_method_exists_on_upstream(self):
        assert hasattr(FileSessionManager, "_read_file")
        assert callable(FileSessionManager._read_file)


class TestEncryptedRoundTrip:
    def test_write_then_read_preserves_data(self, key, storage_dir):
        mgr = EncryptedFileSessionManager(
            encryption_key=key,
            session_id="test-session",
            storage_dir=storage_dir,
        )
        test_data = {"message": "hello", "nested": {"a": [1, 2, 3]}}
        file_path = os.path.join(storage_dir, "test.json")

        mgr._write_file(file_path, test_data)
        result = mgr._read_file(file_path)

        assert result == test_data

    def test_agent_state_with_lone_surrogate_round_trips(self, key, storage_dir):
        """Agent state carrying a lone surrogate is saved and restored instead of failing the write."""
        mgr = EncryptedFileSessionManager(
            encryption_key=key,
            session_id="test-session",
            storage_dir=storage_dir,
        )
        test_data = {"state": {"k": "\ud83d"}}
        file_path = os.path.join(storage_dir, "agent.json")

        mgr._write_file(file_path, test_data)

        assert mgr._read_file(file_path) == test_data

    def test_file_on_disk_is_encrypted(self, key, storage_dir):
        mgr = EncryptedFileSessionManager(
            encryption_key=key,
            session_id="test-session",
            storage_dir=storage_dir,
        )
        test_data = {"secret": "sensitive-value"}
        file_path = os.path.join(storage_dir, "test.json")

        mgr._write_file(file_path, test_data)

        with open(file_path) as f:
            raw = json.load(f)
        assert raw.get("__encrypted") is True
        assert "sensitive-value" not in json.dumps(raw)


class TestTamperDetection:
    def test_tampered_file_raises_on_read(self, key, storage_dir):
        mgr = EncryptedFileSessionManager(
            encryption_key=key,
            session_id="test-session",
            storage_dir=storage_dir,
        )
        test_data = {"secret": "value"}
        file_path = os.path.join(storage_dir, "test.json")

        mgr._write_file(file_path, test_data)

        with open(file_path) as f:
            raw = json.load(f)
        ct = list(raw["ciphertext"])
        ct[0] = "A" if ct[0] != "A" else "B"
        raw["ciphertext"] = "".join(ct)
        with open(file_path, "w") as f:
            json.dump(raw, f)

        from cryptography.exceptions import InvalidTag

        with pytest.raises(InvalidTag):
            mgr._read_file(file_path)


class TestDanglingToolUseGuard:
    """EncryptedFileSessionManager guards restored history via the mixin."""

    def test_dangling_last_message_tool_use_is_resolved(self, key, storage_dir):
        mgr = EncryptedFileSessionManager(
            encryption_key=key,
            session_id="test-session",
            storage_dir=storage_dir,
        )
        messages = [
            {"role": "user", "content": [{"text": "do something"}]},
            {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "tool-1", "name": "some_tool", "input": {}}}],
            },
        ]

        result = mgr._fix_broken_tool_use(messages)

        assert result[-1]["role"] == "user"
        assert any("toolResult" in block for block in result[-1]["content"])

    def test_reject_mode_raises(self, key, storage_dir):
        from foundry_agent_core import AgentCreationError

        mgr = EncryptedFileSessionManager(
            encryption_key=key,
            session_id="test-session",
            storage_dir=storage_dir,
            dangling_tool_use_mode="reject",
        )
        messages = [
            {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "tool-1", "name": "some_tool", "input": {}}}],
            },
        ]

        with pytest.raises(AgentCreationError):
            mgr._fix_broken_tool_use(messages)

    def test_encryption_still_works_with_mixin_added(self, key, storage_dir):
        """Regression: adding DanglingToolUseGuard must not change _read_file/_write_file behavior."""
        mgr = EncryptedFileSessionManager(
            encryption_key=key,
            session_id="test-session",
            storage_dir=storage_dir,
        )
        test_data = {"message": "hello"}
        file_path = os.path.join(storage_dir, "test.json")

        mgr._write_file(file_path, test_data)
        result = mgr._read_file(file_path)

        assert result == test_data


class TestLegacyMigration:
    def test_reads_unencrypted_file_with_warning(self, key, storage_dir, caplog):
        mgr = EncryptedFileSessionManager(
            encryption_key=key,
            session_id="test-session",
            storage_dir=storage_dir,
        )
        plaintext_data = {"old_session": "data", "count": 5}
        file_path = os.path.join(storage_dir, "legacy.json")

        with open(file_path, "w") as f:
            json.dump(plaintext_data, f)

        import logging

        with caplog.at_level(logging.WARNING):
            result = mgr._read_file(file_path)

        assert result == plaintext_data
        assert "unencrypted legacy" in caplog.text

    def test_legacy_warning_does_not_log_session_path(self, key, storage_dir, caplog):
        EncryptedFileSessionManager(encryption_key=key, session_id="raw-legacy-id", storage_dir=storage_dir)
        mgr = EncryptedFileSessionManager(encryption_key=key, session_id="other", storage_dir=storage_dir)
        session_file = os.path.join(storage_dir, "session_raw-legacy-id", "session.json")
        with open(session_file, "w") as f:
            json.dump({"session_id": "raw-legacy-id", "session_type": "AGENT"}, f)

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.encrypted_session"):
            mgr.read_session("raw-legacy-id")

        assert "unencrypted legacy session file: session.json" in caplog.text
        assert mask_session_id("raw-legacy-id") in caplog.text
        assert "raw-legacy-id" not in caplog.text

    def test_legacy_warning_masks_nested_file_session_id(self, key, storage_dir, caplog):
        # A storage dir whose own name starts with "session_" must not be taken for the session.
        store = os.path.join(storage_dir, "session_store")
        mgr = EncryptedFileSessionManager(encryption_key=key, session_id="other", storage_dir=store)
        message_dir = os.path.join(store, "session_raw-msg-id", "agents", "agent_default", "messages")
        os.makedirs(message_dir)
        message_file = os.path.join(message_dir, "message_0.json")
        with open(message_file, "w") as f:
            json.dump({"message": "legacy"}, f)

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.encrypted_session"):
            mgr._read_file(message_file)

        assert "unencrypted legacy session file: message_0.json" in caplog.text
        assert mask_session_id("raw-msg-id") in caplog.text
        assert "raw-msg-id" not in caplog.text
