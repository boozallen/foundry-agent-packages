# foundry-agent-fastapi

![Status: Available](https://img.shields.io/badge/status-available-brightgreen)
![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

Reusable FastAPI middleware, health-check endpoint, API models, and
mappers for agent services built on `foundry-agent-core`. Provides CORS,
error handling, and request logging with correlation-ID tracking; maps
HTTP DTOs to and from domain types.

## Install

```bash
uv add foundry-agent-fastapi
# or
pip install foundry-agent-fastapi
```

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

# Order matters — outermost first
add_request_logging_middleware(app)
add_error_handling_middleware(app)
add_cors_middleware(app)

app.include_router(health_router)  # GET /api/v1/health
```

## What's in the box

| Surface | Highlights |
|---------|------------|
| Middleware | `add_cors_middleware`, `add_error_handling_middleware`, `add_request_logging_middleware` |
| Domain → HTTP error mapping | `ValidationError` → 400, `ResourceNotFoundError` → 404, `ExternalServiceError` → 502, `DomainError` → 500 |
| API models | `QueryAPIRequest`, `QueryAPIResponse`, `ErrorResponse` |
| Mappers | `api_request_to_domain`, `domain_response_to_api`, `domain_error_to_api_response` |
| Health router | `health_router` mounts `GET /api/v1/health` |
| Correlation IDs | `generate_correlation_id()` → `req_<8hex>` |

CORS is configured via env vars: `STRANDS_CORS_ORIGINS`, `STRANDS_CORS_METHODS`,
`STRANDS_CORS_HEADERS`.

## Security

`QueryAPIRequest.session_id` is validated against `^[A-Za-z0-9_-]{8,128}$`;
invalid IDs return HTTP 422 (DISA STIG V-222609). See the
[STIG checklist](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-fastapi/security/stig_checklist.json).

## Reference

- [README](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-fastapi/README.md)
- [Changelog](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-fastapi/CHANGELOG.md)
- [Source](https://github.com/boozallen/foundry-agent-packages/tree/main/packages/foundry-agent-fastapi)
- [License (Apache-2.0)](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-fastapi/LICENSE)
