# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Session store factory functions."""

import os

from foundry_auth.session import RedisSessionStore, SessionStore, SQLiteSessionStore


def get_session_store(prefix: str = "") -> SessionStore:
    """Factory function to get configured session store implementation.

    Creates a session store based on environment configuration. Supports
    prefix-based configuration for multi-service deployments.

    Args:
        prefix: Optional prefix for environment variable names (e.g., "SERVICE_").
               If provided, reads SERVICE_SESSION_STORE_TYPE, SERVICE_SESSION_STORE_PATH, etc.
               If empty or omitted, reads SESSION_STORE_TYPE, SESSION_STORE_PATH, etc.

    Returns:
        SessionStore: Configured session store based on SESSION_STORE_TYPE env var.
                     Returns SQLiteSessionStore or RedisSessionStore instance.

    Raises:
        ValueError: If SESSION_STORE_TYPE is not a supported value ("sqlite" or "redis").

    Environment Variables:
        SESSION_STORE_TYPE: Store type, "sqlite" (default) or "redis"
        SESSION_STORE_PATH: SQLite database path (default: "./data/sessions.db")
        FOUNDRY_AUTH_TOKEN_ENCRYPTION_KEY: 64-char hex key for AES-256-GCM encryption (required)
        REDIS_URL: Redis connection URL (default: "redis://localhost:6379")

    Example:
        from foundry_auth import get_session_store

        # Basic usage (SQLite with defaults)
        store = get_session_store()

        # With prefix for multi-service
        store_a = get_session_store(prefix="SERVICE_A_")
        store_b = get_session_store(prefix="SERVICE_B_")
    """

    def env_name(base: str) -> str:
        return f"{prefix}{base}" if prefix else base

    store_type = os.environ.get(env_name("SESSION_STORE_TYPE"), "sqlite")

    if store_type == "sqlite":
        db_path = os.environ.get(env_name("SESSION_STORE_PATH"), "./data/sessions.db")
        return SQLiteSessionStore(db_path=db_path)
    elif store_type == "redis":
        redis_url = os.environ.get(env_name("REDIS_URL"), "redis://localhost:6379")
        return RedisSessionStore(redis_url=redis_url)
    else:
        raise ValueError(f"Unsupported SESSION_STORE_TYPE: {store_type}. Valid values are: sqlite, redis")
