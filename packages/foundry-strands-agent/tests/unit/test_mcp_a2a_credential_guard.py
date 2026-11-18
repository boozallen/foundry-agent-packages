# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the MCP/A2A plaintext-credential guard on StrandsAgentConfig.

Config load must fail for an http MCP or
A2A endpoint that carries a credential (in a credential-bearing header or the url's
own userinfo), unless the deployer has explicitly opted in via
`allow_insecure_credentialed_endpoints`.
"""

import logging
from pathlib import Path
from types import MappingProxyType

import pytest
import yaml

from foundry_agent_config import load_config
from foundry_agent_core import InvalidConfigurationError
from foundry_strands_agent.config.models import StrandsAgentConfig

# Fake, non-functional values used only to exercise the credential guard below.
# None of these authenticate against anything real.
FAKE_BEARER_SECRET = "Bearer secret"  # trufflehog:ignore
FAKE_API_KEY = "abc123"  # trufflehog:ignore
FAKE_LIVE_API_KEY = "sk-live-abc123"  # trufflehog:ignore
FAKE_BEARER_SUPER_SECRET_TOKEN = "Bearer super-secret-token"  # trufflehog:ignore
FAKE_SUPER_SECRET_TOKEN = "super-secret-token"  # trufflehog:ignore
FAKE_BEARER_OTHER_SECRET = "Bearer other-secret"  # trufflehog:ignore
FAKE_OTHER_SECRET = "other-secret"  # trufflehog:ignore
FAKE_PASSWORD_WITH_AT_SIGN = "p@ssw0rd-tail"  # trufflehog:ignore
FAKE_SUPERSECRETPASSWORD = "supersecretpassword"  # trufflehog:ignore
FAKE_HEADER_SECRET_VALUE = "secret-value"  # trufflehog:ignore
FAKE_HEADER_SECRET = "header-secret"  # trufflehog:ignore
FAKE_UNLISTED_SECRET = "unlisted-secret"  # trufflehog:ignore
FAKE_QUERY_SECRET = "query-secret"  # trufflehog:ignore
FAKE_FRAG_SECRET = "frag-secret"  # trufflehog:ignore
FAKE_EXTRA_SECRET = "extra-secret"  # trufflehog:ignore
FAKE_PASS_SECRET = "pass-secret"  # trufflehog:ignore
FAKE_SECRET_PART_A = "SEC"  # trufflehog:ignore
FAKE_SECRET_PART_B = "RET-tail"  # trufflehog:ignore
FAKE_HTTPS_CREDENTIAL = "token"  # trufflehog:ignore


class TestMcpPlaintextCredentialsRejected:
    """AC1: config load fails for an http MCP endpoint carrying an Authorization header."""

    def test_http_mcp_with_authorization_header_raises(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[{"url": "http://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SECRET}}]
            )

        assert "mcp_servers" in str(exc_info.value)

    def test_http_mcp_with_x_api_key_header_raises(self):
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(mcp_servers=[{"url": "http://example.com/mcp", "headers": {"X-Api-Key": FAKE_API_KEY}}])

    def test_http_mcp_with_lowercase_authorization_header_raises(self):
        """Header-key matching is case-insensitive."""
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(
                mcp_servers=[{"url": "http://example.com/mcp", "headers": {"authorization": FAKE_BEARER_SECRET}}]
            )

    def test_from_env_http_mcp_with_authorization_header_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("STRANDS_ALLOW_INSECURE_CREDENTIALED_ENDPOINTS", raising=False)
        monkeypatch.setenv(
            "STRANDS_MCP_SERVERS",
            f'[{{"url": "http://example.com/mcp", "headers": {{"Authorization": "{FAKE_BEARER_SECRET}"}}}}]',
        )

        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig.from_env()

    def test_mixed_list_with_one_unsafe_entry_raises(self):
        """A single unsafe entry fails the whole list, not just the offending index."""
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(
                mcp_servers=[
                    {"url": "https://safe.example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SECRET}},
                    {"url": "http://unsafe.example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SECRET}},
                ]
            )


class TestA2aPlaintextCredentialsRejected:
    """Same guard applies to a2a_servers, per the issue's explicit mention of A2A."""

    def test_http_a2a_with_authorization_header_raises(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                a2a_servers=[{"url": "http://example.com/a2a", "headers": {"Authorization": FAKE_BEARER_SECRET}}]
            )

        assert "a2a_servers" in str(exc_info.value)


class TestHttpsWithCredentialsStillLoads:
    """AC2: an https endpoint with credentials loads as before.

    Connecting with one is covered by `test_factory_mcp_session.py`'s `TestCollectMcpClients`,
    whose credentialed servers use `https`.
    """

    def test_https_mcp_with_authorization_header_loads(self):
        config = StrandsAgentConfig(
            mcp_servers=[{"url": "https://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SECRET}}]
        )

        assert config.mcp_servers == [
            {"url": "https://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SECRET}}
        ]

    def test_https_a2a_with_authorization_header_loads(self):
        config = StrandsAgentConfig(
            a2a_servers=[{"url": "https://example.com/a2a", "headers": {"Authorization": FAKE_BEARER_SECRET}}]
        )

        assert config.a2a_servers == [
            {"url": "https://example.com/a2a", "headers": {"Authorization": FAKE_BEARER_SECRET}}
        ]


class TestPlaintextWithoutCredentialsStillLoads:
    """Plaintext without credentials keeps working with no opt-in required (existing behavior)."""

    def test_http_mcp_without_headers_loads(self):
        config = StrandsAgentConfig(mcp_servers=[{"url": "http://localhost:8080"}])

        assert config.mcp_servers == [{"url": "http://localhost:8080"}]

    def test_http_mcp_with_non_credential_header_loads(self):
        config = StrandsAgentConfig(
            mcp_servers=[{"url": "http://localhost:8080", "headers": {"Content-Type": "application/json"}}]
        )

        assert config.mcp_servers[0]["headers"] == {"Content-Type": "application/json"}

    def test_from_env_with_mcp_servers_matches_existing_test(self, monkeypatch: pytest.MonkeyPatch):
        """Mirrors test_config_loading.py::test_from_env_with_mcp_servers - must keep passing unmodified."""
        monkeypatch.setenv("STRANDS_MCP_SERVERS", '[{"url": "http://localhost:8080"}]')

        config = StrandsAgentConfig.from_env()

        assert len(config.mcp_servers) == 1
        assert config.mcp_servers[0]["url"] == "http://localhost:8080"


class TestExceptionMessageNeverLeaksCredentials:
    """Regression test: the raised exception must never render the raw credential value.

    `InvalidConfigurationError.__init__` renders `config_value` straight into the
    exception's `str()` via `repr()`. Passing the raw server dict (headers included) would
    print the bearer token into the exception message, which then propagates into whatever
    logs/error paths handle it - defeating the entire purpose of this guard.
    """

    def test_authorization_header_value_not_in_exception_message(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[
                    {"url": "http://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SUPER_SECRET_TOKEN}}
                ]
            )

        message = str(exc_info.value)
        assert FAKE_SUPER_SECRET_TOKEN not in message
        assert "Bearer" not in message
        # Still informative enough to debug: names which field and header key tripped the guard.
        # (Checked via the structured `config_key` attribute, not a domain-shaped substring of
        # the rendered message, to avoid CodeQL's py/incomplete-url-substring-sanitization
        # false positive on test assertions that aren't making a URL-trust decision.)
        assert exc_info.value.config_key == "mcp_servers"
        assert "Authorization" in message

    def test_api_key_header_value_not_in_exception_message(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[{"url": "http://example.com/mcp", "headers": {"X-Api-Key": FAKE_LIVE_API_KEY}}]
            )

        assert FAKE_LIVE_API_KEY not in str(exc_info.value)


class TestMalformedSchemeRejected:
    r"""Regression test: a malformed scheme must not bypass the guard.

    The guard checks the scheme via an RFC 3986-anchored regex, not `urlsplit(url).scheme`.
    `urlsplit` is lenient about what precedes `://` - a NUL byte or a literal space makes it
    return `""` for the scheme, while a `\r`/`\n` embedded in the scheme is stripped and it
    still reports `"http"` - but none of these match the anchored regex. Anything that isn't
    a well-formed `http` or `https` scheme is rejected regardless of the opt-in, with no
    separate blocklist needed per character.
    """

    def test_nul_byte_in_scheme_still_raises(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[
                    {"url": "ht\x00tp://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SUPER_SECRET_TOKEN}}
                ]
            )

        assert FAKE_SUPER_SECRET_TOKEN not in str(exc_info.value)

    def test_space_in_scheme_still_raises(self):
        """A space breaks urlsplit's scheme parsing too."""
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[
                    {"url": "ht p://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SUPER_SECRET_TOKEN}}
                ]
            )

        assert FAKE_SUPER_SECRET_TOKEN not in str(exc_info.value)

    def test_carriage_return_in_scheme_still_raises(self):
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(
                a2a_servers=[{"url": "ht\rtp://example.com/a2a", "headers": {"Authorization": FAKE_BEARER_SECRET}}]
            )

    def test_nul_byte_in_scheme_raises_even_when_insecure_allowed(self):
        """The malformed-scheme rejection is a parsing-integrity issue, not a posture opt-in.

        `allow_insecure_credentialed_endpoints` only ever downgrades a *provably-http*,
        well-formed-scheme entry to a warning - it must not suppress rejection of an entry
        whose scheme can't be proven to be `https` at all.
        """
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(
                allow_insecure_credentialed_endpoints=True,
                mcp_servers=[
                    {"url": "ht\x00tp://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SUPER_SECRET_TOKEN}}
                ],
            )

    def test_nul_byte_without_credential_headers_still_loads(self):
        """No credential-bearing headers means the guard's scope doesn't apply.

        Malformed scheme or not, this matches the existing 'http without credentials is
        fine' behavior.
        """
        config = StrandsAgentConfig(mcp_servers=[{"url": "ht\x00tp://example.com/mcp"}])

        assert config.mcp_servers[0]["url"] == "ht\x00tp://example.com/mcp"


class TestUrlUserinfoCredentialNeverLeaks:
    """Regression test: a credential embedded in the url's userinfo must never leak either.

    `http://user:token@host/path` carries a credential in the url itself, not just in  # trufflehog:ignore
    headers - the exception message (and the redacted server dict inside it) must never
    render that token verbatim, the same guarantee `TestExceptionMessageNeverLeaksCredentials`
    already covers for header values.
    """

    def test_userinfo_credential_not_in_exception_message(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[
                    {
                        "url": f"http://svc:{FAKE_SUPER_SECRET_TOKEN}@example.com/mcp",
                        "headers": {"Authorization": FAKE_BEARER_OTHER_SECRET},
                    }
                ]
            )

        message = str(exc_info.value)
        assert FAKE_SUPER_SECRET_TOKEN not in message
        assert FAKE_OTHER_SECRET not in message

    def test_userinfo_credential_not_in_warning_log_when_insecure_allowed(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.config.models"):
            StrandsAgentConfig(
                allow_insecure_credentialed_endpoints=True,
                mcp_servers=[
                    {
                        "url": f"http://svc:{FAKE_SUPER_SECRET_TOKEN}@example.com/mcp",
                        "headers": {"Authorization": FAKE_BEARER_SECRET},
                    }
                ],
            )

        log_text = " ".join(record.message for record in caplog.records)
        assert FAKE_SUPER_SECRET_TOKEN not in log_text

    def test_userinfo_credential_containing_at_sign_fully_redacted(self):
        """A password containing '@' must be redacted in full, not just up to the first '@'.

        httpx takes the LAST '@' as the userinfo/host boundary, not the first - stopping at
        the first '@' would leak the remainder of a password shaped like `p@ssw0rd`.
        """
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[
                    {
                        "url": f"http://svc:{FAKE_PASSWORD_WITH_AT_SIGN}@example.com/mcp",
                        "headers": {"Authorization": FAKE_BEARER_OTHER_SECRET},
                    }
                ]
            )

        message = str(exc_info.value)
        assert FAKE_PASSWORD_WITH_AT_SIGN not in message
        assert "ssw0rd-tail" not in message

    def test_userinfo_credential_without_double_slash_fully_redacted(self):
        """A credential embedded in a url with no '://' at all must still be redacted.

        Redaction that anchors on a literal '://' would pass the credential through
        unredacted for the RFC-3986-valid `scheme:opaque` form with no authority marker
        (e.g. a dropped-slash typo).
        """
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[
                    {
                        "url": f"http:svc:{FAKE_SUPER_SECRET_TOKEN}@example.com/mcp",
                        "headers": {"Authorization": FAKE_BEARER_OTHER_SECRET},
                    }
                ]
            )

        assert FAKE_SUPER_SECRET_TOKEN not in str(exc_info.value)

    @pytest.mark.parametrize(
        "url",
        [
            f"http://svc:{FAKE_SECRET_PART_A}/{FAKE_SECRET_PART_B}@example.com/mcp",
            f"http://svc:{FAKE_SECRET_PART_A}?{FAKE_SECRET_PART_B}@example.com/mcp",
            f"http://svc:{FAKE_SECRET_PART_A}#{FAKE_SECRET_PART_B}@example.com/mcp",
            f"http://example.com/mcp?token={FAKE_SECRET_PART_A}@{FAKE_SECRET_PART_B}",
        ],
    )
    def test_delimiter_inside_password_or_at_in_query_never_leaks(self, url: str):
        """An unencoded '/', '?' or '#' in the password, or an '@' in the query, must not leak either part."""
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(mcp_servers=[{"url": url, "headers": {"Authorization": FAKE_BEARER_OTHER_SECRET}}])

        message = str(exc_info.value)
        assert FAKE_SECRET_PART_A not in message
        assert FAKE_SECRET_PART_B not in message


class TestMissingOrNonStringUrlRejected:
    """Regression test: a missing/non-string url must not silently bypass the guard.

    Paired with credential headers, it can't be proven to use https, so it's rejected the
    same way an unparseable scheme is.
    """

    def test_null_url_with_credential_header_raises(self):
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(mcp_servers=[{"url": None, "headers": {"Authorization": FAKE_BEARER_SECRET}}])

    def test_missing_url_key_with_credential_header_raises(self):
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(mcp_servers=[{"headers": {"Authorization": FAKE_BEARER_SECRET}}])

    def test_null_url_without_credential_headers_still_loads(self):
        """No credential-bearing headers means the guard's scope doesn't apply.

        Same as any other entry shape - this matches pre-existing behavior for a missing
        or null url.
        """
        config = StrandsAgentConfig(mcp_servers=[{"url": None}])

        assert config.mcp_servers[0]["url"] is None


class TestUrlEmbeddedCredentialWithoutHeadersRejected:
    """Regression test: a url-embedded credential must be caught with no headers at all.

    httpx derives HTTP Basic-Auth from a url's userinfo by default whenever no explicit
    `auth=` is set (`httpx.Client._build_request_auth`) - a plaintext url carrying its own
    embedded credential (`http://user:token@host/path`) sends that credential unencrypted
    exactly like one paired with an `Authorization` header, even when the entry has no
    `headers` key at all, so the url is checked independently of the headers.
    """

    def test_http_url_with_embedded_credential_and_no_headers_raises(self):
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(mcp_servers=[{"url": f"http://svc:{FAKE_SUPERSECRETPASSWORD}@internal-mcp/mcp"}])

    def test_http_a2a_url_with_embedded_credential_and_no_headers_raises(self):
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(a2a_servers=[{"url": f"http://svc:{FAKE_SUPERSECRETPASSWORD}@internal-a2a/a2a"}])

    def test_embedded_credential_value_not_in_exception_message(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(mcp_servers=[{"url": f"http://svc:{FAKE_SUPERSECRETPASSWORD}@internal-mcp/mcp"}])

        assert FAKE_SUPERSECRETPASSWORD not in str(exc_info.value)

    def test_https_url_with_embedded_credential_and_no_headers_still_loads(self):
        """The https case is safe regardless of headers - matches the header-credential case."""
        config = StrandsAgentConfig(mcp_servers=[{"url": f"https://svc:{FAKE_HTTPS_CREDENTIAL}@internal-mcp/mcp"}])

        assert config.mcp_servers == [{"url": f"https://svc:{FAKE_HTTPS_CREDENTIAL}@internal-mcp/mcp"}]

    def test_url_with_no_userinfo_and_no_headers_still_loads(self):
        """A plain url with neither an embedded credential nor headers is unaffected."""
        config = StrandsAgentConfig(mcp_servers=[{"url": "http://internal-mcp/mcp"}])

        assert config.mcp_servers == [{"url": "http://internal-mcp/mcp"}]

    def test_opt_in_allows_http_url_with_embedded_credential_and_no_headers(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.config.models"):
            config = StrandsAgentConfig(
                allow_insecure_credentialed_endpoints=True,
                mcp_servers=[{"url": f"http://svc:{FAKE_SUPERSECRETPASSWORD}@internal-mcp/mcp"}],
            )

        assert config.mcp_servers == [{"url": f"http://svc:{FAKE_SUPERSECRETPASSWORD}@internal-mcp/mcp"}]
        assert any("insecure" in record.message.lower() for record in caplog.records)
        assert FAKE_SUPERSECRETPASSWORD not in " ".join(record.message for record in caplog.records)


class TestCredentialHeaderKeyWhitespaceNormalized:
    """Regression test: incidental whitespace in a header key must not defeat the match.

    httpx does not strip or reject a header key with leading/trailing whitespace (e.g.
    `"Authorization "`) - it lower-cases but preserves it and transmits it as a distinct
    header - so the guard strips the key before comparing it against
    `_CREDENTIAL_HEADER_NAMES` (which holds no whitespace-padded entries).
    """

    def test_header_key_with_trailing_space_still_raises(self):
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(
                mcp_servers=[{"url": "http://internal-mcp/mcp", "headers": {"Authorization ": FAKE_BEARER_SECRET}}]
            )

    def test_header_key_with_leading_space_still_raises(self):
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(
                mcp_servers=[{"url": "http://internal-mcp/mcp", "headers": {" Authorization": FAKE_BEARER_SECRET}}]
            )

    def test_header_value_not_in_exception_message_with_whitespace_padded_key(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[
                    {"url": "http://internal-mcp/mcp", "headers": {"Authorization ": FAKE_BEARER_SUPER_SECRET_TOKEN}}
                ]
            )

        assert FAKE_SUPER_SECRET_TOKEN not in str(exc_info.value)


class TestNonMappingHeadersRejected:
    """A non-mapping `headers` value can't have its header names checked, so it's rejected.

    E.g. a list of `[name, value]` pairs: rejected unconditionally, whatever the scheme and
    even under the opt-in, and rendered as `<redacted>` in the exception.
    """

    @pytest.mark.parametrize("url", ["http://example.com/mcp", "https://example.com/mcp"])
    def test_list_of_pairs_headers_raises(self, url: str):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[{"url": url, "headers": [["Authorization", FAKE_BEARER_SUPER_SECRET_TOKEN]]}]
            )

        assert FAKE_SUPER_SECRET_TOKEN not in str(exc_info.value)
        assert "non-mapping" in str(exc_info.value)

    def test_list_of_pairs_headers_raises_even_when_insecure_allowed(self):
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(
                allow_insecure_credentialed_endpoints=True,
                a2a_servers=[{"url": "http://example.com/a2a", "headers": [["Authorization", FAKE_BEARER_SECRET]]}],
            )

    def test_empty_non_mapping_headers_is_outside_guard_scope(self):
        """An empty value carries no header at all, so there's no credential to guard."""
        config = StrandsAgentConfig(mcp_servers=[{"url": "http://localhost:8080", "headers": []}])

        assert config.mcp_servers[0]["headers"] == []


class TestAllowInsecureCredentialedEndpointsOptIn:
    """The opt-in flag downgrades the rejection to a logged warning instead of raising."""

    def test_defaults_to_false(self):
        config = StrandsAgentConfig()

        assert config.allow_insecure_credentialed_endpoints is False

    def test_opt_in_allows_http_mcp_with_authorization_header(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.config.models"):
            config = StrandsAgentConfig(
                allow_insecure_credentialed_endpoints=True,
                mcp_servers=[{"url": "http://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SECRET}}],
            )

        assert config.mcp_servers == [
            {"url": "http://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SECRET}}
        ]
        assert any("insecure" in record.message.lower() for record in caplog.records)

    def test_opt_in_allows_http_a2a_with_authorization_header(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.config.models"):
            config = StrandsAgentConfig(
                allow_insecure_credentialed_endpoints=True,
                a2a_servers=[{"url": "http://example.com/a2a", "headers": {"Authorization": FAKE_BEARER_SECRET}}],
            )

        assert config.a2a_servers == [
            {"url": "http://example.com/a2a", "headers": {"Authorization": FAKE_BEARER_SECRET}}
        ]
        assert any("insecure" in record.message.lower() for record in caplog.records)

    def test_from_env_opt_in_env_var(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("STRANDS_ALLOW_INSECURE_CREDENTIALED_ENDPOINTS", "true")
        monkeypatch.setenv(
            "STRANDS_MCP_SERVERS",
            f'[{{"url": "http://example.com/mcp", "headers": {{"Authorization": "{FAKE_BEARER_SECRET}"}}}}]',
        )

        config = StrandsAgentConfig.from_env()

        assert config.allow_insecure_credentialed_endpoints is True
        assert config.mcp_servers[0]["url"] == "http://example.com/mcp"

    def test_from_env_opt_in_defaults_false_when_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("STRANDS_ALLOW_INSECURE_CREDENTIALED_ENDPOINTS", raising=False)

        config = StrandsAgentConfig.from_env()

        assert config.allow_insecure_credentialed_endpoints is False


class TestAdditionalCredentialHeaderShapes:
    """Every credential-bearing header name, and header shapes httpx accepts besides a str-keyed dict."""

    @pytest.mark.parametrize(
        "header",
        ["Authorization", "Proxy-Authorization", "Cookie", "X-Api-Key", "X-Api-Token", "Api-Key", "X-Auth-Token"],
    )
    def test_http_with_standard_credential_header_raises(self, header: str):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[{"url": "http://example.com/mcp", "headers": {header: FAKE_HEADER_SECRET_VALUE}}]
            )

        assert header in str(exc_info.value)
        assert FAKE_HEADER_SECRET_VALUE not in str(exc_info.value)

    def test_bytes_authorization_key_raises(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[
                    {"url": "http://example.com/mcp", "headers": {b"Authorization": FAKE_BEARER_SUPER_SECRET_TOKEN}}
                ]
            )

        assert FAKE_SUPER_SECRET_TOKEN not in str(exc_info.value)

    def test_mapping_proxy_headers_over_https_loads(self):
        headers = MappingProxyType({"Authorization": FAKE_BEARER_SECRET})

        config = StrandsAgentConfig(mcp_servers=[{"url": "https://example.com/mcp", "headers": headers}])

        assert config.mcp_servers[0]["headers"] is headers

    def test_mapping_proxy_headers_over_http_raises(self):
        with pytest.raises(InvalidConfigurationError):
            StrandsAgentConfig(
                mcp_servers=[
                    {
                        "url": "http://example.com/mcp",
                        "headers": MappingProxyType({"Authorization": FAKE_BEARER_SECRET}),
                    }
                ]
            )

    def test_ws_scheme_with_authorization_raises_even_when_insecure_allowed(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                allow_insecure_credentialed_endpoints=True,
                mcp_servers=[{"url": "ws://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SECRET}}],
            )

        assert "non-http(s) scheme" in str(exc_info.value)


class TestRedactionCoversEveryValue:
    """No header value, url query/fragment, or extra field value reaches the exception or the warning.

    The entry is still identified: a url with no `@` keeps its scheme, host and path. (Asserted
    by equality on the redacted url, or on the path alone, not a domain-shaped substring, to
    avoid CodeQL's py/incomplete-url-substring-sanitization false positive.)
    """

    _SERVER = {
        "url": f"http://example.com/mcp?token={FAKE_QUERY_SECRET}#{FAKE_FRAG_SECRET}",
        "name": "docs",
        "headers": {"Authorization": f"Bearer {FAKE_HEADER_SECRET}", "X-Custom-Secret": FAKE_UNLISTED_SECRET},
        "extra": FAKE_EXTRA_SECRET,
        "timeout": None,
    }
    _SECRETS = (FAKE_QUERY_SECRET, FAKE_FRAG_SECRET, FAKE_HEADER_SECRET, FAKE_UNLISTED_SECRET, FAKE_EXTRA_SECRET)

    def test_exception_message_carries_no_value(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(mcp_servers=[dict(self._SERVER)])

        message = str(exc_info.value)
        for secret in self._SECRETS:
            assert secret not in message
        assert exc_info.value.config_value["url"] == "http://example.com/mcp?<redacted>"
        assert "X-Custom-Secret" in message
        assert "docs" in message

    def test_opt_in_warning_carries_no_value(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.config.models"):
            StrandsAgentConfig(allow_insecure_credentialed_endpoints=True, mcp_servers=[dict(self._SERVER)])

        warning = caplog.text
        assert "/mcp" in warning
        for secret in self._SECRETS:
            assert secret not in warning

    def test_userinfo_before_query_is_still_redacted(self):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            StrandsAgentConfig(
                mcp_servers=[{"url": f"http://user:{FAKE_PASS_SECRET}@example.com/mcp?token={FAKE_QUERY_SECRET}"}]
            )

        message = str(exc_info.value)
        assert FAKE_PASS_SECRET not in message
        assert FAKE_QUERY_SECRET not in message


class TestLoadConfigPath:
    """The guard and its opt-in also apply on the generic `load_config(..., "STRANDS")` route."""

    @pytest.fixture
    def plaintext_credentialed_yaml(self, tmp_path: Path) -> Path:
        config = {
            "model": {"provider": "bedrock"},
            "mcp_servers": [{"url": "http://example.com/mcp", "headers": {"Authorization": FAKE_BEARER_SECRET}}],
        }
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(yaml.dump(config))
        return yaml_path

    def test_load_config_rejects_plaintext_credentialed_server(
        self, plaintext_credentialed_yaml: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.delenv("STRANDS__ALLOW_INSECURE_CREDENTIALED_ENDPOINTS", raising=False)

        with pytest.raises(InvalidConfigurationError):
            load_config(StrandsAgentConfig, plaintext_credentialed_yaml, "STRANDS")

    def test_load_config_opt_in_env_var(self, plaintext_credentialed_yaml: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("STRANDS__ALLOW_INSECURE_CREDENTIALED_ENDPOINTS", "true")

        config = load_config(StrandsAgentConfig, plaintext_credentialed_yaml, "STRANDS")

        assert config.allow_insecure_credentialed_endpoints is True
        assert config.mcp_servers[0]["url"] == "http://example.com/mcp"
