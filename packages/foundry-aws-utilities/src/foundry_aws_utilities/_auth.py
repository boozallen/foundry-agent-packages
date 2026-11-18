# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Bearer-token authentication for the foundry AWS MCP servers.

The MCP servers in this package expose destructive AWS operations (S3 delete,
DynamoDB delete/update, bucket/table create) over streamable-http on
0.0.0.0:8000. This module provides a fail-closed shared-secret bearer check so
those endpoints are not invocable by arbitrary callers on the pod network.
"""

import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def require_auth_token() -> str:
    """
    Read the shared bearer token from MCP_AUTH_TOKEN.

    Raises RuntimeError if unset or empty so the server refuses to bind an
    unauthenticated HTTP listener (fail-closed).
    """
    token = os.getenv("MCP_AUTH_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "MCP_AUTH_TOKEN is not set. The MCP server exposes destructive AWS "
            "operations over HTTP and will not start without a bearer token. "
            "Set MCP_AUTH_TOKEN to a strong random secret shared with authorized clients."
        )
    return token


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Reject any request without a matching bearer token.

    Requires an ``Authorization: Bearer <token>`` header on every request.
    Only ``GET /health`` is exempt (k8s liveness/readiness probe).
    """

    def __init__(self, app, token: str) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        if not token:
            raise ValueError("BearerTokenMiddleware requires a non-empty token")
        self._token = token

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if request.method == "GET" and request.url.path == "/health":
            return await call_next(request)
        header = request.headers.get("authorization", "")
        scheme, _, credential = header.partition(" ")
        if scheme.lower() != "bearer" or not credential or not secrets.compare_digest(credential, self._token):
            return JSONResponse({"error": "invalid_or_missing_bearer_token"}, status_code=401)
        return await call_next(request)
