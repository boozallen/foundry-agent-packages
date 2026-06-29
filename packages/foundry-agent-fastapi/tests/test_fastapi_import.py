# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for foundry-agent-fastapi package."""

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

import foundry_agent_fastapi
from foundry_agent_fastapi import (
    QueryAPIResponse,
    add_cors_middleware,
    add_error_handling_middleware,
    add_request_logging_middleware,
    generate_correlation_id,
    health_router,
)
from foundry_agent_fastapi.models.responses import ErrorResponse


def test_import():
    assert foundry_agent_fastapi is not None


def test_ac2_query_api_response_lean_fields():
    """AC2: QueryAPIResponse has content, session_id, processing_time_ms — no RAG fields."""
    resp = QueryAPIResponse(
        content="Hello",
        session_id="session1",
        processing_time_ms=42.0,
        timestamp=datetime.now(),
    )
    assert resp.content == "Hello"
    assert resp.session_id == "session1"
    assert resp.processing_time_ms == 42.0

    assert not hasattr(resp, "sources")
    assert not hasattr(resp, "chunks_used")
    assert not hasattr(resp, "confidence_score")
    assert not hasattr(resp, "response_text")


def test_ac3_health_endpoint():
    """AC3: GET /api/v1/health returns {"status": "healthy"} with 200."""
    app = FastAPI()
    app.include_router(health_router)
    client = TestClient(app)

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_ac1_middleware_stack():
    """AC1: CORS, error, logging middleware can be added to a FastAPI app."""
    app = FastAPI()
    add_cors_middleware(app)
    add_error_handling_middleware(app)
    add_request_logging_middleware(app)

    @app.get("/test")
    async def test_route():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/test")
    assert response.status_code == 200


def test_correlation_id_generated():
    """generate_correlation_id returns a string starting with req_."""
    cid = generate_correlation_id()
    assert cid.startswith("req_")
    assert len(cid) == 12


def test_error_response_model():
    """ErrorResponse can be instantiated."""
    err = ErrorResponse(
        error="ValidationError",
        message="field invalid",
        correlation_id="req_abc12345",
    )
    assert err.error == "ValidationError"
    assert err.message == "field invalid"


def test_ac4_dependencies():
    """AC4: Only fastapi and foundry-agent-core as deps."""
    import tomllib
    from pathlib import Path

    toml_path = Path(__file__).parent.parent / "pyproject.toml"
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    deps = data["project"]["dependencies"]
    dep_names = [d.split(">=")[0].split(">")[0].split("==")[0].strip() for d in deps]
    assert "fastapi" in dep_names
    assert "foundry-agent-core" in dep_names
    assert len(dep_names) == 2
