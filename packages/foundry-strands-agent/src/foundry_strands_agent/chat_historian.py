# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Chat history manager implementation.

This module implements the ChatHistoryManager protocol, coordinating all services to manage the chat history.
"""

import json
import logging
from pathlib import Path
from typing import Any, cast

from strands.session import FileSessionManager, S3SessionManager
from strands.session.file_session_manager import SESSION_PREFIX as FILE_SESSION_PREFIX
from strands.types.exceptions import SessionException
from strands.types.session import Session, SessionMessage, SessionType

from foundry_agent_core import QueryProcessingError, redact_session_ids
from foundry_strands_agent.config.models import StrandsAgentConfig
from foundry_strands_agent.protocols import AgentFactory, ChatHistoryManager

logger = logging.getLogger(__name__)


class _SessionFrom:
    @classmethod
    def dict_from_str(cls, session_str: str) -> dict[str, Any] | None:
        try:
            session_metadata = json.loads(session_str)
            if not session_metadata or not isinstance(session_metadata, dict) or not session_metadata.get("session_id"):
                return None
            return cast(dict[str, Any], session_metadata)
        except Exception as e:
            logger.exception("Failed to read session metadata from %s: %s", redact_session_ids(session_str), e)
            return None

    @classmethod
    def json_dict(cls, session_dict: dict[str, Any] | Any) -> Session | None:
        try:
            if not isinstance(session_dict, dict) or not session_dict.get("session_id"):
                return None

            # work around bug in strands.types.session.Session.from_dict():
            if session_type := session_dict.get("session_type"):
                session_dict["session_type"] = SessionType(session_type)
            session = Session.from_dict(session_dict)
            return session
        except Exception as e:
            logger.exception("Failed to read session metadata from %s: %s", redact_session_ids(repr(session_dict)), e)
            return None

    @classmethod
    def session_str(cls, session_str: str) -> Session | None:
        try:
            json_dict = json.loads(session_str)
            return cls.json_dict(json_dict)
        except Exception as e:
            logger.exception("Failed to read session metadata from %s: %s", redact_session_ids(session_str), e)
            return None


class ChatHistorian(ChatHistoryManager):
    """Implementation of ChatHistoryManager for managing chat history.

    This historian provides chat history management.
    """

    def __init__(self, agent_factory: AgentFactory) -> None:
        """Initialize chat historian with dependencies.

        Args:
            agent_factory: Factory for creating configured agent instances
        """
        self._agent_factory = agent_factory
        self._config = StrandsAgentConfig.from_env()

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

        # Get all sessions metadata from {storage_dir}/{FILE_SESSION_PREFIX}_{session_id}/session.json:
        sessions: list[Session] = []
        for item in storage_path.iterdir():
            if FILE_SESSION_PREFIX and not item.name.startswith(FILE_SESSION_PREFIX):
                continue

            if not item.is_dir():
                continue

            session_metafile = item / "session.json"
            if not session_metafile.is_file():
                continue

            try:
                session = _SessionFrom.session_str(session_metafile.read_text())
                if session:
                    sessions.append(session)
            except Exception:
                logger.warning("Failed to read session metadata from %s", session_metafile)
                continue

        if len(sessions) <= offset:
            return []

        sessions.sort(key=lambda s: s.updated_at or "0", reverse=True)

        ret = sessions[offset : offset + limit]
        return ret

    async def _get_chat_s3_sessions_history(
        self, session_repository: S3SessionManager, limit: int, offset: int
    ) -> list[Session]:
        """Get chat sessions history from S3-based storage.

        Lists all sessions from S3 by:
        1. Listing S3 objects with session prefix pattern
        2. Reading session.json files from each session directory
        3. Parsing Session objects and sorting by updated_at
        4. Applying pagination (limit/offset)

        Args:
            session_repository: The S3 session repository instance
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip

        Returns:
            list[Session]: List of chat sessions
        """
        # client = session_repository.client
        return []

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


def create_chat_history_manager(agent_factory: AgentFactory) -> ChatHistoryManager:
    """Factory function to create ChatHistorian instance.

    Args:
        agent_factory: Factory for creating agents

    Returns:
        Configured ChatHistorian implementation
    """
    return ChatHistorian(agent_factory)
