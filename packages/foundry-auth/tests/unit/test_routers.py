# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for authentication router module."""

import time
import urllib.parse

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from foundry_auth.config import AuthConfig
from foundry_auth.routers import create_auth_router
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
    monkeypatch.setenv("SECURE_COOKIES", "false")  # For testing

    return AuthConfig.from_env()


@pytest.fixture
def session_store_for_router(tmp_db_path):
    """Create session store for router tests."""
    store = SQLiteSessionStore(str(tmp_db_path))
    yield store
    store.close()


@pytest.fixture
def app_with_auth(auth_config, session_store_for_router):
    """Create FastAPI app with auth router."""
    app = FastAPI()
    router = create_auth_router(auth_config, session_store_for_router)
    app.include_router(router)
    app.state.session_store = session_store_for_router
    return app


@pytest.fixture
def client(app_with_auth):
    """Create test client."""
    return TestClient(app_with_auth)


@respx.mock
def test_login_redirects_to_oauth_provider(client):
    """Test /auth/login redirects to OAuth provider with correct parameters."""
    # Mock OIDC discovery
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example.com/authorize",
                "token_endpoint": "https://issuer.example.com/token",
                "userinfo_endpoint": "https://issuer.example.com/userinfo",
            },
        )
    )

    response = client.get("/auth/login", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://issuer.example.com/authorize?")

    # Parse redirect URL
    parsed = urllib.parse.urlparse(response.headers["location"])
    params = urllib.parse.parse_qs(parsed.query)

    assert params["client_id"][0] == "test-client-id"
    assert params["response_type"][0] == "code"
    assert params["redirect_uri"][0] == "https://app.example.com/auth/callback"
    assert "state" in params
    assert "code_challenge" in params
    assert params["code_challenge_method"][0] == "S256"


@respx.mock
def test_login_stores_oauth_state(client, app_with_auth):
    """Test /auth/login stores OAuth state with expiration."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example.com/authorize",
                "token_endpoint": "https://issuer.example.com/token",
            },
        )
    )

    response = client.get("/auth/login", follow_redirects=False)

    # Extract state from redirect
    parsed = urllib.parse.urlparse(response.headers["location"])
    params = urllib.parse.parse_qs(parsed.query)
    state = params["state"][0]

    # Verify state was stored
    oauth_state = app_with_auth.state.session_store.get_oauth_state(state)
    assert oauth_state is not None
    assert oauth_state.state == state
    assert oauth_state.redirect_uri == "https://app.example.com/auth/callback"
    assert oauth_state.code_verifier is not None


@respx.mock
def test_callback_with_valid_code_creates_session(client, app_with_auth):
    """Test /auth/callback with valid auth code creates session."""
    # Mock OIDC discovery
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example.com/authorize",
                "token_endpoint": "https://issuer.example.com/token",
                "userinfo_endpoint": "https://issuer.example.com/userinfo",
            },
        )
    )

    # First, initiate login to get state
    login_response = client.get("/auth/login", follow_redirects=False)
    parsed = urllib.parse.urlparse(login_response.headers["location"])
    params = urllib.parse.parse_qs(parsed.query)
    state = params["state"][0]

    # Mock token exchange
    respx.post("https://issuer.example.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "id_token": "test-id-token",
                "expires_in": 3600,
            },
        )
    )

    # Mock userinfo
    respx.get("https://issuer.example.com/userinfo").mock(
        return_value=Response(
            200,
            json={
                "sub": "user-123",
                "email": "test@example.com",
            },
        )
    )

    # Now call callback with code
    callback_response = client.get(
        f"/auth/callback?code=test-auth-code&state={state}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 307
    assert "sid" in callback_response.cookies

    # Verify session was created
    sid = callback_response.cookies["sid"]
    session = app_with_auth.state.session_store.get_session(sid)
    assert session is not None
    assert session.user_id == "user-123"
    assert session.access_token == "test-access-token"
    assert session.id_token == "test-id-token"


@respx.mock
def test_callback_without_id_token_stores_none(client, app_with_auth):
    """An IdP token response omitting id_token must not break login."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example.com/authorize",
                "token_endpoint": "https://issuer.example.com/token",
                "userinfo_endpoint": "https://issuer.example.com/userinfo",
            },
        )
    )

    login_response = client.get("/auth/login", follow_redirects=False)
    parsed = urllib.parse.urlparse(login_response.headers["location"])
    params = urllib.parse.parse_qs(parsed.query)
    state = params["state"][0]

    respx.post("https://issuer.example.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "expires_in": 3600,
            },
        )
    )
    respx.get("https://issuer.example.com/userinfo").mock(
        return_value=Response(200, json={"sub": "user-123", "email": "test@example.com"})
    )

    callback_response = client.get(
        f"/auth/callback?code=test-auth-code&state={state}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 307
    sid = callback_response.cookies["sid"]
    session = app_with_auth.state.session_store.get_session(sid)
    assert session is not None
    assert session.id_token is None


@respx.mock
def test_auth_user_does_not_expose_id_token(client, app_with_auth):
    """/auth/user must keep returning only {"user": {"sub": ...}} - id_token stays internal."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example.com/authorize",
                "token_endpoint": "https://issuer.example.com/token",
                "userinfo_endpoint": "https://issuer.example.com/userinfo",
            },
        )
    )

    login_response = client.get("/auth/login", follow_redirects=False)
    parsed = urllib.parse.urlparse(login_response.headers["location"])
    params = urllib.parse.parse_qs(parsed.query)
    state = params["state"][0]

    respx.post("https://issuer.example.com/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "id_token": "distinctive-id-token-value",
                "expires_in": 3600,
            },
        )
    )
    respx.get("https://issuer.example.com/userinfo").mock(
        return_value=Response(200, json={"sub": "user-123", "email": "test@example.com"})
    )

    callback_response = client.get(
        f"/auth/callback?code=test-auth-code&state={state}",
        follow_redirects=False,
    )
    sid = callback_response.cookies["sid"]

    user_response = client.get("/auth/user", cookies={"sid": sid})

    assert user_response.status_code == 200
    assert user_response.json() == {"user": {"sub": "user-123"}}
    assert "distinctive-id-token-value" not in user_response.text
    assert "id_token" not in user_response.text


@respx.mock
def test_callback_sets_cookie_with_samesite_lax(client, app_with_auth):
    """Test /auth/callback sets session cookie with SameSite=Lax (AC3 partial)."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example.com/authorize",
                "token_endpoint": "https://issuer.example.com/token",
                "userinfo_endpoint": "https://issuer.example.com/userinfo",
            },
        )
    )

    login_response = client.get("/auth/login", follow_redirects=False)
    parsed = urllib.parse.urlparse(login_response.headers["location"])
    params = urllib.parse.parse_qs(parsed.query)
    state = params["state"][0]

    respx.post("https://issuer.example.com/token").mock(
        return_value=Response(200, json={"access_token": "token", "expires_in": 3600})
    )
    respx.get("https://issuer.example.com/userinfo").mock(return_value=Response(200, json={"sub": "user-123"}))

    callback_response = client.get(
        f"/auth/callback?code=code&state={state}",
        follow_redirects=False,
    )

    # Check cookie attributes
    set_cookie_header = callback_response.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie_header
    assert "samesite=lax" in set_cookie_header


@respx.mock
def test_callback_generates_new_session_id(client, app_with_auth):
    """Test /auth/callback generates new session ID on login (AC3)."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example.com/authorize",
                "token_endpoint": "https://issuer.example.com/token",
                "userinfo_endpoint": "https://issuer.example.com/userinfo",
            },
        )
    )

    login_response = client.get("/auth/login", follow_redirects=False)
    parsed = urllib.parse.urlparse(login_response.headers["location"])
    params = urllib.parse.parse_qs(parsed.query)
    state = params["state"][0]

    respx.post("https://issuer.example.com/token").mock(
        return_value=Response(200, json={"access_token": "token", "expires_in": 3600})
    )
    respx.get("https://issuer.example.com/userinfo").mock(return_value=Response(200, json={"sub": "user-123"}))

    callback_response = client.get(
        f"/auth/callback?code=code&state={state}",
        follow_redirects=False,
    )

    sid = callback_response.cookies["sid"]
    assert sid is not None
    assert len(sid) > 20  # Session ID should be substantial length


@respx.mock
def test_callback_with_invalid_state_fails(client):
    """Test /auth/callback with invalid state fails."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example.com/authorize",
                "token_endpoint": "https://issuer.example.com/token",
            },
        )
    )

    response = client.get(
        "/auth/callback?code=code&state=invalid-state",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Invalid or expired state" in response.json()["detail"]


@respx.mock
def test_callback_with_expired_state_fails(client, app_with_auth):
    """Test /auth/callback with expired state fails."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example.com/authorize",
                "token_endpoint": "https://issuer.example.com/token",
            },
        )
    )

    # Create an expired OAuth state
    now = int(time.time())
    app_with_auth.state.session_store.save_oauth_state(
        state="expired-state",
        redirect_uri="https://app.example.com/auth/callback",
        code_verifier="verifier",
        return_to=None,
        expires_at=now - 1,  # Already expired
    )

    response = client.get(
        "/auth/callback?code=code&state=expired-state",
        follow_redirects=False,
    )

    assert response.status_code == 400


@respx.mock
def test_callback_rejects_state_not_bound_to_browser(client, app_with_auth):
    """Login CSRF: callback must reject a server-valid state that wasn't issued to this browser."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "authorization_endpoint": "https://issuer.example.com/authorize",
                "token_endpoint": "https://issuer.example.com/token",
                "userinfo_endpoint": "https://issuer.example.com/userinfo",
            },
        )
    )
    respx.post("https://issuer.example.com/token").mock(
        return_value=Response(200, json={"access_token": "attacker-token", "expires_in": 3600})
    )
    respx.get("https://issuer.example.com/userinfo").mock(return_value=Response(200, json={"sub": "attacker-sub"}))

    # Attacker initiated a flow on their own browser; state is valid server-side
    now = int(time.time())
    app_with_auth.state.session_store.save_oauth_state(
        state="attacker-state",
        redirect_uri="https://app.example.com/auth/callback",
        code_verifier="attacker-verifier",
        return_to=None,
        expires_at=now + 600,
    )

    # Victim's browser hits the attacker's callback URL without an oauth_state cookie
    response = client.get(
        "/auth/callback?code=attacker-code&state=attacker-state",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "sid" not in response.cookies


@respx.mock
def test_logout_deletes_session(client, app_with_auth):
    """Test /auth/logout deletes session from store."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "end_session_endpoint": "https://issuer.example.com/logout",
            },
        )
    )

    # Create a session
    now = int(time.time())
    app_with_auth.state.session_store.create_session(
        session_id="logout-test-session",
        user_id="user-123",
        access_token="token",
        refresh_token=None,
        token_expires_at=now + 3600,
        session_expires_at=now + 86400,
    )

    response = client.post(
        "/auth/logout",
        cookies={"sid": "logout-test-session"},
    )

    assert response.status_code == 200
    assert app_with_auth.state.session_store.get_session("logout-test-session") is None


@respx.mock
def test_logout_clears_cookie(client):
    """Test /auth/logout clears sid cookie."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "end_session_endpoint": "https://issuer.example.com/logout",
            },
        )
    )

    response = client.post("/auth/logout")

    assert response.status_code == 200
    # Check that cookie is deleted
    set_cookie_header = response.headers.get("set-cookie", "")
    assert "sid=" in set_cookie_header


@respx.mock
def test_logout_without_session_succeeds(client):
    """Test /auth/logout without active session succeeds."""
    respx.get("https://issuer.example.com/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "end_session_endpoint": "https://issuer.example.com/logout",
            },
        )
    )

    response = client.post("/auth/logout")

    assert response.status_code == 200
