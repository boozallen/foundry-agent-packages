# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Session storage Protocol and implementations for authentication.

This module defines storage-agnostic session management with SQLite and Redis implementations.
"""

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag

from foundry_agent_core.encryption import decrypt, encrypt, is_encrypted, load_encryption_key
from foundry_agent_core.masking import mask_session_id

logger = logging.getLogger(__name__)


@dataclass
class SessionData:
    """Represents an active user session with OAuth tokens.

    This dataclass contains all information about an authenticated user's session,
    including OAuth tokens and expiration timestamps. Returned by session store
    and authentication dependencies.

    Attributes:
        session_id: Unique session identifier (random token)
        user_id: User identifier from OIDC provider (typically 'sub' claim or email)
        access_token: OAuth access token for API calls to OIDC provider
        refresh_token: OAuth refresh token for obtaining new access tokens (may be None)
        token_expires_at: Unix timestamp when access token expires
        session_expires_at: Unix timestamp when session expires
        created_at: Unix timestamp when session was created
        id_token: Raw OIDC ID token (JWT) from the IdP token response, for use as the
            subject token in RFC 8693 token exchange (e.g. Okta Cross-App Access / ID-JAG).
            None when the IdP returned no id_token, or for sessions created before this
            field existed. Security: never log this value - a JWT payload is
            base64-encoded, not encrypted, and typically carries email/name/groups.

    Example:
        @app.get("/profile")
        async def get_profile(session: SessionData = Depends(require_session)):
            return {
                "user_id": session.user_id,
                "session_valid_until": session.session_expires_at
            }
    """

    session_id: str
    user_id: str
    access_token: str
    refresh_token: str | None
    token_expires_at: int
    session_expires_at: int
    created_at: int
    id_token: str | None = None


@dataclass
class OAuthState:
    """Represents a temporary OAuth state parameter during authentication flow.

    This dataclass stores OAuth state information during the OIDC authorization
    code flow with PKCE. State parameters are short-lived (typically 10 minutes)
    and deleted after successful authentication.

    Attributes:
        state: OAuth state parameter for CSRF protection (random token)
        redirect_uri: OAuth callback URL that will receive the authorization code
        code_verifier: PKCE code verifier for secure authorization code exchange
        return_to: Optional application path to redirect to after authentication
        created_at: Unix timestamp when state was created
        expires_at: Unix timestamp when state expires (typically created_at + 600s)

    Example:
        # Saved during /auth/login
        state = OAuthState(
            state=secrets.token_urlsafe(16),
            redirect_uri="http://localhost:8000/auth/callback",
            code_verifier=generate_pkce_pair()[0],
            return_to="/dashboard",
            created_at=int(time.time()),
            expires_at=int(time.time()) + 600
        )
    """

    state: str
    redirect_uri: str
    code_verifier: str
    return_to: str | None
    created_at: int
    expires_at: int


class SessionStore(Protocol):
    """Protocol for session storage backends.

    This protocol defines the interface for session storage implementations.
    Storage backends can be swapped without changing application code.

    Implementations:
        - SQLiteSessionStore: Thread-safe SQLite-backed storage (production-ready)
        - RedisSessionStore: Redis-backed storage (stub, future work)

    Methods:
        create_session: Store a new user session
        get_session: Retrieve session by ID (returns None if expired/not found)
        delete_session: Remove a session
        refresh_token: Update session with new OAuth tokens
        save_oauth_state: Store OAuth state for PKCE flow
        get_oauth_state: Retrieve OAuth state (returns None if expired/not found)
        delete_oauth_state: Remove OAuth state
        cleanup_expired: Remove expired sessions and states

    Example:
        from foundry_auth import SessionStore, SQLiteSessionStore

        store: SessionStore = SQLiteSessionStore(db_path="./sessions.db")
        session = store.get_session("abc123")
        if session:
            print(f"User: {session.user_id}")
    """

    def create_session(
        self,
        session_id: str,
        user_id: str,
        access_token: str,
        refresh_token: str | None,
        token_expires_at: int,
        session_expires_at: int,
        id_token: str | None = None,
    ) -> None:
        """Create a new session.

        Args:
            id_token: Optional raw OIDC ID token (JWT), stored encrypted alongside
                the other tokens.
        """
        ...

    def get_session(self, session_id: str) -> SessionData | None:
        """Get session by ID, returns None if expired or not found."""
        ...

    def delete_session(self, session_id: str) -> None:
        """Delete a session by ID."""
        ...

    def refresh_token(
        self,
        session_id: str,
        new_access_token: str,
        new_refresh_token: str | None,
        new_token_expires_at: int,
        new_session_expires_at: int | None = None,
        new_id_token: str | None = None,
    ) -> None:
        """Update session tokens and optionally extend session expiry.

        Args:
            new_id_token: New ID token if the IdP rotated one on refresh. Unlike
                new_refresh_token, None here means "leave the stored id_token
                unchanged" rather than "clear it" - a routine token refresh must
                never silently wipe a previously-captured ID token.
        """
        ...

    def save_oauth_state(
        self, state: str, redirect_uri: str, code_verifier: str, return_to: str | None, expires_at: int
    ) -> None:
        """Save OAuth state parameter with PKCE code verifier and return path."""
        ...

    def get_oauth_state(self, state: str) -> OAuthState | None:
        """Get OAuth state, returns None if expired or not found."""
        ...

    def delete_oauth_state(self, state: str) -> None:
        """Delete OAuth state by state parameter."""
        ...

    def cleanup_expired(self) -> int:
        """Remove expired sessions and OAuth states, returns count removed."""
        ...


class SQLiteSessionStore:
    """SQLite-backed session store implementation.

    Thread-safe session storage using SQLite with automatic table creation
    and TTL-based expiration. Suitable for production use in single-server
    deployments or low-to-moderate traffic scenarios.

    Features:
        - Automatic database and table creation
        - Thread-safe operations with internal locking
        - Passive TTL checking (no background cleanup required)
        - OAuth state management for PKCE flow
        - Parent directory creation

    Attributes:
        db_path: Path to SQLite database file
        conn: SQLite connection (persistent)
        _lock: Threading lock for concurrent access

    Example:
        from foundry_auth import SQLiteSessionStore

        store = SQLiteSessionStore(db_path="./data/sessions.db")

        # Create a session
        store.create_session(
            session_id="abc123",
            user_id="user@example.com",
            access_token="token",
            refresh_token="refresh",
            token_expires_at=int(time.time()) + 3600,
            session_expires_at=int(time.time()) + 86400
        )

        # Retrieve session
        session = store.get_session("abc123")
    """

    def __init__(self, db_path: str):
        """Initialize SQLite session store.

        Creates the database file and tables if they don't exist. Parent
        directories are created automatically. Loads the AES-256-GCM
        encryption key from the FOUNDRY_AUTH_TOKEN_ENCRYPTION_KEY env var.

        Args:
            db_path: Path to SQLite database file. Parent directories will be created if needed.

        Raises:
            AgentCreationError: If FOUNDRY_AUTH_TOKEN_ENCRYPTION_KEY is not set or invalid.
        """
        self.db_path = db_path
        self._lock = threading.Lock()
        self._encryption_key = load_encryption_key(env_var="FOUNDRY_AUTH_TOKEN_ENCRYPTION_KEY")

        # Create parent directories if they don't exist
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        # Initialize connection and create tables
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_tables()

    def _create_tables(self) -> None:
        """Create sessions and oauth_states tables if they don't exist."""
        with self._lock:
            cursor = self.conn.cursor()

            # Create sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    encrypted_tokens TEXT NOT NULL,
                    token_expires_at INTEGER NOT NULL,
                    session_expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)

            # Create oauth_states table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    redirect_uri TEXT NOT NULL,
                    code_verifier TEXT NOT NULL,
                    return_to TEXT,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
            """)

            self.conn.commit()

    def _encrypt_tokens(self, access_token: str, refresh_token: str | None, id_token: str | None = None) -> str:
        """Encrypt tokens as a single dict and return JSON-serialized payload."""
        token_data = {"access_token": access_token, "refresh_token": refresh_token, "id_token": id_token}
        encrypted_payload = encrypt(token_data, self._encryption_key)
        return json.dumps(encrypted_payload)

    def _decrypt_tokens(self, stored_value: str) -> tuple[str, str | None, str | None] | None:
        """Decrypt stored token payload. Returns (access_token, refresh_token, id_token) or None for legacy data."""
        try:
            payload = json.loads(stored_value)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Session contains non-JSON token data (legacy format), treating as expired")
            return None

        if not is_encrypted(payload):
            logger.warning("Session contains unencrypted/legacy token data, treating as expired")
            return None

        token_data = decrypt(payload, self._encryption_key)
        return token_data["access_token"], token_data.get("refresh_token"), token_data.get("id_token")

    def create_session(
        self,
        session_id: str,
        user_id: str,
        access_token: str,
        refresh_token: str | None,
        token_expires_at: int,
        session_expires_at: int,
        id_token: str | None = None,
    ) -> None:
        """Create a new session."""
        with self._lock:
            cursor = self.conn.cursor()
            created_at = int(time.time())
            encrypted_tokens = self._encrypt_tokens(access_token, refresh_token, id_token)

            cursor.execute(
                """
                INSERT INTO sessions (
                    session_id, user_id, encrypted_tokens,
                    token_expires_at, session_expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """,
                (session_id, user_id, encrypted_tokens, token_expires_at, session_expires_at, created_at),
            )

            self.conn.commit()

    def get_session(self, session_id: str) -> SessionData | None:
        """Get session by ID, returns None if expired or not found."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT session_id, user_id, encrypted_tokens,
                       token_expires_at, session_expires_at, created_at
                FROM sessions
                WHERE session_id = ?
            """,
                (session_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            # Passive TTL check
            current_time = int(time.time())
            session_expires_at = row[4]
            if session_expires_at <= current_time:
                return None

            try:
                tokens = self._decrypt_tokens(row[2])
                if tokens is None:
                    return None
                access_token, refresh_token, id_token = tokens
                return SessionData(
                    session_id=row[0],
                    user_id=row[1],
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_expires_at=row[3],
                    session_expires_at=row[4],
                    created_at=row[5],
                    id_token=id_token,
                )
            except InvalidTag:
                logger.warning("Session %s has tampered token data", mask_session_id(session_id))
                return None

    def delete_session(self, session_id: str) -> None:
        """Delete a session by ID."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            self.conn.commit()

    def refresh_token(
        self,
        session_id: str,
        new_access_token: str,
        new_refresh_token: str | None,
        new_token_expires_at: int,
        new_session_expires_at: int | None = None,
        new_id_token: str | None = None,
    ) -> None:
        """Update session tokens and optionally extend session expiry.

        new_id_token=None means "leave the stored id_token unchanged", not "clear
        it" - a routine token refresh must never silently wipe a previously
        captured ID token just because this particular refresh response omitted one.
        """
        with self._lock:
            cursor = self.conn.cursor()

            existing_id_token: str | None = None
            if new_id_token is None:
                # BEGIN IMMEDIATE acquires SQLite's RESERVED lock before the read, held until
                # commit/rollback below. self._lock only serializes threads within this process;
                # another process sharing this same SQLite file could otherwise interleave a
                # write between the SELECT and the UPDATE, clobbering a concurrently-rotated
                # id_token with this call's stale snapshot. The lock makes the read-modify-write
                # atomic across processes too, not just threads.
                cursor.execute("BEGIN IMMEDIATE")
                try:
                    row = cursor.execute(
                        "SELECT encrypted_tokens FROM sessions WHERE session_id = ?", (session_id,)
                    ).fetchone()
                    if row:
                        try:
                            existing_tokens = self._decrypt_tokens(row[0])
                            if existing_tokens is not None:
                                existing_id_token = existing_tokens[2]
                        except InvalidTag:
                            existing_id_token = None  # tampered/undecryptable: refresh overwrites the blob anyway
                except Exception:
                    self.conn.rollback()
                    raise

            encrypted_tokens = self._encrypt_tokens(
                new_access_token, new_refresh_token, new_id_token if new_id_token is not None else existing_id_token
            )

            if new_session_expires_at is not None:
                cursor.execute(
                    """
                    UPDATE sessions
                    SET encrypted_tokens = ?, token_expires_at = ?, session_expires_at = ?
                    WHERE session_id = ?
                """,
                    (encrypted_tokens, new_token_expires_at, new_session_expires_at, session_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE sessions
                    SET encrypted_tokens = ?, token_expires_at = ?
                    WHERE session_id = ?
                """,
                    (encrypted_tokens, new_token_expires_at, session_id),
                )

            self.conn.commit()

    def save_oauth_state(
        self, state: str, redirect_uri: str, code_verifier: str, return_to: str | None, expires_at: int
    ) -> None:
        """Save OAuth state parameter with PKCE code verifier and return path."""
        with self._lock:
            cursor = self.conn.cursor()
            created_at = int(time.time())

            cursor.execute(
                """
                INSERT INTO oauth_states (state, redirect_uri, code_verifier, return_to, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (state, redirect_uri, code_verifier, return_to, created_at, expires_at),
            )

            self.conn.commit()

    def get_oauth_state(self, state: str) -> OAuthState | None:
        """Get OAuth state, returns None if expired or not found."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT state, redirect_uri, code_verifier, return_to, created_at, expires_at
                FROM oauth_states
                WHERE state = ?
            """,
                (state,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            # Expiry check
            current_time = int(time.time())
            expires_at = row[5]
            if expires_at <= current_time:
                return None

            return OAuthState(
                state=row[0],
                redirect_uri=row[1],
                code_verifier=row[2],
                return_to=row[3],
                created_at=row[4],
                expires_at=row[5],
            )

    def delete_oauth_state(self, state: str) -> None:
        """Delete OAuth state by state parameter."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            self.conn.commit()

    def cleanup_expired(self) -> int:
        """Remove expired sessions and OAuth states, returns count removed."""
        with self._lock:
            cursor = self.conn.cursor()
            current_time = int(time.time())

            # Delete expired sessions
            cursor.execute("DELETE FROM sessions WHERE session_expires_at <= ?", (current_time,))
            sessions_removed = cursor.rowcount

            # Delete expired oauth_states
            cursor.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (current_time,))
            states_removed = cursor.rowcount

            self.conn.commit()

            return sessions_removed + states_removed

    def close(self) -> None:
        """Close the underlying SQLite connection.

        Takes no arguments and accepts no external/user input, so there is
        nothing here for SRG-APP-000251 (input validation) to apply to.
        """
        with self._lock:
            self.conn.close()


class RedisSessionStore:
    """Redis-backed session store implementation (stub).

    This is a placeholder for future Redis support. Currently raises
    NotImplementedError on initialization. Use SQLiteSessionStore for
    production deployments.

    Future implementation will provide:
        - Distributed session storage across multiple servers
        - Automatic TTL-based expiration via Redis
        - Higher throughput for high-traffic scenarios

    Note:
        This stub exists to define the interface. Install the 'redis' extra
        when Redis support is implemented: pip install foundry-auth[redis]
    """

    def __init__(self, redis_url: str):
        """Initialize Redis session store.

        Args:
            redis_url: Redis connection URL (e.g., "redis://localhost:6379").

        Raises:
            NotImplementedError: Redis implementation is not yet available.

        Example:
            # Will raise NotImplementedError
            store = RedisSessionStore(redis_url="redis://localhost:6379")
        """
        raise NotImplementedError(
            "Redis session store is not yet implemented. Use SQLiteSessionStore or implement RedisSessionStore."
        )

    def create_session(
        self,
        session_id: str,
        user_id: str,
        access_token: str,
        refresh_token: str | None,
        token_expires_at: int,
        session_expires_at: int,
        id_token: str | None = None,
    ) -> None:
        raise NotImplementedError("Redis implementation is future work")

    def get_session(self, session_id: str) -> SessionData | None:
        raise NotImplementedError("Redis implementation is future work")

    def delete_session(self, session_id: str) -> None:
        raise NotImplementedError("Redis implementation is future work")

    def refresh_token(
        self,
        session_id: str,
        new_access_token: str,
        new_refresh_token: str | None,
        new_token_expires_at: int,
        new_session_expires_at: int | None = None,
        new_id_token: str | None = None,
    ) -> None:
        raise NotImplementedError("Redis implementation is future work")

    def save_oauth_state(
        self, state: str, redirect_uri: str, code_verifier: str, return_to: str | None, expires_at: int
    ) -> None:
        raise NotImplementedError("Redis implementation is future work")

    def get_oauth_state(self, state: str) -> OAuthState | None:
        raise NotImplementedError("Redis implementation is future work")

    def delete_oauth_state(self, state: str) -> None:
        raise NotImplementedError("Redis implementation is future work")

    def cleanup_expired(self) -> int:
        raise NotImplementedError("Redis implementation is future work")
