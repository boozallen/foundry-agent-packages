# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Global error handling middleware for consistent API error responses."""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic_core import PydanticSerializationError
from starlette.middleware.base import BaseHTTPMiddleware

from foundry_agent_core.errors.translator import InfrastructureErrorTranslator
from foundry_agent_core.exceptions import (
    DomainError,
    ExternalServiceError,
    ValidationError,
)
from foundry_agent_fastapi.models.responses import ErrorResponse
from foundry_agent_fastapi.utils import generate_correlation_id

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Global error handling middleware using InfrastructureErrorTranslator patterns."""

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self.error_translator = InfrastructureErrorTranslator()

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        correlation_id = (
            request.headers.get("x-correlation-id") or request.headers.get("x-request-id") or generate_correlation_id()
        )

        try:
            request.state.correlation_id = correlation_id
            response = await call_next(request)
            if hasattr(response, "headers"):
                response.headers["x-correlation-id"] = correlation_id
            return response

        except DomainError as e:
            return self._create_error_response(e, correlation_id, request)

        except Exception as e:
            operation_context = self._extract_operation_context(request)
            domain_error = self.error_translator.translate_error(e, operation_context)
            return self._create_error_response(domain_error, correlation_id, request)

    def _create_error_response(
        self,
        domain_error: DomainError,
        correlation_id: str,
        request: Request,
    ) -> JSONResponse:
        status_code = self._get_http_status_code(domain_error)
        error_response = _domain_error_to_api_response(domain_error, correlation_id)
        self._log_error(domain_error, correlation_id, request, status_code)
        try:
            content = error_response.model_dump(mode="json", exclude_unset=True)
        except (TypeError, ValueError, PydanticSerializationError):
            logger.warning(
                "Failed to serialize error response, falling back to minimal envelope",
                extra={"error_type": type(domain_error).__name__, "correlation_id": correlation_id},
            )
            content = {
                "error": type(domain_error).__name__,
                "message": str(domain_error),
                "correlation_id": correlation_id,
                "timestamp": datetime.now().isoformat(),
            }
        return JSONResponse(
            status_code=status_code,
            content=content,
            headers={"x-correlation-id": correlation_id},
        )

    def _get_http_status_code(self, domain_error: DomainError) -> int:
        # Checked via isinstance so subclasses inherit their parent's status code.
        # All unmapped DomainError subclasses fall through to 500.
        status_mapping: list[tuple[type[DomainError], int]] = [
            (ValidationError, status.HTTP_400_BAD_REQUEST),
            (ExternalServiceError, status.HTTP_502_BAD_GATEWAY),
        ]
        for error_class, code in status_mapping:
            if isinstance(domain_error, error_class):
                return code
        return status.HTTP_500_INTERNAL_SERVER_ERROR

    def _extract_operation_context(self, request: Request) -> dict[str, Any]:
        return {
            "request_method": request.method,
            "request_path": str(request.url.path),
            "request_query": dict(request.query_params),
            "user_agent": request.headers.get("user-agent"),
            "request_id": getattr(request.state, "correlation_id", None),
            "client_ip": request.client.host if request.client else None,
        }

    def _log_error(
        self,
        domain_error: DomainError,
        correlation_id: str,
        request: Request,
        status_code: int,
    ) -> None:
        error_context = {
            "correlation_id": correlation_id,
            "error_type": type(domain_error).__name__,
            "error_message": str(domain_error),
            "http_status": status_code,
            "request_method": request.method,
            "request_path": str(request.url.path),
        }
        if hasattr(domain_error, "context") and domain_error.context:
            error_context["error_context"] = domain_error.context

        if status_code >= 500:
            logger.error(
                "Server error during %s %s",
                request.method,
                request.url.path,
                extra=error_context,
                exc_info=True,
            )
        elif status_code >= 400:
            logger.warning(
                "Client error during %s %s",
                request.method,
                request.url.path,
                extra=error_context,
            )


def _domain_error_to_api_response(error: DomainError, correlation_id: str | None = None) -> ErrorResponse:
    """Convert domain error to API error response (inlined from mappers)."""
    error_type_name = type(error).__name__
    details: dict[str, Any] = {}
    if hasattr(error, "context") and error.context:
        excluded = {"traceback_info", "error_attributes", "timestamp"}
        details = {k: v for k, v in error.context.items() if k not in excluded}
    details["error_class"] = error_type_name
    return ErrorResponse(
        error=error_type_name,
        message=str(error),
        details=details,
        correlation_id=correlation_id,
        timestamp=datetime.now(),
    )


def add_error_handling_middleware(app: FastAPI) -> None:
    """Add error handling middleware to FastAPI application."""
    app.add_middleware(ErrorHandlingMiddleware)  # type: ignore[arg-type]
