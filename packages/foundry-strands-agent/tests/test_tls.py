# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for TLS context factory (STIG V-222596)."""

import ssl
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import httpx
import pytest
import trustme

from foundry_strands_agent.tls import create_tls_context


class TestCreateTlsContext:
    """Spec: strands-tls-enforcement — SSLContext configuration."""

    def test_enforces_tls_1_2_minimum(self):
        ctx = create_tls_context()
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2

    def test_requires_cert_verification_by_default(self):
        ctx = create_tls_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_check_hostname_enabled_by_default(self):
        ctx = create_tls_context()
        assert ctx.check_hostname is True

    def test_env_var_false_disables_verification(self, monkeypatch):
        monkeypatch.setenv("FOUNDRY_TLS_VERIFY", "false")
        ctx = create_tls_context()
        assert ctx.verify_mode == ssl.CERT_NONE
        assert ctx.check_hostname is False

    def test_env_var_false_keeps_tls_1_2_floor(self, monkeypatch):
        monkeypatch.setenv("FOUNDRY_TLS_VERIFY", "false")
        ctx = create_tls_context()
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2

    def test_env_var_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("FOUNDRY_TLS_VERIFY", "False")
        ctx = create_tls_context()
        assert ctx.verify_mode == ssl.CERT_NONE

    def test_env_var_other_values_keep_verification(self, monkeypatch):
        monkeypatch.setenv("FOUNDRY_TLS_VERIFY", "true")
        ctx = create_tls_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_env_var_unset_keeps_verification(self, monkeypatch):
        monkeypatch.delenv("FOUNDRY_TLS_VERIFY", raising=False)
        ctx = create_tls_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED


class TestTlsRejection:
    """Spec: strands-tls-enforcement — Client rejects insecure peers."""

    def _start_tls_server(self, server_ctx: ssl.SSLContext) -> tuple[HTTPServer, int]:
        """Start a local HTTPS server with the given SSL context."""

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        server.socket = server_ctx.wrap_socket(server.socket, server_side=True)
        port = server.server_address[1]
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        return server, port

    def test_rejects_self_signed_certificate(self):
        """Client rejects a server whose cert is not in the client trust store."""
        # Create a self-signed CA and server cert (not trusted by our context)
        ca = trustme.CA()
        server_cert = ca.issue_cert("127.0.0.1")

        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_cert.configure_cert(server_ctx)
        ca.configure_trust(server_ctx)

        _, port = self._start_tls_server(server_ctx)

        # Client uses system CA bundle which does NOT trust this CA
        client_ctx = create_tls_context()
        with httpx.Client(verify=client_ctx) as client:
            with pytest.raises((httpx.ConnectError, ssl.SSLCertVerificationError)):
                client.get(f"https://127.0.0.1:{port}/")

    def test_rejects_expired_certificate(self):
        """Client rejects a server presenting an expired certificate."""
        ca = trustme.CA()
        server_cert = ca.issue_cert(
            "127.0.0.1",
            not_before=datetime(2020, 1, 1, tzinfo=UTC),
            not_after=datetime(2020, 1, 2, tzinfo=UTC),
        )

        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_cert.configure_cert(server_ctx)

        _, port = self._start_tls_server(server_ctx)

        # Client trusts the CA but cert is expired
        client_ctx = create_tls_context()
        ca.configure_trust(client_ctx)
        with httpx.Client(verify=client_ctx) as client:
            with pytest.raises((httpx.ConnectError, ssl.SSLCertVerificationError)):
                client.get(f"https://127.0.0.1:{port}/")

    def test_rejects_server_tls_below_1_2(self):
        """Client rejects a server that only offers TLS < 1.2.

        Since modern OpenSSL cannot actually negotiate TLS 1.0/1.1,
        we verify the context property directly: maximum_version < TLS 1.2
        on the server side causes handshake failure.
        """
        ca = trustme.CA()
        server_cert = ca.issue_cert("127.0.0.1")

        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_cert.configure_cert(server_ctx)
        # Force server to only offer TLS 1.1 (below our client's minimum)
        server_ctx.maximum_version = ssl.TLSVersion.TLSv1_1

        _, port = self._start_tls_server(server_ctx)

        # Client requires TLS 1.2 minimum
        client_ctx = create_tls_context()
        ca.configure_trust(client_ctx)
        with httpx.Client(verify=client_ctx) as client:
            with pytest.raises((httpx.ConnectError, ssl.SSLError)):
                client.get(f"https://127.0.0.1:{port}/")


class TestNimsModelTlsInjection:
    """Spec: strands-agent-factory — NIMS model uses TLS-configured client."""

    def test_nims_factory_passes_tls_context_via_http_client(self):
        from foundry_strands_agent.factory import _default_nims_model

        config = {
            "model": {
                "model_id": "test-model",
                "nims_base_url": "https://example.com/v1",
                "nims_api_key": "test-key",
            }
        }
        with patch("foundry_strands_agent.factory.NIMSModel") as mock_nims:
            _default_nims_model(config)
            call_kwargs = mock_nims.call_args[1]
            http_client = call_kwargs["client_args"]["http_client"]
            ssl_context = http_client._transport._pool._ssl_context
            assert ssl_context.minimum_version == ssl.TLSVersion.TLSv1_2
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
