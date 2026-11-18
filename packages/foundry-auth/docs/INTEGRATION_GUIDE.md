# Integration Guide

Add OIDC authentication to any FastAPI service.

## Minimal Integration (3 Lines)

```python
from foundry_auth import AuthConfig, create_auth_router, get_session_store

app.include_router(create_auth_router(
    config=AuthConfig.from_env(),
    session_store=get_session_store(),
))
```

This gives you `/auth/login`, `/auth/callback`, `/auth/logout`, and `/auth/user` endpoints with no additional code.

## Step-by-Step Instructions

For a full walkthrough including Keycloak setup, environment configuration, and verification, see [AUTH_SETUP.md](../AUTH_SETUP.md).

The key integration points are summarized below:

1. Load configuration: `AuthConfig.from_env()` reads all `OIDC_*`, `CORS_*`, and session-related environment variables.
2. Initialize session store: `get_session_store()` creates a SQLite-backed store by default.
3. Mount the auth router: `app.include_router(create_auth_router(config=config, session_store=session_store))`
4. Protect routes: use `create_require_session(config=config, session_store=session_store)` as a FastAPI dependency.

## Common Pitfalls

### Prefix Mismatch

When using prefix-based configuration for multi-service setups, the prefix must be identical across all calls:

```python
# WRONG: Different prefixes
config = AuthConfig.from_env(prefix="SVC_A_")
store = get_session_store(prefix="SVC_B_")  # Bug!

# CORRECT: Same prefix everywhere
config = AuthConfig.from_env(prefix="SVC_A_")
store = get_session_store(prefix="SVC_A_")
```

### Callback URL Must Exactly Match Provider

The `OIDC_CALLBACK_URL` value must be character-for-character identical to what's registered in your OIDC provider:

- Protocol matters: `http://` vs `https://`
- Port matters: `localhost:8000` vs `localhost`
- Trailing slash matters: `/auth/callback` vs `/auth/callback/`
- Host matters: `localhost` vs `127.0.0.1` vs `0.0.0.0`

### CORS Origins Format

Origins must include protocol and port, with no trailing slash:

```bash
# CORRECT
export CORS_ALLOWED_ORIGINS="http://localhost:3000,http://localhost:5173"

# WRONG — missing port
export CORS_ALLOWED_ORIGINS="http://localhost"

# WRONG — trailing slash
export CORS_ALLOWED_ORIGINS="http://localhost:3000/"
```

### Secure Cookies Require HTTPS

The default `SECURE_COOKIES=true` means the session cookie will only be sent over HTTPS. For local development over plain HTTP:

```bash
export SECURE_COOKIES=false
```

Forgetting this results in login appearing to succeed but the session being lost immediately.

### SQLite Path Must Be Writable

The `SESSION_STORE_PATH` parent directory must exist and be writable:

```bash
export SESSION_STORE_PATH="./data/sessions.db"
# Ensure ./data/ exists:
mkdir -p ./data
```

If the path is invalid, session creation will fail silently or raise an OS error.

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OIDC_ISSUER` | Yes | — | OIDC provider issuer URL |
| `OIDC_CLIENT_ID` | Yes | — | OAuth client ID |
| `OIDC_CLIENT_SECRET` | No | `""` | OAuth client secret (confidential clients) |
| `OIDC_CALLBACK_URL` | Yes | — | OAuth callback URL (must match provider) |
| `FRONTEND_URL` | Yes | — | Frontend URL for post-auth redirects |
| `CORS_ALLOWED_ORIGINS` | No | `http://localhost:5173` | Comma-separated allowed origins |
| `SESSION_TTL_HOURS` | No | `24` | Session lifetime in hours |
| `TOKEN_REFRESH_THRESHOLD_MINUTES` | No | `5` | Minutes before expiry to trigger refresh |
| `SECURE_COOKIES` | No | `true` | Require HTTPS for session cookies |
| `SESSION_STORE_TYPE` | No | `sqlite` | Session store backend (`sqlite` or `redis`) |
| `SESSION_STORE_PATH` | No | `./data/sessions.db` | SQLite database file path |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis URL (if `SESSION_STORE_TYPE=redis`) |
| `WEBSOCKET_SESSION_CHECK_INTERVAL_SECONDS` | No | `300` | WebSocket validation interval |
| `WEBSOCKET_MAX_CONNECTION_SECONDS` | No | `3600` | Max WebSocket connection duration |

All variables support prefix-based configuration (e.g., `SERVICE_A_OIDC_ISSUER`) via `AuthConfig.from_env(prefix="SERVICE_A_")`.

## Upgrade Guide

### Version Compatibility

| foundry-auth | Python | FastAPI | Notes |
|--------------|--------|---------|-------|
| 0.1.x | ≥3.11 | 0.133.x | Current stable |

### Upgrading Between Versions

1. Check the [CHANGELOG](../CHANGELOG.md) for breaking changes
2. Update your dependency: `uv pip install --upgrade foundry-auth`
3. Run your test suite to catch API changes
4. Watch for deprecation warnings in logs

### Breaking Change Patterns to Watch For

- **Environment variable renames**: Check that all expected variables are still read
- **Session store schema changes**: May require deleting and recreating the SQLite database
- **New required configuration**: `from_env()` will raise `ValueError` if new required fields are added

## See Also

- [AUTH_SETUP.md](../AUTH_SETUP.md) — Full setup guide with Keycloak walkthrough
- [Security guide](SECURITY.md) — Production security best practices
- [README](../README.md) — Full API reference
