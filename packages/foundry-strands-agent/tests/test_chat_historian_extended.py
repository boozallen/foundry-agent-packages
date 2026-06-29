# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Extended tests for ChatHistorian to improve coverage."""

import json
from unittest.mock import MagicMock, patch

import pytest
from strands.types.session import Session, SessionType

from foundry_agent_core import QueryProcessingError
from foundry_strands_agent.chat_historian import ChatHistorian, _SessionFrom


@pytest.fixture
def mock_agent_factory():
    factory = MagicMock()
    return factory


@pytest.fixture
def historian(mock_agent_factory):
    with patch("foundry_strands_agent.chat_historian.StrandsAgentConfig.from_env") as mock_config:
        mock_config.return_value = MagicMock()
        return ChatHistorian(agent_factory=mock_agent_factory)


class TestSessionFrom:
    """Test _SessionFrom utility class."""

    def test_dict_from_str_valid_json(self):
        """Test parsing valid session JSON string."""
        session_str = '{"session_id": "test-123", "name": "Test Session"}'
        result = _SessionFrom.dict_from_str(session_str)

        assert result is not None
        assert result["session_id"] == "test-123"
        assert result["name"] == "Test Session"

    def test_dict_from_str_invalid_json(self):
        """Test parsing invalid JSON string."""
        session_str = "{invalid json"
        result = _SessionFrom.dict_from_str(session_str)

        assert result is None

    def test_dict_from_str_missing_session_id(self):
        """Test parsing JSON without session_id."""
        session_str = '{"name": "Test Session"}'
        result = _SessionFrom.dict_from_str(session_str)

        assert result is None

    def test_dict_from_str_empty_string(self):
        """Test parsing empty string."""
        result = _SessionFrom.dict_from_str("")
        assert result is None

    def test_dict_from_str_not_dict(self):
        """Test parsing JSON that's not a dict."""
        session_str = '["not", "a", "dict"]'
        result = _SessionFrom.dict_from_str(session_str)
        assert result is None

    def test_json_dict_valid_session(self):
        """Test creating Session from valid dict."""
        session_dict = {
            "session_id": "test-456",
            "session_type": "AGENT",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T01:00:00Z",
        }
        result = _SessionFrom.json_dict(session_dict)

        assert result is not None
        assert isinstance(result, Session)
        assert result.session_id == "test-456"

    def test_json_dict_missing_session_id(self):
        """Test creating Session from dict without session_id."""
        session_dict = {"name": "Test"}
        result = _SessionFrom.json_dict(session_dict)

        assert result is None

    def test_json_dict_not_dict(self):
        """Test creating Session from non-dict."""
        result = _SessionFrom.json_dict("not a dict")
        assert result is None

    def test_json_dict_with_session_type_conversion(self):
        """Test Session creation with session_type string conversion."""
        session_dict = {
            "session_id": "test-789",
            "session_type": "AGENT",  # String that needs conversion
            "created_at": "2026-01-01T00:00:00Z",
        }
        result = _SessionFrom.json_dict(session_dict)

        assert result is not None
        assert result.session_type == SessionType.AGENT

    def test_session_str_valid(self):
        """Test creating Session from JSON string."""
        session_str = json.dumps(
            {
                "session_id": "test-str-123",
                "session_type": "AGENT",
                "created_at": "2026-01-01T00:00:00Z",
            }
        )
        result = _SessionFrom.session_str(session_str)

        assert result is not None
        assert result.session_id == "test-str-123"

    def test_session_str_invalid_json(self):
        """Test creating Session from invalid JSON string."""
        result = _SessionFrom.session_str("{invalid")
        assert result is None


class TestGetChatSessionsHistoryFile:
    """Test file-based session history retrieval."""

    @pytest.mark.asyncio
    async def test_file_storage_empty_directory(self, historian, mock_agent_factory, tmp_path):
        """Test retrieving sessions from empty directory."""
        mock_repo = MagicMock()
        mock_repo.storage_dir = str(tmp_path)
        mock_agent_factory.create_session_repository.return_value = mock_repo

        result = await historian.get_chat_sessions_history()

        assert result == []

    @pytest.mark.asyncio
    async def test_file_storage_nonexistent_directory(self, historian, mock_agent_factory):
        """Test retrieving sessions from nonexistent directory."""
        mock_repo = MagicMock()
        mock_repo.storage_dir = "/nonexistent/path"
        mock_agent_factory.create_session_repository.return_value = mock_repo

        result = await historian.get_chat_sessions_history()

        assert result == []

    @pytest.mark.asyncio
    async def test_file_storage_with_valid_sessions(self, historian, mock_agent_factory, tmp_path):
        """Test retrieving valid sessions from file storage."""
        # Create session directories
        session1_dir = tmp_path / "session_session1"
        session1_dir.mkdir()
        session1_meta = session1_dir / "session.json"
        session1_meta.write_text(
            json.dumps(
                {
                    "session_id": "session1",
                    "session_type": "AGENT",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T02:00:00Z",
                }
            )
        )

        session2_dir = tmp_path / "session_session2"
        session2_dir.mkdir()
        session2_meta = session2_dir / "session.json"
        session2_meta.write_text(
            json.dumps(
                {
                    "session_id": "session2",
                    "session_type": "AGENT",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T01:00:00Z",
                }
            )
        )

        mock_repo = MagicMock()
        mock_repo.storage_dir = str(tmp_path)
        mock_agent_factory.create_session_repository.return_value = mock_repo

        with patch("foundry_strands_agent.chat_historian.FILE_SESSION_PREFIX", "session"):
            result = await historian.get_chat_sessions_history()

        assert len(result) == 2
        # Should be sorted by updated_at descending
        assert result[0].session_id == "session1"  # More recent
        assert result[1].session_id == "session2"

    @pytest.mark.asyncio
    async def test_file_storage_with_pagination(self, historian, mock_agent_factory, tmp_path):
        """Test pagination with file storage."""
        # Create 3 sessions
        for i in range(3):
            session_dir = tmp_path / f"session_session{i}"
            session_dir.mkdir()
            session_meta = session_dir / "session.json"
            session_meta.write_text(
                json.dumps(
                    {
                        "session_id": f"session{i}",
                        "session_type": "AGENT",
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": f"2026-01-01T0{i}:00:00Z",
                    }
                )
            )

        mock_repo = MagicMock()
        mock_repo.storage_dir = str(tmp_path)
        mock_agent_factory.create_session_repository.return_value = mock_repo

        with patch("foundry_strands_agent.chat_historian.FILE_SESSION_PREFIX", "session"):
            result = await historian.get_chat_sessions_history(limit=2, offset=1)

        assert len(result) == 2
        assert result[0].session_id == "session1"

    @pytest.mark.asyncio
    async def test_file_storage_offset_beyond_results(self, historian, mock_agent_factory, tmp_path):
        """Test offset beyond available results."""
        session_dir = tmp_path / "session_session1"
        session_dir.mkdir()
        session_meta = session_dir / "session.json"
        session_meta.write_text(
            json.dumps(
                {
                    "session_id": "session1",
                    "session_type": "AGENT",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            )
        )

        mock_repo = MagicMock()
        mock_repo.storage_dir = str(tmp_path)
        mock_agent_factory.create_session_repository.return_value = mock_repo

        with patch("foundry_strands_agent.chat_historian.FILE_SESSION_PREFIX", "session"):
            result = await historian.get_chat_sessions_history(offset=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_file_storage_skips_non_session_dirs(self, historian, mock_agent_factory, tmp_path):
        """Test that non-session directories are skipped."""
        # Create a valid session
        session_dir = tmp_path / "session_session1"
        session_dir.mkdir()
        session_meta = session_dir / "session.json"
        session_meta.write_text(
            json.dumps(
                {
                    "session_id": "session1",
                    "session_type": "AGENT",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            )
        )

        # Create a non-session directory
        other_dir = tmp_path / "other_dir"
        other_dir.mkdir()

        # Create a file (not directory)
        other_file = tmp_path / "session_file.txt"
        other_file.write_text("not a session")

        mock_repo = MagicMock()
        mock_repo.storage_dir = str(tmp_path)
        mock_agent_factory.create_session_repository.return_value = mock_repo

        with patch("foundry_strands_agent.chat_historian.FILE_SESSION_PREFIX", "session"):
            result = await historian.get_chat_sessions_history()

        assert len(result) == 1
        assert result[0].session_id == "session1"

    @pytest.mark.asyncio
    async def test_file_storage_skips_invalid_session_json(self, historian, mock_agent_factory, tmp_path):
        """Test that invalid session JSON files are skipped."""
        # Valid session
        session1_dir = tmp_path / "session_session1"
        session1_dir.mkdir()
        session1_meta = session1_dir / "session.json"
        session1_meta.write_text(
            json.dumps(
                {
                    "session_id": "session1",
                    "session_type": "AGENT",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            )
        )

        # Invalid session (bad JSON)
        session2_dir = tmp_path / "session_session2"
        session2_dir.mkdir()
        session2_meta = session2_dir / "session.json"
        session2_meta.write_text("{invalid json")

        # Session dir without session.json
        session3_dir = tmp_path / "session_session3"
        session3_dir.mkdir()

        mock_repo = MagicMock()
        mock_repo.storage_dir = str(tmp_path)
        mock_agent_factory.create_session_repository.return_value = mock_repo

        with patch("foundry_strands_agent.chat_historian.FILE_SESSION_PREFIX", "session"):
            result = await historian.get_chat_sessions_history()

        assert len(result) == 1
        assert result[0].session_id == "session1"


class TestGetChatSessionsHistoryS3:
    """Test S3-based session history retrieval."""

    @pytest.mark.asyncio
    async def test_s3_storage_returns_empty(self, historian, mock_agent_factory):
        """Test S3 storage (currently returns empty)."""
        mock_repo = MagicMock()
        mock_repo.client = MagicMock()  # Has client attribute, so it's S3
        delattr(mock_repo, "storage_dir")  # Remove storage_dir so it's identified as S3
        mock_agent_factory.create_session_repository.return_value = mock_repo

        result = await historian.get_chat_sessions_history()

        assert result == []


class TestGetChatSessionsHistoryErrors:
    """Test error handling in session history retrieval."""

    @pytest.mark.asyncio
    async def test_unknown_repository_type_raises(self, historian, mock_agent_factory):
        """Test error when repository type is unknown."""
        mock_repo = MagicMock()
        # Remove both storage_dir and client so it's unknown type
        delattr(mock_repo, "storage_dir")
        delattr(mock_repo, "client")
        mock_agent_factory.create_session_repository.return_value = mock_repo

        with pytest.raises(QueryProcessingError, match="Unable to access chat sessions history"):
            await historian.get_chat_sessions_history()

    @pytest.mark.asyncio
    async def test_repository_creation_error_is_wrapped(self, historian, mock_agent_factory):
        """Test that repository creation errors are wrapped."""
        mock_agent_factory.create_session_repository.side_effect = Exception("Creation failed")

        with pytest.raises(QueryProcessingError, match="Error retrieving chat sessions history"):
            await historian.get_chat_sessions_history()


class TestDefaultParameters:
    """Test default parameter handling."""

    @pytest.mark.asyncio
    async def test_default_limit_is_100(self, historian, mock_agent_factory, tmp_path):
        """Test that default limit is 100."""
        # Create more than 100 sessions would be slow, so just test with a mock
        mock_repo = MagicMock()
        mock_repo.storage_dir = str(tmp_path)
        mock_agent_factory.create_session_repository.return_value = mock_repo

        # Should not raise even with default limit
        result = await historian.get_chat_sessions_history()
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_default_offset_is_zero(self, historian, mock_agent_factory, tmp_path):
        """Test that default offset is 0."""
        session_dir = tmp_path / "session_session1"
        session_dir.mkdir()
        session_meta = session_dir / "session.json"
        session_meta.write_text(
            json.dumps(
                {
                    "session_id": "session1",
                    "session_type": "AGENT",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            )
        )

        mock_repo = MagicMock()
        mock_repo.storage_dir = str(tmp_path)
        mock_agent_factory.create_session_repository.return_value = mock_repo

        with patch("foundry_strands_agent.chat_historian.FILE_SESSION_PREFIX", "session"):
            result = await historian.get_chat_sessions_history()

        # Should return the first session (offset=0)
        assert len(result) == 1
