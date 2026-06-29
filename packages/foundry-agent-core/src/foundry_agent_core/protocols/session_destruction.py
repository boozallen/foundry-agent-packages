# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Protocol for session destruction (STIG V-222578)."""

from typing import Protocol


class SessionDestruction(Protocol):
    """Contract for destroying persisted session state.

    Caller is responsible for invoking on logoff or browser-close events.
    """

    def destroy_session(self, session_id: str) -> None:
        """Destroy all persisted state for the given session.

        Args:
            session_id: The session identifier to destroy.

        Raises:
            Exception: If the session does not exist or destruction fails.
        """
        ...
