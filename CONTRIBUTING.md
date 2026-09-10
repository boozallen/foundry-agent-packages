# Contributing to Foundry Agent Packages

Thank you for your interest in contributing! This guide covers how to get
started, submit changes, and what to expect during review.

## Code of Conduct

All participants are expected to treat others with respect and
professionalism. Harassment or abusive behavior will not be tolerated.

## Getting Started

### Fork and Clone

1. Fork this repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/<your-username>/foundry-agent-packages.git
   cd foundry-agent-packages
   ```
3. Add the upstream remote:
   ```bash
   git remote add upstream https://github.com/boozallen/foundry-agent-packages.git
   ```

### Development Setup

This is a Python monorepo managed with [uv](https://docs.astral.sh/uv/) and
[just](https://github.com/casey/just).

Install all dependencies:

```bash
uv sync --all-packages --all-groups
```

Verify your setup:

```bash
just check
```

### Common Commands

| Command | Description |
|---------|-------------|
| `just sync` | Sync the workspace venv with the lockfile |
| `just setup` | Sync workspace + pre-commit hooks |
| `just lint` | Run ruff lint + the bandit command-injection sink set across all packages |
| `just lint-fix` | Auto-fix linting issues |
| `just format` | Check formatting across all packages |
| `just format-fix` | Auto-fix formatting |
| `just type-check` | Run basedpyright type checking |
| `just check` | Full gate: `lint` + `format` + `type-check` + `test` |
| `just test` | Both tiers for every package (per-package loop + summary table) |
| `just test-unit` | The `tests/unit/` tier only |
| `just test-integration` | The `tests/integration/` tier only; 0 collected is reported as SKIP |
| `just test-pkg <pkg>` | Run one package's full suite |
| `just dead-code` | Advisory vulture scan (not gated) |

`just --list` is the full list. Running `just test` from inside
`packages/<pkg>/` tests only that package, and `just lint` there runs the same
ruff + bandit pair scoped to that package.

Tests are split by directory, not by marker: `packages/<pkg>/tests/unit/` and
`packages/<pkg>/tests/integration/`. HTML coverage is always on, written to
`htmlcov/<module>/index.html` from each package's pytest `addopts`, so there is
no separate coverage recipe.

## Making Changes

### Branch Workflow

1. Sync your fork with upstream:
   ```bash
   git fetch upstream
   git checkout develop
   git merge upstream/develop
   ```
2. Create a feature branch from `develop`:
   ```bash
   git checkout -b feature/your-change
   ```
3. Make your changes, keeping commits focused (one logical change per commit)
4. Push to your fork:
   ```bash
   git push origin feature/your-change
   ```

### Branch Naming

- `feature/<short-description>` for new features
- `fix/<short-description>` for bug fixes

### PR Conventions

- All PRs target the `develop` branch
- Include a clear description of what changed and why
- Reference any related issues
- Ensure all checks pass before requesting review

## Submitting a Pull Request

1. Open a pull request from your fork's branch to `upstream/develop`
2. Fill out the PR template checklist
3. Wait for CI checks to pass
4. A maintainer will review your PR - only designated maintainers have merge
   rights

### What to Expect

- Maintainers review all PRs before merging (role-based permissions)
- You may be asked to make changes; push additional commits to your branch
- Once approved, a maintainer will merge your PR
- External contributors do not have direct push or merge access

## Review and Merge Process

This project uses a maintainer-controlled merge model:

- Only designated maintainers (defined in `CODEOWNERS`) can merge pull requests
- At least two approving reviews are required
- At least one CODEOWNERS review is required
- All CI checks must pass before merge
- Stale approvals are dismissed when new commits are pushed
- No bypass is allowed - maintainers follow the same review process

## Reporting Security Issues

**Do not report security vulnerabilities through public GitHub issues.**

Please see [SECURITY.md](SECURITY.md) for instructions on how to report
vulnerabilities privately.

## License

By contributing, you agree that your contributions will be licensed under the
same license as this project. See [LICENSE](LICENSE) for details.
