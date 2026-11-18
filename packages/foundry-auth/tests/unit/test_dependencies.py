# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for authentication dependencies module."""

import logging
import time

import pytest
import respx
from fastapi import HTTPException
from httpx import Response

from foundry_agent_core.masking import mask_session_id
from foundry_auth.config import AuthConfig
from foundry_auth.dependencies import create_optional_session, create_require_session
from foundry_auth.session import SQLiteSessionStore


@pytest.fixture
def auth_config(monkeypatch):
    """Create test authentication configuration."""
    monkeypatch.setenv("OIDC_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("OIDC_CALLBACK_URL", "https://app.example.com/auth/callback")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    return AuthConfig.from_env()


@pytest.fixture
def session_store_for_deps(tmp_db_path):
    """Create session store for dependency tests."""
    store = SQLiteSessionStore(str(tmp_db_path))
    yield store
    store.close()


@pytest.mark.asyncio
async def test_require_session_with_valid_session(auth_config, session_store_for_deps):
    """Test create_require_session with valid session returns SessionData."""
    require_session_dep = create_require_session(auth_config, session_store_for_deps)

    now = int(time.time())
    session_store_for_deps.create_session(
        session_id="valid-session-123",
        user_id="user-456",
        access_token="token",
        refresh_token=None,
        token_expires_at=now + 3600,
        session_expires_at=now + 86400,
    )

    result = await require_session_dep(sid="valid-session-123")
    assert result is not None
    assert result.user_id == "user-456"


@pytest.mark.asyncio
async def test_require_session_with_missing_session_raises_401(auth_config, session_store_for_deps):
    """Test create_require_session with missing session raises 401."""
    require_session_dep = create_require_session(auth_config, session_store_for_deps)

    with pytest.raises(HTTPException) as exc_info:
        await require_session_dep(sid=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_session_with_invalid_session_raises_401(auth_config, session_store_for_deps):
    """Test create_require_session with invalid session raises 401."""
    require_session_dep = create_require_session(auth_config, session_store_for_deps)

    with pytest.raises(HTTPException) as exc_info:
        await require_session_dep(sid="nonexistent-session")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_optional_session_with_valid_session(auth_config, session_store_for_deps):
    """Test create_optional_session with valid session returns SessionData."""
    optional_session_dep = create_optional_session(auth_config, session_store_for_deps)

    now = int(time.time())
    session_store_for_deps.create_session(
        session_id="optional-valid",
        user_id="user-789",
        access_token="token",
        refresh_token=None,
        token_expires_at=now + 3600,
        session_expires_at=now + 86400,
    )

    result = await optional_session_dep(sid="optional-valid")
    assert result is not None
    assert result.user_id == "user-789"


@pytest.mark.asyncio
async def test_optional_session_with_missing_session_returns_none(auth_config, session_store_for_deps):
    """Test create_optional_session with missing session returns None."""
    optional_session_dep = create_optional_session(auth_config, session_store_for_deps)

    result = await optional_session_dep(sid=None)
    assert result is None


@pytest.mark.asyncio
async def test_require_session_does_not_log_raw_sid(auth_config, session_store_for_deps, caplog):
    """Regression: bearer session ID must not appear verbatim in INFO logs (CWE-532)."""
    require_session_dep = create_require_session(auth_config, session_store_for_deps)

    sid = "S1d-bearer-credential-43chars-1234567890ab"
    now = int(time.time())
    session_store_for_deps.create_session(
        session_id=sid,
        user_id="user-1",
        access_token="token",
        refresh_token=None,
        token_expires_at=now + 3600,
        session_expires_at=now + 86400,
    )

    with caplog.at_level(logging.INFO, logger="foundry_auth.dependencies"):
        await require_session_dep(sid=sid)

    assert any("Session found for sid" in r.getMessage() for r in caplog.records)
    for record in caplog.records:
        assert sid not in record.getMessage()
    expected_masked = mask_session_id(sid)
    assert any(expected_masked in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
@respx.mock
async def test_refresh_preserves_id_token_when_idp_omits_it(auth_config, session_store_for_deps):
    """A refresh whose IdP response has no id_token must not wipe a previously stored one."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(200, json={"token_endpoint": "https://issuer.example.com/token"})
    )
    respx.post("https://issuer.example.com/token").mock(
        return_value=Response(
            200,
            json={"access_token": "refreshed-access", "refresh_token": "refreshed-refresh", "expires_in": 3600},
        )
    )

    require_session_dep = create_require_session(auth_config, session_store_for_deps)

    now = int(time.time())
    session_store_for_deps.create_session(
        session_id="near-expiry-session",
        user_id="user-1",
        access_token="old-access",
        refresh_token="old-refresh",
        token_expires_at=now + 60,  # inside the 5-minute default refresh threshold
        session_expires_at=now + 86400,
        id_token="original-id-token",
    )

    result = await require_session_dep(sid="near-expiry-session")

    assert result.access_token == "refreshed-access"
    assert result.id_token == "original-id-token"
    stored = session_store_for_deps.get_session("near-expiry-session")
    assert stored.id_token == "original-id-token"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_rotates_id_token_when_idp_provides_one(auth_config, session_store_for_deps):
    """A refresh whose IdP response includes a new id_token must replace the stored one."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(200, json={"token_endpoint": "https://issuer.example.com/token"})
    )
    respx.post("https://issuer.example.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "refreshed-access",
                "refresh_token": "refreshed-refresh",
                "id_token": "rotated-id-token",
                "expires_in": 3600,
            },
        )
    )

    require_session_dep = create_require_session(auth_config, session_store_for_deps)

    now = int(time.time())
    session_store_for_deps.create_session(
        session_id="near-expiry-session-2",
        user_id="user-1",
        access_token="old-access",
        refresh_token="old-refresh",
        token_expires_at=now + 60,
        session_expires_at=now + 86400,
        id_token="original-id-token",
    )

    result = await require_session_dep(sid="near-expiry-session-2")

    assert result.id_token == "rotated-id-token"
    stored = session_store_for_deps.get_session("near-expiry-session-2")
    assert stored.id_token == "rotated-id-token"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_with_empty_string_id_token_matches_stored_value(auth_config, session_store_for_deps):
    """An IdP response with id_token="" is a rotation (not-None), not an omission.

    The in-memory SessionData returned to the caller and the persisted store must agree, per
    SessionStore.refresh_token's own `is not None` semantics. A truthiness check here would
    keep the old in-memory value while the store correctly persists "", so this asserts they
    match rather than merely asserting a specific value.
    """
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(200, json={"token_endpoint": "https://issuer.example.com/token"})
    )
    respx.post("https://issuer.example.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "refreshed-access",
                "refresh_token": "refreshed-refresh",
                "id_token": "",
                "expires_in": 3600,
            },
        )
    )

    require_session_dep = create_require_session(auth_config, session_store_for_deps)

    now = int(time.time())
    session_store_for_deps.create_session(
        session_id="near-expiry-session-3",
        user_id="user-1",
        access_token="old-access",
        refresh_token="old-refresh",
        token_expires_at=now + 60,
        session_expires_at=now + 86400,
        id_token="original-id-token",
    )

    result = await require_session_dep(sid="near-expiry-session-3")

    stored = session_store_for_deps.get_session("near-expiry-session-3")
    assert result.id_token == stored.id_token


@pytest.mark.asyncio
@respx.mock
async def test_refresh_never_logs_id_token_value(auth_config, session_store_for_deps, caplog):
    """id_token must never reach a log line, including during a token refresh."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(200, json={"token_endpoint": "https://issuer.example.com/token"})
    )
    respx.post("https://issuer.example.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "refreshed-access",
                "refresh_token": "refreshed-refresh",
                "id_token": "distinctive-jwt-value-should-never-be-logged",
                "expires_in": 3600,
            },
        )
    )

    require_session_dep = create_require_session(auth_config, session_store_for_deps)

    now = int(time.time())
    session_store_for_deps.create_session(
        session_id="log-hygiene-session",
        user_id="user-1",
        access_token="old-access",
        refresh_token="old-refresh",
        token_expires_at=now + 60,
        session_expires_at=now + 86400,
        id_token="distinctive-jwt-value-should-never-be-logged",
    )

    with caplog.at_level(logging.DEBUG):
        await require_session_dep(sid="log-hygiene-session")

    assert "distinctive-jwt-value-should-never-be-logged" not in caplog.text
