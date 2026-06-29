# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Integration tests for session-ID masking in the rewired strands classes.

The masking *utility* now lives in ``foundry_agent_core`` and is unit-tested
there (``foundry_agent_core/tests/test_masking.py``). These tests assert the
*strands integration*: that the classes we rewired to import from core actually
route ``session_id`` through masking at their log / serialization emission
boundaries, so a raw identifier never reaches a log record (STIG V-222577).

Each test drives the real class and inspects the emitted ``LogRecord`` (or
serialized output) for the raw value. We deliberately do not re-test the hash
algorithm here — only that these call sites mask.
"""

import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundry_agent_core import AgentRequest, AgentResponse, mask_session_id
from foundry_strands_agent.backend import StrandsAgentBackend
from foundry_strands_agent.chat_historian import _SessionFrom
from foundry_strands_agent.lifecycle import ExecutionStrategy, RequestLifecycleManager
from foundry_strands_agent.orchestrator import QueryOrchestrator
from foundry_strands_agent.response_processor import DefaultResponseProcessor
from foundry_strands_agent.service import AgentService

# A recognizable raw session id used across these tests. If this literal ever
# appears in a log record's session_id field or in serialized output, masking
# at that boundary has regressed.
RAW_SID = "super-secret-session-id"
MASKED_SID = mask_session_id(RAW_SID)


def _session_id_values(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return every ``session_id`` value attached to a captured log record."""
    return [r.session_id for r in caplog.records if hasattr(r, "session_id")]


class TestLifecycleManagerMasking:
    """RequestLifecycleManager must mask session_id in its log extras."""

    @pytest.mark.asyncio
    async def test_create_execution_context_with_session_id_masks_in_logs(self, caplog):
        manager = RequestLifecycleManager(MagicMock())
        request = AgentRequest(query="test", session_id=RAW_SID)

        with caplog.at_level(logging.INFO, logger="foundry_strands_agent.lifecycle"):
            async with manager.create_execution_context(
                request=request,
                strategy=ExecutionStrategy.STANDARD,
                timeout_ms=5000,
            ) as ctx:
                # Runtime value is preserved for session use.
                assert ctx.session_id == RAW_SID

        emitted = _session_id_values(caplog)
        assert emitted, "expected at least one log record carrying session_id"
        assert all(v == MASKED_SID for v in emitted)
        assert RAW_SID not in caplog.text


class TestResponseProcessorMasking:
    """DefaultResponseProcessor must mask session_id in its completion log."""

    @pytest.mark.asyncio
    async def test_process_response_with_session_id_masks_in_logs(self, caplog):
        processor = DefaultResponseProcessor()
        request = AgentRequest(query="what is ai?", session_id=RAW_SID)

        with caplog.at_level(logging.DEBUG, logger="foundry_strands_agent.response_processor"):
            await processor.process_response(
                agent_response="a plain text answer",
                request=request,
                start_time=time.time(),
                query_id="q-1",
            )

        emitted = _session_id_values(caplog)
        assert emitted, "expected the completion log to carry session_id"
        assert all(v == MASKED_SID for v in emitted)
        assert RAW_SID not in caplog.text


class TestChatHistorianRedaction:
    """_SessionFrom must scrub session_id out of logged session blobs on error."""

    def test_dict_from_str_on_parse_failure_redacts_session_id_in_logs(self, caplog):
        # Malformed JSON that still contains a raw session_id -> triggers the
        # except branch which logs the (redacted) blob.
        blob = '{"session_id": "' + RAW_SID + '", "oops": '
        with caplog.at_level(logging.ERROR, logger="foundry_strands_agent.chat_historian"):
            result = _SessionFrom.dict_from_str(blob)

        assert result is None
        assert RAW_SID not in caplog.text
        assert MASKED_SID in caplog.text

    def test_session_str_on_parse_failure_redacts_session_id_in_logs(self, caplog):
        blob = '{"session_id": "' + RAW_SID + '", broken'
        with caplog.at_level(logging.ERROR, logger="foundry_strands_agent.chat_historian"):
            result = _SessionFrom.session_str(blob)

        assert result is None
        assert RAW_SID not in caplog.text
        assert MASKED_SID in caplog.text


class TestBackendMasking:
    """StrandsAgentBackend.process_message must mask session_id in its log extras."""

    @pytest.mark.asyncio
    async def test_process_message_with_session_id_masks_in_logs(self, caplog):
        container = MagicMock()
        config = MagicMock()
        config.agent_name = "test"
        config.agent_description = "test"
        container.resolve.return_value = config

        processor = AsyncMock()
        processor.process_query.return_value = AgentResponse(content="ok", processing_time_ms=10.0)

        with (
            patch("foundry_strands_agent.backend.create_query_processor", return_value=processor),
            patch("foundry_strands_agent.backend.create_response_processor"),
        ):
            backend = StrandsAgentBackend(container)

        request = AgentRequest(query="hi", session_id=RAW_SID)
        with caplog.at_level(logging.INFO, logger="foundry_strands_agent.backend"):
            await backend.process_message(request)

        emitted = _session_id_values(caplog)
        assert emitted, "expected backend to log session_id"
        assert all(v == MASKED_SID for v in emitted)
        assert RAW_SID not in caplog.text


class TestFactorySessionManagerMasking:
    """factory session-manager creation logs must mask session_id.

    These are the exact call sites named in the original STIG finding
    (factory.py:47,69 in the pre-fix source).
    """

    def test_default_file_session_manager_on_creation_masks_session_id_in_logs(self, caplog, tmp_path):
        from foundry_strands_agent.factory import _default_file_session_manager

        with caplog.at_level(logging.INFO, logger="foundry_strands_agent.factory"):
            _default_file_session_manager(session_id=RAW_SID, storage_dir=str(tmp_path))

        emitted = _session_id_values(caplog)
        assert emitted, "expected file session manager creation to log session_id"
        assert all(v == MASKED_SID for v in emitted)
        assert RAW_SID not in caplog.text

    def test_default_s3_session_manager_on_creation_masks_session_id_in_logs(self, caplog):
        from foundry_strands_agent.factory import _default_s3_session_manager

        # S3SessionManager construction touches boto3; patch it so the test stays
        # offline and we only exercise the masked log emission.
        with (
            patch("foundry_strands_agent.factory.S3SessionManager", return_value=MagicMock()),
            caplog.at_level(logging.INFO, logger="foundry_strands_agent.factory"),
        ):
            _default_s3_session_manager(session_id=RAW_SID, s3_bucket="b")

        emitted = _session_id_values(caplog)
        assert emitted, "expected S3 session manager creation to log session_id"
        assert all(v == MASKED_SID for v in emitted)
        assert RAW_SID not in caplog.text


class TestOrchestratorMasking:
    """QueryOrchestrator.process_query must mask session_id in its log extras."""

    @pytest.mark.asyncio
    async def test_process_query_with_session_id_masks_in_logs(self, caplog):
        container = MagicMock()
        factory = MagicMock()
        tool_registry = MagicMock()
        response_processor = MagicMock()

        with patch("foundry_strands_agent.orchestrator.StrandsAgentConfig.from_env") as mock_config:
            cfg = MagicMock()
            cfg.max_query_length = 2000
            cfg.default_similarity_threshold = 0.7
            mock_config.return_value = cfg
            orch = QueryOrchestrator(container, factory, tool_registry, response_processor)

        agent = MagicMock()
        agent.invoke_async = AsyncMock(return_value="answer")
        agent.close = AsyncMock()
        orch._agent_factory.create_agent_with_tool_registry = AsyncMock(return_value=agent)
        orch._response_processor.process_response = AsyncMock(
            return_value=AgentResponse(content="processed", processing_time_ms=10.0)
        )

        request = AgentRequest(query="hello", session_id=RAW_SID)
        with caplog.at_level(logging.INFO, logger="foundry_strands_agent.orchestrator"):
            await orch.process_query(request)

        emitted = _session_id_values(caplog)
        assert emitted, "expected orchestrator to log session_id"
        assert all(v == MASKED_SID for v in emitted)
        assert RAW_SID not in caplog.text


class TestServiceMasking:
    """AgentService.process_query must mask session_id in its log extras."""

    @pytest.mark.asyncio
    async def test_process_query_with_session_id_masks_in_logs(self, caplog):
        container = MagicMock()
        query_processor = AsyncMock()
        query_processor.process_query.return_value = AgentResponse(content="ok", processing_time_ms=10.0)

        with patch("foundry_strands_agent.service.create_request_lifecycle_manager", return_value=MagicMock()):
            svc = AgentService(
                container=container,
                agent_factory=MagicMock(),
                tool_registry=MagicMock(),
                query_processor=query_processor,
                chat_historian=None,
                response_processor=AsyncMock(),
            )

        # Bypass init/session bookkeeping; we only need the entry log to fire.
        svc._initialized = True
        svc._agent_factory = None

        request = AgentRequest(query="hello", session_id=RAW_SID)
        with caplog.at_level(logging.INFO, logger="foundry_strands_agent.service"):
            try:
                await svc.process_query(request)
            except Exception:
                # Downstream pipeline may raise depending on mocks; the entry
                # log (masked session_id) has already been emitted by then.
                pass

        emitted = _session_id_values(caplog)
        assert emitted, "expected service to log session_id"
        assert all(v == MASKED_SID for v in emitted)
        assert RAW_SID not in caplog.text


class TestImportsResolveToCore:
    """The rewired modules import masking from foundry_agent_core, not a local copy."""

    def test_mask_session_id_when_imported_by_strands_modules_is_core_symbol(self):
        import foundry_agent_core
        from foundry_strands_agent import backend, factory, lifecycle, orchestrator, response_processor, service

        # Every module that masks should reference the SAME function object that
        # foundry_agent_core exports — proving the import was repointed.
        core_fn = foundry_agent_core.mask_session_id
        for module in (backend, factory, lifecycle, orchestrator, response_processor, service):
            assert module.mask_session_id is core_fn

    def test_masking_module_when_imported_from_strands_raises_module_not_found(self):
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("foundry_strands_agent.masking")

    def test_mask_session_id_in_strands_public_api_is_absent(self):
        import foundry_strands_agent

        assert "mask_session_id" not in foundry_strands_agent.__all__
