# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Restore-time guard against a dangling trailing `tool_use` in session history.

`RepositorySessionManager._fix_broken_tool_use()` (the shared base for both
`FileSessionManager` and `S3SessionManager`) fixes orphaned `toolUse`/`toolResult`
pairs on restore, but explicitly excludes the *last* message - its own comment says
that case is "handled in the agent class". `Agent._convert_prompt_to_messages()` does
handle it, but only when the caller supplies a new prompt; resuming with `prompt=None`
(a normal "continue existing history" pattern) skips that branch entirely, and the
event loop proceeds straight into tool execution with the dangling `tool_use` still
last in the restored history - no model call in between. This is the mechanism
CVE-2026-18830 exploited in Bedrock AgentCore's InvokeHarness API.

This mixin closes that gap uniformly for any `RepositorySessionManager` subclass by
extending its `_fix_broken_tool_use()` seam to also cover the last message.
"""

import logging
from typing import Any, Literal

from strands.tools._tool_helpers import generate_missing_tool_result_content
from strands.types.content import Message

from foundry_agent_core import AgentCreationError, mask_session_id

logger = logging.getLogger(__name__)

DanglingToolUseMode = Literal["sanitize", "reject"]


class DanglingToolUseGuard:
    """Mixin closing the last-message dangling `tool_use` gap left by the SDK.

    Must be mixed in ahead of a `RepositorySessionManager` subclass
    (`FileSessionManager` or `S3SessionManager`) in the MRO, e.g.:
    `class Guarded(DanglingToolUseGuard, FileSessionManager): ...`.
    """

    session_id: str
    _dangling_tool_use_mode: DanglingToolUseMode

    def __init__(self, *args: Any, dangling_tool_use_mode: DanglingToolUseMode = "sanitize", **kwargs: Any) -> None:
        self._dangling_tool_use_mode = dangling_tool_use_mode
        super().__init__(*args, **kwargs)  # pyright: ignore[reportCallIssue]

    def _fix_broken_tool_use(self, messages: list[Message]) -> list[Message]:
        messages = super()._fix_broken_tool_use(messages)  # pyright: ignore[reportAttributeAccessIssue]

        if not messages:
            return messages

        last_message = messages[-1]
        if last_message["role"] != "assistant":
            return messages

        tool_use_ids = [content["toolUse"]["toolUseId"] for content in last_message["content"] if "toolUse" in content]
        if not tool_use_ids:
            return messages

        session_id = getattr(self, "session_id", "unknown")

        if self._dangling_tool_use_mode == "reject":
            logger.warning(
                "Restored session %s ends in an unresolved tool_use; rejecting restore "
                "(session_restore_dangling_tool_use=reject).",
                mask_session_id(session_id),
            )
            raise AgentCreationError(
                "Restored session history ends in an unresolved tool_use block",
                context={"session_id": mask_session_id(session_id)},
            )

        logger.warning(
            "Restored session %s ends in an unresolved tool_use; appending a synthetic "
            "tool_result to resolve it (session_restore_dangling_tool_use=sanitize).",
            mask_session_id(session_id),
        )
        messages.append(
            {
                "role": "user",
                "content": generate_missing_tool_result_content(tool_use_ids),
            }
        )
        return messages
