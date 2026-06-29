# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for core domain types and value objects."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from foundry_strands_agent.types import (
    DocumentChunk,
    QueryRequest,
    QueryResponse,
    SearchResult,
)


class TestQueryRequestSessionIdValidation:
    """Test session ID validation enforces DISA STIG V-222609 (CCI-002754).

    Session IDs must match pattern ^[A-Za-z0-9_-]{8,128}$ to prevent:
    - SQL injection attacks
    - Path traversal attacks
    - Control character attacks
    - Special character injection
    """

    def test_valid_session_id_basic(self) -> None:
        """Valid session ID with alphanumeric, hyphens, underscores."""
        req = QueryRequest(query="test query", session_id="session-abc-123")
        assert req.session_id == "session-abc-123"

    def test_valid_session_id_uuid(self) -> None:
        """Valid session ID in UUID format."""
        uuid_session = "550e8400-e29b-41d4-a716-446655440000"
        req = QueryRequest(query="test query", session_id=uuid_session)
        assert req.session_id == uuid_session

    def test_valid_session_id_min_length(self) -> None:
        """Valid session ID at minimum length boundary (8 characters)."""
        req = QueryRequest(query="test query", session_id="12345678")
        assert req.session_id == "12345678"

    def test_valid_session_id_max_length(self) -> None:
        """Valid session ID at maximum length boundary (128 characters)."""
        long_session = "A" * 128
        req = QueryRequest(query="test query", session_id=long_session)
        assert req.session_id == long_session

    def test_valid_session_id_with_whitespace(self) -> None:
        """Whitespace is automatically stripped from valid session ID."""
        req = QueryRequest(query="test query", session_id="  session-123  ")
        assert req.session_id == "session-123"

    def test_invalid_session_id_too_short(self) -> None:
        """Session ID < 8 characters raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(query="test query", session_id="test")

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
            with pytest.raises(ValidationError) as exc_info:
                QueryRequest(query="test query", session_id=session_id)

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
            with pytest.raises(ValidationError) as exc_info:
                QueryRequest(query="test query", session_id=session_id)

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
            with pytest.raises(ValidationError) as exc_info:
                QueryRequest(query="test query", session_id=session_id)

            errors = exc_info.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("session_id",)

    def test_invalid_session_id_control_chars(self) -> None:
        """Session ID with control characters (newline, carriage return, null) is blocked."""
        control_char_sessions = [
            "sess\n12345",  # newline
            "sess\r12345",  # carriage return
            "sess\x0012345",  # null byte
        ]

        for session_id in control_char_sessions:
            with pytest.raises(ValidationError) as exc_info:
                QueryRequest(query="test query", session_id=session_id)

            errors = exc_info.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("session_id",)


class TestQueryRequest:
    """Test QueryRequest model and validators."""

    def test_valid_request_all_fields(self):
        """Test creating a valid QueryRequest with all fields."""
        req = QueryRequest(
            session_id="session-123",
            query="What is AI?",
            context={"user_id": "user-1"},
            max_results=20,
            similarity_threshold=0.8,
        )

        assert req.session_id == "session-123"
        assert req.query == "What is AI?"
        assert req.context == {"user_id": "user-1"}
        assert req.max_results == 20
        assert req.similarity_threshold == 0.8
        assert isinstance(req.timestamp, datetime)

    def test_valid_request_minimal_fields(self):
        """Test creating a QueryRequest with only required field."""
        req = QueryRequest(query="Test query")

        assert req.session_id is None
        assert req.query == "Test query"
        assert req.context is None
        assert req.max_results == 10  # default
        assert req.similarity_threshold == 0.7  # default

    def test_session_id_empty_string_raises(self):
        """Test that empty session_id raises ValueError."""
        with pytest.raises(ValidationError):
            QueryRequest(session_id="", query="Test")

    def test_session_id_whitespace_only_raises(self):
        """Test that whitespace-only session_id raises ValueError."""
        with pytest.raises(ValidationError):
            QueryRequest(session_id="   ", query="Test")

    def test_session_id_strips_whitespace(self):
        """Test that session_id strips whitespace."""
        req = QueryRequest(session_id="  session-123  ", query="Test")
        assert req.session_id == "session-123"

    def test_session_id_none_is_valid(self):
        """Test that None session_id is valid."""
        req = QueryRequest(session_id=None, query="Test")
        assert req.session_id is None

    def test_session_id_redacted_in_serialized_output(self):
        """STIG V-222577: serialized output must redact session_id (raw absent, masked present)."""
        raw = "super-secret-session-id"
        req = QueryRequest(session_id=raw, query="Test")

        # In-memory attribute is preserved for runtime session use.
        assert req.session_id == raw

        # model_dump() and model_dump_json() must not expose the raw identifier.
        dumped = req.model_dump()
        assert dumped["session_id"] != raw
        assert dumped["session_id"].startswith("sid:")

        dumped_json = req.model_dump_json()
        assert raw not in dumped_json
        assert "sid:" in dumped_json

    def test_session_id_none_serializes_to_none(self):
        """A None session_id serializes to None, not a masked placeholder."""
        req = QueryRequest(session_id=None, query="Test")
        assert req.model_dump()["session_id"] is None

    def test_query_empty_string_raises(self):
        """Test that empty query raises ValueError."""
        with pytest.raises(ValidationError):
            QueryRequest(query="")

    def test_query_whitespace_only_raises(self):
        """Test that whitespace-only query raises ValueError."""
        with pytest.raises(ValidationError, match="Query cannot be empty"):
            QueryRequest(query="   ")

    def test_query_strips_whitespace(self):
        """Test that query strips whitespace."""
        req = QueryRequest(query="  What is AI?  ")
        assert req.query == "What is AI?"

    def test_max_results_zero_raises(self):
        """Test that max_results=0 raises ValueError."""
        with pytest.raises(ValidationError):
            QueryRequest(query="Test", max_results=0)

    def test_max_results_negative_raises(self):
        """Test that negative max_results raises ValueError."""
        with pytest.raises(ValidationError):
            QueryRequest(query="Test", max_results=-1)

    def test_max_results_over_100_raises(self):
        """Test that max_results > 100 raises ValueError."""
        with pytest.raises(ValidationError):
            QueryRequest(query="Test", max_results=101)

    def test_max_results_boundary_values(self):
        """Test max_results at boundary values."""
        req1 = QueryRequest(query="Test", max_results=1)
        assert req1.max_results == 1

        req100 = QueryRequest(query="Test", max_results=100)
        assert req100.max_results == 100

    def test_similarity_threshold_negative_raises(self):
        """Test that negative similarity_threshold raises ValueError."""
        with pytest.raises(ValidationError):
            QueryRequest(query="Test", similarity_threshold=-0.1)

    def test_similarity_threshold_over_one_raises(self):
        """Test that similarity_threshold > 1.0 raises ValueError."""
        with pytest.raises(ValidationError):
            QueryRequest(query="Test", similarity_threshold=1.1)

    def test_query_too_long_raises(self):
        """Test query length bound is enforced."""
        with pytest.raises(ValidationError):
            QueryRequest(query="x" * 8193)

    def test_context_too_many_keys_raises(self):
        """Test context key count bound is enforced."""
        with pytest.raises(ValidationError):
            QueryRequest(query="test", context={f"k{i}": i for i in range(33)})

    def test_similarity_threshold_boundary_values(self):
        """Test similarity_threshold at boundary values."""
        req0 = QueryRequest(query="Test", similarity_threshold=0.0)
        assert req0.similarity_threshold == 0.0

        req1 = QueryRequest(query="Test", similarity_threshold=1.0)
        assert req1.similarity_threshold == 1.0

    def test_model_is_frozen(self):
        """Test that QueryRequest is immutable (frozen)."""
        req = QueryRequest(query="Test")
        with pytest.raises(ValidationError):
            req.query = "New query"


class TestSearchResult:
    """Test SearchResult model and validators."""

    def test_valid_result(self):
        """Test creating a valid SearchResult."""
        result = SearchResult(
            document_id="doc-123",
            content_preview="This is a preview of the content...",
            similarity_score=0.85,
            metadata={"source": "database", "page": 42},
        )

        assert result.document_id == "doc-123"
        assert result.content_preview == "This is a preview of the content..."
        assert result.similarity_score == 0.85
        assert result.metadata == {"source": "database", "page": 42}

    def test_document_id_empty_string_raises(self):
        """Test that empty document_id raises ValueError."""
        with pytest.raises(ValidationError):
            SearchResult(
                document_id="",
                content_preview="Content",
                similarity_score=0.5,
                metadata={},
            )

    def test_document_id_whitespace_only_raises(self):
        """Test that whitespace-only document_id raises ValueError."""
        with pytest.raises(ValidationError):
            SearchResult(
                document_id="   ",
                content_preview="Content",
                similarity_score=0.5,
                metadata={},
            )

    def test_document_id_strips_whitespace(self):
        """Test that document_id strips whitespace."""
        result = SearchResult(
            document_id="  doc-123  ",
            content_preview="Content",
            similarity_score=0.5,
            metadata={},
        )
        assert result.document_id == "doc-123"

    def test_similarity_score_out_of_range_raises(self):
        """Test that similarity_score outside 0-1 raises ValueError."""
        with pytest.raises(ValidationError):
            SearchResult(
                document_id="doc-1",
                content_preview="Content",
                similarity_score=1.5,
                metadata={},
            )

        with pytest.raises(ValidationError):
            SearchResult(
                document_id="doc-1",
                content_preview="Content",
                similarity_score=-0.1,
                metadata={},
            )

    def test_model_is_frozen(self):
        """Test that SearchResult is immutable (frozen)."""
        result = SearchResult(
            document_id="doc-1",
            content_preview="Content",
            similarity_score=0.5,
            metadata={},
        )
        with pytest.raises(ValidationError):
            result.similarity_score = 0.9


class TestDocumentChunk:
    """Test DocumentChunk model and validators."""

    def test_valid_chunk(self):
        """Test creating a valid DocumentChunk."""
        chunk = DocumentChunk(
            chunk_id="chunk-1",
            content="This is the chunk content.",
            metadata={"section": "introduction"},
            source_document_id="doc-123",
            chunk_index=0,
            character_start=0,
            character_end=27,
        )

        assert chunk.chunk_id == "chunk-1"
        assert chunk.content == "This is the chunk content."
        assert chunk.metadata == {"section": "introduction"}
        assert chunk.source_document_id == "doc-123"
        assert chunk.chunk_index == 0
        assert chunk.character_start == 0
        assert chunk.character_end == 27

    def test_chunk_id_empty_string_raises(self):
        """Test that empty chunk_id raises ValueError."""
        with pytest.raises(ValidationError):
            DocumentChunk(
                chunk_id="",
                content="Content",
                metadata={},
                source_document_id="doc-1",
                chunk_index=0,
                character_start=0,
                character_end=10,
            )

    def test_chunk_id_whitespace_only_raises(self):
        """Test that whitespace-only chunk_id raises ValueError."""
        with pytest.raises(ValidationError):
            DocumentChunk(
                chunk_id="   ",
                content="Content",
                metadata={},
                source_document_id="doc-1",
                chunk_index=0,
                character_start=0,
                character_end=10,
            )

    def test_content_empty_string_raises(self):
        """Test that empty content raises ValueError."""
        with pytest.raises(ValidationError):
            DocumentChunk(
                chunk_id="chunk-1",
                content="",
                metadata={},
                source_document_id="doc-1",
                chunk_index=0,
                character_start=0,
                character_end=10,
            )

    def test_content_whitespace_only_raises(self):
        """Test that whitespace-only content raises ValueError."""
        with pytest.raises(ValidationError, match="content cannot be empty"):
            DocumentChunk(
                chunk_id="chunk-1",
                content="   ",
                metadata={},
                source_document_id="doc-1",
                chunk_index=0,
                character_start=0,
                character_end=10,
            )

    def test_chunk_index_negative_raises(self):
        """Test that negative chunk_index raises ValueError."""
        with pytest.raises(ValidationError):
            DocumentChunk(
                chunk_id="chunk-1",
                content="Content",
                metadata={},
                source_document_id="doc-1",
                chunk_index=-1,
                character_start=0,
                character_end=10,
            )

    def test_character_start_negative_raises(self):
        """Test that negative character_start raises ValueError."""
        with pytest.raises(ValidationError):
            DocumentChunk(
                chunk_id="chunk-1",
                content="Content",
                metadata={},
                source_document_id="doc-1",
                chunk_index=0,
                character_start=-1,
                character_end=10,
            )

    def test_character_end_less_than_start_raises(self):
        """Test that character_end < character_start raises ValueError."""
        with pytest.raises(ValidationError, match="character_end must be greater than character_start"):
            DocumentChunk(
                chunk_id="chunk-1",
                content="Content",
                metadata={},
                source_document_id="doc-1",
                chunk_index=0,
                character_start=10,
                character_end=5,
            )

    def test_character_end_equal_to_start_raises(self):
        """Test that character_end == character_start raises ValueError."""
        with pytest.raises(ValidationError, match="character_end must be greater than character_start"):
            DocumentChunk(
                chunk_id="chunk-1",
                content="Content",
                metadata={},
                source_document_id="doc-1",
                chunk_index=0,
                character_start=10,
                character_end=10,
            )

    def test_model_is_frozen(self):
        """Test that DocumentChunk is immutable (frozen)."""
        chunk = DocumentChunk(
            chunk_id="chunk-1",
            content="Content",
            metadata={},
            source_document_id="doc-1",
            chunk_index=0,
            character_start=0,
            character_end=10,
        )
        with pytest.raises(ValidationError):
            chunk.chunk_index = 1


class TestQueryResponse:
    """Test QueryResponse model and validators."""

    def test_valid_response(self):
        """Test creating a valid QueryResponse."""
        response = QueryResponse(
            response_text="This is the agent's response.",
            sources=[],
            chunks_used=[],
            confidence_score=0.85,
            processing_time_ms=150.5,
        )

        assert response.response_text == "This is the agent's response."
        assert response.sources == []
        assert response.chunks_used == []
        assert response.confidence_score == 0.85
        assert response.processing_time_ms == 150.5
        assert isinstance(response.timestamp, datetime)
        assert response.metadata is None

    def test_valid_response_with_sources_and_chunks(self):
        """Test QueryResponse with sources and chunks."""
        source = SearchResult(
            document_id="doc-1",
            content_preview="Preview",
            similarity_score=0.9,
            metadata={},
        )
        chunk = DocumentChunk(
            chunk_id="chunk-1",
            content="Content",
            metadata={},
            source_document_id="doc-1",
            chunk_index=0,
            character_start=0,
            character_end=10,
        )
        response = QueryResponse(
            response_text="Response",
            sources=[source],
            chunks_used=[chunk],
            confidence_score=0.9,
            processing_time_ms=200.0,
            metadata={"model": "gpt-4"},
        )

        assert len(response.sources) == 1
        assert len(response.chunks_used) == 1
        assert response.metadata == {"model": "gpt-4"}

    def test_response_text_empty_string_raises(self):
        """Test that empty response_text raises ValueError."""
        with pytest.raises(ValidationError):
            QueryResponse(
                response_text="",
                sources=[],
                chunks_used=[],
                confidence_score=0.5,
                processing_time_ms=100.0,
            )

    def test_response_text_whitespace_only_raises(self):
        """Test that whitespace-only response_text raises ValueError."""
        with pytest.raises(ValidationError, match="response_text cannot be empty"):
            QueryResponse(
                response_text="   ",
                sources=[],
                chunks_used=[],
                confidence_score=0.5,
                processing_time_ms=100.0,
            )

    def test_confidence_score_out_of_range_raises(self):
        """Test that confidence_score outside 0-1 raises ValueError."""
        with pytest.raises(ValidationError):
            QueryResponse(
                response_text="Response",
                sources=[],
                chunks_used=[],
                confidence_score=1.5,
                processing_time_ms=100.0,
            )

        with pytest.raises(ValidationError):
            QueryResponse(
                response_text="Response",
                sources=[],
                chunks_used=[],
                confidence_score=-0.1,
                processing_time_ms=100.0,
            )

    def test_processing_time_ms_negative_raises(self):
        """Test that negative processing_time_ms raises ValueError."""
        with pytest.raises(ValidationError):
            QueryResponse(
                response_text="Response",
                sources=[],
                chunks_used=[],
                confidence_score=0.5,
                processing_time_ms=-10.0,
            )

    def test_response_text_too_long_raises(self):
        """Test response_text length bound is enforced."""
        with pytest.raises(ValidationError):
            QueryResponse(
                response_text="x" * 131073,
                sources=[],
                chunks_used=[],
                confidence_score=0.5,
                processing_time_ms=10.0,
            )

    def test_processing_time_ms_zero_is_valid(self):
        """Test that processing_time_ms=0 is valid."""
        response = QueryResponse(
            response_text="Response",
            sources=[],
            chunks_used=[],
            confidence_score=0.5,
            processing_time_ms=0.0,
        )
        assert response.processing_time_ms == 0.0

    def test_model_is_frozen(self):
        """Test that QueryResponse is immutable (frozen)."""
        response = QueryResponse(
            response_text="Response",
            sources=[],
            chunks_used=[],
            confidence_score=0.5,
            processing_time_ms=100.0,
        )
        with pytest.raises(ValidationError):
            response.confidence_score = 0.9
