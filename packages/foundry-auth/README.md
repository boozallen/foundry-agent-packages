# Foundry Auth

Authentication package for Foundry platform, providing OIDC authentication with session management.

## Table of Contents

- [Features](#features)
- [Documentation](#documentation)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Configuration Options](#configuration-options)
- [Security Considerations](#security-considerations)
- [WebSocket Management](#websocket-management)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## Documentation

| Document | Description |
|----------|-------------|
| [AUTH_SETUP.md](AUTH_SETUP.md) | End-to-end setup guide — get auth working in 15 minutes |
| [Integration Guide](docs/INTEGRATION_GUIDE.md) | Add auth to any FastAPI service in 3 lines of code |
| [Security guide](docs/SECURITY.md) | Production security best practices and secret management |
| [env.development](docs/env.development) | Example environment variables for local development |
| [env.production](docs/env.production) | Example environment variables for production deployment |

## Features

- **OIDC Authentication**: OAuth 2.0 / OIDC integration with authorization code flow and PKCE
- **Session Management**: Protocol-based session storage with SQLite implementation
- **Prefix-Based Configuration**: Support multiple service configurations via environment variable prefixes
- **Security**: Session ID rotation, SameSite=Lax cookies, automatic token refresh
- **FastAPI Integration**: Ready-to-use router factory and authentication dependencies

## Quick Start

**Time to integrate**: ~10 minutes | **New to foundry-auth?** Start with AUTH_SETUP.md for a full walkthrough including Keycloak setup. For the shortest path, see the Integration Guide.

This guide walks you through integrating foundry-auth into your FastAPI application. You'll set up environment variables, configure authentication, and create a protected endpoint.

### 1. Environment Configuration

```bash
# Basic configuration (no prefix)
export OIDC_ISSUER="https://your-idp.com/realms/your-realm"
export OIDC_CLIENT_ID="your-client-id"
export OIDC_CLIENT_SECRET="your-client-secret"
export OIDC_CALLBACK_URL="http://localhost:8000/auth/callback"
export FRONTEND_URL="http://localhost:3000"
export CORS_ALLOWED_ORIGINS="http://localhost:3000,http://localhost:5173"

# Session store configuration
export SESSION_STORE_TYPE="sqlite"
export SESSION_STORE_PATH="./data/sessions.db"  # for SQLite
```

#### Windows (PowerShell)

```powershell
$env:OIDC_ISSUER = "https://your-idp.com/realms/your-realm"
$env:OIDC_CLIENT_ID = "your-client-id"
$env:OIDC_CLIENT_SECRET = "your-client-secret"
$env:OIDC_CALLBACK_URL = "http://localhost:8000/auth/callback"
$env:FRONTEND_URL = "http://localhost:3000"
$env:CORS_ALLOWED_ORIGINS = "http://localhost:3000,http://localhost:5173"
$env:SESSION_STORE_TYPE = "sqlite"
$env:SESSION_STORE_PATH = ".\data\sessions.db"
```

### 2. Prefix-Based Configuration (Multiple Services)

When running multiple services with different auth configurations:

```bash
# Service A configuration
export SERVICE_A_OIDC_ISSUER="https://idp-a.com/realms/service-a"
export SERVICE_A_OIDC_CLIENT_ID="service-a-client"
export SERVICE_A_OIDC_CLIENT_SECRET="secret-a"
export SERVICE_A_OIDC_CALLBACK_URL="http://localhost:8001/auth/callback"
export SERVICE_A_FRONTEND_URL="http://localhost:3001"
```

#### Windows (PowerShell)

```powershell
$env:SERVICE_A_OIDC_ISSUER = "https://idp-a.com/realms/service-a"
$env:SERVICE_A_OIDC_CLIENT_ID = "service-a-client"
$env:SERVICE_A_OIDC_CLIENT_SECRET = "secret-a"
$env:SERVICE_A_OIDC_CALLBACK_URL = "http://localhost:8001/auth/callback"
$env:SERVICE_A_FRONTEND_URL = "http://localhost:3001"
```

### 3. Create Your FastAPI Application

```python
from fastapi import FastAPI, Depends
from foundry_auth import (
    AuthConfig,
    create_auth_router,
    create_require_session,
    get_session_store,
    SessionData,
)

# Step 1: Load configuration (no prefix for basic setup)
config = AuthConfig.from_env()

# Step 2: Initialize session store
session_store = get_session_store()

# Step 3: Create FastAPI app
app = FastAPI()

# Step 4: Add authentication router (provides /auth/login, /auth/callback, /auth/logout, /auth/user)
auth_router = create_auth_router(config=config, session_store=session_store)
app.include_router(auth_router)

# Step 5: Create authentication dependency
require_session = create_require_session(config=config, session_store=session_store)

# Step 6: Create protected routes
@app.get("/api/profile")
async def get_profile(session: SessionData = Depends(require_session)):
    """Protected route - requires authentication."""
    return {
        "user_id": session.user_id,
        "expires_at": session.session_expires_at,
    }

@app.get("/api/data")
async def get_data(session: SessionData = Depends(require_session)):
    """Another protected route."""
    return {"message": f"Hello, {session.user_id}!"}
```

### 4. Run Your Application

```bash
uvicorn main:app --reload
```

That's it! Your application now has:
- Login flow at `/auth/login`
- OIDC callback at `/auth/callback`
- Logout at `/auth/logout`
- User info at `/auth/user`
- Protected routes at `/api/profile` and `/api/data`

## API Reference

### Configuration

#### `AuthConfig`

Dataclass for OIDC authentication configuration.

**Attributes:**
- `oidc_issuer` (str): OIDC issuer URL (e.g., `https://idp.com/realms/myrealm`)
- `oidc_client_id` (str): Client ID from OIDC provider
- `oidc_client_secret` (str): Client secret for confidential clients
- `oidc_callback_url` (str): Callback URL for OAuth flow (e.g., `http://localhost:8000/auth/callback`)
- `cors_allowed_origins` (list[str]): List of allowed CORS origins
- `frontend_url` (str): Frontend application URL for redirects
- `session_ttl_hours` (int): Session lifetime in hours (default: 24)
- `token_refresh_threshold_minutes` (int): Minutes before token expiry to trigger refresh (default: 5)
- `secure_cookies` (bool): Enable secure cookie flag (default: True, requires HTTPS)

**Methods:**

##### `AuthConfig.from_env(prefix: str = "") -> AuthConfig`

Load configuration from environment variables with optional prefix.

**Args:**
- `prefix` (str): Optional prefix for environment variable names (e.g., `"SERVICE_A_"`). If provided, reads `{prefix}OIDC_ISSUER`, `{prefix}CORS_ALLOWED_ORIGINS`, etc. If empty, reads unprefixed variables.

**Returns:**
- `AuthConfig`: Instance populated from environment variables

**Raises:**
- `ValueError`: If required environment variables are missing

**Environment Variables:**
- Required: `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CALLBACK_URL`, `FRONTEND_URL`
- Optional: `OIDC_CLIENT_SECRET` (default: ""), `CORS_ALLOWED_ORIGINS` (default: `http://localhost:5173`), `SESSION_TTL_HOURS` (default: 24), `TOKEN_REFRESH_THRESHOLD_MINUTES` (default: 5), `SECURE_COOKIES` (default: "true")

**Example:**
```python
from foundry_auth import AuthConfig

# Basic usage (no prefix)
config = AuthConfig.from_env()

# Multi-service usage with prefix
config_a = AuthConfig.from_env(prefix="SERVICE_A_")
config_b = AuthConfig.from_env(prefix="SERVICE_B_")
```

### Session Management

#### `SessionData`

Dataclass representing an active user session with OAuth tokens.

**Attributes:**
- `session_id` (str): Unique session identifier
- `user_id` (str): User identifier from OIDC provider (typically `sub` claim)
- `access_token` (str): OAuth access token
- `refresh_token` (str | None): OAuth refresh token for token renewal
- `token_expires_at` (int): Unix timestamp when access token expires
- `session_expires_at` (int): Unix timestamp when session expires
- `created_at` (int): Unix timestamp when session was created
- `id_token` (str | None): Raw OIDC ID token (JWT) from the IdP, for use as the
  subject token in RFC 8693 token exchange (e.g. Okta Cross-App Access / ID-JAG).
  `None` when the IdP returned none, or for sessions created before this field
  existed. Encrypted at rest alongside the other tokens; never logged; not
  returned by `/auth/user`.

**Example:**
```python
@app.get("/profile")
async def get_profile(session: SessionData = Depends(require_session)):
    return {
        "user_id": session.user_id,
        "expires_at": session.session_expires_at
    }
```

#### `SessionStore`

Protocol defining the interface for session storage backends.

**Methods:**
- `create_session(session_id, user_id, access_token, refresh_token, token_expires_at, session_expires_at, id_token=None) -> None`: Create a new session
- `get_session(session_id) -> SessionData | None`: Retrieve session by ID, returns None if expired/not found
- `delete_session(session_id) -> None`: Delete a session
- `refresh_token(session_id, new_access_token, new_refresh_token, new_token_expires_at, new_session_expires_at=None, new_id_token=None) -> None`: Update session tokens. `new_id_token=None` means "leave the stored id_token unchanged," not "clear it."
- `save_oauth_state(state, redirect_uri, code_verifier, return_to, expires_at) -> None`: Save OAuth state for PKCE flow
- `get_oauth_state(state) -> OAuthState | None`: Retrieve OAuth state
- `delete_oauth_state(state) -> None`: Delete OAuth state
- `cleanup_expired() -> int`: Remove expired sessions and states, returns count removed

#### `SQLiteSessionStore`

SQLite-backed session store implementation.

**Constructor:**
```python
SQLiteSessionStore(db_path: str)
```

**Args:**
- `db_path` (str): Path to SQLite database file. Parent directories are created if needed.

**Features:**
- Automatic table creation
- TTL-based expiration with passive checking
- OAuth state management for PKCE flow
- Thread-safe operations with internal locking

**Example:**
```python
from foundry_auth import SQLiteSessionStore

store = SQLiteSessionStore(db_path="./data/sessions.db")
```

#### `OAuthState`

Dataclass representing temporary OAuth state during authentication flow.

**Attributes:**
- `state` (str): OAuth state parameter for CSRF protection
- `redirect_uri` (str): Callback URL
- `code_verifier` (str): PKCE code verifier
- `return_to` (str | None): Application path to return to after auth
- `created_at` (int): Unix timestamp when state was created
- `expires_at` (int): Unix timestamp when state expires

### Factory Functions

#### `get_session_store(prefix: str = "") -> SessionStore`

Factory function to create a configured session store based on environment variables.

**Args:**
- `prefix` (str): Optional prefix for environment variable names (e.g., `"SERVICE_A_"`)

**Returns:**
- `SessionStore`: Configured session store instance (SQLite)

**Raises:**
- `ValueError`: If `SESSION_STORE_TYPE` has an unsupported value

**Environment Variables:**
- `SESSION_STORE_TYPE` (default: "sqlite"): Store type ("sqlite")
- `SESSION_STORE_PATH` (default: "./data/sessions.db"): Path for SQLite

**Example:**
```python
from foundry_auth import get_session_store

# Basic usage
store = get_session_store()

# With prefix
store_a = get_session_store(prefix="SERVICE_A_")
```

### Dependencies

#### `create_require_session(config: AuthConfig, session_store: SessionStore)`

Create a FastAPI dependency that requires authentication.

**Args:**
- `config` (AuthConfig): Authentication configuration
- `session_store` (SessionStore): Session store instance

**Returns:**
- Callable dependency function that validates session and returns `SessionData`

**Raises (in dependency):**
- `HTTPException` (401): If authentication fails (no cookie, invalid/expired session)

**Example:**
```python
from foundry_auth import create_require_session, AuthConfig, get_session_store

config = AuthConfig.from_env()
store = get_session_store()
require_session = create_require_session(config, store)

@app.get("/api/protected")
async def protected_endpoint(session: SessionData = Depends(require_session)):
    return {"user_id": session.user_id}
```

#### `create_optional_session(config: AuthConfig, session_store: SessionStore)`

Create a FastAPI dependency that optionally validates authentication.

**Args:**
- `config` (AuthConfig): Authentication configuration
- `session_store` (SessionStore): Session store instance

**Returns:**
- Callable dependency function that returns `SessionData | None`

**Example:**
```python
from foundry_auth import create_optional_session

optional_session = create_optional_session(config, store)

@app.get("/api/data")
async def data_endpoint(session: SessionData | None = Depends(optional_session)):
    if session:
        return {"user_id": session.user_id, "authenticated": True}
    return {"authenticated": False}
```

### Routers

#### `create_auth_router(config: AuthConfig, session_store: SessionStore) -> APIRouter`

Create a FastAPI router with authentication endpoints.

**Args:**
- `config` (AuthConfig): Authentication configuration
- `session_store` (SessionStore): Session store instance

**Returns:**
- `APIRouter`: Router with `/auth/**` endpoints

**Endpoints provided:**
- `GET /auth/login?returnTo=/path`: Initiate OIDC login flow
- `GET /auth/callback`: Handle OIDC provider callback
- `GET /auth/user`: Get current user information
- `POST /auth/logout`: Logout and clear session

**Example:**
```python
from fastapi import FastAPI
from foundry_auth import create_auth_router, AuthConfig, get_session_store

app = FastAPI()
config = AuthConfig.from_env()
store = get_session_store()

auth_router = create_auth_router(config, store)
app.include_router(auth_router)
```

### WebSocket Management

#### `register_connection(session_id: str, websocket: WebSocket) -> None`

Register a WebSocket connection for session tracking.

**Args:**
- `session_id` (str): Session ID associated with the connection
- `websocket` (WebSocket): WebSocket connection to register

**Example:**
```python
from fastapi import WebSocket
from foundry_auth.websocket import register_connection, unregister_connection

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, sid: str):
    await websocket.accept()
    try:
        register_connection(sid, websocket)
        while True:
            data = await websocket.receive_text()
            # Handle messages...
    finally:
        unregister_connection(sid, websocket)
```

#### `unregister_connection(session_id: str, websocket: WebSocket) -> None`

Unregister a WebSocket connection from session tracking.

**Args:**
- `session_id` (str): Session ID to remove connection from
- `websocket` (WebSocket): WebSocket connection to unregister

#### `start_session_validation_task(session_store: SessionStore) -> asyncio.Task`

Start periodic validation of WebSocket connections.

**Args:**
- `session_store` (SessionStore): Session store for validation

**Returns:**
- `asyncio.Task`: Background task handle

**Note:** Must be called from an async context with a running event loop.

**Example:**
```python
from foundry_auth.websocket import start_session_validation_task

@app.on_event("startup")
async def startup():
    await start_session_validation_task(session_store)
```

**Configuration (environment variables):**
- `WEBSOCKET_SESSION_CHECK_INTERVAL_SECONDS` (default: 300): Validation interval
- `WEBSOCKET_MAX_CONNECTION_SECONDS` (default: 3600): Maximum connection duration

#### `delete_session_and_close_connections(session_id: str, session_store: SessionStore) -> None`

Delete a session and close all associated WebSocket connections.

**Args:**
- `session_id` (str): Session ID to delete
- `session_store` (SessionStore): Session store instance

**Note:** Use this instead of `session_store.delete_session()` when WebSocket connections need immediate closure.

**Example:**
```python
from foundry_auth.websocket import delete_session_and_close_connections

@app.post("/admin/revoke-session")
async def revoke_session(session_id: str):
    await delete_session_and_close_connections(session_id, session_store)
    return {"status": "revoked"}
```

## Configuration Options

### Environment Variables

The package is configured entirely through environment variables. Use the `prefix` parameter in `AuthConfig.from_env()` and `get_session_store()` to support multiple services with different configurations.

For copy-paste-ready templates, see `docs/env.development` and `docs/env.production`.

#### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `OIDC_ISSUER` | OIDC provider issuer URL | `https://idp.example.com/realms/myrealm` |
| `OIDC_CLIENT_ID` | OAuth client ID from your OIDC provider | `my-app-client` |
| `OIDC_CALLBACK_URL` | Callback URL for OAuth flow (must match provider config) | `http://localhost:8000/auth/callback` |
| `FRONTEND_URL` | Frontend application URL for redirects after auth | `http://localhost:3000` |

#### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OIDC_CLIENT_SECRET` | OAuth client secret (for confidential clients) | `""` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of allowed CORS origins | `http://localhost:5173` |
| `SESSION_TTL_HOURS` | Session lifetime in hours | `24` |
| `TOKEN_REFRESH_THRESHOLD_MINUTES` | Minutes before token expiry to trigger refresh | `5` |
| `SECURE_COOKIES` | Enable secure cookie flag (requires HTTPS) | `true` |
| `SESSION_STORE_TYPE` | Session store backend ("sqlite") | `sqlite` |
| `SESSION_STORE_PATH` | SQLite database file path | `./data/sessions.db` |
| `WEBSOCKET_SESSION_CHECK_INTERVAL_SECONDS` | WebSocket validation interval | `300` |
| `WEBSOCKET_MAX_CONNECTION_SECONDS` | Maximum WebSocket connection duration | `3600` |

### Prefix-Based Configuration

When running multiple services with different auth configurations, use environment variable prefixes to isolate configurations.

**Pattern**: Add a prefix to all environment variables (e.g., `SERVICE_A_OIDC_ISSUER` instead of `OIDC_ISSUER`).

**Example - Multiple Services:**

```bash
# Service A configuration
export SERVICE_A_OIDC_ISSUER="https://idp-a.com/realms/service-a"
export SERVICE_A_OIDC_CLIENT_ID="service-a-client"
export SERVICE_A_OIDC_CLIENT_SECRET="secret-a"
export SERVICE_A_OIDC_CALLBACK_URL="http://localhost:8001/auth/callback"
export SERVICE_A_FRONTEND_URL="http://localhost:3001"
export SERVICE_A_SESSION_STORE_PATH="./data/sessions-a.db"

# Service B configuration  
export SERVICE_B_OIDC_ISSUER="https://idp-b.com/realms/service-b"
export SERVICE_B_OIDC_CLIENT_ID="service-b-client"
export SERVICE_B_OIDC_CLIENT_SECRET="secret-b"
export SERVICE_B_OIDC_CALLBACK_URL="http://localhost:8002/auth/callback"
export SERVICE_B_FRONTEND_URL="http://localhost:3002"
export SERVICE_B_SESSION_STORE_PATH="./data/sessions-b.db"
```

**Application code:**

```python
from fastapi import FastAPI
from foundry_auth import AuthConfig, get_session_store, create_auth_router

# Service A
app_a = FastAPI()
config_a = AuthConfig.from_env(prefix="SERVICE_A_")
store_a = get_session_store(prefix="SERVICE_A_")
app_a.include_router(create_auth_router(config_a, store_a))

# Service B
app_b = FastAPI()
config_b = AuthConfig.from_env(prefix="SERVICE_B_")
store_b = get_session_store(prefix="SERVICE_B_")
app_b.include_router(create_auth_router(config_b, store_b))
```

## Security Considerations

For comprehensive security guidance including secret management, CORS hardening, and WebSocket session security, see the package's Security guide (`docs/SECURITY.md` in `packages/foundry-auth/`).

### Session ID Rotation

The package implements session ID rotation to prevent **session fixation attacks**. When a user successfully authenticates via the `/auth/callback` endpoint:

1. A new session ID is generated using `secrets.token_urlsafe(32)`
2. The new session is created in the session store
3. The old pre-login session (if any) is never reused

This ensures attackers cannot fixate a session ID before authentication and hijack the session after the victim logs in.

**Implementation detail**: See `create_auth_router` in `routers.py` - the callback handler creates a completely new session ID rather than updating an existing one.

### WebSocket Connection Cleanup

When a session is invalidated (logout, admin revocation, expiration), associated WebSocket connections must be closed immediately to prevent unauthorized access.

**Recommended approach**: Use `delete_session_and_close_connections()` instead of `session_store.delete_session()` when WebSockets are in use:

```python
from foundry_auth.websocket import delete_session_and_close_connections

@app.post("/auth/logout")
async def logout(request: Request):
    sid = request.cookies.get("sid")
    if sid:
        await delete_session_and_close_connections(sid, session_store)
    return {"status": "logged out"}
```

The periodic validation task (`start_session_validation_task`) also closes connections for expired sessions, but explicit cleanup on logout provides immediate security.

### Cookie Security Attributes

Session cookies are configured with multiple security layers:

| Attribute | Value | Purpose |
|-----------|-------|---------|
| `httponly=True` | Always enabled | Prevents JavaScript access to cookies, mitigating XSS attacks |
| `samesite="lax"` | Always enabled | CSRF protection while allowing OAuth redirects from IdP |
| `secure` | Configurable (default: True) | Requires HTTPS transmission. Set `SECURE_COOKIES=false` only for local development |

**Production recommendation**: Always use `secure=True` (default) and serve your application over HTTPS.

### Automatic Token Refresh

OAuth access tokens have limited lifetimes. The package automatically refreshes tokens when they approach expiry:

- **Trigger**: Token refresh occurs when `time_until_expiry < TOKEN_REFRESH_THRESHOLD_MINUTES` (default: 5 minutes)
- **Mechanism**: Uses the OAuth refresh token to obtain a new access token from the OIDC provider
- **Session extension**: Session expiry is extended on successful token refresh
- **Failure handling**: If token refresh fails (e.g., refresh token revoked), the session is deleted and the user receives a 401 response

This ensures uninterrupted user experience while maintaining short access token lifetimes for security.

### CORS Configuration Best Practices

Configure `CORS_ALLOWED_ORIGINS` to explicitly list allowed frontend origins:

```bash
# Good - explicit list
export CORS_ALLOWED_ORIGINS="https://app.example.com,https://admin.example.com"

# Bad - wildcard (avoid in production)
# Using "*" or overly permissive origins weakens CSRF protection
```

**Why it matters**: The OIDC callback sets session cookies. Proper CORS configuration ensures only trusted origins can make authenticated requests.

## WebSocket Management

The package provides utilities for tracking WebSocket connections tied to authentication sessions. This enables immediate connection closure on logout/revocation and periodic validation to handle session expiration.

### Connection Registry

The connection registry maintains a mapping of `session_id → Set[WebSocket]`, allowing multiple WebSocket connections per session.

**Thread-safety**: Registry operations are protected by a threading lock for concurrent access.

### Basic Usage

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from foundry_auth.websocket import (
    register_connection,
    unregister_connection,
    start_session_validation_task
)

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, sid: str):
    """WebSocket endpoint with authentication."""
    # Validate session exists
    session = session_store.get_session(sid)
    if not session:
        await websocket.close(code=1008, reason="Invalid session")
        return

    await websocket.accept()

    try:
        # Register connection for tracking
        register_connection(sid, websocket)

        while True:
            # Handle messages
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")

    except WebSocketDisconnect:
        pass
    finally:
        # Always unregister on disconnect
        unregister_connection(sid, websocket)

@app.on_event("startup")
async def startup():
    """Start periodic session validation on application startup."""
    await start_session_validation_task(session_store)
```

### Session Validation Task

The `start_session_validation_task()` function runs a background task that periodically validates all active WebSocket connections:

**Validation checks:**
1. Session still exists and is not expired
2. Connection duration hasn't exceeded `WEBSOCKET_MAX_CONNECTION_SECONDS`

**Close codes:**
- `1008` (Policy Violation): Session expired
- `1000` (Normal Closure): Connection timeout

**Configuration:**
```bash
# Check connections every 5 minutes
export WEBSOCKET_SESSION_CHECK_INTERVAL_SECONDS=300

# Close connections after 1 hour
export WEBSOCKET_MAX_CONNECTION_SECONDS=3600
```

### Immediate Cleanup on Logout

For immediate security, close connections when sessions are explicitly deleted:

```python
from foundry_auth.websocket import delete_session_and_close_connections

@app.post("/auth/logout")
async def logout(request: Request):
    sid = request.cookies.get("sid")
    if sid:
        # Closes all WebSocket connections immediately
        await delete_session_and_close_connections(sid, session_store)

    resp = Response(content='{"status": "logged out"}')
    resp.delete_cookie("sid")
    return resp
```

### Admin Session Revocation

Revoke a user's session and close connections from an admin endpoint:

```python
@app.post("/admin/revoke-session")
async def revoke_session(session_id: str, admin: SessionData = Depends(require_admin)):
    await delete_session_and_close_connections(session_id, session_store)
    return {"status": "session revoked", "session_id": session_id}
```

## Troubleshooting

### Token Refresh Failures

**Symptom**: Users getting logged out unexpectedly with 401 errors

**Common causes:**
1. **Refresh token expired**: OIDC provider limits refresh token lifetime
2. **Refresh token revoked**: User changed password or admin revoked access
3. **OIDC provider unreachable**: Network issues or provider downtime

**Solutions:**
- Check `TOKEN_REFRESH_THRESHOLD_MINUTES` - increase if refresh attempts are too late
- Verify OIDC provider's refresh token policy matches your `SESSION_TTL_HOURS`
- Monitor logs for "Token refresh failed" warnings to identify patterns
- Consider implementing graceful logout redirect instead of showing 401 error page

### CORS Configuration Issues

**Symptom**: Authentication works but frontend can't make API requests, or `/auth/callback` fails with CORS errors

**Common causes:**
1. `CORS_ALLOWED_ORIGINS` doesn't include the frontend origin
2. Mismatched protocols (http vs https)
3. Port number omitted or incorrect

**Solutions:**
```bash
# Include exact origin with protocol and port
export CORS_ALLOWED_ORIGINS="http://localhost:3000,http://localhost:5173"

# For production
export CORS_ALLOWED_ORIGINS="https://app.example.com,https://admin.example.com"
```

**Debugging tip**: Check browser console for CORS errors. The error message will show the origin that was rejected.

### Session Persistence Problems

**Symptom**: Users logged out on page refresh or session not found

**Common causes:**
1. **SQLite path incorrect**: `SESSION_STORE_PATH` points to nonexistent directory
2. **Cookie domain mismatch**: Frontend and API on different domains
3. **Secure cookies with HTTP**: `SECURE_COOKIES=true` but using HTTP (not HTTPS)

**Solutions:**
```bash
# Ensure parent directory exists for SQLite
export SESSION_STORE_PATH="./data/sessions.db"  # ./data must exist

# For local development with HTTP
export SECURE_COOKIES=false

# For production with HTTPS
export SECURE_COOKIES=true  # default
```

**Debugging SQLite**: Check if database file is created and sessions table exists:
```bash
sqlite3 ./data/sessions.db "SELECT COUNT(*) FROM sessions;"
```

### Callback URL Mismatches

**Symptom**: Authentication fails at `/auth/callback` with "Invalid redirect URI" error from OIDC provider

**Common causes:**
1. `OIDC_CALLBACK_URL` doesn't match value registered with OIDC provider
2. Protocol mismatch (http vs https)
3. Port number missing or incorrect
4. Trailing slash mismatch

**Solutions:**
```bash
# Exact match required - check OIDC provider configuration
export OIDC_CALLBACK_URL="http://localhost:8000/auth/callback"

# NOT: http://localhost:8000/auth/callback/  (trailing slash)
# NOT: http://0.0.0.0:8000/auth/callback  (use localhost, not 0.0.0.0)
```

**Provider-specific notes:**
- **Keycloak**: Check "Valid Redirect URIs" in client settings
- **Auth0**: Check "Allowed Callback URLs" in application settings
- **Okta**: Check "Sign-in redirect URIs" in application settings

### Prefix Configuration Errors

**Symptom**: `ValueError: Missing required environment variables` even though variables are set

**Common causes:**
1. Prefix inconsistent between `AuthConfig.from_env()` and `get_session_store()`
2. Prefix has wrong format (missing or extra underscore)
3. Copy-paste error with variable names

**Solutions:**
```python
# CORRECT: Same prefix everywhere
config = AuthConfig.from_env(prefix="SERVICE_A_")
store = get_session_store(prefix="SERVICE_A_")
router = create_auth_router(config, store)

# INCORRECT: Inconsistent prefixes
config = AuthConfig.from_env(prefix="SERVICE_A_")
store = get_session_store(prefix="SERVICE_B_")  # Wrong!
```

**Environment variable format:**
```bash
# CORRECT: Prefix with trailing underscore
export SERVICE_A_OIDC_ISSUER="..."

# INCORRECT: Missing underscore separator
export SERVICE_AOIDC_ISSUER="..."
```

**Debugging tip**: Print the actual environment variable names being looked up:
```python
prefix = "SERVICE_A_"
print(f"Looking for: {prefix}OIDC_ISSUER")  # SERVICE_A_OIDC_ISSUER
```

## API Endpoints

- `GET /auth/login?returnTo=/dashboard` - Initiate OIDC login flow
- `GET /auth/callback?code=...&state=...` - OIDC callback handler
- `GET /auth/user` - Get current user information (requires authentication)
- `POST /auth/logout` - Logout and clear session

## Development

This package is part of the foundry-agent-packages monorepo.

```bash
uv pip install -e packages/foundry-auth
```
