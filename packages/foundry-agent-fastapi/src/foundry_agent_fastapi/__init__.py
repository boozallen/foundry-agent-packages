# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""foundry-agent-fastapi — Reusable FastAPI middleware, health check, and API models."""

from foundry_agent_fastapi.mappers import api_request_to_domain, domain_error_to_api_response, domain_response_to_api
from foundry_agent_fastapi.middleware.cors import add_cors_middleware
from foundry_agent_fastapi.middleware.errors import add_error_handling_middleware
from foundry_agent_fastapi.middleware.logging import add_request_logging_middleware
from foundry_agent_fastapi.models.requests import QueryAPIRequest
from foundry_agent_fastapi.models.responses import ErrorResponse, QueryAPIResponse
from foundry_agent_fastapi.routes.health import router as health_router
from foundry_agent_fastapi.utils import generate_correlation_id

__all__ = [
    "add_cors_middleware",
    "add_error_handling_middleware",
    "add_request_logging_middleware",
    "api_request_to_domain",
    "domain_error_to_api_response",
    "domain_response_to_api",
    "health_router",
    "QueryAPIRequest",
    "QueryAPIResponse",
    "ErrorResponse",
    "generate_correlation_id",
]
