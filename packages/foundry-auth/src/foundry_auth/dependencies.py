# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Authentication dependency for FastAPI routes."""

import logging
import time

from fastapi import Cookie, HTTPException

from foundry_agent_core.masking import mask_session_id
from foundry_auth.config import AuthConfig
from foundry_auth.oidc import get_metadata, refresh_oauth_tokens
from foundry_auth.session import SessionData, SessionStore

logger = logging.getLogger(__name__)


async def _refresh_session_token_if_needed(
    sid: str,
    session: SessionData,
    session_store: SessionStore,
    config: AuthConfig,
) -> SessionData:
    """Refresh OAuth tokens if near expiry. Returns updated session.

    Args:
        sid: Session ID
        session: Current session data
        session_store: Session store instance
        config: Authentication configuration

    Returns:
        SessionData: Updated session with refreshed tokens, or original if no refresh needed

    Raises:
        HTTPException: 401 if token refresh fails
    """
    now = int(time.time())
    time_until_expiry = session.token_expires_at - now
    threshold_seconds = config.token_refresh_threshold_minutes * 60

    logger.debug(
        "Token refresh check: time_until_expiry=%ds, threshold=%ds, has_refresh_token=%s",
        time_until_expiry,
        threshold_seconds,
        session.refresh_token is not None,
    )

    # Check if token refresh is needed
    if time_until_expiry < threshold_seconds and session.refresh_token:
        try:
            # Refresh tokens from OIDC provider
            discovery_url = f"{config.oidc_issuer}/.well-known/openid-configuration"
            meta = await get_metadata(discovery_url)
            new_access_token, new_refresh_token, expires_in, new_id_token = await refresh_oauth_tokens(
                session.refresh_token, config.oidc_client_id, meta, config.oidc_client_secret
            )

            # Update session with new tokens and extend session expiry
            new_token_expires_at = now + expires_in
            new_session_expires_at = now + (config.session_ttl_hours * 3600)
            session_store.refresh_token(
                session_id=sid,
                new_access_token=new_access_token,
                new_refresh_token=new_refresh_token,
                new_token_expires_at=new_token_expires_at,
                new_session_expires_at=new_session_expires_at,
                new_id_token=new_id_token,
            )

            # Return updated session data
            session.access_token = new_access_token
            session.refresh_token = new_refresh_token
            session.token_expires_at = new_token_expires_at
            session.session_expires_at = new_session_expires_at
            session.id_token = new_id_token if new_id_token is not None else session.id_token

            logger.info("Successfully refreshed tokens and extended session for %s", mask_session_id(sid))
            return session

        except Exception as e:
            # Token refresh failed, delete session and return 401
            logger.warning("Token refresh failed for session %s: %s", mask_session_id(sid), e)
            session_store.delete_session(sid)
            raise HTTPException(401, "Session expired") from e
    else:
        logger.debug("Token refresh not needed (time_until_expiry=%ds or no refresh_token)", time_until_expiry)

    # No refresh needed, return original session
    return session


def create_require_session(config: AuthConfig, session_store: SessionStore):
    """Create a require_session dependency with the given config and session store.

    Returns a FastAPI dependency function that validates session authentication
    and automatically refreshes OAuth tokens when they approach expiry.

    Args:
        config: Authentication configuration
        session_store: Session store instance

    Returns:
        Callable dependency function that:
            - Validates the 'sid' cookie
            - Retrieves and validates the session
            - Refreshes OAuth tokens if needed
            - Returns SessionData on success
            - Raises HTTPException(401) on failure

    Example:
        from fastapi import FastAPI, Depends
        from foundry_auth import (
            AuthConfig,
            get_session_store,
            create_require_session,
            SessionData
        )

        config = AuthConfig.from_env()
        store = get_session_store()
        require_session = create_require_session(config, store)

        @app.get("/protected")
        async def protected_route(session: SessionData = Depends(require_session)):
            return {"user_id": session.user_id}
    """

    async def require_session(
        sid: str | None = Cookie(None),
    ) -> SessionData:
        """FastAPI dependency that validates session authentication.

        Validates the session cookie, retrieves session data, and automatically
        refreshes OAuth tokens if they are near expiry.

        Args:
            sid: Session ID from cookie

        Returns:
            SessionData: Validated session data with user information and tokens

        Raises:
            HTTPException: 401 if authentication fails (no cookie, invalid session, or expired)
        """
        # Validate session cookie exists
        if not sid:
            logger.info("No session cookie (sid) provided")
            raise HTTPException(401, "Not authenticated")

        # Retrieve session from store
        session = session_store.get_session(sid)
        if not session:
            logger.info("Session not found or expired for sid: %s", mask_session_id(sid))
            raise HTTPException(401, "Not authenticated")

        logger.info(
            "Session found for sid: %s, token_expires_at: %s, session_expires_at: %s, has_refresh: %s",
            mask_session_id(sid),
            session.token_expires_at,
            session.session_expires_at,
            session.refresh_token is not None,
        )

        # Refresh tokens if needed
        session = await _refresh_session_token_if_needed(
            sid=sid,
            session=session,
            session_store=session_store,
            config=config,
        )

        return session

    return require_session


def create_optional_session(config: AuthConfig, session_store: SessionStore):
    """Create an optional_session dependency with the given config and session store.

    Returns a FastAPI dependency function that optionally validates authentication
    without raising exceptions. Useful for endpoints that work for both
    authenticated and anonymous users.

    Args:
        config: Authentication configuration
        session_store: Session store instance

    Returns:
        Callable dependency function that:
            - Returns SessionData if authenticated
            - Returns None if not authenticated (no cookie or invalid session)
            - Never raises HTTPException

    Example:
        from foundry_auth import create_optional_session

        optional_session = create_optional_session(config, store)

        @app.get("/api/data")
        async def get_data(session: SessionData | None = Depends(optional_session)):
            if session:
                # Authenticated user
                return {"user_id": session.user_id, "premium": True}
            else:
                # Anonymous user
                return {"user_id": None, "premium": False}
    """

    async def optional_session(
        sid: str | None = Cookie(None),
    ) -> SessionData | None:
        """FastAPI dependency that optionally validates session authentication.

        Returns session data if authenticated, None otherwise. Does not raise HTTPException.

        Args:
            sid: Session ID from cookie

        Returns:
            SessionData | None: Validated session data if authenticated, None otherwise
        """
        if not sid:
            return None

        session = session_store.get_session(sid)
        if not session:
            return None

        # Refresh tokens if needed
        try:
            session = await _refresh_session_token_if_needed(
                sid=sid,
                session=session,
                session_store=session_store,
                config=config,
            )
        except HTTPException:
            # Token refresh failed, return None instead of raising
            return None

        return session

    return optional_session
