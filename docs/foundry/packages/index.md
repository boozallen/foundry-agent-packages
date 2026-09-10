---
sidebar_position: 1
---

# Packages

Four independently versioned packages live under `packages/`. Each ships
its own wheel and CHANGELOG; consumers pick the subset they need.

## `foundry-agent-core`

DI container, protocol definitions, type primitives, exception hierarchy,
agent lifecycle, masking/redaction helpers. **No runtime dependencies on
other packages in this repo.**

- [README](../../../packages/foundry-agent-core/README.md)
- [CHANGELOG](../../../packages/foundry-agent-core/CHANGELOG.md)

## `foundry-agent-config`

YAML configuration loader with environment-variable overrides (double-underscore
nesting), bounded input controls, and Pydantic-based schema validation. **No
runtime dependencies on other packages in this repo.**

- [README](../../../packages/foundry-agent-config/README.md)
- [CHANGELOG](../../../packages/foundry-agent-config/CHANGELOG.md)

## `foundry-agent-fastapi`

CORS / error / logging middleware, request/response models, mappers between
domain types and HTTP DTOs, a health router. **Depends on:** `foundry-agent-core`.

- [README](../../../packages/foundry-agent-fastapi/README.md)
- [CHANGELOG](../../../packages/foundry-agent-fastapi/CHANGELOG.md)

## `foundry-strands-agent`

AWS Strands SDK adapter — `StrandsAgentBackend`, factory, orchestrator, tool
loader, chat historian. **Depends on:** `foundry-agent-core`, `foundry-agent-config`.

- [README](../../../packages/foundry-strands-agent/README.md)
- [CHANGELOG](../../../packages/foundry-strands-agent/CHANGELOG.md)

## Dependency graph

```
foundry-agent-core ←── foundry-agent-fastapi
       ↑
       ├──────────────── foundry-strands-agent
       │                        ↑
foundry-agent-config ───────────┘
```

Every arrow is a hard runtime dependency. `foundry-agent-core` and
`foundry-agent-config` are leaves; consumers that only need configuration
loading can install `foundry-agent-config` standalone, and consumers that
only need the DI container can install `foundry-agent-core` standalone.
