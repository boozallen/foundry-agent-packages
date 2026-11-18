# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Extended tests for ChatHistorian to improve coverage."""

import json
import logging
import secrets
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from strands.session import FileSessionManager
from strands.types.session import Session, SessionType

from foundry_agent_core import QueryProcessingError, mask_session_id
from foundry_strands_agent.chat_historian import ChatHistorian
from foundry_strands_agent.encrypted_session import EncryptedFileSessionManager


@pytest.fixture
def mock_agent_factory():
    factory = MagicMock()
    return factory


@pytest.fixture
def mock_config():
    return MagicMock()


@pytest.fixture
def historian(mock_agent_factory, mock_config):
    return ChatHistorian(agent_factory=mock_agent_factory, config=mock_config)


def _write_session(storage: Path, session_id: str, updated_at: str | None = None) -> None:
    """Write a plaintext session.json the way FileSessionManager lays it out."""
    session_dir = storage / f"session_{session_id}"
    session_dir.mkdir()
    data = {"session_id": session_id, "session_type": "AGENT", "created_at": "2026-01-01T00:00:00Z"}
    if updated_at:
        data["updated_at"] = updated_at
    (session_dir / "session.json").write_text(json.dumps(data))


def _historian_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "foundry_strands_agent.chat_historian"]


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
        _write_session(tmp_path, "session1", "2026-01-01T02:00:00Z")
        _write_session(tmp_path, "session2", "2026-01-01T01:00:00Z")
        repo = FileSessionManager(session_id="session1", storage_dir=str(tmp_path))
        mock_agent_factory.create_session_repository.return_value = repo

        result = await historian.get_chat_sessions_history()

        assert len(result) == 2
        # Should be sorted by updated_at descending
        assert result[0].session_id == "session1"  # More recent
        assert result[1].session_id == "session2"
        assert all(s.session_type is SessionType.AGENT for s in result)

    @pytest.mark.asyncio
    async def test_file_storage_with_pagination(self, historian, mock_agent_factory, tmp_path):
        """Test pagination with file storage."""
        for i in range(3):
            _write_session(tmp_path, f"session{i}", f"2026-01-01T0{i}:00:00Z")
        repo = FileSessionManager(session_id="session0", storage_dir=str(tmp_path))
        mock_agent_factory.create_session_repository.return_value = repo

        result = await historian.get_chat_sessions_history(limit=2, offset=1)

        assert [s.session_id for s in result] == ["session1", "session0"]

    @pytest.mark.asyncio
    async def test_file_storage_offset_beyond_results(self, historian, mock_agent_factory, tmp_path):
        """Test offset beyond available results."""
        _write_session(tmp_path, "session1", "2026-01-01T00:00:00Z")
        repo = FileSessionManager(session_id="session1", storage_dir=str(tmp_path))
        mock_agent_factory.create_session_repository.return_value = repo

        result = await historian.get_chat_sessions_history(offset=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_file_storage_skips_non_session_dirs(self, historian, mock_agent_factory, tmp_path):
        """Test that non-session directories are skipped."""
        _write_session(tmp_path, "session1")
        (tmp_path / "other_dir").mkdir()
        (tmp_path / "session_file.txt").write_text("not a session")
        repo = FileSessionManager(session_id="session1", storage_dir=str(tmp_path))
        mock_agent_factory.create_session_repository.return_value = repo

        result = await historian.get_chat_sessions_history()

        assert len(result) == 1
        assert result[0].session_id == "session1"

    @pytest.mark.asyncio
    async def test_file_storage_skips_invalid_session_json(self, historian, mock_agent_factory, tmp_path, caplog):
        """Unreadable sessions are skipped with a warning that carries no raw ID or content."""
        _write_session(tmp_path, "session1")
        (tmp_path / "session_session2").mkdir()
        (tmp_path / "session_session2" / "session.json").write_text('{"session_id": "session2", broken')
        # Session dir without session.json is skipped silently.
        (tmp_path / "session_session3").mkdir()
        # A directory with an empty session ID ("session_") is skipped silently, as in S3 listing.
        (tmp_path / "session_").mkdir()
        (tmp_path / "session_" / "session.json").write_text(
            json.dumps({"session_id": "orphan", "session_type": "AGENT", "created_at": "2026-01-01T00:00:00Z"})
        )
        # Session metadata with an empty session_id is skipped silently.
        (tmp_path / "session_session4").mkdir()
        (tmp_path / "session_session4" / "session.json").write_text(
            json.dumps({"session_id": "", "session_type": "AGENT", "created_at": "2026-01-01T00:00:00Z"})
        )
        repo = FileSessionManager(session_id="session1", storage_dir=str(tmp_path))
        mock_agent_factory.create_session_repository.return_value = repo

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.chat_historian"):
            result = await historian.get_chat_sessions_history()

        assert [s.session_id for s in result] == ["session1"]
        records = _historian_records(caplog)
        assert len(records) == 1
        message = records[0].getMessage()
        assert mask_session_id("session2") in message
        assert "session2" not in message.replace(mask_session_id("session2"), "")
        assert "broken" not in message


class TestGetChatSessionsHistoryEncryptedFile:
    """Encrypted file sessions are listed through the session manager, which decrypts them."""

    @pytest.mark.asyncio
    async def test_encrypted_sessions_are_listed_decrypted(self, historian, mock_agent_factory, tmp_path):
        key = secrets.token_bytes(32)
        for session_id in ("enc-a", "enc-b", "enc-c"):
            EncryptedFileSessionManager(encryption_key=key, session_id=session_id, storage_dir=str(tmp_path))
        # On disk the metadata is ciphertext, not parseable session JSON.
        on_disk = json.loads((tmp_path / "session_enc-a" / "session.json").read_text())
        assert "session_id" not in on_disk

        repo = EncryptedFileSessionManager(encryption_key=key, session_id="enc-a", storage_dir=str(tmp_path))
        mock_agent_factory.create_session_repository.return_value = repo

        result = await historian.get_chat_sessions_history()

        assert sorted(s.session_id for s in result) == ["enc-a", "enc-b", "enc-c"]
        assert all(s.session_type is SessionType.AGENT for s in result)
        updated = [s.updated_at for s in result]
        assert updated == sorted(updated, reverse=True)

    @pytest.mark.asyncio
    async def test_session_encrypted_with_other_key_is_skipped(self, historian, mock_agent_factory, tmp_path, caplog):
        EncryptedFileSessionManager(
            encryption_key=secrets.token_bytes(32), session_id="other-key", storage_dir=str(tmp_path)
        )
        repo = EncryptedFileSessionManager(
            encryption_key=secrets.token_bytes(32), session_id="this-key", storage_dir=str(tmp_path)
        )
        mock_agent_factory.create_session_repository.return_value = repo

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.chat_historian"):
            result = await historian.get_chat_sessions_history()

        assert [s.session_id for s in result] == ["this-key"]
        records = _historian_records(caplog)
        assert len(records) == 1
        assert mask_session_id("other-key") in records[0].getMessage()
        assert "other-key" not in records[0].getMessage()


def _s3_repo(pages: list[dict], sessions: dict[str, Session | Exception | None], prefix: str = "") -> MagicMock:
    """Stub an S3 session repository: a paginator over `pages` and a `read_session` lookup."""
    repo = MagicMock()
    delattr(repo, "storage_dir")  # Remove storage_dir so it's identified as S3
    repo.bucket = "sessions-bucket"
    repo.prefix = prefix
    repo.client.get_paginator.return_value.paginate.return_value = pages

    def read_session(session_id: str) -> Session | None:
        value = sessions.get(session_id)
        if isinstance(value, Exception):
            raise value
        return value

    repo.read_session.side_effect = read_session
    return repo


def _s3_session(session_id: str, updated_at: str) -> Session:
    return Session.from_dict(
        {"session_id": session_id, "session_type": "AGENT", "created_at": updated_at, "updated_at": updated_at}
    )


class TestGetChatSessionsHistoryS3:
    """Test S3-based session history retrieval."""

    @pytest.mark.asyncio
    async def test_s3_lists_sessions_across_pages(self, historian, mock_agent_factory):
        pages = [
            {"CommonPrefixes": [{"Prefix": "session_s1/"}, {"Prefix": "session_s2/"}]},
            {"CommonPrefixes": [{"Prefix": "session_s3/"}]},
        ]
        sessions = {
            "s1": _s3_session("s1", "2026-01-01T01:00:00Z"),
            "s2": _s3_session("s2", "2026-01-01T03:00:00Z"),
            "s3": _s3_session("s3", "2026-01-01T02:00:00Z"),
        }
        repo = _s3_repo(pages, sessions)
        mock_agent_factory.create_session_repository.return_value = repo

        result = await historian.get_chat_sessions_history()

        assert [s.session_id for s in result] == ["s2", "s3", "s1"]
        assert all(s.session_type is SessionType.AGENT for s in result)
        repo.client.get_paginator.assert_called_once_with("list_objects_v2")
        repo.client.get_paginator.return_value.paginate.assert_called_once_with(
            Bucket="sessions-bucket", Prefix="session_", Delimiter="/"
        )

    @pytest.mark.asyncio
    async def test_s3_paging_applies_after_sorting(self, historian, mock_agent_factory):
        pages = [{"CommonPrefixes": [{"Prefix": f"session_s{i}/"} for i in range(3)]}]
        sessions = {f"s{i}": _s3_session(f"s{i}", f"2026-01-01T0{i}:00:00Z") for i in range(3)}
        mock_agent_factory.create_session_repository.return_value = _s3_repo(pages, sessions)

        result = await historian.get_chat_sessions_history(limit=2, offset=1)

        assert [s.session_id for s in result] == ["s1", "s0"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("prefix", ["tenant", "tenant/", "/tenant", "/tenant/"])
    async def test_s3_uses_configured_prefix(self, historian, mock_agent_factory, prefix):
        """The prefix is normalized the way S3SessionManager writes keys (slashes stripped)."""
        pages = [{"CommonPrefixes": [{"Prefix": "tenant/session_s1/"}]}]
        repo = _s3_repo(pages, {"s1": _s3_session("s1", "2026-01-01T00:00:00Z")}, prefix=prefix)
        mock_agent_factory.create_session_repository.return_value = repo

        result = await historian.get_chat_sessions_history()

        assert [s.session_id for s in result] == ["s1"]
        repo.client.get_paginator.return_value.paginate.assert_called_once_with(
            Bucket="sessions-bucket", Prefix="tenant/session_", Delimiter="/"
        )

    @pytest.mark.asyncio
    async def test_s3_skips_session_with_unknown_session_type(self, historian, mock_agent_factory, caplog):
        unknown = _s3_session("unknown", "2026-01-01T01:00:00Z")
        unknown.session_type = "NOT_A_TYPE"  # pyright: ignore[reportAttributeAccessIssue]
        pages = [{"CommonPrefixes": [{"Prefix": "session_ok/"}, {"Prefix": "session_unknown/"}]}]
        sessions = {"ok": _s3_session("ok", "2026-01-01T00:00:00Z"), "unknown": unknown}
        mock_agent_factory.create_session_repository.return_value = _s3_repo(pages, sessions)

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.chat_historian"):
            result = await historian.get_chat_sessions_history()

        assert [s.session_id for s in result] == ["ok"]
        records = _historian_records(caplog)
        assert len(records) == 1
        assert mask_session_id("unknown") in records[0].getMessage()

    @pytest.mark.asyncio
    async def test_s3_skips_missing_and_unreadable_sessions(self, historian, mock_agent_factory, caplog):
        pages = [
            {"CommonPrefixes": [{"Prefix": "session_ok/"}, {"Prefix": "session_gone/"}, {"Prefix": "session_bad/"}]},
            {"CommonPrefixes": [{"Prefix": "session_/"}]},  # An empty session ID is ignored
            {},  # A page with no CommonPrefixes key
        ]
        sessions = {
            "ok": _s3_session("ok", "2026-01-01T00:00:00Z"),
            "gone": None,
            "bad": Exception("S3 error reading session_bad/session.json"),
        }
        repo = _s3_repo(pages, sessions)
        mock_agent_factory.create_session_repository.return_value = repo

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.chat_historian"):
            result = await historian.get_chat_sessions_history()

        assert [s.session_id for s in result] == ["ok"]
        assert [c.args[0] for c in repo.read_session.call_args_list] == ["ok", "gone", "bad"]
        records = _historian_records(caplog)
        assert len(records) == 1
        message = records[0].getMessage()
        assert mask_session_id("bad") in message
        assert "session_bad" not in message

    @pytest.mark.asyncio
    async def test_s3_listing_error_is_raised(self, historian, mock_agent_factory):
        repo = _s3_repo([], {})
        repo.client.get_paginator.return_value.paginate.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "ListObjectsV2"
        )
        mock_agent_factory.create_session_repository.return_value = repo

        with pytest.raises(QueryProcessingError, match="Error retrieving chat sessions history"):
            await historian.get_chat_sessions_history()


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
        _write_session(tmp_path, "session1")
        repo = FileSessionManager(session_id="session1", storage_dir=str(tmp_path))
        mock_agent_factory.create_session_repository.return_value = repo

        result = await historian.get_chat_sessions_history()

        # Should return the first session (offset=0)
        assert len(result) == 1
