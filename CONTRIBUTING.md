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
uv sync --all-groups
```

Verify your setup:

```bash
just check
just test
```

### Common Commands

| Command | Description |
|---------|-------------|
| `just install` | Install all workspace packages |
| `just check` | Run lint, format check, and type check |
| `just test` | Run all tests |
| `just lint-fix` | Auto-fix linting issues |
| `just format-fix` | Auto-fix formatting |
| `just type-check` | Run type checking (pyright) |

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
4. A maintainer will review your PR — only designated maintainers have merge
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
- No bypass is allowed — maintainers follow the same review process

## Reporting Security Issues

**Do not report security vulnerabilities through public GitHub issues.**

Please see [SECURITY.md](SECURITY.md) for instructions on how to report
vulnerabilities privately.

## License

By contributing, you agree that your contributions will be licensed under the
same license as this project. See [LICENSE](LICENSE) for details.
