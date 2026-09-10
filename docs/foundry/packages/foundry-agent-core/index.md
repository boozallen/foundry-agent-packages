# foundry-agent-core

![Status: Available](https://img.shields.io/badge/status-available-brightgreen)
![Version](https://img.shields.io/badge/version-1.2.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

Framework-agnostic agent infrastructure: dependency-injection container,
protocol surface, exception hierarchy, request/response types, and
lifecycle primitives. Zero coupling to any specific agent framework.

## Install

Install a released wheel from this repo's
[GitHub Releases](https://github.com/boozallen/foundry-agent-packages/releases).
See [docs/foundry/releases/adopting.md](../../releases/adopting.md) for
the full flow - pinning a release URL directly for evaluation, or
hosting the wheel in your own index for production, plus verifying the
SBOM/scan assets.

## Quickstart

```python
from foundry_agent_core import (
    AgentRequest,
    AgentResponse,
    create_dependency_container,
)

container = create_dependency_container()
container.register_factory(MyService, my_service_factory, singleton=True)

service = container.resolve(MyService)
request = AgentRequest(session_id="user-session-01", query="Hello")
```

## What's in the box

| Surface | Highlights |
|---------|------------|
| DI container | `create_dependency_container()`, scoped resolution, cycle detection, startup validation |
| Protocols | `AgentBackend`, `QueryProcessor`, `ResponseProcessor`, `ErrorTranslator`, `DependencyContainer` |
| Types | `AgentRequest`, `AgentResponse` (Pydantic v2, frozen) |
| Exceptions | `DomainError` and a typed hierarchy (`ConfigurationError`, `AgentCreationError`, `ExternalServiceError`, `ToolExecutionError`, `QueryTimeoutError`) |
| Encryption | `encrypt`, `decrypt`, `is_encrypted`, `load_encryption_key` (AES-256-GCM) |
| Masking | `mask_session_id`, `redact_session_ids` for log sanitization |

## Security

Session IDs in `AgentRequest`/`AgentResponse` must match pattern
`^[A-Za-z0-9_-]+$` with 8-128 character length constraints
(DISA STIG V-222609). Invalid IDs raise `ValidationError` at model
construction. Input-size bounds enforce
resource limits (DISA STIG V-222612).

## Reference

- [README](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-core/README.md)
- [Changelog](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-core/CHANGELOG.md)
- [Source](https://github.com/boozallen/foundry-agent-packages/tree/main/packages/foundry-agent-core)
- [License (Apache-2.0)](https://github.com/boozallen/foundry-agent-packages/blob/main/LICENSE)
