# AGENTS.md - foundry-agent-packages (Monorepo)

Guidance for AI assistants and human contributors working on the
`foundry-agent-*` packages.

## What this repo is

A uv-workspace monorepo of the shared Python packages consumed by
Foundry-built agents. Composition roots like `strands-base-agent` install
these packages from a release artifact and extend them — they do not
re-implement what lives here. Treat this repo as **library code**: each
change ships to downstream agents as a versioned wheel, so back-compat
and clear API boundaries matter.

The repo provides:

- Four independently versioned packages under `packages/`
- A shared workspace `pyproject.toml` with cross-cutting tooling
  (ruff, basedpyright, bandit, vulture, deptry, pytest)
- Per-package security checklists tracked in `packages/<pkg>/security/`
- Release tooling that builds wheels + SBOM + scan reports per package
  and attaches them to GitHub Releases (no public PyPI yet — adopters
  host the wheels in their own internal index)
- An OpenSpec workflow (`openspec/`) for spec-driven changes when
  proposals are worth writing down

## First 90 seconds

```bash
just setup           # uv sync + pre-commit install
just check           # ruff + bandit narrow set + format check + basedpyright
just test            # full test suite across all packages
```

## Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│   Composition root (e.g. strands-base-agent — separate repo)│
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
| `foundry-strands-agent` | AWS Strands SDK adapter — `StrandsAgentBackend`, factory, orchestrator, tool loader, chat historian | `foundry-agent-core`, `foundry-agent-config` |

## File Structure

```
foundry-agent-packages/
├── packages/
│   ├── foundry-agent-core/
│   │   ├── src/foundry_agent_core/
│   │   ├── tests/
│   │   ├── security/stig_checklist.json
│   │   ├── CHANGELOG.md
│   │   └── pyproject.toml
│   ├── foundry-agent-config/
│   ├── foundry-agent-fastapi/
│   └── foundry-strands-agent/
├── docs/                       # cross-cutting docs (release model, dev setup)
├── openspec/                   # spec-driven workflow (optional)
├── scripts/bump_version.py     # per-package version bumper
├── .github/workflows/          # ci.yml, release.yml
├── pyproject.toml              # workspace root, shared tooling config
└── justfile                    # developer commands
```

## Development Commands

```bash
just setup           # Install workspace + pre-commit hooks
just check           # All quality checks (lint, format, type-check)
just lint            # ruff check + bandit narrow set (B602/B603/B605/B607)
just lint-fix        # ruff check --fix
just format          # ruff format --check
just format-fix      # ruff format
just type-check      # basedpyright across all packages
just dead-code       # Advisory vulture scan (not gated)
just test            # Run all tests
just test-cov        # Run tests with coverage report
just test-pkg <name> # Run tests for a single package
just build <name>    # Build a single package wheel
just build-all       # Build all packages
just ci              # check + test (pre-PR gate)
```

Per-package version bumps use `scripts/bump_version.py` via:

```bash
just version-patch foundry-agent-core   # 0.2.4 → 0.2.5
just version-minor foundry-agent-config
just version-set foundry-agent-fastapi 0.3.0
```

## Common Tasks

### Modify a Package's Public API

1. Make the change in `packages/<pkg>/src/`
2. Add or update tests in `packages/<pkg>/tests/`
3. Run `just check && just test-pkg <pkg>`
4. Update `packages/<pkg>/CHANGELOG.md` (Unreleased section)
5. Bump version via `just version-<patch|minor|major> <pkg>` per semver
6. If the change affects a STIG-relevant area, update
   `packages/<pkg>/security/stig_checklist.json` in the same PR

### Add a Cross-Cutting Dependency Floor

Supply-chain floors live in root `pyproject.toml` under
`[tool.uv].constraint-dependencies`. Add the floor, regenerate `uv.lock`
(`uv lock`), and call out the resolution diff in the PR description.

### Spec-Driven Changes via OpenSpec (opt-in)

For larger work where a written proposal helps:

- `openspec/specs/` documents the per-capability specs that exist today
- `openspec/changes/` is where new proposals live
- See `openspec/AGENTS.md` and `openspec/config.yaml` for orientation

Small or exploratory changes don't need a spec — go straight to code.

## Security posture

Each package owns its own DISA Application Security and Development
(ASD) STIG checklist under `packages/<pkg>/security/stig_checklist.json`.
When a change touches an auth, authz, crypto, audit-logging, session-
handling, data-handling, or input-validation surface, update the relevant
checklist in the same PR.

**Security policy: command injection.** STIG V-222604 (CCI-001310) is
gated three ways:

- `ruff` extend-select includes `S102`, `S307`, `S602–S607`
- `just lint` runs `bandit -r packages -t B602,B603,B605,B607` (narrow
  STIG sink set)
- The same bandit invocation is wired into both `ci.yml` (PR-to-develop)
  and `release.yml` (PR-to-main) as a gating step

`bandit`'s broader rule set is configured under `[tool.bandit]` for
ad-hoc local runs but is not gated in CI. `vulture` and `deptry` are
installed for advisory use only.

## Release Model

This repo ships releases as GitHub Releases — **adopters host the wheels
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
  `strands-base-agent` deliberately — change them only when there is a
  security or compatibility driver, not on whim
- The bandit narrow set (`B602/B603/B605/B607`) gates a STIG control;
  don't disable rules to silence findings — fix the call site
- `tool_loader.py` (frozen for security review) — see comment in
  `pyproject.toml` per-file-ignores

## Documentation

- `README.md` — short orientation + quick start
- `CHANGELOG.md` — cross-package release summary
- `packages/<pkg>/README.md` — per-package usage
- `packages/<pkg>/CHANGELOG.md` — per-package release history
- `docs/` — repo-level guides (local development, release channels,
  adding new packages)
- `openspec/` — spec-driven workflow
