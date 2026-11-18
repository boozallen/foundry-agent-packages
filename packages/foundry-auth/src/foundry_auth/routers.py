# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Authentication router module."""

import json
import logging
import secrets
import time
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from foundry_auth.config import AuthConfig
from foundry_auth.oidc import get_metadata
from foundry_auth.session import SessionStore
from foundry_auth.utils import generate_pkce_pair, sanitize_redirect_path

logger = logging.getLogger(__name__)


def create_auth_router(config: AuthConfig, session_store: SessionStore) -> APIRouter:
    """Create a configured authentication router.

    Creates a FastAPI router with OIDC authentication endpoints. Include this
    router in your FastAPI application to enable authentication.

    Args:
        config: Authentication configuration
        session_store: Session store instance

    Returns:
        FastAPI APIRouter with /auth/** endpoints:
            - GET /auth/login?returnTo=/path: Initiate OIDC login flow
            - GET /auth/callback: Handle OIDC provider callback
            - GET /auth/user: Get current user information (requires auth)
            - POST /auth/logout: Logout and clear session

    Example:
        from fastapi import FastAPI
        from foundry_auth import (
            AuthConfig,
            get_session_store,
            create_auth_router
        )

        app = FastAPI()
        config = AuthConfig.from_env()
        store = get_session_store()

        # Add authentication routes
        auth_router = create_auth_router(config, store)
        app.include_router(auth_router)

        # Now /auth/login, /auth/callback, /auth/user, /auth/logout are available
    """
    router = APIRouter(prefix="/auth", tags=["auth"])

    # Precompute discovery URL
    discovery_url = f"{config.oidc_issuer}/.well-known/openid-configuration"

    @router.get("/login")
    async def auth_login(returnTo: str | None = None):
        """Initiate OIDC authentication flow.

        Args:
            returnTo: Optional return path after successful authentication

        Returns:
            RedirectResponse: Redirect to OIDC authorization endpoint
        """
        meta = await get_metadata(discovery_url)
        state = secrets.token_urlsafe(16)
        verifier, challenge = generate_pkce_pair()

        # Save OAuth state with 10 minute TTL
        state_expires_at = int(time.time()) + 600
        session_store.save_oauth_state(
            state=state,
            redirect_uri=config.oidc_callback_url,
            code_verifier=verifier,
            return_to=sanitize_redirect_path(returnTo),
            expires_at=state_expires_at,
        )

        params = {
            "client_id": config.oidc_client_id,
            "response_type": "code",
            "redirect_uri": config.oidc_callback_url,
            "scope": "openid email profile offline_access",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        auth_endpoint = meta["authorization_endpoint"]
        resp = RedirectResponse(f"{auth_endpoint}?{urllib.parse.urlencode(params)}")
        # Bind state to the initiating browser to prevent login CSRF
        resp.set_cookie(
            "oauth_state", state, max_age=600, httponly=True, samesite="lax", path="/", secure=config.secure_cookies
        )
        return resp

    @router.get("/callback")
    async def auth_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
        error_description: str | None = None,
    ):
        """Handle OIDC provider callback.

        Args:
            code: Authorization code from OIDC provider (may be None on error)
            state: State parameter for CSRF protection (may be None on error)
            error: Optional error code from OIDC provider
            error_description: Optional error description from OIDC provider

        Returns:
            RedirectResponse: Redirect to frontend with session cookie

        Raises:
            HTTPException: If authentication fails
        """
        # Handle error responses from IdP
        if error:
            # clear state if present
            if state:
                session_store.delete_oauth_state(state)
            # log the IdP error; do not put it in the redirect URL (security).
            # repr(): this value is attacker-controlled, prevents log injection.
            safe_error = repr(error_description or error)
            logger.error("Auth callback error: %s", safe_error)
            return RedirectResponse(f"{config.frontend_url}/login?error=auth_error", status_code=303)

        if not code or not state:
            raise HTTPException(400, "Missing 'code' or 'state'")

        # Verify state is bound to this browser (login CSRF protection)
        cookie_state = request.cookies.get("oauth_state")
        if not cookie_state or not secrets.compare_digest(cookie_state, state):
            raise HTTPException(400, "Invalid or expired state")

        oauth_state = session_store.get_oauth_state(state)
        if not oauth_state:
            raise HTTPException(400, "Invalid or expired state")

        meta = await get_metadata(discovery_url)
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.oidc_callback_url,
            "client_id": config.oidc_client_id,
            "code_verifier": oauth_state.code_verifier,
        }
        if config.oidc_client_secret:  # confidential client
            data["client_secret"] = config.oidc_client_secret

        async with httpx.AsyncClient() as c:
            token_endpoint = meta["token_endpoint"]
            tr = await c.post(token_endpoint, data=data, timeout=10)
            tr.raise_for_status()
            token = tr.json()

            user = {}
            if "userinfo_endpoint" in meta:
                userinfo_endpoint = meta["userinfo_endpoint"]
                ur = await c.get(
                    userinfo_endpoint,
                    headers={"Authorization": f"Bearer {token['access_token']}"},
                    timeout=10,
                )
                ur.raise_for_status()
                user = ur.json()

        # Consume state after success
        session_store.delete_oauth_state(state)
        return_to = oauth_state.return_to or "/"

        # Create NEW session with session ID rotation (security: prevents session fixation)
        new_sid = secrets.token_urlsafe(32)
        now = int(time.time())
        session_expires_at = now + (config.session_ttl_hours * 3600)
        token_expires_at = now + token.get("expires_in", 3600)

        session_store.create_session(
            session_id=new_sid,
            user_id=user.get("sub", user.get("email", "unknown")),
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            token_expires_at=token_expires_at,
            session_expires_at=session_expires_at,
            id_token=token.get("id_token"),
        )

        target = urllib.parse.urljoin(config.frontend_url.rstrip("/") + "/", return_to.lstrip("/"))

        resp = RedirectResponse(url=target)
        # Session cookie with security attributes: HttpOnly, SameSite=Lax, Secure
        resp.set_cookie("sid", new_sid, httponly=True, samesite="lax", secure=config.secure_cookies)
        resp.delete_cookie("oauth_state", path="/")
        return resp

    @router.get("/user")
    async def auth_user(request: Request):
        """Get current user information.

        Args:
            request: FastAPI request object with session cookie

        Returns:
            dict: User information from session

        Raises:
            HTTPException: 401 if not authenticated
        """
        sid = request.cookies.get("sid")
        if not sid:
            raise HTTPException(401, "Not authenticated")

        session = session_store.get_session(sid)
        if not session:
            raise HTTPException(401, "Not authenticated")

        return {"user": {"sub": session.user_id}}

    @router.post("/logout")
    async def auth_logout(request: Request):
        """Logout user and clear session.

        Args:
            request: FastAPI request object with session cookie

        Returns:
            Response: JSON response with logout URL
        """
        sid = request.cookies.get("sid")
        if sid:
            session_store.delete_session(sid)

        # Get OIDC logout endpoint
        meta = await get_metadata(discovery_url)
        end_session_endpoint = meta.get("end_session_endpoint")

        # Build post_logout_redirect_uri (where OIDC provider redirects after logout)
        post_logout_redirect = urllib.parse.urljoin(config.frontend_url.rstrip("/") + "/", "login")

        # Construct the OIDC logout URL
        logout_url = None
        if end_session_endpoint:
            params = {
                "client_id": config.oidc_client_id,
                "post_logout_redirect_uri": post_logout_redirect,
            }
            logout_url = f"{end_session_endpoint}?{urllib.parse.urlencode(params)}"

        # Clear the session cookie and return logout URL
        resp = Response(status_code=200, content=json.dumps({"logout_url": logout_url}), media_type="application/json")
        resp.delete_cookie("sid", path="/")
        return resp

    return router
