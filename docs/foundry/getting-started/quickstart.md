---
sidebar_position: 1
---

# Quickstart

Get the workspace installed and verified in under five minutes. This page is
for **contributors** to this repo.

## Prerequisites

- Python 3.13 (the floor for every package in this repo)
- [uv](https://docs.astral.sh/uv/) >= 0.8
- [just](https://github.com/casey/just) command runner

## Install

1. Clone the repository:

   ```bash
   git clone <repo-url>
   cd foundry-agent-packages
   ```

2. Install the workspace + pre-commit hooks:

   ```bash
   just setup
   ```

   This runs `uv sync` (installs all four packages in editable mode plus the
   dev dependency group) and `pre-commit install`.

## Verify

Run the full local gate:

```bash
just check    # ruff + bandit narrow set + ruff format + basedpyright
just test     # pytest across all packages
```

Both should be clean against `develop`. A successful run looks like:

- `just check` — no findings; basedpyright reports `0 errors, 0 warnings, 0 informations`
- `just test` — 530+ tests pass; 1 skipped is expected (intentional)

If `just check` fails on a clean clone, the most likely cause is a stale
`uv.lock` against a newer dev-deps floor; re-run `just setup`.

## Build a wheel

```bash
just build foundry-agent-core    # one package
just build-all                   # all four
```

Wheels land under `packages/<pkg>/dist/`. Per-package version bumps go
through `scripts/bump_version.py`:

```bash
just version-patch foundry-agent-core    # 0.2.4 → 0.2.5
just version-minor foundry-agent-config
just version-set foundry-agent-fastapi 0.3.0
```

## Where to go next

- **[Local development](./local-development.md)** — daily workflow, per-package `just` recipes, consuming a local package from a sibling repo
