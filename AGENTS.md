# AGENTS.md - foundry-agent-packages (Monorepo)

Guidance for AI assistants and human contributors working on the
`foundry-agent-*` packages.

## What this repo is

A uv-workspace monorepo of the shared Python packages consumed by
Foundry-built agents. Composition roots like `strands-base-agent` install
these packages from a release artifact and extend them - they do not
re-implement what lives here. Treat this repo as **library code**: each
change ships to downstream agents as a versioned wheel, so back-compat
and clear API boundaries matter.

The repo provides:

- Four independently versioned packages under `packages/`
- A shared workspace `pyproject.toml` with cross-cutting tooling
  (ruff, basedpyright, bandit, vulture, deptry, pytest)
- Per-package security checklists tracked in `packages/<pkg>/security/`
- Release tooling that builds wheels + SBOM + scan reports per package
  and attaches them to GitHub Releases (no public PyPI yet - adopters
  host the wheels in their own internal index)
- An OpenSpec workflow (`openspec/`) for spec-driven changes when
  proposals are worth writing down

## First 90 seconds

```bash
just setup           # uv sync + pre-commit install
just check           # ruff + format check + basedpyright + test suite
just test            # unit + integration tiers, looped per package
```

## Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│   Composition root (e.g. strands-base-agent - separate repo)│
├────────────────────────────────────────────────────────────┤
│   server.py, config.yaml, tools/, api/routes/               │
└────────────────────────────────────────────────────────────┘
                            │ pip install
                            ▼
┌────────────────────────────────────────────────────────────┐
│              foundry-agent-* Packages (this repo)           │
├────────────────────────────────────────────────────────────┤
│  foundry-agent-core   ◄── foundry-agent-fastapi             │
│        ▲                                                    │
│        │                                                    │
│        ├──────────────────── foundry-strands-agent          │
│        │                            ▲                       │
│  foundry-agent-config ──────────────┘                       │
└────────────────────────────────────────────────────────────┘
```

## Packages

| Package | Purpose | Depends on |
|---------|---------|------------|
| `foundry-agent-core` | DI container, protocols, types, exceptions, lifecycle, masking/redaction | _(none)_ |
| `foundry-agent-config` | YAML loader with env-var overrides (double-underscore nesting), bounded input controls | _(none)_ |
| `foundry-agent-fastapi` | CORS / error / logging middleware, request/response models, mappers, health router | `foundry-agent-core` |
| `foundry-strands-agent` | AWS Strands SDK adapter - `StrandsAgentBackend`, factory, orchestrator, tool loader, chat historian | `foundry-agent-core`, `foundry-agent-config` |

## File Structure

```
foundry-agent-packages/
├── packages/
│   ├── foundry-agent-core/
│   │   ├── src/foundry_agent_core/
│   │   ├── tests/
│   │   ├── CHANGELOG.md
│   │   └── pyproject.toml
│   ├── foundry-agent-config/
│   ├── foundry-agent-fastapi/
│   └── foundry-strands-agent/
├── docs/                       # cross-cutting docs (release model, dev setup)
├── openspec/                   # spec-driven workflow (optional)
├── scripts/bump_version.py     # per-package version bumper
├── .github/                    # issue/PR templates, dependabot.yml, release workflow
├── pyproject.toml              # workspace root, shared tooling config
└── justfile                    # developer commands
```

## Development Commands

The root `justfile` is grouped into four banner-delimited sections - *Setup &
Dependencies*, *Code Quality*, *Testing*, *Building & Release* - matching the
sibling `temporal-packages` repo's root justfile, so the shared recipe names and
observable behavior are the same in both repos.

```bash
# Setup & Dependencies
just sync            # uv sync --all-packages --all-groups
just setup           # Sync workspace + pre-commit hooks
just add-package <spec>      # Add a runtime dependency to the workspace
just add-dev-package <spec>  # Add a development dependency to the workspace

# Code Quality
just lint            # ruff check (S102/S307/S602-S607 STIG rules) + bandit B602,B603,B605,B607
just lint-fix        # ruff check --fix
just format          # ruff format --check
just format-fix      # ruff format
just type-check      # basedpyright across all packages (explicit packages/*/src paths)
just check           # Full gate: lint + format + type-check + test
just lint-pkg <name> # ruff check + bandit, one package
just format-pkg <name>      # ruff format --check, one package
just type-check-pkg <name>  # basedpyright, one package
just check-pkg <name>       # Full gate scoped to one package
just dead-code       # Advisory vulture scan (not gated)

# Testing
just test            # Both tiers (tests/) for every package, looped per package
just test-unit       # The tests/unit/ tier only, looped per package
just test-integration # The tests/integration/ tier only; 0 collected is SKIP
just test-pkg <name> # Run one package's full suite (uses that package's own pytest/coverage config)

# Building & Release
just build <name>    # Build a single package wheel
just build-all       # Build all packages
just publish <name>  # Dry-run publish (validates credentials + metadata)
just version-<patch|minor|major> <name>  # Bump a package version
just clean           # Remove build artifacts and tooling caches
```

### The unit/integration split is by DIRECTORY

Every package has `tests/unit/` and `tests/integration/`, and a test's tier is
decided by **where its file lives**, not by a marker, so the classification
cannot be forgotten. No recipe passes `-m`, ever. The `integration` marker stays
declared in every `markers` list (it remains a valid trait tag) but nothing
selects on it, and `-m "not integration"` is absent from every `addopts`.
`conftest.py` stays at the `tests/` root so both tiers share it. A package with
no integration tests still has an empty `tests/integration/` (holding a
`.gitkeep`) so `just test-integration` behaves the same everywhere.

`just test` / `test-unit` / `test-integration` loop per package from the
workspace root (never a single glob across `packages/*/tests`) and print a
per-package pass/fail/count summary. They share one internal `_test-loop`,
parameterized by the test **directory** (`tests`, `tests/unit`,
`tests/integration`), which overrides the package-relative `--cov=src/<mod>`
addopt with a workspace-root-relative `--cov=packages/<pkg>/src/<mod>` -
coverage resolves `--cov` against the process cwd, so a root-invoked pytest
needs the root-relative path or it measures nothing and every package fails the
coverage gate at 0%. Because that gate lives in each package's `addopts`, `test`
and `test-unit` both enforce it; the sole exception is `test-integration`, which
disables coverage (`--no-cov --cov-fail-under=0`) since an integration-only
slice can't represent overall coverage. A package with no matching test
directory is reported as `SKIP`, as is a run that collects nothing under
`test-integration` (pytest exit code 5).

HTML coverage is **always on**, never a recipe: each package's `addopts` carries
`--cov-report=html:htmlcov/<module>`, keyed by module name so root-invoked
per-package runs write to distinct directories instead of overwriting one flat
`htmlcov/`. There is no `test-cov` recipe; it was a second name for `just test`.

Each of the four packages also has its own local `justfile`
(`packages/<pkg>/justfile`) scoped to just that package - running `just test`
from inside a package directory intercepts there and tests only that package,
not the whole workspace.

Those four files are **stubs**: each one imports the workspace-root
`_package.justfile`, which is the single definition of the shared per-package
recipe set (`sync`, `lint`, `lint-fix`, `format`, `format-fix`, `type-check`,
`test`, `test-unit`, `test-integration`, `check`) plus a local `default` that
lists recipes. Per-package `test` runs `tests` (both tiers), `test-unit` runs
`tests/unit`, and `test-integration` runs `tests/integration` with
`--no-cov --cov-fail-under=0`, treating pytest exit code 5 as success with the
message `No integration tests collected - not a failure.` **Edit a shared
per-package recipe in `_package.justfile` only** - there are no per-package
copies to keep in sync. `just` runs recipes with the invoking directory as cwd,
so the relative paths in those recipes (`src`, `tests/unit`) resolve against
whichever package you are in - and for the same reason the per-package `lint`, which runs the
narrow bandit sink set alongside ruff, reaches the shared bandit config as
`../../pyproject.toml`. A package that genuinely must diverge declares
`set allow-duplicate-recipes := true` in its own justfile and redefines the
recipe there. Note that bare `just` inside a package lists recipes rather than
running one.

Each package declares its own `[dependency-groups] dev` and
`[tool.basedpyright]` so those recipes resolve dev tooling and type-check
settings when run from inside the package on a cold clone. Each package's
`pyproject.toml` gates coverage via `--cov-fail-under=70` on the pytest
invocation itself (not only via `[tool.coverage.report] fail_under`).

All four packages' `[tool.pytest.ini_options]` blocks are identical apart from
the two module-keyed paths (`--cov=src/<module>` and
`--cov-report=html:htmlcov/<module>`): the same remaining `addopts` (including
`--strict-markers`, so an undeclared/typo'd marker is an error rather than a
silent no-op, and `--strict-config`, so an unknown ini key is an error rather than
a silently ignored line), the same one-entry `markers` list, and the same
narrow `filterwarnings` list. None of them carries `-m`. Keep them that way -
change all four together. The
root `pyproject.toml` carries the same strictness flags, marker list, and warning
filters so a bare root `uv run pytest` is gated the same way; it deliberately
carries no coverage flags, since a root-level `--cov=src/<module>` would resolve
against the workspace root and measure nothing.

Which of those blocks a run reads is set by pytest's rootdir logic, which uses the
common ancestor of the **command-line arguments**, not the process working
directory. `_test-loop` passes a single `packages/<pkg>/<test_dir>` argument, so
it reads that **package's** block despite running from the root with no `cd`; so
do `test-pkg` and `just` from inside a package. A bare root `uv run pytest`, or any
invocation spanning two or more packages, reads the **root** block.

No package's `tests/`, `tests/unit/`, or `tests/integration/` has an
`__init__.py`, and none should be added. An `__init__.py` there makes the
directory a real Python package, so every test module's importable name becomes
`tests.unit.<basename>` - shared across all four packages.
`foundry-agent-core` and `foundry-strands-agent` both have a `test_types.py`, and
with a shared package path the first one collected wins the `sys.modules` slot,
so the second is never imported and the first is collected a second time in its
place: no error, no warning, just a lower collected count and reported passes for
a module that never ran. Plain, `__init__.py`-free test directories give each module a
path-derived name, so the collision cannot form. `--import-mode=importlib` does not substitute for this - it
only changes the shape of the failure.

Either the root or the per-package `just test-integration` is safe when a
package has no integration tests yet: the root loop reports 0-collected as
`SKIP`, and the per-package recipe maps pytest exit code 5 to success with
`No integration tests collected - not a failure.`

Per-package version bumps use `scripts/bump_version.py` via:

```bash
just version-patch foundry-agent-core   # 0.2.4 → 0.2.5
just version-minor foundry-agent-config
just version-set foundry-agent-fastapi 0.3.0
```

## Common Tasks

### Modify a Package's Public API

1. Make the change in `packages/<pkg>/src/`
2. Add or update tests in `packages/<pkg>/tests/unit/` (or
   `packages/<pkg>/tests/integration/` if the test needs an external service,
   network access, or real credentials)
3. Run `just check && just test-pkg <pkg>`
4. Update `packages/<pkg>/CHANGELOG.md` (Unreleased section)
5. Bump version via `just version-<patch|minor|major> <pkg>` per semver

### Add a Cross-Cutting Dependency Floor

Supply-chain floors live in root `pyproject.toml` under
`[tool.uv].constraint-dependencies`. Add the floor, regenerate `uv.lock`
(`uv lock`), and call out the resolution diff in the PR description.

### Spec-Driven Changes via OpenSpec (opt-in)

For larger work where a written proposal helps:

- `openspec/specs/` documents the per-capability specs that exist today
- `openspec/changes/` is where new proposals live
- See `openspec/AGENTS.md` and `openspec/config.yaml` for orientation

Small or exploratory changes don't need a spec - go straight to code.

## Security posture

When a change touches an auth, authz, crypto, audit-logging, session-
handling, data-handling, or input-validation surface, call that out
explicitly in the PR description.

**Security policy: command injection.** This is gated three ways:

- `ruff` extend-select includes `S102`, `S307`, `S602-S607`
- `just lint` and `just lint-pkg <name>` additionally run
  `bandit -c pyproject.toml -r packages -t B602,B603,B605,B607` (narrow sink
  set)
- the per-package `lint` in `_package.justfile` runs the same narrow set scoped
  to that package (`bandit -c ../../pyproject.toml -r src -t
  B602,B603,B605,B607`), so `just lint` / `just check` from inside
  `packages/<pkg>/` is gated identically to the root

`bandit`'s broader rule set is configured under `[tool.bandit]` for
ad-hoc local runs but is not gated in CI. `vulture` and `deptry` are
installed for advisory use only.

## Release Model

This repo ships releases as GitHub Releases - **adopters host the wheels
in their own internal index** (no public PyPI yet).

- PRs to `develop` → CI runs (lint, type-check, test, dry-run build,
  bandit narrow set)
- PRs to `main` → release validation runs
- Tag a release on `main` → builds wheels + Syft SBOM + Grype scan per
  changed package and attaches them to the GitHub Release

See `docs/foundry/releases/release-channels.md` for the internal RC/dev
publishing model and `docs/foundry/releases/adopting.md` for the
GitHub-Release adopter flow.

## Python Style

- Modern PEP 585: `list[int]`, `dict[str, Any]`, `X | Y | None`
- Logging: `%` interpolation, never f-strings (allowed via ruff `G002`
  ignore)
- Pydantic v2: `@field_validator`, `model_config = {"frozen": True}` on
  immutable types
- No mutable default arguments, no global mutable state
- Prefer composition over inheritance
- `tool_loader.py` and `_tool_factory.py` in `foundry-strands-agent`
  are security-critical: never restructure them as part of a drive-by
  cleanup
- Python 3.13 floor (the 3.14 upgrade is a post-OSS task)

## Commit Guidelines

- One logical change per commit
- Each commit should compile and pass tests
- Small, incremental, reviewable diffs

```
<type>: <short description>

<optional body explaining why, not what>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

## Things to leave alone

- The `[tool.uv].constraint-dependencies` floors mirror
  `strands-base-agent` deliberately - change them only when there is a
  security or compatibility driver, not on whim
- The bandit narrow set (`B602/B603/B605/B607`) gates a STIG control;
  don't disable rules to silence findings - fix the call site
- `tool_loader.py` (frozen for security review) - see comment in
  `pyproject.toml` per-file-ignores

## Documentation

- `README.md` - short orientation + quick start
- `CHANGELOG.md` - cross-package release summary
- `packages/<pkg>/README.md` - per-package usage
- `packages/<pkg>/CHANGELOG.md` - per-package release history
- `docs/` - repo-level guides (local development, release channels,
  adding new packages)
- `openspec/` - spec-driven workflow
