# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for AuthConfig module."""

import pytest

from foundry_auth.config import AuthConfig


@pytest.fixture
def base_env_vars(monkeypatch):
    """Set up base environment variables for AuthConfig."""
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("OIDC_CALLBACK_URL", "https://app.example.com/callback")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")


def test_single_prefix_configuration(monkeypatch):
    """Test single prefix configuration loading (AC2 partial)."""
    monkeypatch.setenv("API_OIDC_ISSUER", "https://api-issuer.example.com")
    monkeypatch.setenv("API_OIDC_CLIENT_ID", "api-client-id")
    monkeypatch.setenv("API_OIDC_CLIENT_SECRET", "api-secret")
    monkeypatch.setenv("API_OIDC_CALLBACK_URL", "https://api.example.com/callback")
    monkeypatch.setenv("API_FRONTEND_URL", "https://api.example.com")

    config = AuthConfig.from_env(prefix="API_")

    assert config.oidc_issuer == "https://api-issuer.example.com"
    assert config.oidc_client_id == "api-client-id"
    assert config.oidc_client_secret == "api-secret"
    assert config.oidc_callback_url == "https://api.example.com/callback"
    assert config.frontend_url == "https://api.example.com"


def test_multiple_independent_prefixes(monkeypatch):
    """Test multiple independent prefixes in same process (AC2)."""
    # Set up API config
    monkeypatch.setenv("API_OIDC_ISSUER", "https://api-issuer.example.com")
    monkeypatch.setenv("API_OIDC_CLIENT_ID", "api-client-id")
    monkeypatch.setenv("API_OIDC_CLIENT_SECRET", "api-secret")
    monkeypatch.setenv("API_OIDC_CALLBACK_URL", "https://api.example.com/callback")
    monkeypatch.setenv("API_FRONTEND_URL", "https://api.example.com")

    # Set up UI config
    monkeypatch.setenv("UI_OIDC_ISSUER", "https://ui-issuer.example.com")
    monkeypatch.setenv("UI_OIDC_CLIENT_ID", "ui-client-id")
    monkeypatch.setenv("UI_OIDC_CLIENT_SECRET", "ui-secret")
    monkeypatch.setenv("UI_OIDC_CALLBACK_URL", "https://ui.example.com/callback")
    monkeypatch.setenv("UI_FRONTEND_URL", "https://ui.example.com")

    api_config = AuthConfig.from_env(prefix="API_")
    ui_config = AuthConfig.from_env(prefix="UI_")

    assert api_config.oidc_issuer == "https://api-issuer.example.com"
    assert api_config.oidc_client_id == "api-client-id"
    assert ui_config.oidc_issuer == "https://ui-issuer.example.com"
    assert ui_config.oidc_client_id == "ui-client-id"
    assert api_config.oidc_client_id != ui_config.oidc_client_id


def test_prefixed_variables_independent_from_unprefixed(monkeypatch):
    """Test prefixed variables are read independently (no fallback to unprefixed)."""
    # Set unprefixed variables that should be ignored when using prefix
    monkeypatch.setenv("OIDC_ISSUER", "https://default-issuer.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "default-client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "default-secret")
    monkeypatch.setenv("OIDC_CALLBACK_URL", "https://default.example.com/callback")
    monkeypatch.setenv("FRONTEND_URL", "https://default.example.com")

    # Set complete prefixed configuration
    monkeypatch.setenv("API_OIDC_ISSUER", "https://api-issuer.example.com")
    monkeypatch.setenv("API_OIDC_CLIENT_ID", "api-client-id")
    monkeypatch.setenv("API_OIDC_CLIENT_SECRET", "api-secret")
    monkeypatch.setenv("API_OIDC_CALLBACK_URL", "https://api.example.com/callback")
    monkeypatch.setenv("API_FRONTEND_URL", "https://api.example.com")

    config = AuthConfig.from_env(prefix="API_")

    # Should use prefixed values, not unprefixed
    assert config.oidc_issuer == "https://api-issuer.example.com"
    assert config.oidc_client_id == "api-client-id"
    assert config.frontend_url == "https://api.example.com"


def test_unprefixed_configuration(base_env_vars):
    """Test unprefixed configuration loading."""
    config = AuthConfig.from_env()

    assert config.oidc_issuer == "https://issuer.example.com"
    assert config.oidc_client_id == "test-client-id"
    assert config.oidc_client_secret == "test-secret"
    assert config.oidc_callback_url == "https://app.example.com/callback"
    assert config.frontend_url == "https://app.example.com"


def test_single_cors_origin(monkeypatch, base_env_vars):
    """Test single CORS origin parsing (AC5 partial)."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://single.example.com")

    config = AuthConfig.from_env()

    assert config.cors_allowed_origins == ["https://single.example.com"]


def test_multiple_cors_origins(monkeypatch, base_env_vars):
    """Test multiple CORS origins parsing (AC5)."""
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS", "https://one.example.com,https://two.example.com,https://three.example.com"
    )

    config = AuthConfig.from_env()

    assert config.cors_allowed_origins == [
        "https://one.example.com",
        "https://two.example.com",
        "https://three.example.com",
    ]


def test_wildcard_cors_origin(monkeypatch, base_env_vars):
    """Test wildcard CORS origin."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")

    config = AuthConfig.from_env()

    assert config.cors_allowed_origins == ["*"]


def test_empty_cors_origins(monkeypatch, base_env_vars):
    """Test empty CORS origins uses default."""
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    config = AuthConfig.from_env()

    # Default is "http://localhost:5173"
    assert config.cors_allowed_origins == ["http://localhost:5173"]


def test_missing_oidc_issuer(monkeypatch):
    """Test missing OIDC_ISSUER raises error."""
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("OIDC_CALLBACK_URL", "https://app.example.com/callback")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")

    with pytest.raises(ValueError, match="Missing required environment variables.*OIDC_ISSUER"):
        AuthConfig.from_env()


def test_missing_client_id(monkeypatch):
    """Test missing OIDC_CLIENT_ID raises error."""
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("OIDC_CALLBACK_URL", "https://app.example.com/callback")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")

    with pytest.raises(ValueError, match="Missing required environment variables.*OIDC_CLIENT_ID"):
        AuthConfig.from_env()


def test_missing_callback_url(monkeypatch):
    """Test missing OIDC_CALLBACK_URL raises error."""
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")

    with pytest.raises(ValueError, match="Missing required environment variables.*OIDC_CALLBACK_URL"):
        AuthConfig.from_env()


def test_missing_frontend_url(monkeypatch):
    """Test missing FRONTEND_URL raises error."""
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("OIDC_CALLBACK_URL", "https://app.example.com/callback")

    with pytest.raises(ValueError, match="Missing required environment variables.*FRONTEND_URL"):
        AuthConfig.from_env()


def test_default_session_ttl(base_env_vars):
    """Test default session TTL."""
    config = AuthConfig.from_env()

    assert config.session_ttl_hours == 24


def test_default_token_refresh_threshold(base_env_vars):
    """Test default token refresh threshold."""
    config = AuthConfig.from_env()

    assert config.token_refresh_threshold_minutes == 5


def test_default_secure_cookies(base_env_vars):
    """Test default secure cookies."""
    config = AuthConfig.from_env()

    assert config.secure_cookies is True


def test_integer_field_parsing(monkeypatch, base_env_vars):
    """Test integer fields parsed correctly."""
    monkeypatch.setenv("SESSION_TTL_HOURS", "48")
    monkeypatch.setenv("TOKEN_REFRESH_THRESHOLD_MINUTES", "10")

    config = AuthConfig.from_env()

    assert isinstance(config.session_ttl_hours, int)
    assert config.session_ttl_hours == 48
    assert isinstance(config.token_refresh_threshold_minutes, int)
    assert config.token_refresh_threshold_minutes == 10


def test_boolean_field_parsing(monkeypatch, base_env_vars):
    """Test boolean fields parsed correctly."""
    # Test "true"
    monkeypatch.setenv("SECURE_COOKIES", "true")
    config = AuthConfig.from_env()
    assert config.secure_cookies is True

    # Test "1"
    monkeypatch.setenv("SECURE_COOKIES", "1")
    config = AuthConfig.from_env()
    assert config.secure_cookies is True

    # Test "false"
    monkeypatch.setenv("SECURE_COOKIES", "false")
    config = AuthConfig.from_env()
    assert config.secure_cookies is False

    # Test "0"
    monkeypatch.setenv("SECURE_COOKIES", "0")
    config = AuthConfig.from_env()
    assert config.secure_cookies is False


def test_list_field_parsing(monkeypatch, base_env_vars):
    """Test list fields parsed correctly."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://one.com, https://two.com , https://three.com")

    config = AuthConfig.from_env()

    assert isinstance(config.cors_allowed_origins, list)
    assert len(config.cors_allowed_origins) == 3
    # Whitespace should be stripped
    assert config.cors_allowed_origins == ["https://one.com", "https://two.com", "https://three.com"]


def test_https_issuer_accepted():
    """Test HTTPS oidc_issuer is accepted."""
    config = AuthConfig(
        oidc_issuer="https://idp.example.com",
        oidc_client_id="client",
        oidc_client_secret="secret",
        oidc_callback_url="https://app.example.com/callback",
        cors_allowed_origins=["https://app.example.com"],
        frontend_url="https://app.example.com",
    )
    assert config.oidc_issuer == "https://idp.example.com"


def test_http_issuer_rejected():
    """Test HTTP oidc_issuer is rejected."""
    with pytest.raises(ValueError, match="oidc_issuer must use HTTPS"):
        AuthConfig(
            oidc_issuer="http://idp.example.com",
            oidc_client_id="client",
            oidc_client_secret="secret",
            oidc_callback_url="https://app.example.com/callback",
            cors_allowed_origins=["https://app.example.com"],
            frontend_url="https://app.example.com",
        )


def test_http_callback_rejected():
    """Test HTTP oidc_callback_url is rejected."""
    with pytest.raises(ValueError, match="oidc_callback_url must use HTTPS"):
        AuthConfig(
            oidc_issuer="https://idp.example.com",
            oidc_client_id="client",
            oidc_client_secret="secret",
            oidc_callback_url="http://app.example.com/callback",
            cors_allowed_origins=["https://app.example.com"],
            frontend_url="https://app.example.com",
        )


def test_allow_http_override(monkeypatch):
    """Test FOUNDRY_AUTH_ALLOW_HTTP=1 bypasses HTTPS enforcement."""
    monkeypatch.setenv("FOUNDRY_AUTH_ALLOW_HTTP", "1")
    config = AuthConfig(
        oidc_issuer="http://localhost:8080",
        oidc_client_id="client",
        oidc_client_secret="secret",
        oidc_callback_url="http://localhost:8000/auth/callback",
        cors_allowed_origins=["http://localhost:3000"],
        frontend_url="http://localhost:3000",
    )
    assert config.oidc_issuer == "http://localhost:8080"
