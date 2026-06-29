# foundry-agent-packages

![Status: Available](https://img.shields.io/badge/status-available-brightgreen)
![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

A uv-workspace monorepo of the shared Python libraries that Foundry-built
agents install and extend. Each package is independently versioned and
ships as a wheel attached to a GitHub Release; adopters host the wheels
in their own internal index. Composition roots like `strands-base-agent`
wire these libraries into a runnable service — they do not re-implement
what lives here.

## Packages

| Package | Purpose | Depends on |
|---------|---------|------------|
| [`foundry-agent-core`](packages/foundry-agent-core) | DI container, protocols, types, exceptions, lifecycle | _(none)_ |
| [`foundry-agent-config`](packages/foundry-agent-config) | YAML loader with env-var overrides, bounded input controls | _(none)_ |
| [`foundry-agent-fastapi`](packages/foundry-agent-fastapi) | CORS / error / logging middleware, request models, health router | `foundry-agent-core` |
| [`foundry-strands-agent`](packages/foundry-strands-agent) | AWS Strands SDK adapter — backend, factory, orchestrator, tool loader | `foundry-agent-core`, `foundry-agent-config` |

```
foundry-agent-core ◄── foundry-agent-fastapi
       ▲
       ├──────────────── foundry-strands-agent
       │                        ▲
foundry-agent-config ───────────┘
```

## Requirements

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/)
- [just](https://github.com/casey/just)

## Quick Start

```bash
just setup           # uv sync + pre-commit install
just check           # ruff + bandit narrow set + format check + basedpyright
just test            # full test suite across all packages
```

Per-package commands:

```bash
just test-pkg foundry-agent-core      # test a single package
just check-pkg foundry-agent-core     # lint + format + type-check + test, one package
just build foundry-agent-core         # build a single wheel
```

## Documentation

| If you want to… | Read |
|---|---|
| Install the workspace and build a wheel | [Quickstart](docs/foundry/getting-started/quickstart.md) |
| Run the daily developer loop | [Local development](docs/foundry/getting-started/local-development.md) |
| Understand the codebase (layout, packages, conventions) | [AGENTS.md](AGENTS.md) |
| See per-package summaries | [Packages](docs/foundry/packages/index.md) |
| Consume these packages from a downstream repo | [Adopting](docs/foundry/releases/adopting.md) |
| Understand the security posture and STIG checklists | Each package's `security/stig_checklist.json` |
| Contribute changes | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Release model

Releases ship as GitHub Releases — adopters host the wheels in their own
internal index (no public PyPI yet).

- PRs to `develop` → CI runs (lint, type-check, test, dry-run build, bandit narrow set)
- PRs to `main` → release validation runs
- Tag a release on `main` → builds wheels + Syft SBOM + Grype scan per
  changed package and attaches them to the GitHub Release

See [docs/foundry/releases/release-channels.md](docs/foundry/releases/release-channels.md)
for internal RC/dev publishing and [docs/foundry/releases/adopting.md](docs/foundry/releases/adopting.md)
for the adopter flow.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
