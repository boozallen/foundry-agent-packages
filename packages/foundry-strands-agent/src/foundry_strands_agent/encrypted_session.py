# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Encrypted file session manager wrapping the Strands SDK's FileSessionManager."""

import logging
import os
from pathlib import Path
from typing import Any

from strands.session import FileSessionManager
from strands.session.file_session_manager import SESSION_PREFIX

from foundry_agent_core import mask_session_id
from foundry_agent_core.encryption import decrypt, encrypt, is_encrypted
from foundry_strands_agent.session_guard import DanglingToolUseGuard

logger = logging.getLogger(__name__)


class EncryptedFileSessionManager(DanglingToolUseGuard, FileSessionManager):
    """FileSessionManager with AES-256-GCM encryption on disk I/O.

    Also guards against restoring history that ends in an unresolved `tool_use`
    block - see `DanglingToolUseGuard`.
    """

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
        # The path holds the raw session ID, so log the file name and the masked session ID.
        dirs = reversed(Path(path).parent.parts)  # Nearest first: messages/, agent_<id>/, then session_<id>/.
        session_id = next((d.removeprefix(SESSION_PREFIX) for d in dirs if d.startswith(SESSION_PREFIX)), None)
        logger.warning(
            "Read unencrypted legacy session file: %s (session %s)",
            os.path.basename(path),
            mask_session_id(session_id),
        )
        return raw
