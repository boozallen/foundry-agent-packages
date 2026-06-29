# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for mappers and request/response models."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from foundry_agent_core import AgentRequest, AgentResponse
from foundry_agent_core.exceptions import ResourceNotFoundError
from foundry_agent_fastapi.mappers import (
    api_request_to_domain,
    domain_error_to_api_response,
    domain_response_to_api,
)
from foundry_agent_fastapi.models.requests import QueryAPIRequest


def test_api_request_to_domain_basic():
    """Test converting API request to domain request."""
    api_req = QueryAPIRequest(
        query="What is AI?",
        session_id="session-123",
        context={"user": "john"},
    )

    domain_req = api_request_to_domain(api_req)

    assert isinstance(domain_req, AgentRequest)
    assert domain_req.query == "What is AI?"
    assert domain_req.session_id == "session-123"
    assert domain_req.context == {"user": "john"}


def test_api_request_to_domain_no_session():
    """Test converting API request without session_id."""
    api_req = QueryAPIRequest(query="What is AI?")

    domain_req = api_request_to_domain(api_req)

    assert domain_req.query == "What is AI?"
    assert domain_req.session_id is None


def test_domain_response_to_api_basic():
    """Test converting domain response to API response."""
    domain_resp = AgentResponse(
        content="AI is artificial intelligence",
        session_id="session-123",
        processing_time_ms=150.5,
        metadata={"model": "gpt-4"},
    )

    api_resp = domain_response_to_api(domain_resp, correlation_id="req_abc123")

    assert api_resp.content == "AI is artificial intelligence"
    assert api_resp.session_id == "session-123"
    assert api_resp.processing_time_ms == 150.5
    assert api_resp.metadata == {"model": "gpt-4"}
    assert api_resp.correlation_id == "req_abc123"
    assert api_resp.api_version == "1.0"


def test_domain_response_to_api_custom_version():
    """Test converting domain response with custom API version."""
    domain_resp = AgentResponse(
        content="Response",
        session_id="session1",
        processing_time_ms=100.0,
    )

    api_resp = domain_response_to_api(domain_resp, api_version="2.0")

    assert api_resp.api_version == "2.0"


def test_domain_error_to_api_response_basic():
    """Test converting domain error to API error response."""
    error = ResourceNotFoundError(["user-123"], context={"user_id": "123"})

    api_err = domain_error_to_api_response(error, correlation_id="req_xyz789")

    assert api_err.error == "ResourceNotFoundError"
    assert "user-123" in api_err.message
    assert api_err.correlation_id == "req_xyz789"
    assert "user_id" in api_err.details
    assert api_err.details["user_id"] == "123"


def test_domain_error_to_api_response_filters_excluded_context():
    """Test that sensitive context fields are excluded."""
    error = ResourceNotFoundError(
        ["resource-1"],
        context={
            "user_id": "123",
            "traceback_info": "sensitive stack trace",
            "error_attributes": "internal",
            "original_error_message": "internal msg",
            "timestamp": datetime.now(),
        },
    )

    api_err = domain_error_to_api_response(error)

    # Should include user_id but exclude sensitive fields
    assert "user_id" in api_err.details
    assert "traceback_info" not in api_err.details
    assert "error_attributes" not in api_err.details
    assert "original_error_message" not in api_err.details
    assert "timestamp" not in api_err.details


def test_query_api_request_validation_empty_query():
    """Test that empty query is rejected."""
    with pytest.raises(PydanticValidationError, match="Query cannot be empty"):
        QueryAPIRequest(query="   ")


def test_query_api_request_validation_query_too_long():
    """Test that query longer than max_length is rejected."""
    long_query = "x" * 8193
    with pytest.raises(PydanticValidationError):
        QueryAPIRequest(query=long_query)


def test_query_api_request_validation_session_id_too_short():
    """Test that session_id shorter than min_length is rejected."""
    with pytest.raises(PydanticValidationError):
        QueryAPIRequest(query="test", session_id="ab")


def test_query_api_request_validation_session_id_too_long():
    """Test that session_id longer than max_length is rejected."""
    with pytest.raises(PydanticValidationError):
        QueryAPIRequest(query="test", session_id="x" * 129)


def test_query_api_request_validation_context_not_dict():
    """Test that non-dict context is rejected."""
    with pytest.raises(PydanticValidationError, match="Context must be a dictionary"):
        QueryAPIRequest(query="test", context="not a dict")  # type: ignore


def test_query_api_request_validation_context_non_string_keys():
    """Test that context with non-string keys is rejected."""
    with pytest.raises(PydanticValidationError, match="All context keys must be strings"):
        QueryAPIRequest(query="test", context={1: "value"})  # type: ignore


def test_query_api_request_validation_context_too_many_keys():
    """Test that context with too many keys is rejected."""
    context = {f"k{i}": "v" for i in range(33)}
    with pytest.raises(PydanticValidationError):
        QueryAPIRequest(query="test", context=context)


def test_query_api_request_validation_context_key_too_long():
    """Test that context with oversized key is rejected."""
    with pytest.raises(PydanticValidationError):
        QueryAPIRequest(query="test", context={"x" * 129: "value"})


def test_query_api_request_validation_max_results_out_of_range():
    """Test that max_results outside valid range is rejected."""
    with pytest.raises(PydanticValidationError):
        QueryAPIRequest(query="test", max_results=0)

    with pytest.raises(PydanticValidationError):
        QueryAPIRequest(query="test", max_results=101)


def test_query_api_request_validation_similarity_threshold_out_of_range():
    """Test that similarity_threshold outside 0.0-1.0 is rejected."""
    with pytest.raises(PydanticValidationError):
        QueryAPIRequest(query="test", similarity_threshold=-0.1)

    with pytest.raises(PydanticValidationError):
        QueryAPIRequest(query="test", similarity_threshold=1.1)


def test_query_api_request_defaults():
    """Test default values for optional fields."""
    req = QueryAPIRequest(query="test query")

    assert req.session_id is None
    assert req.context is None
    assert req.max_results == 10
    assert req.similarity_threshold == 0.7


def test_query_api_request_over_limit_maps_to_422():
    """Test that oversized API request is rejected as 422."""
    app = FastAPI()

    @app.post("/query")
    async def query(request: QueryAPIRequest):
        return {"query": request.query}

    client = TestClient(app)
    response = client.post("/query", json={"query": "x" * 8193})

    assert response.status_code == 422


def test_query_api_request_strips_whitespace():
    """Test that query whitespace is stripped."""
    req = QueryAPIRequest(query="  test query  ")
    assert req.query == "test query"


def test_query_api_request_extra_fields_ignored():
    """Test that extra fields in request are ignored."""
    req = QueryAPIRequest(
        query="test",
        extra_field="ignored",  # type: ignore
    )
    assert req.query == "test"
    assert not hasattr(req, "extra_field")


class TestQueryAPIRequestSessionIdValidation:
    """Test session ID validation enforces DISA STIG V-222609 (CCI-002754).

    Session IDs must match pattern ^[A-Za-z0-9_-]{8,128}$ to prevent:
    - SQL injection attacks
    - Path traversal attacks
    - Control character attacks
    - Special character injection
    """

    def test_valid_session_id_basic(self) -> None:
        """Valid session ID with alphanumeric, hyphens, underscores."""
        req = QueryAPIRequest(query="test query", session_id="session-abc-123")
        assert req.session_id == "session-abc-123"

    def test_valid_session_id_uuid(self) -> None:
        """Valid session ID in UUID format."""
        uuid_session = "550e8400-e29b-41d4-a716-446655440000"
        req = QueryAPIRequest(query="test query", session_id=uuid_session)
        assert req.session_id == uuid_session

    def test_valid_session_id_min_length(self) -> None:
        """Valid session ID at minimum length boundary (8 characters)."""
        req = QueryAPIRequest(query="test query", session_id="12345678")
        assert req.session_id == "12345678"

    def test_valid_session_id_max_length(self) -> None:
        """Valid session ID at maximum length boundary (128 characters)."""
        long_session = "A" * 128
        req = QueryAPIRequest(query="test query", session_id=long_session)
        assert req.session_id == long_session

    def test_valid_session_id_with_whitespace(self) -> None:
        """Whitespace is automatically stripped from valid session ID."""
        req = QueryAPIRequest(query="test query", session_id="  session-123  ")
        assert req.session_id == "session-123"

    def test_invalid_session_id_too_short(self) -> None:
        """Session ID < 8 characters raises ValidationError."""
        with pytest.raises(PydanticValidationError) as exc_info:
            QueryAPIRequest(query="test query", session_id="test")

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("session_id",)
        assert "at least 8 characters" in errors[0]["msg"]

    def test_invalid_session_id_special_chars(self) -> None:
        """Session ID with special characters (@, :, #, space) raises ValidationError."""
        invalid_sessions = [
            "user@session",  # @ character
            "sess:12345",  # : character
            "id#456789",  # # character
            "test session",  # space character
        ]

        for session_id in invalid_sessions:
            with pytest.raises(PydanticValidationError) as exc_info:
                QueryAPIRequest(query="test query", session_id=session_id)

            errors = exc_info.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("session_id",)
            assert "match pattern" in errors[0]["msg"]

    def test_invalid_session_id_sql_injection(self) -> None:
        """Session ID with SQL injection syntax is blocked."""
        sql_injections = [
            "'; DROP TABLE--",
            "1' OR '1'='1",
            "admin'--",
        ]

        for session_id in sql_injections:
            with pytest.raises(PydanticValidationError) as exc_info:
                QueryAPIRequest(query="test query", session_id=session_id)

            errors = exc_info.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("session_id",)

    def test_invalid_session_id_path_traversal(self) -> None:
        """Session ID with path traversal syntax is blocked."""
        path_traversals = [
            "../../etc/passwd",
            "../../../etc/shadow",
            "..\\..\\windows\\system32",
        ]

        for session_id in path_traversals:
            with pytest.raises(PydanticValidationError) as exc_info:
                QueryAPIRequest(query="test query", session_id=session_id)

            errors = exc_info.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("session_id",)
