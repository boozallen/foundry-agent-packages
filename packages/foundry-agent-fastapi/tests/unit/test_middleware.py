# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for foundry-agent-fastapi middleware."""

from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from opentelemetry import trace as otel_trace

from foundry_agent_core import mask_session_id
from foundry_agent_core.exceptions import ExternalServiceError, ValidationError
from foundry_agent_fastapi import (
    add_cors_middleware,
    add_error_handling_middleware,
    add_request_logging_middleware,
    add_tracing_middleware,
)
from foundry_agent_fastapi.middleware._request_masking import mask_path


def test_cors_middleware_adds_headers():
    """Test CORS middleware adds appropriate headers."""
    app = FastAPI()
    add_cors_middleware(app)

    @app.get("/test")
    async def test_route():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/test", headers={"Origin": "http://example.com"})

    assert response.status_code == 200
    # CORS middleware is added - verify it's in the middleware stack
    assert any("cors" in str(m).lower() for m in app.user_middleware)


def test_error_handling_middleware_http_exceptions():
    """Test error middleware handles HTTP exceptions properly."""
    app = FastAPI()
    add_error_handling_middleware(app)

    @app.get("/not-found")
    async def route_not_found():
        raise HTTPException(status_code=404, detail="Not found")

    @app.get("/validation")
    async def route_validation():
        raise HTTPException(status_code=400, detail="Bad request")

    client = TestClient(app)

    # HTTPException -> passed through
    response = client.get("/not-found")
    assert response.status_code == 404

    # HTTPException -> passed through
    response = client.get("/validation")
    assert response.status_code == 400


def test_error_handling_middleware_http_exception():
    """Test error middleware passes through HTTPException."""
    app = FastAPI()
    add_error_handling_middleware(app)

    @app.get("/forbidden")
    async def route_forbidden():
        raise HTTPException(status_code=403, detail="Forbidden")

    client = TestClient(app)
    response = client.get("/forbidden")

    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"


def test_error_handling_middleware_generic_exception():
    """Test error middleware handles generic exceptions."""
    app = FastAPI()
    add_error_handling_middleware(app)

    @app.get("/error")
    async def route_error():
        raise ValueError("Something went wrong")

    client = TestClient(app)
    response = client.get("/error")

    assert response.status_code == 500
    json_resp = response.json()
    # ValueError is translated to ConfigurationError by the error translator
    assert json_resp["error"] == "ConfigurationError"
    assert "correlation_id" in json_resp


def test_error_handling_middleware_returns_json_with_timestamp_and_correlation_id():
    """Regression test: error response is valid JSON with correlation_id and ISO timestamp."""
    app = FastAPI()
    add_error_handling_middleware(app)

    @app.get("/service-error")
    async def route_service_error():
        raise ExternalServiceError("Connection refused", context={"host": "localhost"})

    client = TestClient(app)
    response = client.get("/service-error")

    assert response.status_code == 502
    assert response.headers["content-type"] == "application/json"
    json_resp = response.json()
    assert json_resp["error"] == "ExternalServiceError"
    assert json_resp["message"]
    assert json_resp["correlation_id"]
    assert datetime.fromisoformat(json_resp["timestamp"])


def test_error_handling_middleware_generic_error_returns_json_500():
    """Regression test: unhandled exception produces structured JSON 500, not plain text."""
    app = FastAPI()
    add_error_handling_middleware(app)

    @app.get("/unhandled")
    async def route_unhandled():
        raise RuntimeError("something broke")

    client = TestClient(app)
    response = client.get("/unhandled")

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    json_resp = response.json()
    assert json_resp["error"]
    assert json_resp["correlation_id"]
    assert datetime.fromisoformat(json_resp["timestamp"])


def test_error_handling_middleware_non_serializable_context():
    """Test error middleware returns valid JSON even with non-serializable error context."""
    app = FastAPI()
    add_error_handling_middleware(app)

    class NonSerializable:
        pass

    @app.get("/bad-context")
    async def route_bad_context():
        raise ExternalServiceError(
            "Connection failed",
            context={"bad_value": NonSerializable()},
        )

    client = TestClient(app)
    response = client.get("/bad-context")

    assert response.status_code == 502
    assert response.headers["content-type"] == "application/json"
    json_resp = response.json()
    assert json_resp["error"] == "ExternalServiceError"
    assert json_resp["correlation_id"]
    assert datetime.fromisoformat(json_resp["timestamp"])


def test_error_response_does_not_leak_internal_details():
    """Regression test: error responses must not expose internal details."""
    app = FastAPI()
    add_error_handling_middleware(app)

    @app.get("/internal-error")
    async def route_internal():
        raise RuntimeError("Connection to bedrock.us-east-1.amazonaws.com refused")

    client = TestClient(app)
    response = client.get("/internal-error")

    json_resp = response.json()
    assert "bedrock" not in json_resp["message"]
    assert json_resp.get("details") is None


def test_request_logging_middleware():
    """Test logging middleware logs requests."""
    app = FastAPI()
    add_request_logging_middleware(app)

    @app.get("/test")
    async def test_route():
        return {"ok": True}

    @app.post("/post-test")
    async def post_route(data: dict):
        return {"received": data}

    client = TestClient(app)

    # GET request
    response = client.get("/test")
    assert response.status_code == 200

    # POST request
    response = client.post("/post-test", json={"key": "value"})
    assert response.status_code == 200


def test_mask_path_masks_segment_after_session_marker():
    """Test the literal "sessions" segment is preserved while the identifier after it is masked."""
    masked = mask_path("/api/v1/sessions/abcdef1234567890/history")
    assert "abcdef1234567890" not in masked
    assert "/sessions/" in masked
    assert masked.endswith("/history")


def test_mask_path_leaves_unrelated_paths_unchanged():
    """Test a path with no session marker segment is returned unchanged."""
    assert mask_path("/api/v1/health") == "/api/v1/health"


def test_mask_path_ignores_trailing_session_marker():
    """Test a session marker with nothing after it is left unchanged."""
    assert mask_path("/api/v1/sessions") == "/api/v1/sessions"


def test_mask_path_masks_short_identifier():
    """Test a session identifier under 8 characters is still masked, not left raw."""
    masked = mask_path("/api/v1/sessions/abc123/history")
    assert "abc123" not in masked


def test_mask_path_masks_identifier_with_special_characters():
    """Test a session identifier containing '.', '+', '=', or '~' is still masked."""
    masked = mask_path("/api/v1/sessions/abc.123+456=789~xyz/history")
    assert "abc.123+456=789~xyz" not in masked


def test_request_logging_middleware_does_not_remask_after_percent_encoded_slash(caplog):
    """Documents a known gap: content after a percent-encoded slash is not re-masked.

    Starlette decodes a percent-encoded slash (%2F) in the identifier before
    mask_path runs, so only the segment up to the decoded slash is masked.
    """
    app = FastAPI()
    add_request_logging_middleware(app)

    @app.get("/{path:path}")
    async def catch_all(path: str):
        return {"path": path}

    client = TestClient(app)

    with caplog.at_level("INFO"):
        response = client.get("/sessions/a%2FSECRET/history")

    assert response.status_code == 200
    middleware_records = [r for r in caplog.records if r.name == "foundry_agent_fastapi.middleware.logging"]
    assert middleware_records
    for record in middleware_records:
        assert "SECRET" in record.request_path


def test_request_logging_middleware_masks_session_id_in_path(caplog):
    """Test request/response/failure logs mask a session identifier in the URL path."""
    app = FastAPI()
    add_request_logging_middleware(app)

    @app.get("/sessions/{session_id}/history")
    async def history_route(session_id: str):
        return {"session_id": session_id}

    client = TestClient(app)
    session_id = "abcdef1234567890"

    with caplog.at_level("INFO"):
        response = client.get(f"/sessions/{session_id}/history")

    assert response.status_code == 200
    middleware_records = [r for r in caplog.records if r.name == "foundry_agent_fastapi.middleware.logging"]
    assert middleware_records
    for record in middleware_records:
        request_path = getattr(record, "request_path", "")
        assert session_id not in request_path
        assert session_id not in record.getMessage()


def test_request_logging_middleware_masks_session_id_on_failure(caplog):
    """Test the failure-path log masks a session identifier in the URL path."""
    app = FastAPI()
    add_request_logging_middleware(app)

    @app.get("/sessions/{session_id}/history")
    async def failing_history_route(session_id: str):
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    session_id = "abcdef1234567890"

    with caplog.at_level("INFO"):
        client.get(f"/sessions/{session_id}/history")

    failure_records = [r for r in caplog.records if "Request failed" in r.getMessage()]
    assert failure_records
    for record in failure_records:
        request_path = getattr(record, "request_path", "")
        assert session_id not in request_path
        assert session_id not in record.getMessage()


def test_request_logging_middleware_masks_session_id_query_param(caplog):
    """Test a session_id query parameter is masked while other query params are untouched."""
    app = FastAPI()
    add_request_logging_middleware(app)

    @app.get("/history")
    async def history_route(session_id: str, page: int = 1):
        return {"session_id": session_id, "page": page}

    client = TestClient(app)
    session_id = "abcdef1234567890"

    with caplog.at_level("INFO"):
        response = client.get("/history", params={"session_id": session_id, "page": 2})

    assert response.status_code == 200
    middleware_records = [r for r in caplog.records if r.name == "foundry_agent_fastapi.middleware.logging"]
    assert middleware_records
    for record in middleware_records:
        request_query = record.request_query
        assert request_query["session_id"] == mask_session_id(session_id)
        assert request_query["page"] == "2"


def test_error_handling_middleware_masks_session_id_on_domain_error(caplog):
    """Test a DomainError raised on a /sessions/{id} route masks the id in the error log."""
    app = FastAPI()
    add_error_handling_middleware(app)

    @app.get("/sessions/{session_id}/history")
    async def failing_history_route(session_id: str):
        raise ValidationError("bad request")

    client = TestClient(app)
    session_id = "abcdef1234567890"

    with caplog.at_level("WARNING"):
        client.get(f"/sessions/{session_id}/history")

    middleware_records = [r for r in caplog.records if r.name == "foundry_agent_fastapi.middleware.errors"]
    assert middleware_records
    for record in middleware_records:
        assert session_id not in record.getMessage()
        assert session_id not in record.request_path


def test_error_handling_middleware_masks_session_id_on_unhandled_exception(caplog):
    """Test an unhandled exception on a /sessions/{id} route masks the id in path and query."""
    app = FastAPI()
    add_error_handling_middleware(app)

    @app.get("/sessions/{session_id}/history")
    async def failing_history_route(session_id: str, other_id: str):
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    session_id = "abcdef1234567890"
    other_id = "unrelated12345"

    with caplog.at_level("ERROR"):
        client.get(f"/sessions/{session_id}/history", params={"other_id": other_id})

    middleware_records = [r for r in caplog.records if r.name == "foundry_agent_fastapi.middleware.errors"]
    assert middleware_records
    for record in middleware_records:
        assert session_id not in record.getMessage()
        assert session_id not in record.request_path
        # The unhandled-exception path always populates error_context (it's
        # domain_error.context, merged from a non-empty operation_context by
        # the translator) - assert on it directly rather than behind an `if`,
        # so a future regression that empties it fails this test instead of
        # silently skipping the check.
        error_context = record.error_context
        assert session_id not in str(error_context)
        # other_id is not a known session-identifier query key, so it's untouched.
        assert error_context["request_query"]["other_id"] == other_id


def test_error_handling_middleware_leaks_session_id_embedded_in_exception_message(caplog):
    """Documents a known gap: an identifier embedded in an exception's own message is not masked.

    Only request_path/request_query are masked - error_message and
    error_context.original_error_message come from str(original_error), which
    InfrastructureErrorTranslator.preserve_error_context preserves verbatim.
    """
    app = FastAPI()
    add_error_handling_middleware(app)
    session_id = "abcdef1234567890"

    @app.get("/lookup")
    async def failing_lookup_route():
        raise KeyError(session_id)

    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level("ERROR"):
        client.get("/lookup")

    middleware_records = [r for r in caplog.records if r.name == "foundry_agent_fastapi.middleware.errors"]
    assert middleware_records
    for record in middleware_records:
        assert session_id in record.error_message
        assert session_id in str(record.error_context)


def test_combined_middleware_stack():
    """Test all middleware work together."""
    app = FastAPI()
    add_cors_middleware(app)
    add_error_handling_middleware(app)
    add_request_logging_middleware(app)

    @app.get("/test")
    async def test_route():
        return {"ok": True}

    @app.get("/error")
    async def error_route():
        raise HTTPException(status_code=404, detail="Not found")

    client = TestClient(app)

    # Normal request
    response = client.get("/test")
    assert response.status_code == 200

    # Error request (HTTP exception passes through)
    response = client.get("/error")
    assert response.status_code == 404


def _tracing_app() -> FastAPI:
    app = FastAPI()
    add_tracing_middleware(app)

    @app.get("/span")
    async def span_route():
        span_context = otel_trace.get_current_span().get_span_context()
        return {
            "trace_id": format(span_context.trace_id, "032x"),
            "span_id": format(span_context.span_id, "016x"),
            "is_valid": span_context.is_valid,
        }

    return app


def test_tracing_middleware_adds_middleware():
    """Test add_tracing_middleware registers without error."""
    app = FastAPI()
    add_tracing_middleware(app)
    assert len(app.user_middleware) == 1


def test_tracing_middleware_extracts_valid_traceparent():
    """Test a valid traceparent header is extracted and active during the request."""
    client = TestClient(_tracing_app())
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    span_id = "b7ad6b7169203331"

    response = client.get("/span", headers={"traceparent": f"00-{trace_id}-{span_id}-01"})

    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == trace_id
    assert body["span_id"] == span_id
    assert body["is_valid"] is True


def test_tracing_middleware_missing_header_no_error():
    """Test a request with no traceparent header is handled normally with no remote span."""
    client = TestClient(_tracing_app())

    response = client.get("/span")

    assert response.status_code == 200
    assert response.json()["is_valid"] is False


def test_tracing_middleware_malformed_header_no_error():
    """Test a malformed traceparent header behaves identically to a missing one."""
    client = TestClient(_tracing_app())

    response = client.get("/span", headers={"traceparent": "not-a-valid-traceparent-header"})

    assert response.status_code == 200
    assert response.json()["is_valid"] is False


def test_tracing_middleware_no_tracer_provider_configured():
    """Test the middleware works with no TracerProvider configured (default test environment)."""
    assert isinstance(otel_trace.get_tracer_provider(), otel_trace.ProxyTracerProvider)

    client = TestClient(_tracing_app())
    response = client.get("/span", headers={"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"})

    assert response.status_code == 200
    assert response.json()["is_valid"] is True


def test_tracing_middleware_context_does_not_leak_across_requests():
    """Test sequential requests with different traceparent headers each see only their own context."""
    client = TestClient(_tracing_app())
    trace_id_a = "0af7651916cd43dd8448eb211c80319c"
    trace_id_b = "1bf7651916cd43dd8448eb211c80319d"

    response_a = client.get("/span", headers={"traceparent": f"00-{trace_id_a}-b7ad6b7169203331-01"})
    response_b = client.get("/span", headers={"traceparent": f"00-{trace_id_b}-b7ad6b7169203332-01"})
    response_c = client.get("/span")

    assert response_a.json()["trace_id"] == trace_id_a
    assert response_b.json()["trace_id"] == trace_id_b
    assert response_c.json()["is_valid"] is False
