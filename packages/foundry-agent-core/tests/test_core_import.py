# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for foundry-agent-core package."""

import pytest

import foundry_agent_core


def test_import():
    assert foundry_agent_core is not None


def test_ac1_key_imports():
    """AC1: All key imports succeed."""
    from foundry_agent_core import AgentBackend, AgentRequest, AgentResponse, FunctionalDependencyContainer

    assert AgentBackend is not None
    assert AgentRequest is not None
    assert AgentResponse is not None
    assert FunctionalDependencyContainer is not None


def test_protocol_imports():
    """Protocol submodule imports succeed."""
    from foundry_agent_core.protocols import (
        AgentBackend,
        DependencyContainer,
        ErrorTranslator,
        QueryProcessor,
        ResponseProcessor,
    )

    assert AgentBackend is not None
    assert DependencyContainer is not None
    assert ErrorTranslator is not None
    assert QueryProcessor is not None
    assert ResponseProcessor is not None


def test_exception_imports_and_hierarchy():
    """Exception hierarchy is intact."""
    from foundry_agent_core.exceptions import (
        AgentCreationError,
        AgentError,
        ConfigurationError,
        DomainError,
        ExternalServiceError,
        InvalidConfigurationError,
        QueryProcessingError,
        QueryTimeoutError,
        ValidationError,
    )

    assert issubclass(AgentError, DomainError)
    assert issubclass(AgentCreationError, AgentError)
    assert issubclass(ConfigurationError, DomainError)
    assert issubclass(InvalidConfigurationError, ConfigurationError)
    assert issubclass(QueryProcessingError, DomainError)
    assert issubclass(QueryTimeoutError, QueryProcessingError)
    assert issubclass(ExternalServiceError, DomainError)
    assert issubclass(ValidationError, DomainError)


def test_agent_request_validation():
    """AgentRequest validates fields."""
    from foundry_agent_core.types import AgentRequest

    req = AgentRequest(query="Hello")
    assert req.query == "Hello"
    assert req.session_id is None
    assert req.context is None

    with pytest.raises(ValueError):
        AgentRequest(query="")

    with pytest.raises(ValueError):
        AgentRequest(query="test", session_id="")


def test_agent_response_validation():
    """AgentResponse validates fields."""
    from foundry_agent_core.types import AgentResponse

    resp = AgentResponse(content="Answer", processing_time_ms=42.0)
    assert resp.content == "Answer"
    assert resp.processing_time_ms == 42.0

    with pytest.raises(ValueError):
        AgentResponse(content="", processing_time_ms=10.0)

    with pytest.raises(ValueError):
        AgentResponse(content="ok", processing_time_ms=-1.0)


def test_agent_backend_protocol_structural_subtyping():
    """AC3: A class satisfying AgentBackend structurally is accepted."""
    from foundry_agent_core.protocols import AgentBackend
    from foundry_agent_core.types import AgentRequest, AgentResponse

    class MyBackend:
        @property
        def name(self) -> str:
            return "test"

        @property
        def description(self) -> str:
            return "test backend"

        async def process_message(self, request: AgentRequest) -> AgentResponse:
            return AgentResponse(content="ok", processing_time_ms=1.0)

    backend: AgentBackend = MyBackend()  # type: ignore[assignment]
    assert backend.name == "test"
    assert backend.description == "test backend"


def test_agent_request_boundary_pass():
    """STIG V-222612: AgentRequest accepts inputs at the maximum bounds."""
    from foundry_agent_core.types import (
        _MAX_QUERY_LEN,
        _MAX_SESSION_ID_LEN,
        AgentRequest,
    )

    req = AgentRequest(
        query="q" * _MAX_QUERY_LEN,
        session_id="s" * _MAX_SESSION_ID_LEN,
    )
    assert len(req.query) == _MAX_QUERY_LEN
    assert req.session_id is not None
    assert len(req.session_id) == _MAX_SESSION_ID_LEN


def test_agent_request_oversized_query_rejected():
    """STIG V-222612: AgentRequest rejects oversized query (boundary+1)."""
    from pydantic import ValidationError as PydanticValidationError

    from foundry_agent_core.types import _MAX_QUERY_LEN, AgentRequest

    with pytest.raises(PydanticValidationError):
        AgentRequest(query="q" * (_MAX_QUERY_LEN + 1))


def test_agent_request_oversized_session_id_rejected():
    """STIG V-222612: AgentRequest rejects oversized session_id (boundary+1)."""
    from pydantic import ValidationError as PydanticValidationError

    from foundry_agent_core.types import _MAX_SESSION_ID_LEN, AgentRequest

    with pytest.raises(PydanticValidationError):
        AgentRequest(query="ok", session_id="s" * (_MAX_SESSION_ID_LEN + 1))


def test_agent_response_boundary_pass():
    """STIG V-222612: AgentResponse accepts inputs at the maximum bounds."""
    from foundry_agent_core.types import (
        _MAX_CONTENT_LEN,
        _MAX_PROCESSING_TIME_MS,
        _MAX_SESSION_ID_LEN,
        AgentResponse,
    )

    resp = AgentResponse(
        content="c" * _MAX_CONTENT_LEN,
        session_id="s" * _MAX_SESSION_ID_LEN,
        processing_time_ms=float(_MAX_PROCESSING_TIME_MS),
    )
    assert len(resp.content) == _MAX_CONTENT_LEN
    assert resp.processing_time_ms == float(_MAX_PROCESSING_TIME_MS)


def test_agent_response_oversized_content_rejected():
    """STIG V-222612: AgentResponse rejects oversized content (boundary+1)."""
    from pydantic import ValidationError as PydanticValidationError

    from foundry_agent_core.types import _MAX_CONTENT_LEN, AgentResponse

    with pytest.raises(PydanticValidationError):
        AgentResponse(content="c" * (_MAX_CONTENT_LEN + 1), processing_time_ms=1.0)


def test_agent_response_oversized_session_id_rejected():
    """STIG V-222612: AgentResponse rejects oversized session_id (boundary+1)."""
    from pydantic import ValidationError as PydanticValidationError

    from foundry_agent_core.types import _MAX_SESSION_ID_LEN, AgentResponse

    with pytest.raises(PydanticValidationError):
        AgentResponse(
            content="ok",
            session_id="s" * (_MAX_SESSION_ID_LEN + 1),
            processing_time_ms=1.0,
        )


def test_agent_response_excessive_processing_time_rejected():
    """STIG V-222612: AgentResponse rejects processing_time_ms above 24h."""
    from pydantic import ValidationError as PydanticValidationError

    from foundry_agent_core.types import _MAX_PROCESSING_TIME_MS, AgentResponse

    with pytest.raises(PydanticValidationError):
        AgentResponse(content="ok", processing_time_ms=float(_MAX_PROCESSING_TIME_MS + 1))


def test_agent_request_context_too_many_keys_rejected():
    """STIG V-222612: AgentRequest rejects context dict exceeding key count."""
    from pydantic import ValidationError as PydanticValidationError

    from foundry_agent_core.types import _MAX_DICT_KEYS, AgentRequest

    oversized = {f"k{i}": i for i in range(_MAX_DICT_KEYS + 1)}
    with pytest.raises(PydanticValidationError):
        AgentRequest(query="ok", context=oversized)


def test_agent_request_context_oversized_key_rejected():
    """STIG V-222612: AgentRequest rejects context with an oversized key."""
    from pydantic import ValidationError as PydanticValidationError

    from foundry_agent_core.types import _MAX_DICT_KEY_LEN, AgentRequest

    with pytest.raises(PydanticValidationError):
        AgentRequest(query="ok", context={"x" * (_MAX_DICT_KEY_LEN + 1): "v"})


def test_agent_request_context_oversized_payload_rejected():
    """STIG V-222612: AgentRequest rejects context whose JSON payload is too big."""
    from pydantic import ValidationError as PydanticValidationError

    from foundry_agent_core.types import _MAX_DICT_BYTES, AgentRequest

    big_value = "v" * (_MAX_DICT_BYTES + 16)
    with pytest.raises(PydanticValidationError):
        AgentRequest(query="ok", context={"k": big_value})


def test_agent_response_metadata_oversized_payload_rejected():
    """STIG V-222612: AgentResponse rejects metadata whose JSON payload is too big."""
    from pydantic import ValidationError as PydanticValidationError

    from foundry_agent_core.types import _MAX_DICT_BYTES, AgentResponse

    big_value = "v" * (_MAX_DICT_BYTES + 16)
    with pytest.raises(PydanticValidationError):
        AgentResponse(content="ok", processing_time_ms=1.0, metadata={"k": big_value})


def test_agent_response_metadata_too_many_keys_rejected():
    """STIG V-222612: AgentResponse rejects metadata exceeding key count."""
    from pydantic import ValidationError as PydanticValidationError

    from foundry_agent_core.types import _MAX_DICT_KEYS, AgentResponse

    oversized = {f"k{i}": i for i in range(_MAX_DICT_KEYS + 1)}
    with pytest.raises(PydanticValidationError):
        AgentResponse(content="ok", processing_time_ms=1.0, metadata=oversized)


def test_bound_constants_are_positive_ints():
    """STIG V-222612: bound constants are positive integers importable from types."""
    from foundry_agent_core.types import (
        _MAX_CONTENT_LEN,
        _MAX_DICT_BYTES,
        _MAX_DICT_KEY_LEN,
        _MAX_DICT_KEYS,
        _MAX_PROCESSING_TIME_MS,
        _MAX_QUERY_LEN,
        _MAX_SESSION_ID_LEN,
    )

    for value in (
        _MAX_QUERY_LEN,
        _MAX_CONTENT_LEN,
        _MAX_SESSION_ID_LEN,
        _MAX_DICT_KEYS,
        _MAX_DICT_KEY_LEN,
        _MAX_DICT_BYTES,
        _MAX_PROCESSING_TIME_MS,
    ):
        assert isinstance(value, int)
        assert value > 0


def test_di_container_basic():
    """DI container basic register and resolve."""
    from foundry_agent_core.container import FunctionalDependencyContainer

    container = FunctionalDependencyContainer()
    container.register_factory(str, lambda: "hello", singleton=True)
    assert container.resolve(str) == "hello"


class TestAgentRequestSerialization:
    """Test AgentRequest session_id serialization masking (STIG V-222577)."""

    def test_session_id_redacted_in_serialized_output(self):
        """Serialized output must redact session_id."""
        from foundry_agent_core.types import AgentRequest

        raw = "super-secret-session-id"
        req = AgentRequest(session_id=raw, query="Test")

        # In-memory: preserved
        assert req.session_id == raw

        # Serialized: raw NOT present, masked present
        dumped = req.model_dump()
        assert dumped["session_id"] != raw
        assert dumped["session_id"].startswith("sid:")

        dumped_json = req.model_dump_json()
        assert raw not in dumped_json
        assert "sid:" in dumped_json

    def test_none_session_id_serializes_to_none(self):
        """None session_id serializes to None, not a placeholder."""
        from foundry_agent_core.types import AgentRequest

        req = AgentRequest(query="Test", session_id=None)
        dumped = req.model_dump()
        assert dumped["session_id"] is None


class TestAgentResponseSerialization:
    """Test AgentResponse session_id serialization masking (STIG V-222577)."""

    def test_session_id_redacted_in_serialized_output(self):
        """Serialized output must redact session_id."""
        from foundry_agent_core.types import AgentResponse

        raw = "super-secret-session-id"
        resp = AgentResponse(
            content="Test response",
            session_id=raw,
            processing_time_ms=100.0,
        )

        # In-memory: preserved
        assert resp.session_id == raw

        # Serialized: raw NOT present, masked present
        dumped = resp.model_dump()
        assert dumped["session_id"] != raw
        assert dumped["session_id"].startswith("sid:")

        dumped_json = resp.model_dump_json()
        assert raw not in dumped_json
        assert "sid:" in dumped_json
