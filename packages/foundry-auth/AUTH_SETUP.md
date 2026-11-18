# Auth Setup Guide

Get foundry-auth working end-to-end in under 15 minutes.

## Prerequisites

- **Python 3.11+**
- **Dependencies**: `fastapi`, `httpx`, `uvicorn` (installed automatically — see [Step 2](#2-install-the-package))
- **Running Keycloak instance** (or any OIDC provider): See the [Keycloak Setup](#keycloak-setup) section below

## Keycloak Setup

A `docker-compose.yml` for Keycloak is included in this package directory (`packages/foundry-auth/`):

```yaml
# packages/foundry-auth/docker-compose.yml
services:
  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    command: start-dev
    environment:
      KC_HTTP_PORT: "8080"
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
    ports:
      - "8080:8080"
```

Ensure Docker Desktop (or Rancher Desktop) is running, then start Keycloak from the package directory:

```bash
cd packages/foundry-auth
docker compose up keycloak -d
```

Wait for Keycloak to become healthy (typically 15–30 seconds)

## Keycloak Admin Access

| Item | Value |
|------|-------|
| Admin Console | `http://localhost:8080/admin` |
| Default Admin User | `admin` |
| Default Admin Password | `admin` |

### Realm Setup

1. Log in to the admin console at `http://localhost:8080/admin`
2. Click the realm dropdown (top-left, says **master**) → **Create realm**
3. Set **Realm name** to `foundry`, ensure **Enabled** is ON, click **Create**
4. Verify: `curl -sf http://localhost:8080/realms/foundry | jq .realm` should return `"foundry"`
5. Navigate to **Clients** → **Create client**

### Client Configuration

1. **Client ID**: e.g., `foundry-app`, **Client type**: OpenID Connect, hit next
2. **Client authentication**: ON (confidential client), hit next
3. **Valid redirect URIs**: `http://localhost:8000/auth/callback`, **Web origins**: `http://localhost:3000`, `http://localhost:5173`; hit save
4. After creation, go to the **Credentials** tab to copy the client secret
5. (Optional) To enable programmatic testing via `curl` (resource owner password grant), go to the **Settings** tab and enable **Direct access grants**

## Test Credentials

> **WARNING: Development Only**
>
> These credentials are for local development only. Never use default or shared credentials in staging or production environments. See the package's [Security guide](docs/SECURITY.md) for production secret management.

Create a test user in Keycloak:

1. Navigate to **Users** → **Add user**
2. Set username: `testuser`
3. Set email: `testuser@example.com`
4. Set first name: `Test`, last name: `User`
5. Enable **Email verified** toggle
6. Click **Create**
7. Go to **Credentials** tab → **Set password** → enter `testpass`
8. Disable the "Temporary" toggle, click **Save**

> **Note (Keycloak 26+):** All of first name, last name, and email verified are required for the account to be considered "fully set up." Without them, login attempts will fail with "Account is not fully set up" even though `requiredActions` appears empty.

| Field | Value |
|-------|-------|
| Username | `testuser` |
| Password | `testpass` |
| Email | `testuser@example.com` |
| First Name | `Test` |
| Last Name | `User` |
| Email Verified | `true` |

## Step-by-Step Setup Walkthrough

### 1. Set Environment Variables

Create a `.env` file in `packages/foundry-auth/` (you can copy `docs/env.development` and replace `OIDC_CLIENT_SECRET`). On Windows without WSL, set variables via PowerShell (`$env:VAR = "value"`) instead of sourcing a `.env` file. See the [README](README.md#windows-powershell) for the full list.

```bash
OIDC_ISSUER=http://localhost:8080/realms/foundry
OIDC_CLIENT_ID=foundry-app
OIDC_CLIENT_SECRET=<your-client-secret-from-keycloak>
OIDC_CALLBACK_URL=http://localhost:8000/auth/callback
FRONTEND_URL=http://localhost:3000
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
SESSION_STORE_TYPE=sqlite
SESSION_STORE_PATH=./data/sessions.db
SECURE_COOKIES=false
```

### 2. Install the Package

From the repo root:

```bash
uv pip install -e packages/foundry-auth
```

### 3. Create a Minimal Python Application (call it main.py)

```python
from fastapi import FastAPI, Depends
from foundry_auth import AuthConfig, create_auth_router, create_require_session, get_session_store, SessionData

config = AuthConfig.from_env()
session_store = get_session_store()
app = FastAPI()

auth_router = create_auth_router(config=config, session_store=session_store)
app.include_router(auth_router)

require_session = create_require_session(config=config, session_store=session_store)

@app.get("/api/protected")
async def protected(session: SessionData = Depends(require_session)):
    return {"user": session.user_id, "expires_at": session.session_expires_at}
```

### 4. Run the Application

From `packages/foundry-auth/`:

```bash
# Create the data directory for SQLite session storage
mkdir -p data

# Activate the workspace venv
source ../../.venv/bin/activate

# Source env vars and start the server
set -a && source .env && set +a && uvicorn main:app --reload \
  --port 8000
```

### 5. Verify the Login Flow

1. Open `http://localhost:8000/auth/login` in your browser
2. You should be redirected to Keycloak's login page
3. Enter test credentials (`testuser` / `testpass`)
4. After login, the server redirects to your `FRONTEND_URL` (`http://localhost:3000`). If you don't have a frontend running, the browser will show a connection error — this is expected. The session cookie has already been set.
5. Navigate to `http://localhost:8000/auth/user` — you should see user info JSON confirming the session is active

## WebSocket Auth Patterns

WebSocket connections require session validation at connect time and periodic re-validation during the connection lifetime.

### Connection Flow

```
Client                    Server                    Session Store
  |                         |                           |
  |-- WS connect (sid) ---->|                           |
  |                         |-- get_session(sid) ------>|
  |                         |<-- SessionData -----------|
  |<-- accept() ------------|                           |
  |                         |                           |
  |== messages flow ========|                           |
  |                         |                           |
  |                         |-- periodic validation --->|
  |                         |<-- session valid/expired -|
  |                         |                           |
  |<-- close(1008) ---------|  (if session expired)     |
```

### Session Validation Task Example

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from foundry_auth import AuthConfig, get_session_store
from foundry_auth.websocket import (
    register_connection,
    unregister_connection,
    start_session_validation_task,
)

app = FastAPI()
session_store = get_session_store()

@app.on_event("startup")
async def startup():
    await start_session_validation_task(session_store)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, sid: str):
    session = session_store.get_session(sid)
    if not session:
        await websocket.close(code=1008, reason="Invalid session")
        return

    await websocket.accept()
    try:
        register_connection(sid, websocket)
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        pass
    finally:
        unregister_connection(sid, websocket)
```

### Verify WebSocket Auth

1. Install `wscat`:
   ```bash
   npm install -g wscat
   ```
2. Add the WebSocket endpoint above to the existing `main.py`
   (do not replace the file — keep the auth routes).
3. Restart uvicorn:
   ```bash
   set -a && source .env && set +a && \
     uvicorn main:app --reload --port 8000
   ```
4. Get your session ID from the browser (Application tab,
   Cookies, copy `sid`) or query the database:
   ```bash
   sqlite3 data/sessions.db \
     "SELECT session_id FROM sessions LIMIT 1;"
   ```
5. Connect with a valid session:
   ```bash
   wscat -c "ws://localhost:8000/ws?sid=<your-sid>"
   ```
6. Type a message and verify you get `Echo: <your message>` back.
7. Test rejection with an invalid session:
   ```bash
   wscat -c "ws://localhost:8000/ws?sid=invalid-session-id"
   ```
8. Expected: connection is rejected with HTTP 403 (the WebSocket
   handshake is denied before it completes).

Environment variables for WebSocket management:

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBSOCKET_SESSION_CHECK_INTERVAL_SECONDS` | `300` | Seconds between periodic session checks |
| `WEBSOCKET_MAX_CONNECTION_SECONDS` | `3600` | Max connection lifetime before forced close |

## Troubleshooting

### Token Exchange Fails (401)

**Symptom**: Login redirects to Keycloak successfully, but the callback returns a 500 with `httpx.HTTPStatusError: Client error '401 Unauthorized'` for the token endpoint.

**Fixes**:
- Verify `OIDC_CLIENT_SECRET` in your `.env` matches the value in Keycloak (Clients → foundry-app → Credentials)
- If you regenerated the secret in Keycloak, update `.env` and restart uvicorn

### Keycloak Unreachable

**Symptom**: `ConnectionRefusedError` or timeout when starting login flow.

**Fixes**:
- Verify Keycloak is running (from `packages/foundry-auth/`): `docker compose ps`
- Check the `OIDC_ISSUER` URL is accessible: `curl http://localhost:8080/realms/foundry/.well-known/openid-configuration`
- Ensure port 8080 is not blocked by another process

### Callback URL Mismatch

**Symptom**: "Invalid redirect URI" error from Keycloak after login.

**Fixes**:
- Ensure `OIDC_CALLBACK_URL` exactly matches the "Valid Redirect URIs" in your Keycloak client settings
- Check for trailing slashes — `http://localhost:8000/auth/callback` ≠ `http://localhost:8000/auth/callback/`
- Use `localhost`, not `0.0.0.0` or `127.0.0.1`, unless that's what you registered

### Missing Environment Variables

**Symptom**: `ValueError: Missing required environment variables: OIDC_ISSUER, ...`

**Fixes**:
- Verify all required variables are exported: `env | grep OIDC`
- If using a prefix, ensure it's consistent: `AuthConfig.from_env(prefix="MY_")` reads `MY_OIDC_ISSUER`
- Check for typos in variable names

### CORS Errors

**Symptom**: Browser console shows "Access to fetch has been blocked by CORS policy".

**Fixes**:
- Add your frontend origin to `CORS_ALLOWED_ORIGINS` (include protocol and port)
- Ensure no trailing slashes in origin URLs
- Restart the server after changing environment variables

### Cookie Issues

**Symptom**: Login succeeds but session is lost on next request / page refresh.

**Fixes**:
- For local HTTP development, set `SECURE_COOKIES=false` (secure cookies require HTTPS)
- Verify frontend and API are on the same domain (or configure cookie domain)
- Check browser dev tools → Application → Cookies to confirm `sid` cookie is set
- If using a proxy, ensure it forwards cookies correctly

### Account Not Fully Set Up (Keycloak 26+)

**Symptom**: `"error":"invalid_grant","error_description":"Account is not fully set up"` when attempting to log in, even though `requiredActions` is empty on the user.

**Fixes**:
- Ensure the user has **first name** and **last name** set (Keycloak 26 treats these as required for a complete profile)
- Ensure **Email verified** is enabled on the user
- After fixing, reset the password again via the Credentials tab (or the admin API) to clear any stale credential state

Via the admin API:
```bash
# Get an admin token
ADMIN_TOKEN=$(curl -sf -X POST http://localhost:8080/realms/master/protocol/openid-connect/token \
  -d "client_id=admin-cli&grant_type=password&username=admin&password=admin" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Get user ID
USER_ID=$(curl -sf "http://localhost:8080/admin/realms/foundry/users?username=testuser" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")

# Fix the user profile
curl -sf -X PUT "http://localhost:8080/admin/realms/foundry/users/$USER_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"firstName": "Test", "lastName": "User", "emailVerified": true}'

# Reset password
curl -sf -X PUT "http://localhost:8080/admin/realms/foundry/users/$USER_ID/reset-password" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"type": "password", "value": "testpass", "temporary": false}'
```

## Teardown

When you're done, shut down the services this guide had you start:

### Stop the Uvicorn Dev Server

If running in the foreground, press `Ctrl+C` in the terminal where `uvicorn main:app --reload --port 8000` is running.

### Stop Keycloak

From `packages/foundry-auth/`:

```bash
docker compose down
```

This stops and removes the Keycloak container. Add `-v` to also remove the named volume (deletes all realm/user data):

```bash
docker compose down -v
```

### Clean Up Session Data

Remove the SQLite session database created during development:

```bash
rm -rf data/
```

## See Also

- [Integration Guide](docs/INTEGRATION_GUIDE.md) — Add auth to any FastAPI service in 3 lines
- [Security guide](docs/SECURITY.md) — Production secret management and best practices
- [README](README.md) — Full API reference
