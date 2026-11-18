# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Chat history manager implementation.

This module implements the ChatHistoryManager protocol, coordinating all services to manage the chat history.
"""

import logging
from pathlib import Path
from typing import cast

from strands.session import FileSessionManager, S3SessionManager, SessionRepository
from strands.session.file_session_manager import SESSION_PREFIX as FILE_SESSION_PREFIX
from strands.session.s3_session_manager import SESSION_PREFIX as S3_SESSION_PREFIX
from strands.types.exceptions import SessionException
from strands.types.session import Session, SessionMessage, SessionType

from foundry_agent_core import QueryProcessingError, mask_session_id
from foundry_strands_agent.config.models import StrandsAgentConfig
from foundry_strands_agent.protocols import AgentFactory, ChatHistoryManager

logger = logging.getLogger(__name__)


class ChatHistorian(ChatHistoryManager):
    """Implementation of ChatHistoryManager for managing chat history.

    This historian provides chat history management.
    """

    def __init__(self, agent_factory: AgentFactory, config: StrandsAgentConfig) -> None:
        """Initialize chat historian with dependencies.

        Args:
            agent_factory: Factory for creating configured agent instances
            config: Agent configuration
        """
        self._agent_factory = agent_factory
        self._config = config

    async def get_chat_sessions_history(self, limit: int | None = None, offset: int | None = None) -> list[Session]:
        """Get all chat sessions history with most recent sessions first.

        Retrieves a list of all chat sessions with their creation and update timestamps.
        Uses the established service lifecycle pattern for consistent error handling.

        Args:
            limit: Maximum number of sessions to return (1-100)
            offset: Number of sessions to skip for pagination

        Returns:
            list[Session]: List of chat sessions with metadata

        Raises:
            QueryProcessingError: If retrieval fails
        """
        if offset is None:
            offset = 0
        elif offset < 0:
            raise ValueError("Offset must be 0 or greater")

        if limit is None:
            limit = 100
        elif limit < 1 or 100 < limit:
            raise ValueError("Limit must be between 1 and 100")

        try:
            session_repository = self._agent_factory.create_session_repository()
            if not session_repository:
                raise Exception("Chat session history is disabled")

            if hasattr(session_repository, "storage_dir"):
                repo = cast(FileSessionManager, session_repository)
                return await self._get_chat_file_sessions_history(repo, limit, offset)
            if hasattr(session_repository, "client"):
                repo = cast(S3SessionManager, session_repository)
                return await self._get_chat_s3_sessions_history(repo, limit, offset)
            raise Exception("Unable to access chat sessions history.")
        except Exception as e:
            raise QueryProcessingError(f"Error retrieving chat sessions history: {e}", context={"error": str(e)}) from e

    async def _get_chat_file_sessions_history(
        self, session_repository: FileSessionManager, limit: int, offset: int
    ) -> list[Session]:
        """Get chat sessions history from file-based storage.

        Session IDs come from the `session_<id>` directory names under `storage_dir`.
        Each session is read through `session_repository.read_session()`, so a
        session manager that encrypts at rest (`EncryptedFileSessionManager`)
        decrypts it the same way it does for a single-session read.

        Args:
            session_repository: The session repository instance
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip

        Returns:
            list[Session]: List of chat sessions
        """
        storage_dir = session_repository.storage_dir
        if not storage_dir:
            return []

        storage_path = Path(storage_dir)
        if not storage_path.exists() or not storage_path.is_dir():
            return []

        sessions: list[Session] = []
        for item in storage_path.iterdir():
            if not item.name.startswith(FILE_SESSION_PREFIX) or not item.is_dir():
                continue

            session = self._read_listed_session(session_repository, item.name[len(FILE_SESSION_PREFIX) :])
            if session:
                sessions.append(session)

        return self._page_sessions(sessions, limit, offset)

    async def _get_chat_s3_sessions_history(
        self, session_repository: S3SessionManager, limit: int, offset: int
    ) -> list[Session]:
        """Get chat sessions history from S3-based storage.

        Lists the `session_<id>/` prefixes under the repository's bucket and prefix
        with the `list_objects_v2` paginator (one entry per session, past 1000
        sessions), then reads each session through `session_repository.read_session()`.

        IAM: uses `s3:ListBucket` on the session bucket and prefix (as the S3 session
        manager's own message listing and session delete already do) plus one
        `s3:GetObject` per session. Without `s3:ListBucket` the listing call fails and
        the error is raised; it is not reported as an empty list.

        Args:
            session_repository: The S3 session repository instance
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip

        Returns:
            list[Session]: List of chat sessions
        """
        # Normalize the prefix the way S3SessionManager._get_session_path() does when it writes keys.
        base = session_repository.prefix.strip("/")
        list_prefix = f"{base}/{S3_SESSION_PREFIX}" if base else S3_SESSION_PREFIX

        paginator = session_repository.client.get_paginator("list_objects_v2")
        sessions: list[Session] = []
        for page in paginator.paginate(Bucket=session_repository.bucket, Prefix=list_prefix, Delimiter="/"):
            for common_prefix in page.get("CommonPrefixes", []):
                session_id = common_prefix["Prefix"][len(list_prefix) :].rstrip("/")
                session = self._read_listed_session(session_repository, session_id)
                if session:
                    sessions.append(session)

        return self._page_sessions(sessions, limit, offset)

    @staticmethod
    def _read_listed_session(session_repository: SessionRepository, session_id: str) -> Session | None:
        """Read one session for a listing, or return None to leave it out.

        An empty session ID, a missing session, or one whose metadata has no
        session_id is skipped silently. A session that can't be read or parsed is skipped with a warning
        that carries only the masked session ID and the exception type: SDK error
        messages embed paths and keys that contain the raw session ID.
        """
        if not session_id:
            return None

        try:
            session = session_repository.read_session(session_id)
            if session is None or not session.session_id:
                return None

            # Session.from_dict() leaves session_type as the raw string from storage.
            if not isinstance(session.session_type, SessionType):
                session.session_type = SessionType(session.session_type)
            return session
        except Exception as e:
            logger.warning("Skipping unreadable chat session %s: %s", mask_session_id(session_id), type(e).__name__)
            return None

    @staticmethod
    def _page_sessions(sessions: list[Session], limit: int, offset: int) -> list[Session]:
        """Sort sessions most recently updated first, then apply offset and limit."""
        sessions.sort(key=lambda s: s.updated_at or "0", reverse=True)
        return sessions[offset : offset + limit]

    async def get_chat_session_messages_history(
        self, session_id: str, limit: int | None = None, offset: int | None = None
    ) -> list[SessionMessage]:
        """Get messages from a specific chat session with most recent messages last.

        Retrieves messages from the specified chat session with optional pagination.
        Uses the established service lifecycle pattern for consistent error handling.

        Args:
            session_id: Unique identifier for the chat session
            limit: Maximum number of messages to return (1-100)
            offset: Number of messages to skip for pagination

        Returns:
            list[SessionMessage]: Messages from the session with metadata

        Raises:
            QueryProcessingError: If retrieval fails
        """
        if offset is None:
            offset = 0
        elif offset < 0:
            raise ValueError("Offset must be 0 or greater")

        if limit is None:
            limit = 100
        elif limit < 1 or 100 < limit:
            raise ValueError("Limit must be between 1 and 100")

        try:
            session_repository = self._agent_factory.create_session_repository()
            if not session_repository:
                raise Exception("Chat session history is disabled")

            messages = session_repository.list_messages(  # pyright: ignore[reportAttributeAccessIssue]
                session_id=session_id, agent_id="default", limit=limit, offset=offset
            )
            messages.sort(key=lambda s: s.updated_at or "0")
            return messages
        except SessionException as e:
            if str(e).startswith("Messages directory missing from agent: default in session "):
                return []
            raise QueryProcessingError(
                f"Error retrieving chat session messages history: {e}", context={"error": str(e)}
            ) from e

        except Exception as e:
            raise QueryProcessingError(
                f"Error retrieving chat session messages history: {e}", context={"error": str(e)}
            ) from e

    async def create_chat_session_messages_history(self, session_id: str) -> Session | None:
        """Create chat sessions history for a specific chat session id.

        Uses the established service lifecycle pattern for consistent error handling.

        Args:
            session_id: Unique identifier for the chat session

        Returns:
            Session | None: The createdchat session with metadata or None if session already exists

        Raises:
            QueryProcessingError: If creation fails
        """
        try:
            session_repository = self._agent_factory.create_session_repository()
            if not session_repository:
                raise Exception("Chat session history is disabled")

            session = Session(session_id=session_id, session_type=SessionType.AGENT)
            created = session_repository.create_session(session)  # pyright: ignore[reportAttributeAccessIssue]
            return created
        except SessionException as e:
            if " already exists" in str(e):
                return None
            raise QueryProcessingError(f"Error creating chat session history: {e}", context={"error": str(e)}) from e

        except Exception as e:
            raise QueryProcessingError(f"Error creating chat session history: {e}", context={"error": str(e)}) from e

    async def delete_chat_session_messages_history(self, session_id: str) -> None:
        """Delete chat sessions history for a specific chat session id.

        Uses the established service lifecycle pattern for consistent error handling.

        Args:
            session_id: Unique identifier for the chat session

        Returns:
            None

        Raises:
            QueryProcessingError: If creation fails
        """
        try:
            session_repository = self._agent_factory.create_session_repository()
            if not session_repository:
                raise Exception("Chat session history is disabled")

            if hasattr(session_repository, "storage_dir"):
                repo = cast(FileSessionManager, session_repository)
                return await self._delete_chat_file_session_messages_history(repo, session_id)
            if hasattr(session_repository, "client"):
                repo = cast(S3SessionManager, session_repository)
                return await self._delete_chat_s3_session_messages_history(repo, session_id)
            raise Exception("Unable to access chat sessions history.")
        except SessionException as e:
            if " does not exist" in str(e):
                return
            raise QueryProcessingError(f"Error deleting chat session history: {e}", context={"error": str(e)}) from e

        except Exception as e:
            raise QueryProcessingError(f"Error deleting chat session history: {e}", context={"error": str(e)}) from e

    async def _delete_chat_file_session_messages_history(
        self, session_repository: FileSessionManager, session_id: str
    ) -> None:
        """Delete a specific chat sessions history from file-based storage.

        Args:
            session_repository: The file session repository instance
            session_id: Unique identifier for the chat session to delete

        Returns:
            None
        """
        try:
            session_repository.delete_session(session_id=session_id)
        except SessionException as e:
            if " does not exist" in str(e):
                return
            raise QueryProcessingError(f"Error deleting chat session history: {e}", context={"error": str(e)}) from e
        except Exception:
            raise

    async def _delete_chat_s3_session_messages_history(
        self, session_repository: S3SessionManager, session_id: str
    ) -> None:
        """Delete a specific chat sessions history from S3-based storage.

        Args:
            session_repository: The S3 session repository instance
            session_id: Unique identifier for the chat session to delete

        Returns:
            None
        """
        try:
            session_repository.delete_session(session_id=session_id)
        except Exception:
            raise

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
        await self.delete_chat_session_messages_history(session_id)


def create_chat_history_manager(agent_factory: AgentFactory, config: StrandsAgentConfig) -> ChatHistoryManager:
    """Factory function to create ChatHistorian instance.

    Args:
        agent_factory: Factory for creating agents
        config: Agent configuration

    Returns:
        Configured ChatHistorian implementation
    """
    return ChatHistorian(agent_factory, config)
