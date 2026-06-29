# foundry-agent-core

![Status: Available](https://img.shields.io/badge/status-available-brightgreen)
![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

Framework-agnostic agent infrastructure: dependency-injection container,
protocol surface, exception hierarchy, request/response types, and
lifecycle primitives. Zero coupling to any specific agent framework.

## Install

```bash
uv add foundry-agent-core
# or
pip install foundry-agent-core
```

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
| Exceptions | `DomainError` and a typed hierarchy (`ConfigurationError`, `AgentCreationError`, `ExternalServiceError`, `ToolExecutionError`, `QueryTimeoutError`, …) |

## Security

Session IDs in `AgentRequest`/`AgentResponse` must match
`^[A-Za-z0-9_-]{8,128}$` (DISA STIG V-222609). Invalid IDs raise
`ValidationError` at model construction. See the
[STIG checklist](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-core/security/stig_checklist.json)
for the full control list.

## Reference

- [README](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-core/README.md)
- [Changelog](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-core/CHANGELOG.md)
- [Source](https://github.com/boozallen/foundry-agent-packages/tree/main/packages/foundry-agent-core)
- [License (Apache-2.0)](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-core/LICENSE)
