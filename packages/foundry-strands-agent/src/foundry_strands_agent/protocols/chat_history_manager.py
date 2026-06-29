# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Chat history manager protocol for chat history management.

This module defines the ChatHistoryManager protocol for coordinating all services to manage the chat history.
"""

from abc import abstractmethod
from typing import Protocol

from strands.types.session import Session, SessionMessage


class ChatHistoryManager(Protocol):
    """Protocol for processing chat history management requests.

    This is the main service that coordinates chat history operations.
    """

    @abstractmethod
    async def get_chat_sessions_history(self, limit: int | None = None, offset: int | None = None) -> list[Session]:
        """Get all chat sessions history with most recent sessions first.

        Args:
            limit: Maximum number of sessions to return (1-100)
            offset: Number of sessions to skip for pagination

        Returns:
            list[Session]: List of chat sessions with metadata
        """

    @abstractmethod
    async def get_chat_session_messages_history(
        self, session_id: str, limit: int | None = None, offset: int | None = None
    ) -> list[SessionMessage]:
        """Get messages from a specific chat session with most recent messages last.

        Args:
            session_id: Unique identifier for the chat session
            limit: Maximum number of messages to return (1-100)
            offset: Number of messages to skip for pagination

        Returns:
            list[SessionMessage]: Messages from the session with metadata
        """

    @abstractmethod
    async def create_chat_session_messages_history(self, session_id: str) -> Session | None:
        """Create a new chat session history.

        Args:
            session_id: Unique identifier for the chat session to create

        Returns:
            Session | None: The created chat session with metadata or None if session already exists
        """

    @abstractmethod
    async def delete_chat_session_messages_history(self, session_id: str) -> None:
        """Delete a specific chat session and its messages.

        Args:
            session_id: Unique identifier for the chat session to delete

        Returns:
            None
        """

    @abstractmethod
    async def on_logoff(self, session_id: str) -> None:
        """Destroy all persisted session state on logoff or browser close.

        STIG V-222578 (CCI-001185) entry point. Caller (service layer) is
        responsible for invoking this method on logoff or browser-close events.
        Delegates to delete_chat_session_messages_history(session_id).

        Args:
            session_id: Unique identifier for the session to destroy.

        Returns:
            None
        """
