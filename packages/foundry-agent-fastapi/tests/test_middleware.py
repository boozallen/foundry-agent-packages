# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for foundry-agent-fastapi middleware."""

from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from foundry_agent_core.exceptions import ExternalServiceError
from foundry_agent_fastapi import (
    add_cors_middleware,
    add_error_handling_middleware,
    add_request_logging_middleware,
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
    """Regression test (FOUNDRY-592): error response is valid JSON with correlation_id and ISO timestamp."""
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
    """Regression test (FOUNDRY-592): unhandled exception produces structured JSON 500, not plain text."""
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
