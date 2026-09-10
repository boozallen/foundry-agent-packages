---
sidebar_position: 1
---

# Overview

Shared Python packages consumed by Foundry-built AI agents.

`foundry-agent-packages` is a uv-workspace monorepo of the libraries that
composition roots like `strands-base-agent` install and extend. Each package
is independently versioned and ships as a wheel attached to a GitHub Release;
adopters host the wheels in their own internal index. This repo is **library
code** — back-compat and clear API boundaries matter because every change
flows downstream to real agents.

## Packages

| Package | Purpose | Depends on |
|---------|---------|------------|
| `foundry-agent-core` | DI container, protocols, types, exceptions, lifecycle, masking/redaction | _(none)_ |
| `foundry-agent-config` | YAML loader with env-var overrides (double-underscore nesting), bounded input controls | _(none)_ |
| `foundry-agent-fastapi` | CORS / error / logging middleware, request/response models, mappers, health router | `foundry-agent-core` |
| `foundry-strands-agent` | AWS Strands SDK adapter — `StrandsAgentBackend`, factory, orchestrator, tool loader, chat historian | `foundry-agent-core`, `foundry-agent-config` |

```
foundry-agent-core ←── foundry-agent-fastapi
       ↑
       ├──────────────── foundry-strands-agent
       │                        ↑
foundry-agent-config ───────────┘
```

## Security posture

Command-injection sinks are gated by Ruff plus a narrow `bandit` set. Both run locally and in CI.
`bandit`'s broader rule set runs ad-hoc; `vulture` (`just dead-code`) and `deptry` are installed for advisory use only.

## Where to go next

- **[Quickstart](./getting-started/quickstart.md)** — install the workspace, run `just check`, build a wheel
- **[Local development](./getting-started/local-development.md)** — daily workflow, per-package recipes, consuming local packages from another repo
- **[Packages](./packages/index.md)** — one-line summary of each package and a link to its README
- **[Adopting these packages](./releases/adopting.md)** — how to consume the wheels from a downstream repo
- **[Release channels](./releases/release-channels.md)** — RC vs. stable vs. manual dev builds (pre-OSS legacy; see adopting.md for the GitHub-Release flow)
