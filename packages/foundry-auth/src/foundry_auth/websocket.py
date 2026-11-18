# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""WebSocket connection registry and session management.

This module provides utilities for tracking and managing WebSocket connections
tied to authentication sessions. It enables immediate connection closure on
logout/revocation and periodic validation to handle session expiration.

WebSocket Close Codes:
- 1000 (Normal Closure): Used for logout and max connection timeout
- 1008 (Policy Violation): Used for session expiration

Example Usage:
    from fastapi import WebSocket
    from foundry_auth.websocket import (
        register_connection,
        unregister_connection,
        start_session_validation_task
    )

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, sid: str):
        await websocket.accept()
        try:
            register_connection(sid, websocket)
            # Handle messages...
        finally:
            unregister_connection(sid, websocket)

    @app.on_event("startup")
    async def startup():
        await start_session_validation_task(session_store)
"""

import asyncio
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from fastapi import WebSocket

from foundry_agent_core.masking import mask_session_id
from foundry_auth.session import SessionStore

logger = logging.getLogger(__name__)

# Global connection registry: session_id → Set[WebSocket]
_connection_registry: defaultdict[str, set[WebSocket]] = defaultdict(set)

# Thread lock for thread-safe registry access
_registry_lock = threading.Lock()

# Connection start timestamps: WebSocket → timestamp
_connection_timestamps: dict[WebSocket, float] = {}


@dataclass
class WebSocketConfig:
    """WebSocket connection management configuration."""

    session_check_interval_seconds: int
    max_connection_seconds: int


# Load config once at module level
_config = WebSocketConfig(
    session_check_interval_seconds=int(os.environ.get("WEBSOCKET_SESSION_CHECK_INTERVAL_SECONDS", "300")),
    max_connection_seconds=int(os.environ.get("WEBSOCKET_MAX_CONNECTION_SECONDS", "3600")),
)


def get_config() -> WebSocketConfig:
    """Get WebSocket configuration.

    Returns:
        WebSocketConfig with session check interval and max connection duration

    Configuration is loaded from environment variables at module import time:
        WEBSOCKET_SESSION_CHECK_INTERVAL_SECONDS: Periodic validation interval (default: 300)
        WEBSOCKET_MAX_CONNECTION_SECONDS: Maximum connection duration (default: 3600)
    """
    return _config


def register_connection(session_id: str, websocket: WebSocket) -> None:
    """Register a WebSocket connection for a session.

    Adds the WebSocket to the connection registry for tracking and management.
    Call this after accepting the WebSocket connection and validating the session.

    Args:
        session_id: Session ID to associate with the connection
        websocket: WebSocket connection to register

    Returns:
        None

    Example:
        from fastapi import WebSocket, WebSocketDisconnect
        from foundry_auth.websocket import register_connection, unregister_connection

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket, sid: str):
            # Validate session first
            session = session_store.get_session(sid)
            if not session:
                await websocket.close(code=1008, reason="Invalid session")
                return

            await websocket.accept()
            try:
                register_connection(sid, websocket)
                while True:
                    data = await websocket.receive_text()
                    # Handle messages...
            except WebSocketDisconnect:
                pass
            finally:
                unregister_connection(sid, websocket)
    """
    with _registry_lock:
        _connection_registry[session_id].add(websocket)
        _connection_timestamps[websocket] = time.time()
        logger.info(
            "Registered WebSocket connection for session %s (total: %d)",
            mask_session_id(session_id),
            len(_connection_registry[session_id]),
        )


def unregister_connection(session_id: str, websocket: WebSocket) -> None:
    """Unregister a WebSocket connection from a session.

    Removes the WebSocket from the connection registry. Always call this when
    a connection closes (typically in a finally block).

    Args:
        session_id: Session ID to remove the connection from
        websocket: WebSocket connection to unregister

    Returns:
        None

    Example:
        try:
            register_connection(sid, websocket)
            # Handle messages...
        finally:
            unregister_connection(sid, websocket)
    """
    with _registry_lock:
        if session_id in _connection_registry:
            _connection_registry[session_id].discard(websocket)
            # Clean up empty session entries
            if not _connection_registry[session_id]:
                del _connection_registry[session_id]
                logger.info("Removed last connection for session %s, cleaned up entry", mask_session_id(session_id))
            else:
                logger.info(
                    "Unregistered WebSocket connection for session %s (remaining: %d)",
                    mask_session_id(session_id),
                    len(_connection_registry[session_id]),
                )

        # Clean up timestamp
        _connection_timestamps.pop(websocket, None)


async def close_all_connections_for_session(session_id: str) -> None:
    """Close all WebSocket connections for a session.

    Args:
        session_id: Session ID whose connections should be closed

    Example:
        # In logout endpoint
        await close_all_connections_for_session(sid)
    """
    # Create snapshot with lock, then release before I/O
    with _registry_lock:
        connections = set(_connection_registry.get(session_id, set()))

    if not connections:
        logger.debug("No connections to close for session %s", mask_session_id(session_id))
        return

    logger.info("Closing %d WebSocket connections for session %s", len(connections), mask_session_id(session_id))

    # Close all connections (I/O without holding lock)
    for websocket in connections:
        try:
            await websocket.close(code=1000, reason="Session closed")
        except Exception as e:
            logger.warning("Error closing WebSocket for session %s: %s", mask_session_id(session_id), e)
        finally:
            # Unregister after close attempt
            unregister_connection(session_id, websocket)


async def delete_session_and_close_connections(session_id: str, session_store: SessionStore) -> None:
    """Delete a session and close all associated WebSocket connections.

    This is a helper function that ensures immediate connection closure when
    a session is deleted (e.g., on logout or admin revocation). Services using
    WebSockets should use this instead of calling session_store.delete_session()
    directly.

    Closes connections first, then deletes the session from the store.

    Args:
        session_id: Session ID to delete
        session_store: SessionStore instance to delete from

    Returns:
        None

    Example:
        from foundry_auth.websocket import delete_session_and_close_connections

        # Use in logout endpoint
        @app.post("/auth/logout")
        async def logout(request: Request):
            sid = request.cookies.get("sid")
            if sid:
                await delete_session_and_close_connections(sid, session_store)

            resp = Response(content='{"status": "logged out"}')
            resp.delete_cookie("sid")
            return resp

        # Use in admin revocation endpoint
        @app.post("/admin/revoke-session")
        async def revoke_session(session_id: str):
            await delete_session_and_close_connections(session_id, session_store)
            return {"status": "revoked", "session_id": session_id}
    """
    # Close connections first, then delete session
    await close_all_connections_for_session(session_id)
    session_store.delete_session(session_id)
    logger.info("Deleted session %s and closed all connections", mask_session_id(session_id))


def validate_connection_session(
    websocket: WebSocket, session_id: str, session_store: SessionStore
) -> tuple[bool, int, str]:
    """Validate if a WebSocket connection's session is still valid.

    Args:
        websocket: WebSocket connection to validate
        session_id: Session ID associated with the connection
        session_store: SessionStore instance for validation

    Returns:
        Tuple of (is_valid, close_code, close_reason)
        - is_valid: True if session is valid and connection within max duration
        - close_code: WebSocket close code (1000 for timeout, 1008 for session expired)
        - close_reason: Human-readable reason for closure
    """
    config = get_config()

    # Check if session is still valid
    session = session_store.get_session(session_id)
    if not session:
        logger.debug("Session %s not found or expired", mask_session_id(session_id))
        return False, 1008, "Session expired"

    # Check connection age against max duration
    connection_start = _connection_timestamps.get(websocket)
    if connection_start:
        connection_age = time.time() - connection_start
        if connection_age > config.max_connection_seconds:
            logger.info(
                "Connection for session %s exceeded max duration (%d seconds)",
                mask_session_id(session_id),
                connection_age,
            )
            return False, 1000, "Connection timeout"

    return True, 0, ""


async def _validation_loop(session_store: SessionStore) -> None:
    """Periodic validation loop for WebSocket connections.

    Validates all active connections at regular intervals and closes connections
    with invalid sessions or that have exceeded max duration.

    Args:
        session_store: SessionStore instance for session validation
    """
    config = get_config()

    while True:
        try:
            await asyncio.sleep(config.session_check_interval_seconds)

            # Optimization: skip validation if registry is empty
            with _registry_lock:
                if not _connection_registry:
                    logger.debug("Registry empty, skipping validation")
                    continue

                # Create snapshot for iteration (avoid holding lock during I/O)
                registry_snapshot = {sid: set(connections) for sid, connections in _connection_registry.items()}

            logger.debug("Running periodic validation for %d sessions", len(registry_snapshot))

            # Validate each connection (I/O without holding lock)
            for session_id, connections in registry_snapshot.items():
                for websocket in connections:
                    try:
                        is_valid, close_code, close_reason = validate_connection_session(
                            websocket, session_id, session_store
                        )

                        if not is_valid:
                            logger.info(
                                "Closing connection for session %s: %s",
                                mask_session_id(session_id),
                                close_reason,
                            )

                            # Close connection
                            try:
                                await websocket.close(code=close_code, reason=close_reason)
                            except Exception as e:
                                logger.warning(
                                    "Error closing WebSocket for session %s: %s",
                                    mask_session_id(session_id),
                                    e,
                                )
                            finally:
                                unregister_connection(session_id, websocket)

                    except Exception as e:
                        logger.error("Error validating connection for session %s: %s", mask_session_id(session_id), e)

        except Exception as e:
            logger.error("Error in validation loop: %s", e)
            # Continue running despite errors


async def start_session_validation_task(session_store: SessionStore) -> asyncio.Task:
    """Start the periodic session validation background task.

    This should be called on application startup to begin monitoring WebSocket
    connections and validating sessions. The task runs indefinitely, checking
    all active connections at regular intervals.

    Must be called from an async context with a running event loop.

    Args:
        session_store: SessionStore instance for session validation

    Returns:
        The created asyncio Task handle

    Example:
        from foundry_auth.websocket import start_session_validation_task

        @app.on_event("startup")
        async def startup():
            validation_task = await start_session_validation_task(session_store)
            # Task runs in background, no need to await it

    Configuration:
        WEBSOCKET_SESSION_CHECK_INTERVAL_SECONDS: Check interval (default: 300)
        WEBSOCKET_MAX_CONNECTION_SECONDS: Max connection duration (default: 3600)
    """
    task = asyncio.create_task(_validation_loop(session_store))
    logger.info("Started WebSocket session validation task")
    return task
