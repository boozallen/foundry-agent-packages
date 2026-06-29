# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Bi-directional mapping between API and domain models."""

from datetime import datetime
from typing import Any

from foundry_agent_core import AgentRequest, AgentResponse
from foundry_agent_core.exceptions import DomainError, ValidationError
from foundry_agent_fastapi.models.requests import QueryAPIRequest
from foundry_agent_fastapi.models.responses import ErrorResponse, QueryAPIResponse


def api_request_to_domain(api_request: QueryAPIRequest) -> AgentRequest:
    try:
        return AgentRequest(
            session_id=api_request.session_id,
            query=api_request.query,
            context=api_request.context,
        )
    except Exception as e:
        raise ValidationError(
            field_name="api_request",
            field_value=api_request,
            validation_rule="Failed to convert API request to domain model",
            context={
                "api_request_data": {
                    "session_id": api_request.session_id,
                    "query": api_request.query,
                    "has_context": api_request.context is not None,
                },
                "conversion_error": str(e),
            },
        ) from e


def domain_response_to_api(
    domain_response: AgentResponse,
    correlation_id: str | None = None,
    api_version: str = "1.0",
) -> QueryAPIResponse:
    try:
        return QueryAPIResponse(
            content=domain_response.content,
            session_id=domain_response.session_id,
            processing_time_ms=domain_response.processing_time_ms,
            timestamp=datetime.now(),
            metadata=domain_response.metadata,
            correlation_id=correlation_id,
            api_version=api_version,
        )
    except Exception as e:
        raise ValidationError(
            field_name="domain_response",
            field_value=domain_response,
            validation_rule="Failed to convert domain response to API model",
            context={
                "domain_response_data": {
                    "has_content": bool(domain_response.content),
                    "processing_time_ms": domain_response.processing_time_ms,
                },
                "correlation_id": correlation_id,
                "session_id": domain_response.session_id,
                "api_version": api_version,
                "conversion_error": str(e),
            },
        ) from e


def domain_error_to_api_response(
    error: DomainError,
    correlation_id: str | None = None,
) -> ErrorResponse:
    error_type_name = type(error).__name__
    details: dict[str, Any] = {}
    if hasattr(error, "context") and error.context:
        excluded = {"traceback_info", "error_attributes", "original_error_message", "timestamp"}
        details = {k: v for k, v in error.context.items() if k not in excluded}
    details["error_class"] = error_type_name
    return ErrorResponse(
        error=error_type_name,
        message=str(error),
        details=details,
        correlation_id=correlation_id,
        timestamp=datetime.now(),
    )
