# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Authentication configuration module."""

import os
from dataclasses import dataclass


@dataclass
class AuthConfig:
    """OIDC authentication configuration.

    This dataclass holds all configuration needed for OIDC authentication,
    session management, and security settings. Typically loaded from environment
    variables using the `from_env()` class method.

    Attributes:
        oidc_issuer: OIDC provider issuer URL (e.g., "https://idp.com/realms/myrealm")
        oidc_client_id: OAuth client ID from OIDC provider
        oidc_client_secret: OAuth client secret (empty string for public clients)
        oidc_callback_url: OAuth callback URL (must match provider configuration)
        cors_allowed_origins: List of allowed CORS origins for API requests
        frontend_url: Frontend application URL for post-auth redirects
        session_ttl_hours: Session lifetime in hours (default: 24)
        token_refresh_threshold_minutes: Trigger token refresh N minutes before expiry (default: 5)
        secure_cookies: Enable secure cookie flag requiring HTTPS (default: True)

    Example:
        # Load from environment variables
        config = AuthConfig.from_env()

        # Manual instantiation (testing)
        config = AuthConfig(
            oidc_issuer="https://idp.example.com",
            oidc_client_id="my-client",
            oidc_client_secret="my-secret",
            oidc_callback_url="https://app.example.com/auth/callback",
            cors_allowed_origins=["http://localhost:3000"],
            frontend_url="http://localhost:3000"
        )
    """

    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    oidc_callback_url: str
    cors_allowed_origins: list[str]
    frontend_url: str
    session_ttl_hours: int = 24
    token_refresh_threshold_minutes: int = 5
    secure_cookies: bool = True

    def __post_init__(self) -> None:
        """Validate HTTPS on OIDC URLs unless local-dev override is set."""
        if os.getenv("FOUNDRY_AUTH_ALLOW_HTTP") == "1":
            return

        for field_name in ("oidc_issuer", "oidc_callback_url"):
            value = getattr(self, field_name)
            if not value.startswith("https://"):
                raise ValueError(
                    f"{field_name} must use HTTPS (got {value!r}). "
                    "Set FOUNDRY_AUTH_ALLOW_HTTP=1 to bypass for local development."
                )

    @classmethod
    def from_env(cls, prefix: str = "") -> "AuthConfig":
        """Load configuration from environment variables with optional prefix.

        Args:
            prefix: Optional prefix for environment variable names (e.g., "SERVICE_").
                   If provided, reads SERVICE_OIDC_ISSUER, SERVICE_CORS_ALLOWED_ORIGINS, etc.
                   If empty or omitted, reads OIDC_ISSUER, CORS_ALLOWED_ORIGINS, etc.

        Returns:
            AuthConfig instance populated from environment variables.

        Raises:
            ValueError: If required environment variables are missing.
        """

        # Build environment variable names with prefix
        def env_name(base: str) -> str:
            return f"{prefix}{base}" if prefix else base

        # Read required fields
        oidc_issuer = os.getenv(env_name("OIDC_ISSUER"))
        oidc_client_id = os.getenv(env_name("OIDC_CLIENT_ID"))
        oidc_client_secret = os.getenv(env_name("OIDC_CLIENT_SECRET"), "")
        oidc_callback_url = os.getenv(env_name("OIDC_CALLBACK_URL"))
        frontend_url = os.getenv(env_name("FRONTEND_URL"))

        # Validate required fields
        missing_fields = []
        if not oidc_issuer:
            missing_fields.append(env_name("OIDC_ISSUER"))
        if not oidc_client_id:
            missing_fields.append(env_name("OIDC_CLIENT_ID"))
        if not oidc_callback_url:
            missing_fields.append(env_name("OIDC_CALLBACK_URL"))
        if not frontend_url:
            missing_fields.append(env_name("FRONTEND_URL"))

        if missing_fields:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_fields)}")

        # Type narrowing - all required fields are now guaranteed to be non-None
        assert oidc_issuer is not None
        assert oidc_client_id is not None
        assert oidc_callback_url is not None
        assert frontend_url is not None

        # Parse CORS_ALLOWED_ORIGINS as comma-separated list
        cors_origins_raw = os.getenv(env_name("CORS_ALLOWED_ORIGINS"), "http://localhost:5173")
        cors_allowed_origins = [origin.strip() for origin in cors_origins_raw.split(",")]

        # Read optional fields with defaults
        session_ttl_hours = int(os.getenv(env_name("SESSION_TTL_HOURS"), "24"))
        token_refresh_threshold_minutes = int(os.getenv(env_name("TOKEN_REFRESH_THRESHOLD_MINUTES"), "5"))
        secure_cookies = os.getenv(env_name("SECURE_COOKIES"), "true").lower() in ("true", "1", "yes")

        return cls(
            oidc_issuer=oidc_issuer,
            oidc_client_id=oidc_client_id,
            oidc_client_secret=oidc_client_secret,
            oidc_callback_url=oidc_callback_url,
            cors_allowed_origins=cors_allowed_origins,
            frontend_url=frontend_url,
            session_ttl_hours=session_ttl_hours,
            token_refresh_threshold_minutes=token_refresh_threshold_minutes,
            secure_cookies=secure_cookies,
        )
