# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for AES-256-GCM encryption module (STIG V-222588, V-222589)."""

import secrets

import pytest
from cryptography.exceptions import InvalidTag

from foundry_agent_core import AgentCreationError
from foundry_strands_agent.encryption import (
    decrypt,
    encrypt,
    is_encrypted,
    load_encryption_key,
)


@pytest.fixture
def key() -> bytes:
    return secrets.token_bytes(32)


class TestEncrypt:
    def test_produces_encrypted_payload_structure(self, key):
        data = {"message": "hello", "count": 42}
        result = encrypt(data, key)
        assert result["__encrypted"] is True
        assert "ciphertext" in result
        assert "nonce" in result

    def test_unique_nonces_per_call(self, key):
        data = {"same": "data"}
        result1 = encrypt(data, key)
        result2 = encrypt(data, key)
        assert result1["ciphertext"] != result2["ciphertext"]
        assert result1["nonce"] != result2["nonce"]


class TestDecrypt:
    def test_round_trip(self, key):
        data = {"message": "hello", "nested": {"a": [1, 2, 3]}}
        encrypted = encrypt(data, key)
        decrypted = decrypt(encrypted, key)
        assert decrypted == data

    def test_tampered_ciphertext_raises(self, key):
        data = {"secret": "value"}
        encrypted = encrypt(data, key)
        tampered = encrypted.copy()
        ct = list(tampered["ciphertext"])
        ct[0] = "A" if ct[0] != "A" else "B"
        tampered["ciphertext"] = "".join(ct)
        with pytest.raises(InvalidTag):
            decrypt(tampered, key)

    def test_wrong_key_raises(self, key):
        data = {"secret": "value"}
        encrypted = encrypt(data, key)
        wrong_key = secrets.token_bytes(32)
        with pytest.raises(InvalidTag):
            decrypt(encrypted, wrong_key)


class TestIsEncrypted:
    def test_detects_encrypted_payload(self, key):
        encrypted = encrypt({"a": 1}, key)
        assert is_encrypted(encrypted) is True

    def test_rejects_plain_dict(self):
        assert is_encrypted({"a": 1, "b": 2}) is False

    def test_rejects_false_marker(self):
        assert is_encrypted({"__encrypted": False}) is False


class TestLoadEncryptionKey:
    def test_valid_hex_key(self, monkeypatch):
        hex_key = secrets.token_hex(32)
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", hex_key)
        result = load_encryption_key()
        assert result == bytes.fromhex(hex_key)
        assert len(result) == 32

    def test_missing_env_var_raises(self, monkeypatch):
        monkeypatch.delenv("SESSION_ENCRYPTION_KEY", raising=False)
        with pytest.raises(AgentCreationError, match="required but not set"):
            load_encryption_key()

    def test_empty_env_var_raises(self, monkeypatch):
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "")
        with pytest.raises(AgentCreationError, match="required but not set"):
            load_encryption_key()

    def test_invalid_length_raises(self, monkeypatch):
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "abcdef")
        with pytest.raises(AgentCreationError, match="64-character hex string"):
            load_encryption_key()

    def test_invalid_hex_raises(self, monkeypatch):
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "g" * 64)
        with pytest.raises(AgentCreationError, match="not valid hexadecimal"):
            load_encryption_key()

    def test_whitespace_stripped(self, monkeypatch):
        hex_key = secrets.token_hex(32)
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", f"  {hex_key}  ")
        result = load_encryption_key()
        assert result == bytes.fromhex(hex_key)
