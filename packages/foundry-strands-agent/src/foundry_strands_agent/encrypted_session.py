# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Encrypted file session manager wrapping the Strands SDK's FileSessionManager."""

import logging
from typing import Any

from strands.session import FileSessionManager

from foundry_strands_agent.encryption import decrypt, encrypt, is_encrypted

logger = logging.getLogger(__name__)


class EncryptedFileSessionManager(FileSessionManager):
    """FileSessionManager with AES-256-GCM encryption on disk I/O."""

    def __init__(self, encryption_key: bytes, **kwargs: Any) -> None:
        self._encryption_key = encryption_key
        super().__init__(**kwargs)

    def _write_file(self, path: str, data: dict[str, Any]) -> None:
        encrypted_payload = encrypt(data, self._encryption_key)
        super()._write_file(path, encrypted_payload)

    def _read_file(self, path: str) -> dict[str, Any]:
        raw = super()._read_file(path)
        if is_encrypted(raw):
            return decrypt(raw, self._encryption_key)
        logger.warning("Read unencrypted legacy session file: %s", path)
        return raw
