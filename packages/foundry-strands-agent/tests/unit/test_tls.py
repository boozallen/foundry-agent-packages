# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for TLS context factory (STIG V-222596)."""

import logging
import ssl
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import httpx
import pytest
import trustme

from foundry_strands_agent.tls import _check_key_file_permissions, create_mcp_http_client, create_tls_context

_WIN32_SKIP_REASON = "POSIX permission bits are not meaningful on Windows"

# Fake, non-functional value used only to exercise redirect-scheme enforcement.
FAKE_URL_SECRET = "url-secret"  # trufflehog:ignore


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
        # Deliberately weak/self-signed/expired server contexts by design - this
        # helper backs TestTlsRejection, which asserts create_tls_context()'s
        # client rejects exactly this kind of insecure peer.
        # codeql[py/insecure-protocol]
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


class TestClientCertLoading:
    """Spec: strands-tls-enforcement — Client certificate for outbound mTLS."""

    def test_both_vars_set_loads_cert_chain(self, monkeypatch, tmp_path):
        cert = tmp_path / "client.crt"
        key = tmp_path / "client.key"
        cert.write_text("CERT")
        key.write_text("KEY")
        key.chmod(0o600)  # avoid an unasserted permission warning on POSIX CI (umask default)

        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_CERTFILE", str(cert))
        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_KEYFILE", str(key))

        with patch("ssl.SSLContext.load_cert_chain") as mock_load:
            create_tls_context()
            mock_load.assert_called_once_with(certfile=str(cert), keyfile=str(key))

    def test_neither_var_set_no_cert_chain(self, monkeypatch):
        monkeypatch.delenv("FOUNDRY_TLS_CLIENT_CERTFILE", raising=False)
        monkeypatch.delenv("FOUNDRY_TLS_CLIENT_KEYFILE", raising=False)

        with patch("ssl.SSLContext.load_cert_chain") as mock_load:
            create_tls_context()
            mock_load.assert_not_called()

    def test_only_certfile_set_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_CERTFILE", "/some/cert.pem")
        monkeypatch.delenv("FOUNDRY_TLS_CLIENT_KEYFILE", raising=False)

        import logging

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.tls"):
            ctx = create_tls_context()

        assert ctx is not None
        assert "FOUNDRY_TLS_CLIENT_CERTFILE is set but FOUNDRY_TLS_CLIENT_KEYFILE is not" in caplog.text

    def test_only_keyfile_set_logs_warning(self, monkeypatch, caplog):
        monkeypatch.delenv("FOUNDRY_TLS_CLIENT_CERTFILE", raising=False)
        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_KEYFILE", "/some/key.pem")

        import logging

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.tls"):
            ctx = create_tls_context()

        assert ctx is not None
        assert "FOUNDRY_TLS_CLIENT_KEYFILE is set but FOUNDRY_TLS_CLIENT_CERTFILE is not" in caplog.text

    def test_certfile_missing_raises_file_not_found(self, monkeypatch, tmp_path):
        key = tmp_path / "client.key"
        key.write_text("KEY")

        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_CERTFILE", "/nonexistent/cert.pem")
        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_KEYFILE", str(key))

        with pytest.raises(FileNotFoundError, match="FOUNDRY_TLS_CLIENT_CERTFILE"):
            create_tls_context()

    def test_keyfile_missing_raises_file_not_found(self, monkeypatch, tmp_path):
        cert = tmp_path / "client.crt"
        cert.write_text("CERT")

        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_CERTFILE", str(cert))
        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_KEYFILE", "/nonexistent/key.pem")

        with pytest.raises(FileNotFoundError, match="FOUNDRY_TLS_CLIENT_KEYFILE"):
            create_tls_context()

    def test_client_cert_with_verify_disabled(self, monkeypatch, tmp_path):
        cert = tmp_path / "client.crt"
        key = tmp_path / "client.key"
        cert.write_text("CERT")
        key.write_text("KEY")
        key.chmod(0o600)  # avoid an unasserted permission warning on POSIX CI (umask default)

        monkeypatch.setenv("FOUNDRY_TLS_VERIFY", "false")
        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_CERTFILE", str(cert))
        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_KEYFILE", str(key))

        with patch("ssl.SSLContext.load_cert_chain") as mock_load:
            ctx = create_tls_context()
            mock_load.assert_called_once_with(certfile=str(cert), keyfile=str(key))
            assert ctx.verify_mode == ssl.CERT_NONE


class TestKeyFilePermissionCheck:
    """Spec: strands-tls-enforcement — Client certificate key file permission check (V-222551)."""

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SKIP_REASON)
    def test_warns_on_group_or_world_readable_key(self, tmp_path, caplog):
        key = tmp_path / "client.key"
        key.write_text("KEY")
        key.chmod(0o644)

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.tls"):
            _check_key_file_permissions(key)

        assert "readable/writable by group or other" in caplog.text
        assert str(key) in caplog.text

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SKIP_REASON)
    def test_silent_on_owner_only_key(self, tmp_path, caplog):
        key = tmp_path / "client.key"
        key.write_text("KEY")
        key.chmod(0o600)

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.tls"):
            _check_key_file_permissions(key)

        assert caplog.text == ""

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SKIP_REASON)
    def test_silent_on_group_or_world_execute_only_key(self, tmp_path, caplog):
        """Execute bits alone grant no read/write access; must not trigger the warning."""
        key = tmp_path / "client.key"
        key.write_text("KEY")
        key.chmod(0o711)

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.tls"):
            _check_key_file_permissions(key)

        assert caplog.text == ""

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SKIP_REASON)
    def test_silent_when_stat_raises_oserror(self, tmp_path, caplog):
        """A TOCTOU race (file removed between is_file() and stat()) must not crash."""
        key = tmp_path / "client.key"
        key.write_text("KEY")
        key.unlink()  # gone by the time _check_key_file_permissions() stats it

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.tls"):
            _check_key_file_permissions(key)

        assert "readable/writable by group or other" not in caplog.text

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SKIP_REASON)
    def test_warns_again_on_repeated_calls(self, tmp_path, caplog):
        """create_tls_context() runs per agent/session, not just at startup - re-warn every call.

        Deliberate: a misconfigured key needs to be fixed, and a warning that
        keeps firing is harder to miss in scrollback than a one-time warning
        that goes silent after the first session.
        """
        key = tmp_path / "client.key"
        key.write_text("KEY")
        key.chmod(0o644)

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.tls"):
            _check_key_file_permissions(key)
            caplog.clear()
            _check_key_file_permissions(key)

        assert "readable/writable by group or other" in caplog.text

    def test_permission_error_on_stat_is_not_swallowed(self, monkeypatch):
        """Only the documented TOCTOU race (FileNotFoundError) is caught.

        Other stat() failures (e.g. permission denied) must surface rather than
        be silently skipped - those mean the defense-in-depth check itself
        didn't run. Uses a duck-typed stand-in rather than a real Path: Path
        defines __slots__ (no instance-attribute patching), and patching the
        Path class itself would affect every Path.stat() call process-wide
        during the test - the same class of hazard as monkeypatching os.name.
        Forces the POSIX branch via the _is_posix() seam so this runs on any host.
        """
        monkeypatch.setattr("foundry_strands_agent.tls._is_posix", lambda: True)

        class _StatRaisesPermissionError:
            def __str__(self) -> str:
                return "/fake/client.key"

            def stat(self) -> None:
                raise PermissionError("denied")

        with pytest.raises(PermissionError):
            _check_key_file_permissions(_StatRaisesPermissionError())  # type: ignore[arg-type]

    def test_noop_on_non_posix(self, tmp_path, monkeypatch, caplog):
        """Simulates a non-POSIX host via the _is_posix() seam, not the real os.name.

        Monkeypatching the process-global os.name directly is unsafe here:
        pathlib's Path.__new__ also reads it to pick WindowsPath vs PosixPath,
        so patching it corrupts Path(str) construction anywhere else in the
        process during the patched window - including inside pytest's own
        result-reporting machinery, which runs before a monkeypatch fixture's
        teardown reverts the value. That previously caused a pytest
        INTERNALERROR on a real POSIX CI runner. The _is_posix() indirection
        sidesteps this entirely.
        """
        key = tmp_path / "client.key"
        key.write_text("KEY")
        monkeypatch.setattr("foundry_strands_agent.tls._is_posix", lambda: False)

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.tls"):
            _check_key_file_permissions(key)

        assert caplog.text == ""

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SKIP_REASON)
    def test_load_client_cert_warns_but_still_loads_permissive_key(self, monkeypatch, tmp_path, caplog):
        cert = tmp_path / "client.crt"
        key = tmp_path / "client.key"
        cert.write_text("CERT")
        key.write_text("KEY")
        key.chmod(0o644)

        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_CERTFILE", str(cert))
        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_KEYFILE", str(key))

        with (
            caplog.at_level(logging.WARNING, logger="foundry_strands_agent.tls"),
            patch("ssl.SSLContext.load_cert_chain") as mock_load,
        ):
            create_tls_context()

        mock_load.assert_called_once_with(certfile=str(cert), keyfile=str(key))
        assert "readable/writable by group or other" in caplog.text

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SKIP_REASON)
    def test_load_client_cert_silent_for_restrictive_key(self, monkeypatch, tmp_path, caplog):
        cert = tmp_path / "client.crt"
        key = tmp_path / "client.key"
        cert.write_text("CERT")
        key.write_text("KEY")
        key.chmod(0o600)

        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_CERTFILE", str(cert))
        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_KEYFILE", str(key))

        with (
            caplog.at_level(logging.WARNING, logger="foundry_strands_agent.tls"),
            patch("ssl.SSLContext.load_cert_chain") as mock_load,
        ):
            create_tls_context()

        mock_load.assert_called_once_with(certfile=str(cert), keyfile=str(key))
        assert caplog.text == ""

    def test_load_client_cert_calls_permission_check(self, monkeypatch, tmp_path):
        """Wiring check: _check_key_file_permissions() is invoked before load_cert_chain().

        The no-op-on-non-POSIX branch itself is unit-tested directly against
        an already-constructed Path in test_noop_on_non_posix - it is not
        re-verified end-to-end here because monkeypatching the real os.name
        away from the host's actual value corrupts pathlib's Path flavor
        dispatch (WindowsPath vs PosixPath) for any Path(str) constructed
        during the patched window, which _load_client_cert() does internally
        for FOUNDRY_TLS_CLIENT_CERTFILE/KEYFILE - breaking is_file() in a way
        unrelated to the behavior under test.
        """
        cert = tmp_path / "client.crt"
        key = tmp_path / "client.key"
        cert.write_text("CERT")
        key.write_text("KEY")

        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_CERTFILE", str(cert))
        monkeypatch.setenv("FOUNDRY_TLS_CLIENT_KEYFILE", str(key))

        with (
            patch("foundry_strands_agent.tls._check_key_file_permissions") as mock_check,
            patch("ssl.SSLContext.load_cert_chain") as mock_load,
        ):
            create_tls_context()

        mock_check.assert_called_once_with(key)
        mock_load.assert_called_once_with(certfile=str(cert), keyfile=str(key))


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
        # http_client is no longer in the static client_args dict passed to NIMSModel's
        # constructor - NIMSModel._resolve_client_args() injects a fresh TLS-configured
        # client on every call instead (see TestNimsModelClientLifecycle in
        # test_factory.py), so this test exercises the real NIMSModel, not a mocked one.
        model = _default_nims_model(config)
        http_client = model._resolve_client_args()["http_client"]
        ssl_context = http_client._transport._pool._ssl_context
        assert ssl_context.minimum_version == ssl.TLSVersion.TLSv1_2
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED


def _mcp_client_with_transport(handler) -> httpx.AsyncClient:
    """A client built with `create_mcp_http_client`'s exact kwargs, but a mock transport."""
    with patch("foundry_strands_agent.tls.httpx.AsyncClient") as mock_client:
        create_mcp_http_client(headers={"X-Api-Key": "header-secret"})
    return httpx.AsyncClient(**mock_client.call_args.kwargs, transport=httpx.MockTransport(handler), trust_env=False)


class TestMcpClientRedirectDowngrade:
    """An https MCP endpoint must not redirect the client's credential headers to plaintext."""

    @staticmethod
    def _redirecting_handler(location: str, seen: list[httpx.URL]):
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url)
            if request.url.path == "/mcp":
                return httpx.Response(307, headers={"Location": location})
            return httpx.Response(200)

        return handler

    async def test_https_to_http_redirect_is_refused(self):
        seen: list[httpx.URL] = []
        location = f"http://user:{FAKE_URL_SECRET}@example.com/next"
        async with _mcp_client_with_transport(self._redirecting_handler(location, seen)) as client:
            with pytest.raises(httpx.UnsupportedProtocol) as exc_info:
                await client.get("https://example.com/mcp")

        assert [url.scheme for url in seen] == ["https"]
        assert FAKE_URL_SECRET not in str(exc_info.value)

    @pytest.mark.parametrize("location", ["https://other.example.com/next", "/next"])
    async def test_https_to_https_redirect_is_followed(self, location: str):
        seen: list[httpx.URL] = []
        async with _mcp_client_with_transport(self._redirecting_handler(location, seen)) as client:
            response = await client.get("https://example.com/mcp")

        assert response.status_code == 200
        assert [url.scheme for url in seen] == ["https", "https"]

    async def test_http_to_http_redirect_is_unaffected(self):
        seen: list[httpx.URL] = []
        async with _mcp_client_with_transport(self._redirecting_handler("http://example.com/next", seen)) as client:
            response = await client.get("http://example.com/mcp")

        assert response.status_code == 200
        assert len(seen) == 2
