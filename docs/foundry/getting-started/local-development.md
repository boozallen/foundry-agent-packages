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
uv sync --all-packages --all-groups
```

This installs all five workspace packages in editable mode plus the dev
dependency group (pytest, ruff, pyright).

## Development Workflow

### Running Tests

```bash
just test                            # every package, both tiers
just test-unit                       # the `tests/unit/` tier only
just test-integration                # the `tests/integration/` tier; 0 collected is reported as SKIP
just test-pkg foundry-agent-core     # one package's full suite, using that package's own config
```

Tests are split by **directory**, not by marker: every package has
`tests/unit/` and `tests/integration/`, and a test's tier is decided by where
its file lives. No recipe passes `-m`. The `integration` marker stays declared
as a trait tag, but nothing selects on it. `conftest.py` stays at the `tests/`
root, and no `tests/` directory has an `__init__.py` (see [AGENTS.md](../../../AGENTS.md)
for why adding one silently drops tests).

Uses `pytest` with `asyncio_mode = "auto"`. Each package owns its own coverage
configuration in its `pyproject.toml`, including the `--cov-fail-under=70` gate,
so **every** root test recipe enforces the threshold per package. HTML coverage
is always on, written to `htmlcov/<module>/index.html` per package, so there is
no separate coverage recipe.

`test` / `test-unit` / `test-integration` loop pytest once per package from the
workspace root (never a single glob across `packages/*/tests`), so each
package's own pytest/coverage config is honored and the run prints a per-package
pass/fail/count summary table. Each package also has its own local `justfile`,
so `just test` run from inside `packages/<pkg>/` tests only that package.

### Linting and Formatting

```bash
just lint                                  # check lint rules (ruff + bandit)
just lint-pkg foundry-agent-core           # single package (ruff + bandit)
just lint-fix                              # auto-fix lint issues
just format                                # check formatting (ruff format --check)
just format-pkg foundry-agent-core         # single package
just format-fix                            # auto-fix formatting
just dead-code                             # advisory vulture scan (not gated)
```

Ruff is configured for Python 3.13 with a 120-char line length. See
`pyproject.toml` for the full rule set; STIG V-222604 command-injection sinks
(`S102`, `S307`, `S602-S607`) are gated via Ruff, and `just lint` additionally
runs the narrow `bandit` sink set (`B602,B603,B605,B607`). `just lint` run
from inside `packages/<pkg>/` runs both tools too,
scoped to that package (it resolves the shared bandit config as
`../../pyproject.toml`, since `just` runs recipes with the invoking directory as
the working directory).

### Type Checking

```bash
just type-check                            # basedpyright on all packages
just type-check-pkg foundry-agent-core     # single package
```

Uses basedpyright in `basic` mode targeting Python 3.13.

### All Quality Checks

```bash
just check                             # full gate: lint + format + type-check + test
just check-pkg foundry-agent-core      # same gate scoped to one package
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

Create a throwaway consuming app next to this checkout (once), then install a
package in editable mode from that app:

```bash
mkdir -p ~/projects/my-agent
cd ~/projects/my-agent
uv init --python 3.13
uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e ../foundry-agent-packages/packages/foundry-agent-core
```

If `my-agent` already exists and its venv is active, you only need the last
command. Changes to the package source are immediately available — no reinstall
needed.

### Revert to Published Package

`uv sync` only reverts to a published version if one is already declared as
a dependency with a resolvable source. Add that first:

```toml
# pyproject.toml in the downstream agent
[[tool.uv.index]]
name = "my-index"
url = "https://<your-index>/simple"
explicit = true

[tool.uv.sources]
foundry-agent-core = { index = "my-index" }
```

```bash
uv add foundry-agent-core
uv sync
```

### Check Current State

```bash
uv pip list --editable
```

## Where to go next

- **[Quickstart](./quickstart.md)** — `just setup` / `just check` contributor path
- **[Adopting](../releases/adopting.md)** — consume published wheels from a downstream repo
