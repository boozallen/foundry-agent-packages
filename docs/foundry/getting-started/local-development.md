---
sidebar_position: 2
---

# Local Development

## Prerequisites

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/) >= 0.5.0
- [just](https://github.com/casey/just) (command runner)

## Setup

Clone the repository and install all workspace packages with dev dependencies:

```bash
git clone <repo-url>
cd foundry-agent-packages
uv sync --all-groups
```

This installs all five workspace packages in editable mode plus the dev
dependency group (pytest, ruff, pyright).

## Development Workflow

### Running Tests

```bash
just test                            # all packages, no coverage gate
just test-pkg foundry-agent-core     # single package — enforces that package's coverage threshold
```

Uses `pytest` with `asyncio_mode = "auto"`. Each package owns its own coverage
configuration in its `pyproject.toml`.

### Linting and Formatting

```bash
just lint                                  # check lint rules (ruff + bandit narrow set)
just lint-pkg foundry-agent-core           # single package
just lint-fix                              # auto-fix lint issues
just format                                # check formatting (ruff format --check)
just format-pkg foundry-agent-core         # single package
just format-fix                            # auto-fix formatting
```

Ruff is configured for Python 3.13 with a 120-char line length. See
`pyproject.toml` for the full rule set; STIG V-222604 command-injection sinks
(`S102`, `S307`, `S602-S607`) are gated via Ruff and via `bandit` in `just lint`.

### Type Checking

```bash
just type-check                            # basedpyright on all packages
just type-check-pkg foundry-agent-core     # single package
```

Uses basedpyright in `basic` mode targeting Python 3.13.

### All Quality Checks

```bash
just check                             # lint + format + type-check (workspace)
just check-pkg foundry-agent-core      # lint + format + type-check + test for one package
just ci                                # check + test (mirrors CI pipeline)
```

### Building Packages

```bash
just build foundry-agent-core    # build one package
just build-all                   # build all packages
just clean                       # remove dist/, __pycache__, etc.
```

## Using Local Packages in a Consuming Application

When developing packages alongside a consuming application, use editable installs
so changes are immediately available without re-publishing.

### Directory Layout

```
~/projects/
├── foundry-agent-packages/
│   └── packages/
│       ├── foundry-agent-core/
│       ├── foundry-agent-config/
│       ├── foundry-agent-fastapi/
│       └── foundry-strands-agent/
└── my-agent/  # your consuming application
```

### Install Local Package

From your consuming application directory:

```bash
uv pip install -e ../foundry-agent-packages/packages/foundry-agent-core
```

Changes to the package source are immediately available — no reinstall needed.

### Revert to Published Package

```bash
uv sync
```

### Check Current State

```bash
uv pip list --editable
```
