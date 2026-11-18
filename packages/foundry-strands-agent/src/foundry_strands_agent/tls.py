# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""TLS context factory for outbound HTTPS connections.

Provides a configured ssl.SSLContext with TLS 1.2 minimum and certificate
verification enabled by default. Satisfies STIG V-222596 (CCI-002418).
"""

import logging
import os
import ssl
import stat
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def create_tls_context() -> ssl.SSLContext:
    """Create an SSLContext enforcing TLS 1.2+ with certificate verification.

    Set FOUNDRY_TLS_VERIFY=false to disable cert verification for dev
    environments with self-signed certs. The TLS 1.2 floor is always enforced.

    Set FOUNDRY_TLS_CLIENT_CERTFILE and FOUNDRY_TLS_CLIENT_KEYFILE to present
    a client certificate for outbound mTLS connections.
    """
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    verify = os.getenv("FOUNDRY_TLS_VERIFY", "true").lower() != "false"
    if not verify:
        logger.warning("TLS certificate verification disabled via FOUNDRY_TLS_VERIFY=false")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    _load_client_cert(ctx)

    return ctx


def _is_posix() -> bool:
    """Indirection so tests can simulate non-POSIX platforms deterministically.

    Tests must monkeypatch this function rather than the process-global
    os.name: pathlib's Path.__new__ also reads os.name to pick WindowsPath
    vs PosixPath, so patching it directly corrupts any Path(str) built while
    the patch is active - including ones pytest's own reporting builds mid-test,
    before a monkeypatch fixture's teardown reverts it.
    """
    return os.name == "posix"


def _check_key_file_permissions(key_path: Path) -> None:
    """Warn if the private key file is readable/writable by group or other.

    Defense-in-depth only (STIG V-222551): the deploying environment is
    responsible for actually enforcing key-file access control (file
    ownership, secrets manager, k8s Secret mount). No-op on non-POSIX
    platforms, since Windows ACL semantics don't map to POSIX mode bits.

    create_tls_context() runs on every TLS context creation, which can be
    several times per agent (once per MCP connection, A2A provider, and
    NIMS client) rather than just once at process startup, so a
    misconfigured key file re-warns on every one of those calls instead of
    once per process. This volume is intended: a warning that keeps firing
    is harder to miss in scrollback than a one-time warning that goes
    silent, and it stops as soon as the file's permissions are fixed.
    """
    if not _is_posix():
        return
    try:
        mode = stat.S_IMODE(key_path.stat().st_mode)
    except FileNotFoundError:
        # TOCTOU: removed between the caller's is_file() check and this stat().
        # Other OSErrors (permission denied, I/O error) propagate - those mean
        # the check didn't run, which is itself worth surfacing rather than
        # silently swallowing.
        logger.debug("Could not stat %s to check permissions; skipping check.", key_path)
        return
    excess_bits = mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
    if excess_bits:
        logger.warning(
            "FOUNDRY_TLS_CLIENT_KEYFILE %s is readable/writable by group or other "
            "(mode %s) — restrict permissions to owner-only (e.g. chmod 600).",
            key_path,
            oct(mode),
        )


def _load_client_cert(ctx: ssl.SSLContext) -> None:
    """Load client certificate chain if both env vars are configured."""
    client_certfile = os.getenv("FOUNDRY_TLS_CLIENT_CERTFILE")
    client_keyfile = os.getenv("FOUNDRY_TLS_CLIENT_KEYFILE")

    if client_certfile and client_keyfile:
        cert_path = Path(client_certfile)
        key_path = Path(client_keyfile)

        if not cert_path.is_file():
            msg = f"FOUNDRY_TLS_CLIENT_CERTFILE not found: {client_certfile}"
            raise FileNotFoundError(msg)
        if not key_path.is_file():
            msg = f"FOUNDRY_TLS_CLIENT_KEYFILE not found: {client_keyfile}"
            raise FileNotFoundError(msg)

        _check_key_file_permissions(key_path)

        ctx.load_cert_chain(certfile=client_certfile, keyfile=client_keyfile)
        logger.info("Loaded client certificate for outbound mTLS: %s", client_certfile)

    elif client_certfile or client_keyfile:
        set_var = "FOUNDRY_TLS_CLIENT_CERTFILE" if client_certfile else "FOUNDRY_TLS_CLIENT_KEYFILE"
        missing_var = "FOUNDRY_TLS_CLIENT_KEYFILE" if client_certfile else "FOUNDRY_TLS_CLIENT_CERTFILE"
        logger.warning(
            "Incomplete outbound mTLS config: %s is set but %s is not. Client certificate not loaded.",
            set_var,
            missing_var,
        )


async def _refuse_https_downgrade_redirect(response: httpx.Response) -> None:
    """Refuse to follow a redirect from an https url to a non-https one.

    Since mcp 1.30.0 the MCP transports send with `follow_redirects=False` and follow only
    same-origin redirects themselves, so this hook is defense in depth: it still refuses a
    downgrade if a caller uses the client to follow redirects directly. httpx forwards the
    client's headers to the
    redirect target except `Authorization` (dropped cross-origin) and `Cookie` (rebuilt from its
    cookie store), so an https MCP server redirecting to http would send e.g. an `X-Api-Key`
    header in plaintext, past `StrandsAgentConfig`'s config-time plaintext-credential guard.
    httpx runs response hooks on every response in a redirect chain before following it. The
    target url isn't rendered in the error, since it may itself carry a credential.
    """
    if not response.has_redirect_location or response.request.url.scheme != "https":
        return
    target = response.request.url.join(response.headers["Location"])
    if target.scheme != "https":
        msg = "Refusing to follow a redirect from an https MCP endpoint to a non-https url"
        raise httpx.UnsupportedProtocol(msg, request=response.request)


def create_mcp_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """MCP-compatible httpx client factory with TLS enforcement.

    `follow_redirects` is set to match the MCP SDK default, but mcp 1.30.0 and later transports
    ignore it and follow only same-origin redirects. A redirect from https to a non-https url is
    never followed.
    """
    kwargs: dict[str, Any] = {
        # Matches MCP SDK default (mcp.shared._httpx_utils.create_mcp_http_client)
        "follow_redirects": True,
        "event_hooks": {"response": [_refuse_https_downgrade_redirect]},
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
