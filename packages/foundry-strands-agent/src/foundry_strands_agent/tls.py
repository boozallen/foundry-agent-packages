# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""TLS context factory for outbound HTTPS connections.

Provides a configured ssl.SSLContext with TLS 1.2 minimum and certificate
verification enabled by default. Satisfies STIG V-222596 (CCI-002418).
"""

import logging
import os
import ssl
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def create_tls_context() -> ssl.SSLContext:
    """Create an SSLContext enforcing TLS 1.2+ with certificate verification.

    Set FOUNDRY_TLS_VERIFY=false to disable cert verification for dev
    environments with self-signed certs. The TLS 1.2 floor is always enforced.
    """
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    verify = os.getenv("FOUNDRY_TLS_VERIFY", "true").lower() != "false"
    if not verify:
        logger.warning("TLS certificate verification disabled via FOUNDRY_TLS_VERIFY=false")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    return ctx


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """MCP-compatible httpx client factory with TLS enforcement."""
    kwargs: dict[str, Any] = {
        # Matches MCP SDK default (mcp.shared._httpx_utils.create_mcp_http_client)
        "follow_redirects": True,
        "verify": create_tls_context(),
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    else:
        kwargs["timeout"] = httpx.Timeout(30, read=300)
    if headers is not None:
        kwargs["headers"] = headers
    if auth is not None:
        kwargs["auth"] = auth
    return httpx.AsyncClient(**kwargs)
