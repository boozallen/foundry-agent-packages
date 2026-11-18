# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Foundry authentication package."""

from importlib.metadata import PackageNotFoundError, version

from foundry_auth.config import AuthConfig
from foundry_auth.dependencies import create_optional_session, create_require_session
from foundry_auth.routers import create_auth_router
from foundry_auth.session import OAuthState, RedisSessionStore, SessionData, SessionStore, SQLiteSessionStore
from foundry_auth.stores import get_session_store
from foundry_auth.websocket import (
    delete_session_and_close_connections,
    register_connection,
    start_session_validation_task,
    unregister_connection,
)

try:
    __version__ = version("foundry-auth")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

__all__ = [
    "__version__",
    # Config
    "AuthConfig",
    # Session
    "SessionData",
    "SessionStore",
    "SQLiteSessionStore",
    "RedisSessionStore",
    "OAuthState",
    # Stores
    "get_session_store",
    # Dependencies
    "create_require_session",
    "create_optional_session",
    # Routers
    "create_auth_router",
    # WebSocket
    "register_connection",
    "unregister_connection",
    "start_session_validation_task",
    "delete_session_and_close_connections",
]
