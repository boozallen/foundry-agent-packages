# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Request logging middleware with correlation tracking and structured logging.

Provides comprehensive request/response logging with correlation ID generation,
performance metrics, and structured logging for debugging and monitoring.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from foundry_agent_fastapi.utils import generate_correlation_id

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Request logging middleware with correlation tracking and performance metrics.

    Logs all HTTP requests and responses with structured data including:
    - Request metadata (method, path, headers, query parameters)
    - Response metadata (status code, response time)
    - Correlation IDs for request tracing
    - Performance metrics for monitoring
    """

    def __init__(self, app: FastAPI) -> None:
        """Initialize request logging middleware.

        Args:
            app: FastAPI application instance
        """
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Process request with logging and correlation tracking.

        Logs request initiation, processes the request through the pipeline,
        measures performance metrics, and logs the response with structured data.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in the chain

        Returns:
            HTTP response with correlation headers added
        """
        # Generate or extract correlation ID
        correlation_id = (
            request.headers.get("x-correlation-id") or request.headers.get("x-request-id") or generate_correlation_id()
        )

        # Store correlation ID in request state
        request.state.correlation_id = correlation_id

        # Record request start time
        start_time = time.time()

        # Extract request information
        request_info = self._extract_request_info(request, correlation_id)

        # Log request initiation
        logger.info(
            "Request started: %s %s",
            request.method,
            request.url.path,
            extra=request_info,
        )

        try:
            # Process request through the application
            response = await call_next(request)

            # Calculate processing time
            processing_time_ms = (time.time() - start_time) * 1000

            # Extract response information
            response_info = self._extract_response_info(response, processing_time_ms, correlation_id)

            # Add correlation ID and timing headers to response
            if hasattr(response, "headers"):
                response.headers["x-correlation-id"] = correlation_id
                response.headers["x-response-time-ms"] = str(round(processing_time_ms, 2))

            # Log successful response
            logger.info(
                "Request completed: %s %s -> %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={**request_info, **response_info},
            )

            return response

        except Exception as e:
            # Calculate processing time for failed requests
            processing_time_ms = (time.time() - start_time) * 1000

            # Log request failure
            logger.exception(
                "Request failed: %s %s",
                request.method,
                request.url.path,
                extra={
                    **request_info,
                    "processing_time_ms": round(processing_time_ms, 2),
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

            # Re-raise exception for error middleware to handle
            raise

    def _extract_request_info(self, request: Request, correlation_id: str) -> dict[str, Any]:
        """Extract structured information from HTTP request for logging.

        Args:
            request: HTTP request to extract information from
            correlation_id: Request correlation ID

        Returns:
            Dictionary with structured request information
        """
        # Extract query parameters safely
        query_params = dict(request.query_params) if request.query_params else {}

        # Extract relevant headers (excluding sensitive ones)
        headers_to_log = {
            "user-agent": request.headers.get("user-agent"),
            "content-type": request.headers.get("content-type"),
            "accept": request.headers.get("accept"),
            "x-forwarded-for": request.headers.get("x-forwarded-for"),
        }
        # Filter out None values
        headers_to_log = {k: v for k, v in headers_to_log.items() if v is not None}

        return {
            "correlation_id": correlation_id,
            "request_method": request.method,
            "request_path": str(request.url.path),
            "request_query": query_params,
            "request_headers": headers_to_log,
            "client_ip": request.client.host if request.client else None,
            "request_size_bytes": self._get_content_length(request),
        }

    def _extract_response_info(
        self,
        response: Response,
        processing_time_ms: float,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Extract structured information from HTTP response for logging.

        Args:
            response: HTTP response to extract information from
            processing_time_ms: Request processing time in milliseconds
            correlation_id: Request correlation ID

        Returns:
            Dictionary with structured response information
        """
        return {
            "correlation_id": correlation_id,
            "response_status": response.status_code,
            "processing_time_ms": round(processing_time_ms, 2),
            "response_size_bytes": self._get_response_size(response),
            "response_content_type": getattr(response, "media_type", None),
        }

    def _get_content_length(self, request: Request) -> int | None:
        """Get request content length from headers.

        Args:
            request: HTTP request

        Returns:
            Content length in bytes or None if not available
        """
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                return int(content_length)
            except (ValueError, TypeError):
                return None
        return None

    def _get_response_size(self, response: Response) -> int | None:
        """Get response size from headers or body.

        Args:
            response: HTTP response

        Returns:
            Response size in bytes or None if not available
        """
        # Try to get from content-length header first
        if hasattr(response, "headers") and "content-length" in response.headers:
            try:
                return int(response.headers["content-length"])
            except (ValueError, TypeError):
                pass

        # Try to estimate from body if available
        if hasattr(response, "body") and response.body:
            try:
                if isinstance(response.body, bytes | str):
                    return len(response.body)
            except (AttributeError, TypeError):
                pass

        return None


def add_request_logging_middleware(app: FastAPI) -> None:
    """Add request logging middleware to FastAPI application.

    Registers the RequestLoggingMiddleware that provides comprehensive
    request/response logging with correlation IDs, performance metrics,
    and structured logging data.

    Args:
        app: FastAPI application instance to configure
    """
    app.add_middleware(RequestLoggingMiddleware)  # type: ignore[arg-type]
