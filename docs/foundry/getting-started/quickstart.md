---
sidebar_position: 1
---

# Quickstart

Get the workspace installed and verified in under five minutes. This page is
for **contributors** to this repo. If you want to consume the published
wheels from a downstream agent, see
[Adopting these packages](../releases/adopting.md).

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
just check    # full gate: ruff lint + ruff format check + basedpyright + tests
just test     # pytest looped per package, with a summary table
```

Both should be clean against `develop`. A successful run looks like:

- `just check` — no findings; basedpyright reports `0 errors, 0 warnings, 0 informations`,
  followed by a per-package summary table with all four packages `PASS` and every
  package meeting its 70% coverage gate
- `just test` — the same suite; skips and warnings are expected, failures are not

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

Confirm a built wheel actually installs and imports:

```bash
uv pip install packages/foundry-agent-core/dist/*.whl
uv run python -c "import foundry_agent_core"
```

## Where to go next

- **[Local development](./local-development.md)** — daily workflow, per-package `just` recipes, consuming a local package from a sibling repo
- **[Release channels](../releases/release-channels.md)** — RC vs. stable vs. manual dev builds
