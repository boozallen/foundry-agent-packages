# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Incoming-request OpenTelemetry trace-context extraction middleware."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from opentelemetry import context as otel_context
from opentelemetry import propagate
from starlette.middleware.base import BaseHTTPMiddleware


class TracingMiddleware(BaseHTTPMiddleware):
    """Extracts W3C trace context from inbound request headers and activates it.

    Uses only opentelemetry-api primitives (extract/attach/detach), which are
    inert no-ops when no TracerProvider has been configured - no SDK, exporter,
    or collector is required for this middleware to run safely.
    """

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Extract trace context from request headers and activate it for this request."""
        ctx = propagate.extract(request.headers)
        token = otel_context.attach(ctx)
        try:
            return await call_next(request)
        finally:
            otel_context.detach(token)


def add_tracing_middleware(app: FastAPI) -> None:
    """Add tracing middleware to FastAPI application.

    Registers the TracingMiddleware that extracts W3C trace context from
    inbound request headers so downstream spans (e.g. from the Strands SDK's
    reasoning loop) nest under the caller's trace.

    Args:
        app: FastAPI application instance to configure
    """
    app.add_middleware(TracingMiddleware)  # type: ignore[arg-type]
