---
sidebar_position: 1
---

# Packages

Six independently versioned packages live under [`packages/`](../../../packages/). Each ships
its own wheel and CHANGELOG; consumers pick the subset they need.

The open-source copy of this repository can lag behind this page. Any package
listed here but missing from the open-source copy arrives with the next
open-source release.

## [`foundry-agent-core`](./foundry-agent-core/index.md)

DI container, protocol definitions, type primitives, exception hierarchy,
agent lifecycle, masking/redaction helpers. **No runtime dependencies on
other packages in this repo.**

- [README](../../../packages/foundry-agent-core/README.md)
- [CHANGELOG](../../../packages/foundry-agent-core/CHANGELOG.md)

## [`foundry-agent-config`](./foundry-agent-config/index.md)

YAML configuration loader with environment-variable overrides (double-underscore
nesting), bounded input controls, and Pydantic-based schema validation. **No
runtime dependencies on other packages in this repo.**

- [README](../../../packages/foundry-agent-config/README.md)
- [CHANGELOG](../../../packages/foundry-agent-config/CHANGELOG.md)

## [`foundry-agent-fastapi`](./foundry-agent-fastapi/index.md)

CORS / error / logging middleware, request/response models, mappers between
domain types and HTTP DTOs, a health router. **Depends on:** `foundry-agent-core`.

- [README](../../../packages/foundry-agent-fastapi/README.md)
- [CHANGELOG](../../../packages/foundry-agent-fastapi/CHANGELOG.md)

## [`foundry-strands-agent`](./foundry-strands-agent/index.md)

AWS Strands SDK adapter — `StrandsAgentBackend`, factory, orchestrator, tool
loader, chat historian. **Depends on:** `foundry-agent-core`, `foundry-agent-config`.

- [README](../../../packages/foundry-strands-agent/README.md)
- [CHANGELOG](../../../packages/foundry-strands-agent/CHANGELOG.md)

## [`foundry-aws-utilities`](./foundry-aws-utilities/index.md)

DynamoDB, S3, and [Bedrock Knowledge Base](https://aws.amazon.com/bedrock/knowledge-bases/) MCP servers. **No runtime
dependencies on other packages in this repo.**

- [README](../../../packages/foundry-aws-utilities/README.md)
- [CHANGELOG](../../../packages/foundry-aws-utilities/CHANGELOG.md)

## [`foundry-auth`](./foundry-auth/index.md)

OIDC authentication — authorization-code + PKCE flow, protocol-based
session storage (SQLite implemented, Redis planned), a FastAPI
router factory, auth dependencies, and WebSocket session validation.
**Depends on:** `foundry-agent-core`.

- [README](../../../packages/foundry-auth/README.md)
- [CHANGELOG](../../../packages/foundry-auth/CHANGELOG.md)

## Dependency graph

```
foundry-agent-core ←── foundry-agent-fastapi
       ↑          ↑
       │          └──────── foundry-auth
       ├──────────────── foundry-strands-agent
       │                        ↑
       │                        │
foundry-agent-config ───────────┘

foundry-aws-utilities (standalone - no dependents here)
```

Every arrow is a hard runtime dependency. `foundry-agent-core`,
`foundry-agent-config`, and `foundry-aws-utilities` are leaves; consumers
that only need configuration loading can install `foundry-agent-config`
standalone, and consumers that only need the DI container can install
`foundry-agent-core` standalone.
