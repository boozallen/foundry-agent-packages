# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for DanglingToolUseGuard."""

import logging
from typing import Any

import pytest
from strands.session.repository_session_manager import RepositorySessionManager
from strands.session.session_repository import SessionRepository
from strands.types.session import Session, SessionAgent, SessionMessage

from foundry_agent_core import AgentCreationError
from foundry_agent_core.masking import mask_session_id
from foundry_strands_agent.session_guard import DanglingToolUseGuard


class _FakeSessionRepository(SessionRepository):
    """Minimal in-memory stub - only `read_session`/`create_session` are exercised."""

    def create_session(self, session: Session, **kwargs: Any) -> Session:
        return session

    def read_session(self, session_id: str, **kwargs: Any) -> Session | None:
        return None

    def create_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        pass

    def read_agent(self, session_id: str, agent_id: str, **kwargs: Any) -> SessionAgent | None:
        return None

    def update_agent(self, session_id: str, session_agent: SessionAgent, **kwargs: Any) -> None:
        pass

    def create_message(self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any) -> None:
        pass

    def read_message(self, session_id: str, agent_id: str, message_id: int, **kwargs: Any) -> SessionMessage | None:
        return None

    def update_message(self, session_id: str, agent_id: str, session_message: SessionMessage, **kwargs: Any) -> None:
        pass

    def list_messages(
        self, session_id: str, agent_id: str, limit: int | None = None, offset: int = 0, **kwargs: Any
    ) -> list[SessionMessage]:
        return []

    def create_multi_agent(self, session_id: str, multi_agent: Any, **kwargs: Any) -> None:
        pass

    def read_multi_agent(self, session_id: str, multi_agent_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return None

    def update_multi_agent(self, session_id: str, multi_agent: Any, **kwargs: Any) -> None:
        pass


class GuardedRepositorySessionManager(DanglingToolUseGuard, RepositorySessionManager):
    """Real RepositorySessionManager mixed with the guard - not a fake/stub of the guard itself."""


def _make_manager(session_id: str = "sess-1", **kwargs: Any) -> GuardedRepositorySessionManager:
    return GuardedRepositorySessionManager(session_id=session_id, session_repository=_FakeSessionRepository(), **kwargs)


def _dangling_tool_use_messages() -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": [{"text": "do something"}]},
        {
            "role": "assistant",
            "content": [{"toolUse": {"toolUseId": "tool-1", "name": "some_tool", "input": {}}}],
        },
    ]


class TestSanitizeMode:
    def test_dangling_last_message_tool_use_is_resolved(self):
        mgr = _make_manager()
        messages = _dangling_tool_use_messages()

        result = mgr._fix_broken_tool_use(messages)

        assert result[-1]["role"] == "user"
        assert any("toolResult" in block for block in result[-1]["content"])
        result_ids = [block["toolResult"]["toolUseId"] for block in result[-1]["content"] if "toolResult" in block]
        assert result_ids == ["tool-1"]

    def test_is_default_mode(self):
        mgr = _make_manager()
        assert mgr._dangling_tool_use_mode == "sanitize"

    def test_logs_warning_with_masked_session_id(self, caplog):
        mgr = _make_manager(session_id="s3cr3t-session")
        with caplog.at_level(logging.WARNING):
            mgr._fix_broken_tool_use(_dangling_tool_use_messages())

        assert "s3cr3t-session" not in caplog.text
        assert mask_session_id("s3cr3t-session") in caplog.text


class TestRejectMode:
    def test_dangling_last_message_tool_use_raises(self):
        mgr = _make_manager(dangling_tool_use_mode="reject")

        with pytest.raises(AgentCreationError):
            mgr._fix_broken_tool_use(_dangling_tool_use_messages())

    def test_accepts_reject_literal(self):
        mgr = _make_manager(dangling_tool_use_mode="reject")
        assert mgr._dangling_tool_use_mode == "reject"

    def test_logs_warning_with_masked_session_id_before_raising(self, caplog):
        mgr = _make_manager(session_id="s3cr3t-session", dangling_tool_use_mode="reject")
        with caplog.at_level(logging.WARNING), pytest.raises(AgentCreationError):
            mgr._fix_broken_tool_use(_dangling_tool_use_messages())

        assert "s3cr3t-session" not in caplog.text
        assert mask_session_id("s3cr3t-session") in caplog.text


class TestNoOpCase:
    def test_no_dangling_tool_use_returns_unchanged(self, caplog):
        mgr = _make_manager()
        messages = [
            {"role": "user", "content": [{"text": "hello"}]},
            {"role": "assistant", "content": [{"text": "hi there"}]},
        ]

        with caplog.at_level(logging.WARNING):
            result = mgr._fix_broken_tool_use(list(messages))

        assert result == messages
        assert caplog.text == ""

    def test_resolved_tool_use_returns_unchanged(self, caplog):
        mgr = _make_manager()
        messages = [
            {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "tool-1", "name": "some_tool", "input": {}}}],
            },
            {"role": "user", "content": [{"toolResult": {"toolUseId": "tool-1", "status": "success", "content": []}}]},
        ]

        with caplog.at_level(logging.WARNING):
            result = mgr._fix_broken_tool_use(list(messages))

        assert result == messages
        assert caplog.text == ""

    def test_empty_messages_returns_unchanged(self):
        mgr = _make_manager()
        assert mgr._fix_broken_tool_use([]) == []

    def test_mid_history_orphan_still_fixed_by_sdk(self):
        """The guard must not break the SDK's own mid-history fix-up (super() call)."""
        mgr = _make_manager()
        messages = [
            {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "mid-tool", "name": "some_tool", "input": {}}}],
            },
            {"role": "assistant", "content": [{"text": "unrelated follow-up"}]},
        ]

        result = mgr._fix_broken_tool_use(list(messages))

        # SDK's own mid-history fix inserts a synthetic tool_result between the two messages.
        assert len(result) == 3
        assert any("toolResult" in block for block in result[1]["content"])
