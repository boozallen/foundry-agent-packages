# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""AES-256-GCM encryption for file-backed session state.

Satisfies STIG V-222588 (CCI-002475) and V-222589 (CCI-002476).
"""

import base64
import json
import logging
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from foundry_agent_core import AgentCreationError

logger = logging.getLogger(__name__)

_ENCRYPTED_MARKER = "__encrypted"
_KEY_ENV_VAR = "SESSION_ENCRYPTION_KEY"
_NONCE_BYTES = 12


def load_encryption_key() -> bytes:
    """Load and validate the encryption key from environment.

    Returns:
        32-byte AES-256 key.

    Raises:
        AgentCreationError: If key is missing or invalid format.
    """
    raw = os.getenv(_KEY_ENV_VAR)
    if not raw:
        raise AgentCreationError(
            f"{_KEY_ENV_VAR} environment variable is required but not set",
            context={"env_var": _KEY_ENV_VAR},
        )
    raw = raw.strip()
    if len(raw) != 64:
        raise AgentCreationError(
            f"{_KEY_ENV_VAR} must be a 64-character hex string (32 bytes)",
            context={"env_var": _KEY_ENV_VAR, "length": len(raw)},
        )
    try:
        return bytes.fromhex(raw)
    except ValueError as e:
        raise AgentCreationError(
            f"{_KEY_ENV_VAR} is not valid hexadecimal",
            context={"env_var": _KEY_ENV_VAR},
        ) from e


def encrypt(data: dict[str, Any], key: bytes) -> dict[str, Any]:
    """Encrypt a dict using AES-256-GCM.

    Returns:
        Dict with __encrypted marker, base64-encoded ciphertext, and nonce.
    """
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    nonce = os.urandom(_NONCE_BYTES)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return {
        _ENCRYPTED_MARKER: True,
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }


def decrypt(payload: dict[str, Any], key: bytes) -> dict[str, Any]:
    """Decrypt an AES-256-GCM encrypted payload.

    Raises:
        cryptography.exceptions.InvalidTag: If ciphertext is tampered.
    """
    ciphertext = base64.b64decode(payload["ciphertext"])
    nonce = base64.b64decode(payload["nonce"])
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))


def is_encrypted(data: dict[str, Any]) -> bool:
    """Check if a payload has the encrypted marker."""
    return data.get(_ENCRYPTED_MARKER) is True
