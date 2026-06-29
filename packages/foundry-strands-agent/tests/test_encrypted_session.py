# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for EncryptedFileSessionManager."""

import json
import os
import secrets
import tempfile

import pytest
from strands.session import FileSessionManager

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
