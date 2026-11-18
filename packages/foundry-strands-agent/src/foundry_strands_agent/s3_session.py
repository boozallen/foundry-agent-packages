# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""S3-backed session manager wrapping the Strands SDK's S3SessionManager.

Mirrors `EncryptedFileSessionManager`'s wrapper pattern: today the S3 backend has no
integrity wrapper of any kind, so it's exposed to the dangling-`tool_use`
gap with nothing guarding it at all. See `session_guard.DanglingToolUseGuard`.
"""

from strands.session import S3SessionManager

from foundry_strands_agent.session_guard import DanglingToolUseGuard


class GuardedS3SessionManager(DanglingToolUseGuard, S3SessionManager):
    """S3SessionManager guarded against restoring history ending in an unresolved `tool_use`."""
