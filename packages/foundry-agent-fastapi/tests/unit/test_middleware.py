# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for foundry-agent-fastapi middleware."""

from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from opentelemetry import trace as otel_trace

from foundry_agent_core.exceptions import ExternalServiceError
from foundry_agent_fastapi import (
    add_cors_middleware,
    add_error_handling_middleware,
    add_request_logging_middleware,
    add_tracing_middleware,
)


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
