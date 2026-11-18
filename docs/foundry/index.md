---
sidebar_position: 1
---

# Overview

Shared Python packages consumed by Foundry-built AI agents.

`foundry-agent-packages` is a uv-workspace monorepo of the libraries that
composition roots like [`strands-base-agent`](https://github.com/boozallen/strands-base-agent) install and extend. Each package
is independently versioned and ships as a wheel attached to a GitHub Release;
adopters host the wheels in their own internal index. This repo is **library
code** — back-compat and clear API boundaries matter because every change
flows downstream to real agents.

## Packages

| Package | Purpose | Depends on |
|---------|---------|------------|
| [`foundry-agent-core`](./packages/foundry-agent-core/index.md) | DI container, protocols, types, exceptions, lifecycle, masking/redaction | _(none)_ |
| [`foundry-agent-config`](./packages/foundry-agent-config/index.md) | YAML loader with env-var overrides (double-underscore nesting), bounded input controls | _(none)_ |
| [`foundry-agent-fastapi`](./packages/foundry-agent-fastapi/index.md) | CORS / error / logging middleware, request/response models, mappers, health router | `foundry-agent-core` |
| [`foundry-strands-agent`](./packages/foundry-strands-agent/index.md) | AWS Strands SDK adapter — `StrandsAgentBackend`, factory, orchestrator, tool loader, chat historian | `foundry-agent-core`, `foundry-agent-config` |
| [`foundry-aws-utilities`](./packages/foundry-aws-utilities/index.md) | DynamoDB, S3, and Bedrock Knowledge Base MCP servers | _(none)_ |
| [`foundry-auth`](./packages/foundry-auth/index.md) | OIDC authentication — authorization-code + PKCE flow, session storage, FastAPI router factory | `foundry-agent-core` |

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

## Security posture

Command-injection sinks (STIG V-222604) are gated by Ruff
`S102`/`S307`/`S602–S607` plus a narrow `bandit -t B602,B603,B605,B607` set —
both run by `just lint` locally, and the bandit set again independently in CI.
`bandit`'s broader rule set runs ad-hoc; `vulture` (`just dead-code`) and
`deptry` are installed for advisory use only.

## Where to go next

- **[Quickstart](./getting-started/quickstart.md)** — install the workspace, run `just check`, build a wheel
- **[Local development](./getting-started/local-development.md)** — daily workflow, per-package recipes, consuming local packages from another repo
- **[Packages](./packages/index.md)** — one-line summary of each package and a link to its README
- **[Adopting these packages](./releases/adopting.md)** — how to consume the wheels from a downstream repo
