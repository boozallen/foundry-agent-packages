---
sidebar_position: 1
---

# Overview

Shared Python packages consumed by Foundry-built AI agents.

**Source:** [github.com/boozallen/foundry-agent-packages](https://github.com/boozallen/foundry-agent-packages)

`foundry-agent-packages` is a uv-workspace monorepo of the libraries that
composition roots like `strands-base-agent` install and extend. Each package
is independently versioned and ships as a wheel attached to a GitHub Release;
adopters host the wheels in their own internal index.

## Key features

- **Library code, not a fork-it template** — back-compat and clear API boundaries are first-class concerns because every change flows downstream to real agents
- **Independently versioned packages** — pick the subset you need; `foundry-agent-core` and `foundry-agent-config` have no in-repo dependencies
- **uv-workspace monorepo** — one `uv sync` installs all four packages in editable mode for cross-package development
- **Wheels published as GitHub Release assets**
- **STIG-aligned security posture** — per-package DISA ASD STIG checklists with command-injection sinks gated by Ruff + bandit in CI

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

Each package owns a DISA ASD STIG checklist under
`packages/<pkg>/security/`. Static analysis (Ruff + bandit) runs in
both `just lint` and CI to gate the highest-risk sinks; additional
tooling (broader `bandit`, `vulture`, `deptry`) is installed for
advisory use during package development.

## Where to go next

- **[Quickstart](./getting-started/quickstart.md)** — install the workspace, run `just check`, build a wheel
- **[Local development](./getting-started/local-development.md)** — daily workflow, per-package recipes, consuming local packages from another repo
- **[Packages](./packages/index.md)** — one-line summary of each package and a link to its README

## Proposing changes to these packages

These are library APIs — changes ripple downstream. For anything non-trivial
(new package, breaking signature change, new middleware), it's worth writing
a proposal first. See [Spec-Driven Extensions with OpenSpec](/docs/guides/spec-driven-extensions)
for the workflow we use.
