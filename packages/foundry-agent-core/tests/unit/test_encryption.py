# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for foundry_agent_core.encryption module."""

import base64

import pytest
from cryptography.exceptions import InvalidTag

from foundry_agent_core.encryption import decrypt, encrypt, is_encrypted, load_encryption_key
from foundry_agent_core.exceptions import AgentCreationError

VALID_KEY_HEX = "a" * 64
VALID_KEY = bytes.fromhex(VALID_KEY_HEX)
ALT_KEY = bytes.fromhex("b" * 64)


class TestEncryptDecryptRoundTrip:
    def test_round_trip_preserves_data(self):
        data = {"user": "alice", "tokens": ["t1", "t2"], "count": 42}
        payload = encrypt(data, VALID_KEY)
        result = decrypt(payload, VALID_KEY)
        assert result == data

    def test_round_trip_empty_dict(self):
        data: dict = {}
        payload = encrypt(data, VALID_KEY)
        result = decrypt(payload, VALID_KEY)
        assert result == data

    def test_round_trip_unicode(self):
        data = {"name": "café", "emoji": "\U0001f680"}
        payload = encrypt(data, VALID_KEY)
        result = decrypt(payload, VALID_KEY)
        assert result == data


class TestEncryptOutput:
    def test_encrypted_marker_present(self):
        payload = encrypt({"x": 1}, VALID_KEY)
        assert payload["__encrypted"] is True
        assert "ciphertext" in payload
        assert "nonce" in payload

    def test_unique_nonce_per_call(self):
        data = {"same": "data"}
        p1 = encrypt(data, VALID_KEY)
        p2 = encrypt(data, VALID_KEY)
        assert p1["nonce"] != p2["nonce"]
        assert p1["ciphertext"] != p2["ciphertext"]


class TestDecryptTampering:
    def test_tampered_ciphertext_raises_invalid_tag(self):
        payload = encrypt({"secret": "value"}, VALID_KEY)
        raw = bytearray(base64.b64decode(payload["ciphertext"]))
        raw[0] ^= 0x01
        payload["ciphertext"] = base64.b64encode(raw).decode("ascii")
        with pytest.raises(InvalidTag):
            decrypt(payload, VALID_KEY)

    def test_tampered_nonce_raises_invalid_tag(self):
        payload = encrypt({"secret": "value"}, VALID_KEY)
        raw = bytearray(base64.b64decode(payload["nonce"]))
        raw[0] ^= 0x01
        payload["nonce"] = base64.b64encode(raw).decode("ascii")
        with pytest.raises(InvalidTag):
            decrypt(payload, VALID_KEY)

    def test_wrong_key_raises_invalid_tag(self):
        payload = encrypt({"secret": "value"}, VALID_KEY)
        with pytest.raises(InvalidTag):
            decrypt(payload, ALT_KEY)


class TestLoadEncryptionKey:
    def test_valid_key_from_env(self, monkeypatch):
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", VALID_KEY_HEX)
        key = load_encryption_key()
        assert key == VALID_KEY

    def test_custom_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_CUSTOM_KEY", VALID_KEY_HEX)
        key = load_encryption_key(env_var="MY_CUSTOM_KEY")
        assert key == VALID_KEY

    def test_missing_env_var_raises(self, monkeypatch):
        monkeypatch.delenv("SESSION_ENCRYPTION_KEY", raising=False)
        with pytest.raises(AgentCreationError, match="required but not set"):
            load_encryption_key()

    def test_empty_env_var_raises(self, monkeypatch):
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "")
        with pytest.raises(AgentCreationError, match="required but not set"):
            load_encryption_key()

    def test_wrong_length_raises(self, monkeypatch):
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "abcd")
        with pytest.raises(AgentCreationError, match="64-character hex string"):
            load_encryption_key()

    def test_invalid_hex_raises(self, monkeypatch):
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "z" * 64)
        with pytest.raises(AgentCreationError, match="not valid hexadecimal"):
            load_encryption_key()

    def test_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", f"  {VALID_KEY_HEX}  ")
        key = load_encryption_key()
        assert key == VALID_KEY


class TestIsEncrypted:
    def test_encrypted_payload(self):
        payload = encrypt({"x": 1}, VALID_KEY)
        assert is_encrypted(payload) is True

    def test_plain_dict(self):
        assert is_encrypted({"user": "alice"}) is False

    def test_empty_dict(self):
        assert is_encrypted({}) is False

    def test_marker_false(self):
        assert is_encrypted({"__encrypted": False}) is False
