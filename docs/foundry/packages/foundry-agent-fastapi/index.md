# foundry-agent-fastapi

![Status: Available](https://img.shields.io/badge/status-available-brightgreen)
![Version](https://img.shields.io/badge/version-1.2.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

Reusable FastAPI middleware, health-check endpoint, API models, and
mappers for agent services built on `foundry-agent-core`. Provides CORS,
error handling, and request logging with correlation-ID tracking; maps
HTTP DTOs to and from domain types.

## Install

Install a released wheel from this repo's
[GitHub Releases](https://github.com/boozallen/foundry-agent-packages/releases).
See [docs/foundry/releases/adopting.md](../../releases/adopting.md) for
the full flow - pinning a release URL directly for evaluation, or
hosting the wheel in your own index for production, plus verifying the
SBOM/scan assets.

## Quickstart

```python
from fastapi import FastAPI
from foundry_agent_fastapi import (
    add_cors_middleware,
    add_error_handling_middleware,
    add_request_logging_middleware,
    health_router,
)

app = FastAPI()

# Registration order matters: the LAST middleware registered is the outermost.
add_request_logging_middleware(app)  # innermost — closest to the route handler
add_error_handling_middleware(app)   # middle
add_cors_middleware(app)             # outermost — sees the request first

app.include_router(health_router)  # GET /api/v1/health
```

Each `add_*_middleware` call inserts at the **front** of Starlette's middleware
list, and the stack is built by wrapping that list in reverse — so the last
registration ends up outermost. The outermost middleware sees the request
first and writes the response last; the innermost runs closest to the route
handler.

## What's in the box

| Surface | Highlights |
|---------|------------|
| Middleware | `add_cors_middleware`, `add_error_handling_middleware`, `add_request_logging_middleware` |
| Domain to HTTP error mapping | `ValidationError` to 400, `ExternalServiceError` to 502, all other `DomainError` to 500 |
| API models | `QueryAPIRequest`, `QueryAPIResponse`, `ErrorResponse` |
| Mappers | `api_request_to_domain`, `domain_response_to_api`, `domain_error_to_api_response` |
| Health router | `health_router` mounts `GET /api/v1/health` |
| Correlation IDs | `generate_correlation_id()` produces `req_<8hex>` |

CORS is configured via env vars: `STRANDS_CORS_ORIGINS`,
`STRANDS_CORS_ALLOW_METHODS`, `STRANDS_CORS_ALLOW_HEADERS`.

## Security

`QueryAPIRequest.session_id` is validated against pattern
`^[A-Za-z0-9_-]+$` with 8-128 character length constraints; invalid IDs
return HTTP 422 (DISA STIG V-222609).

## Reference

- [README](https://github.com/boozallen/foundry-agent-packages/blob/develop/packages/foundry-agent-fastapi/README.md)
- [Changelog](https://github.com/boozallen/foundry-agent-packages/blob/develop/packages/foundry-agent-fastapi/CHANGELOG.md)
- [Source](https://github.com/boozallen/foundry-agent-packages/tree/main/packages/foundry-agent-fastapi)
- [License (Apache-2.0)](https://github.com/boozallen/foundry-agent-packages/blob/develop/LICENSE)
