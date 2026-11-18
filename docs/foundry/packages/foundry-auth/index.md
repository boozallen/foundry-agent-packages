# foundry-auth

![Status: Available](https://img.shields.io/badge/status-available-brightgreen)
![Version](https://img.shields.io/badge/version-0.3.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

OIDC authentication for Foundry agents: authorization-code + PKCE flow,
protocol-based session storage (SQLite implemented, Redis planned),
a FastAPI router factory, auth dependencies, and WebSocket session
validation. **Depends on:** [`foundry-agent-core`](../foundry-agent-core/index.md).

## Install

Install a released wheel from this repo's
[GitHub Releases](https://github.com/boozallen/foundry-agent-packages/releases).
See [Adopting these packages](../../releases/adopting.md) for
the full flow - pinning a release URL directly for evaluation, or
hosting the wheel in your own index for production, plus verifying the
SBOM/scan assets.

## Quickstart

```python
from fastapi import Depends, FastAPI
from foundry_auth import AuthConfig, SessionData, create_auth_router, create_require_session, get_session_store

app = FastAPI()
config = AuthConfig.from_env()
session_store = get_session_store(config)

app.include_router(create_auth_router(config=config, session_store=session_store))
require_session = create_require_session(config=config, session_store=session_store)

@app.get("/profile")
async def profile(session: SessionData = Depends(require_session)):
    return {"user_id": session.user_id}
```

See [AUTH_SETUP.md](../../../../packages/foundry-auth/AUTH_SETUP.md)
for a full walkthrough including Keycloak setup, and the
[Integration Guide](../../../../packages/foundry-auth/docs/INTEGRATION_GUIDE.md)
for adding auth to an existing FastAPI service in three lines of code.

## What's in the box

| Surface | Highlights |
|---------|------------|
| [OIDC flow](../../../../packages/foundry-auth/src/foundry_auth/oidc.py) | Authorization-code + PKCE, prefix-based configuration for multiple service configs |
| [Session storage](../../../../packages/foundry-auth/src/foundry_auth/session.py) | `SessionStore` protocol, `SQLiteSessionStore` (implemented), `RedisSessionStore` (stub) |
| [FastAPI integration](../../../../packages/foundry-auth/src/foundry_auth/routers.py) | `create_auth_router`, `create_require_session`, `create_optional_session` |
| [WebSocket support](../../../../packages/foundry-auth/src/foundry_auth/websocket.py) | `register_connection`, session validation loop, connection cleanup on session expiry/deletion |

## Security

- **Tokens encrypted at rest**: OAuth access/refresh tokens and the
  captured OIDC `id_token` are encrypted in SQLite using Fernet
  (AES-128-CBC + HMAC-SHA256); `SESSION_ENCRYPTION_KEY` is required at
  startup.
- **Session ID rotation and masking**: session IDs are rotated on
  refresh and redacted in log output.
- **CSRF protection**: OAuth state is bound to the initiating browser.
- **Open-redirect protection**: `sanitize_redirect_path` rejects
  absolute URLs, protocol-relative paths, and control characters
  (including CR/LF) in the `returnTo` parameter.

See the package's
[Security guide](../../../../packages/foundry-auth/docs/SECURITY.md)
for the full control list.

## Reference

- [README](../../../../packages/foundry-auth/README.md)
- [Changelog](../../../../packages/foundry-auth/CHANGELOG.md)
- [Source](../../../../packages/foundry-auth/)
- [License (Apache-2.0)](../../../../LICENSE)
