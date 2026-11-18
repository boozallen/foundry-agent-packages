# Security Documentation

Security considerations and best practices for foundry-auth deployments.

## Development Secrets Warning

> **CRITICAL: The following secrets are for local development only.**
>
> - `OIDC_CLIENT_SECRET` — OAuth client secret
> - Keycloak admin password (`admin`/`admin`)
> - Test user credentials (`testuser`/`testpass`)
>
> **Never deploy these values to staging, production, or any shared environment.**
> Never commit secrets to version control. Never share them via chat, email, or tickets.

> **Note**: `OIDC_CALLBACK_URL` may reveal internal URLs but is not a secret. Avoid exposing it publicly, but it does not require secrets manager storage.

## Secret Management Recommendations

### Production Cookie Security

Set `SECURE_COOKIES=true` in production. This ensures session cookies are only transmitted over HTTPS. The default is `true`, but verify it is not overridden in your deployment configuration.

### Use a Secrets Manager

Store all production secrets in a dedicated secrets management system:

- **AWS Secrets Manager** or **AWS SSM Parameter Store**
- **HashiCorp Vault**
- **Azure Key Vault**
- **GCP Secret Manager**

Inject secrets at runtime via environment variables populated by your deployment platform (ECS task definitions, Kubernetes secrets, etc.), not via `.env` files on disk.

### Rotation Policy

| Secret | Rotation Frequency | Notes |
|--------|-------------------|-------|
| `OIDC_CLIENT_SECRET` | Every 90 days | Use your OIDC provider's recommended schedule; 90 days is a generic baseline |
| Database credentials | Every 90 days | Use connection poolers that support rotation |

### Environment Separation

Maintain completely separate credentials for each environment:

| Environment | OIDC Provider | Client ID | Session Store |
|-------------|---------------|-----------|---------------|
| Development | Local Keycloak | `foundry-dev` | SQLite (local) |
| Staging | Staging IdP | `foundry-staging` | SQLite (staging) |
| Production | Production IdP | `foundry-prod` | SQLite (production) |

> **Note:** SQLite session storage does not support multiple replicas sharing one database. Run a single replica per session database. Running more than one replica needs a shared session store such as Redis, which this package does not support yet.

Never reuse client secrets, database credentials, or signing keys across environments.

## Anti-Patterns

### Committing Secrets to Version Control

```bash
# NEVER do this
echo 'OIDC_CLIENT_SECRET=real-secret-value' >> .env
git add .env
git commit -m "add config"
```

**Why it's dangerous**: Git history is permanent. Even after removing the file, the secret remains in commit history and may be in developer clones, backups, and CI caches.

**Instead**: Use `.env.example` with placeholder values. Add `.env` to `.gitignore`. Use a secrets manager for real values.

### Sharing Secrets via Chat or Email

Slack messages, Teams chats, emails, and Jira tickets are not secure channels for secrets. They persist in search indexes, backups, and third-party integrations.

**Instead**: Use your secrets manager's sharing features, or share via time-limited secure links (e.g., Vault's wrapping tokens).

### Reusing Secrets Across Environments

Using the same `OIDC_CLIENT_SECRET` in dev and production means a compromise of the dev environment immediately compromises production.

**Instead**: Generate unique secrets per environment. Rotate independently.

## CORS Configuration Security

### Wildcard Dangers

```bash
# DANGEROUS — allows any origin to make authenticated requests
export CORS_ALLOWED_ORIGINS="*"
```

A wildcard CORS policy combined with cookie-based authentication allows any website to make authenticated API requests on behalf of your users (CSRF attacks bypass SameSite=Lax in some scenarios).

### Per-Environment Origins

Configure the minimum set of origins needed for each environment:

```bash
# Development — only local frontends
export CORS_ALLOWED_ORIGINS="http://localhost:3000,http://localhost:5173"

# Production — only your production domains
export CORS_ALLOWED_ORIGINS="https://app.yourcompany.com,https://admin.yourcompany.com"
```

### Validation Checklist

- [ ] No wildcards in production CORS configuration
- [ ] All origins use HTTPS in production
- [ ] No unnecessary origins (remove old/unused frontends)
- [ ] Origins match exactly (protocol + host + port, no trailing slash)

## Package Version Pinning

### Why It Matters

Unpinned dependencies can introduce breaking changes, security vulnerabilities, or incompatible behavior on any install:

```toml
# Risky — any minor/patch version could change behavior
dependencies = ["foundry-auth"]

# Safe — locked to known-good version
dependencies = ["foundry-auth==0.1.2"]
```

### How to Pin

In your `pyproject.toml`:

```toml
[project]
dependencies = [
    "foundry-auth==0.1.2",
]
```

Or use a lock file (`uv.lock`, `requirements.lock`) to pin the entire dependency tree.

### Checking for Updates

```bash
# Check for available updates
uv pip list --outdated

# Update to a specific version after reviewing changelog
uv pip install foundry-auth==0.1.3
```

Review changelogs before upgrading — security fixes should be applied promptly, but feature releases should be tested in staging first.

## WebSocket Session Security

### Validation Frequency

WebSocket connections are long-lived and bypass per-request session validation. The periodic validation task checks sessions at a configurable interval:

```bash
# Check every 5 minutes (default: 300 seconds)
export WEBSOCKET_SESSION_CHECK_INTERVAL_SECONDS=300
```

**Trade-off**: Lower intervals increase security (faster revocation) but add load to the session store. For high-security applications, consider 60–120 seconds.

### Maximum Connection Duration

Even with valid sessions, connections should not persist indefinitely:

```bash
# Force reconnection after 1 hour (default: 3600 seconds)
export WEBSOCKET_MAX_CONNECTION_SECONDS=3600
```

This limits the damage window if a session is compromised and ensures clients periodically re-authenticate.

### Revocation and Cleanup

When a session is revoked (logout, admin action, password change), associated WebSocket connections must be closed immediately:

```python
from foundry_auth.websocket import delete_session_and_close_connections

# Use this instead of session_store.delete_session()
await delete_session_and_close_connections(session_id, session_store)
```

This closes all active WebSocket connections for the session before deleting it from the store, ensuring no orphaned connections continue operating with a revoked session.

### Security Checklist

- [ ] `start_session_validation_task` called on application startup
- [ ] `WEBSOCKET_MAX_CONNECTION_SECONDS` set appropriately for your use case
- [ ] Logout/revocation uses `delete_session_and_close_connections`
- [ ] WebSocket endpoints validate session before accepting connections
- [ ] Unregister connections in `finally` blocks to prevent leaks

## See Also

- [AUTH_SETUP.md](../AUTH_SETUP.md) — Development setup guide
- [Integration Guide](INTEGRATION_GUIDE.md) — Adding auth to your service
- [Example env files](env.development) — Template configurations
