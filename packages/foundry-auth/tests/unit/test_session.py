# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for session storage module."""

import json
import logging
import sqlite3
import threading
import time

import pytest

from foundry_agent_core.encryption import encrypt, load_encryption_key
from foundry_auth.session import RedisSessionStore, SessionData, SQLiteSessionStore


@pytest.fixture
def session_store(tmp_db_path):
    """Create a SQLite session store for testing."""
    store = SQLiteSessionStore(str(tmp_db_path))
    yield store
    store.close()


@pytest.fixture
def sample_session_data():
    """Sample session data for testing."""
    now = int(time.time())
    return {
        "session_id": "test-session-123",
        "user_id": "user-456",
        "access_token": "access-token-abc",
        "refresh_token": "refresh-token-xyz",
        "token_expires_at": now + 3600,
        "session_expires_at": now + 86400,
        "id_token": "id-token-jwt-abc",
    }


def test_session_creation_with_unique_id(session_store, sample_session_data):
    """Test session creation with unique ID generation."""
    session_store.create_session(**sample_session_data)

    retrieved = session_store.get_session(sample_session_data["session_id"])
    assert retrieved is not None
    assert retrieved.session_id == sample_session_data["session_id"]
    assert retrieved.user_id == sample_session_data["user_id"]


def test_multiple_sessions_have_unique_ids(session_store):
    """Test that multiple sessions have unique IDs."""
    now = int(time.time())

    session_store.create_session(
        session_id="session-1",
        user_id="user-1",
        access_token="token-1",
        refresh_token=None,
        token_expires_at=now + 3600,
        session_expires_at=now + 86400,
    )

    session_store.create_session(
        session_id="session-2",
        user_id="user-2",
        access_token="token-2",
        refresh_token=None,
        token_expires_at=now + 3600,
        session_expires_at=now + 86400,
    )

    session1 = session_store.get_session("session-1")
    session2 = session_store.get_session("session-2")

    assert session1 is not None
    assert session2 is not None
    assert session1.session_id != session2.session_id


def test_get_valid_session(session_store, sample_session_data):
    """Test retrieval of valid, non-expired session."""
    session_store.create_session(**sample_session_data)

    retrieved = session_store.get_session(sample_session_data["session_id"])

    assert retrieved is not None
    assert retrieved.user_id == sample_session_data["user_id"]
    assert retrieved.access_token == sample_session_data["access_token"]
    assert retrieved.id_token == sample_session_data["id_token"]


def test_get_expired_session_returns_none(session_store):
    """Test that expired session returns None."""
    now = int(time.time())

    session_store.create_session(
        session_id="expired-session",
        user_id="user-123",
        access_token="token",
        refresh_token=None,
        token_expires_at=now - 3600,
        session_expires_at=now - 1,  # Expired 1 second ago
    )

    retrieved = session_store.get_session("expired-session")
    assert retrieved is None


def test_get_nonexistent_session_returns_none(session_store):
    """Test that non-existent session returns None."""
    retrieved = session_store.get_session("nonexistent-session-id")
    assert retrieved is None


def test_delete_existing_session(session_store, sample_session_data):
    """Test deletion of existing session."""
    session_store.create_session(**sample_session_data)

    assert session_store.get_session(sample_session_data["session_id"]) is not None

    session_store.delete_session(sample_session_data["session_id"])

    assert session_store.get_session(sample_session_data["session_id"]) is None


def test_delete_nonexistent_session_succeeds(session_store):
    """Test that deleting non-existent session doesn't error."""
    session_store.delete_session("nonexistent-session")


def test_session_expiration_after_expiration_time(session_store):
    """Test session expires after expiration time."""
    now = int(time.time())

    # Create session that expires in 1 second
    session_store.create_session(
        session_id="short-lived",
        user_id="user-123",
        access_token="token",
        refresh_token=None,
        token_expires_at=now + 3600,
        session_expires_at=now + 2,
    )

    # Should be valid immediately
    assert session_store.get_session("short-lived") is not None

    # Wait for expiration
    time.sleep(2.1)

    # Should be expired now
    assert session_store.get_session("short-lived") is None


def test_session_valid_before_expiration(session_store, sample_session_data):
    """Test session is valid before expiration time."""
    session_store.create_session(**sample_session_data)

    # Should be valid (expires in 24 hours)
    retrieved = session_store.get_session(sample_session_data["session_id"])
    assert retrieved is not None


def test_sqlite_database_file_creation(tmp_path):
    """Test SQLite store creates database file."""
    db_path = tmp_path / "subdir" / "sessions.db"

    store = SQLiteSessionStore(str(db_path))
    try:
        assert store.db_path == str(db_path)
        assert db_path.exists()
        assert db_path.is_file()
    finally:
        store.close()


def test_sqlite_thread_safe_concurrent_access(session_store):
    """Test SQLite store handles concurrent access safely."""
    now = int(time.time())
    results = []

    def create_session(session_id: str):
        try:
            session_store.create_session(
                session_id=session_id,
                user_id=f"user-{session_id}",
                access_token=f"token-{session_id}",
                refresh_token=None,
                token_expires_at=now + 3600,
                session_expires_at=now + 86400,
            )
            results.append(True)
        except Exception:
            results.append(False)

    # Create multiple threads
    threads = [threading.Thread(target=create_session, args=(f"session-{i}",)) for i in range(10)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    # All operations should succeed
    assert all(results)

    # Verify all sessions were created
    for i in range(10):
        assert session_store.get_session(f"session-{i}") is not None


def test_sqlite_cleanup_removes_expired_sessions(session_store):
    """Test SQLite cleanup removes expired sessions."""
    now = int(time.time())

    # Create expired session
    session_store.create_session(
        session_id="expired",
        user_id="user-1",
        access_token="token",
        refresh_token=None,
        token_expires_at=now - 3600,
        session_expires_at=now - 1,
    )

    # Create valid session
    session_store.create_session(
        session_id="valid",
        user_id="user-2",
        access_token="token",
        refresh_token=None,
        token_expires_at=now + 3600,
        session_expires_at=now + 86400,
    )

    removed_count = session_store.cleanup_expired()

    assert removed_count >= 1
    assert session_store.get_session("expired") is None
    assert session_store.get_session("valid") is not None


def test_redis_create_session_raises_not_implemented():
    """Test Redis stub raises NotImplementedError on init."""
    with pytest.raises(NotImplementedError, match="Redis session store is not yet implemented"):
        RedisSessionStore("redis://localhost")


def test_session_data_fields():
    """Test SessionData contains required fields."""
    now = int(time.time())

    session = SessionData(
        session_id="test-id",
        user_id="user-123",
        access_token="access",
        refresh_token="refresh",
        token_expires_at=now + 3600,
        session_expires_at=now + 86400,
        created_at=now,
        id_token="id-token",
    )

    assert session.session_id == "test-id"
    assert session.user_id == "user-123"
    assert session.access_token == "access"
    assert session.refresh_token == "refresh"
    assert session.token_expires_at == now + 3600
    assert session.session_expires_at == now + 86400
    assert session.created_at == now
    assert session.id_token == "id-token"


def test_session_data_id_token_defaults_to_none():
    """id_token must be optional so pre-existing SessionData(...) call sites keep working."""
    now = int(time.time())

    session = SessionData(
        session_id="test-id",
        user_id="user-123",
        access_token="access",
        refresh_token="refresh",
        token_expires_at=now + 3600,
        session_expires_at=now + 86400,
        created_at=now,
    )

    assert session.id_token is None


def test_oauth_state_storage(session_store):
    """Test OAuth state storage and retrieval."""
    now = int(time.time())

    session_store.save_oauth_state(
        state="test-state-123",
        redirect_uri="https://app.example.com/callback",
        code_verifier="verifier-abc",
        return_to="/dashboard",
        expires_at=now + 600,
    )

    state = session_store.get_oauth_state("test-state-123")

    assert state is not None
    assert state.state == "test-state-123"
    assert state.redirect_uri == "https://app.example.com/callback"
    assert state.code_verifier == "verifier-abc"
    assert state.return_to == "/dashboard"


def test_oauth_state_expiration(session_store):
    """Test OAuth state expires correctly."""
    now = int(time.time())

    # Create OAuth state that expires in 2 seconds (enough headroom for slow CI)
    session_store.save_oauth_state(
        state="short-lived-state",
        redirect_uri="https://app.example.com/callback",
        code_verifier="verifier",
        return_to=None,
        expires_at=now + 2,
    )

    # Should be valid immediately
    assert session_store.get_oauth_state("short-lived-state") is not None

    # Wait for expiration
    time.sleep(2.1)

    # Should be expired
    assert session_store.get_oauth_state("short-lived-state") is None


def test_oauth_state_deleted_after_use(session_store):
    """Test OAuth state can be deleted."""
    now = int(time.time())

    session_store.save_oauth_state(
        state="deletable-state",
        redirect_uri="https://app.example.com/callback",
        code_verifier="verifier",
        return_to=None,
        expires_at=now + 600,
    )

    assert session_store.get_oauth_state("deletable-state") is not None

    session_store.delete_oauth_state("deletable-state")

    assert session_store.get_oauth_state("deletable-state") is None


def test_tokens_encrypted_at_rest(tmp_db_path):
    """CWE-312 regression: OAuth tokens must not be stored as plaintext on disk."""
    store = SQLiteSessionStore(str(tmp_db_path))
    try:
        now = int(time.time())
        plaintext_access = "secret-access-token-xyz"
        plaintext_refresh = "secret-refresh-token-abc"
        plaintext_id = "secret-id-token-jwt"

        store.create_session(
            session_id="enc-test",
            user_id="user-1",
            access_token=plaintext_access,
            refresh_token=plaintext_refresh,
            token_expires_at=now + 3600,
            session_expires_at=now + 86400,
            id_token=plaintext_id,
        )

        # Raw on-disk values must not equal plaintext
        raw = sqlite3.connect(str(tmp_db_path))
        row = raw.execute("SELECT encrypted_tokens FROM sessions WHERE session_id = ?", ("enc-test",)).fetchone()
        raw.close()
        assert plaintext_access not in row[0]
        assert plaintext_refresh not in row[0]
        assert plaintext_id not in row[0]

        # Round-trip via the store still yields plaintext
        session = store.get_session("enc-test")
        assert session is not None
        assert session.access_token == plaintext_access
        assert session.refresh_token == plaintext_refresh
        assert session.id_token == plaintext_id
    finally:
        store.close()


def test_tampered_ciphertext_returns_none(tmp_db_path):
    """Tampered ciphertext should cause get_session to return None (InvalidTag caught)."""
    store = SQLiteSessionStore(str(tmp_db_path))
    try:
        now = int(time.time())

        store.create_session(
            session_id="tamper-test",
            user_id="user-1",
            access_token="secret-token",
            refresh_token="refresh-token",
            token_expires_at=now + 3600,
            session_expires_at=now + 86400,
        )

        # Tamper with the stored encrypted_tokens
        raw = sqlite3.connect(str(tmp_db_path))
        row = raw.execute("SELECT encrypted_tokens FROM sessions WHERE session_id = ?", ("tamper-test",)).fetchone()
        payload = json.loads(row[0])
        # Corrupt the ciphertext
        payload["ciphertext"] = payload["ciphertext"][:-4] + "XXXX"
        raw.execute(
            "UPDATE sessions SET encrypted_tokens = ? WHERE session_id = ?", (json.dumps(payload), "tamper-test")
        )
        raw.commit()
        raw.close()

        # Should return None due to InvalidTag
        assert store.get_session("tamper-test") is None
    finally:
        store.close()


def test_tampered_ciphertext_does_not_log_raw_session_id(tmp_db_path, caplog):
    """The InvalidTag warning must mask the session ID, not log it raw."""
    store = SQLiteSessionStore(str(tmp_db_path))
    try:
        now = int(time.time())
        raw_session_id = "tamper-log-hygiene-test"

        store.create_session(
            session_id=raw_session_id,
            user_id="user-1",
            access_token="secret-token",
            refresh_token="refresh-token",
            token_expires_at=now + 3600,
            session_expires_at=now + 86400,
        )

        raw = sqlite3.connect(str(tmp_db_path))
        row = raw.execute("SELECT encrypted_tokens FROM sessions WHERE session_id = ?", (raw_session_id,)).fetchone()
        payload = json.loads(row[0])
        payload["ciphertext"] = payload["ciphertext"][:-4] + "XXXX"
        raw.execute(
            "UPDATE sessions SET encrypted_tokens = ? WHERE session_id = ?", (json.dumps(payload), raw_session_id)
        )
        raw.commit()
        raw.close()

        with caplog.at_level(logging.WARNING):
            assert store.get_session(raw_session_id) is None

        assert raw_session_id not in caplog.text
        assert "has tampered token data" in caplog.text
    finally:
        store.close()


def test_legacy_fernet_value_returns_none(tmp_db_path):
    """Legacy Fernet-encrypted tokens (no __encrypted marker) should return None gracefully."""
    store = SQLiteSessionStore(str(tmp_db_path))
    try:
        now = int(time.time())

        # Directly insert a legacy Fernet-style value
        raw = sqlite3.connect(str(tmp_db_path))
        raw.execute(
            """INSERT INTO sessions
            (session_id, user_id, encrypted_tokens, token_expires_at, session_expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("legacy-session", "user-1", "gAAAAABfakebase64fernetdata", now + 3600, now + 86400, now),
        )
        raw.commit()
        raw.close()

        # Should return None (non-JSON / no __encrypted marker)
        assert store.get_session("legacy-session") is None
    finally:
        store.close()


def test_legacy_encrypted_blob_without_id_token_decrypts(tmp_db_path):
    """A blob encrypted before id_token existed (no id_token key at all) must still decrypt cleanly and yield id_token=None - no migration, no invalidation."""
    store = SQLiteSessionStore(str(tmp_db_path))
    try:
        now = int(time.time())
        key = load_encryption_key(env_var="FOUNDRY_AUTH_TOKEN_ENCRYPTION_KEY")

        # Hand-construct a pre-change blob: only access_token/refresh_token keys.
        legacy_payload = encrypt({"access_token": "legacy-access", "refresh_token": "legacy-refresh"}, key)

        raw = sqlite3.connect(str(tmp_db_path))
        raw.execute(
            """INSERT INTO sessions
            (session_id, user_id, encrypted_tokens, token_expires_at, session_expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("pre-id-token-session", "user-1", json.dumps(legacy_payload), now + 3600, now + 86400, now),
        )
        raw.commit()
        raw.close()

        session = store.get_session("pre-id-token-session")
        assert session is not None
        assert session.access_token == "legacy-access"
        assert session.refresh_token == "legacy-refresh"
        assert session.id_token is None
    finally:
        store.close()


def test_refresh_token_preserves_existing_id_token(session_store, sample_session_data):
    """A refresh whose IdP response omits id_token must not wipe a previously stored one."""
    session_store.create_session(**sample_session_data)
    now = int(time.time())

    session_store.refresh_token(
        session_id=sample_session_data["session_id"],
        new_access_token="new-access-token",
        new_refresh_token="new-refresh-token",
        new_token_expires_at=now + 7200,
    )

    retrieved = session_store.get_session(sample_session_data["session_id"])
    assert retrieved is not None
    assert retrieved.access_token == "new-access-token"
    assert retrieved.id_token == sample_session_data["id_token"]


def test_refresh_token_rotates_id_token_when_provided(session_store, sample_session_data):
    """A refresh whose IdP response includes a new id_token must replace the stored one."""
    session_store.create_session(**sample_session_data)
    now = int(time.time())

    session_store.refresh_token(
        session_id=sample_session_data["session_id"],
        new_access_token="new-access-token",
        new_refresh_token="new-refresh-token",
        new_token_expires_at=now + 7200,
        new_id_token="rotated-id-token",
    )

    retrieved = session_store.get_session(sample_session_data["session_id"])
    assert retrieved is not None
    assert retrieved.id_token == "rotated-id-token"


def test_refresh_token_on_legacy_blob_does_not_raise(tmp_db_path):
    """Refreshing a session whose stored blob predates id_token must not raise."""
    store = SQLiteSessionStore(str(tmp_db_path))
    try:
        now = int(time.time())
        key = load_encryption_key(env_var="FOUNDRY_AUTH_TOKEN_ENCRYPTION_KEY")
        legacy_payload = encrypt({"access_token": "legacy-access", "refresh_token": "legacy-refresh"}, key)

        raw = sqlite3.connect(str(tmp_db_path))
        raw.execute(
            """INSERT INTO sessions
            (session_id, user_id, encrypted_tokens, token_expires_at, session_expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            ("legacy-refresh-session", "user-1", json.dumps(legacy_payload), now + 3600, now + 86400, now),
        )
        raw.commit()
        raw.close()

        store.refresh_token(
            session_id="legacy-refresh-session",
            new_access_token="fresh-access",
            new_refresh_token="fresh-refresh",
            new_token_expires_at=now + 7200,
        )

        retrieved = store.get_session("legacy-refresh-session")
        assert retrieved is not None
        assert retrieved.access_token == "fresh-access"
        assert retrieved.id_token is None
    finally:
        store.close()


def test_refresh_token_none_id_token_holds_exclusive_lock_across_read_and_write(tmp_db_path):
    """When preserving an existing id_token, the SELECT-then-UPDATE must hold a lock across both.

    It must run inside a single BEGIN IMMEDIATE transaction so another process sharing this
    same SQLite file can't write in between and clobber a concurrently-rotated id_token with
    this call's stale snapshot. self._lock alone only serializes threads within this process,
    not other processes - this test proves the SQLite-level lock (not the Python-level one) is
    what's protecting the gap, by opening a second, independent connection to the same file and
    confirming it cannot write while the first connection's transaction is open.
    """
    store = SQLiteSessionStore(str(tmp_db_path))
    try:
        now = int(time.time())
        store.create_session(
            session_id="race-test",
            user_id="user-1",
            access_token="access",
            refresh_token="refresh",
            token_expires_at=now + 3600,
            session_expires_at=now + 86400,
            id_token="original-id-token",
        )

        lock_acquired = threading.Event()
        proceed = threading.Event()
        original_decrypt = store._decrypt_tokens

        # _decrypt_tokens is called after the SELECT (inside the BEGIN IMMEDIATE transaction) and
        # before the UPDATE - blocking here proves the SQLite write lock is held for that exact
        # read-then-write window, not just that BEGIN IMMEDIATE was issued at some point.
        def blocking_decrypt(stored_value):
            result = original_decrypt(stored_value)
            lock_acquired.set()
            proceed.wait(timeout=5)
            return result

        def do_refresh():
            store._decrypt_tokens = blocking_decrypt
            try:
                store.refresh_token(
                    session_id="race-test",
                    new_access_token="refreshed-access",
                    new_refresh_token="refreshed-refresh",
                    new_token_expires_at=now + 7200,
                )
            finally:
                store._decrypt_tokens = original_decrypt

        thread = threading.Thread(target=do_refresh)
        thread.start()
        try:
            assert lock_acquired.wait(timeout=5), "refresh_token never reached the locked read-modify-write window"

            second_conn = sqlite3.connect(str(tmp_db_path), timeout=0.1)
            try:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    second_conn.execute(
                        "UPDATE sessions SET token_expires_at = ? WHERE session_id = ?", (now + 1, "race-test")
                    )
            finally:
                second_conn.close()
        finally:
            proceed.set()
            thread.join(timeout=5)

        retrieved = store.get_session("race-test")
        assert retrieved is not None
        assert retrieved.access_token == "refreshed-access"
        assert retrieved.id_token == "original-id-token"
    finally:
        store.close()
