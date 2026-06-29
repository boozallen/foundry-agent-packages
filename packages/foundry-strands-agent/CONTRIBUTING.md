# Contributing

Thank you for contributing to `foundry-strands-agent`.

## Development Setup

Clone the monorepo and sync all dependencies:

```bash
git clone https://github.com/boozallen/foundry-agent-packages
cd foundry-agent-packages
uv sync --all-groups
```

## Running Tests

Run the full test suite for this package:

```bash
just test-pkg foundry-strands-agent
```

## Lint and Type Check

```bash
just check
```

This runs ruff (linting + formatting check) and pyright across all packages.
Fix issues automatically with:

```bash
just lint-fix
just format-fix
```

## Build

```bash
just build foundry-strands-agent
```

## Docs

Serve the MkDocs site locally:

```bash
just docs-serve
```

Build a static site:

```bash
just docs-build
```

## PR Conventions

- Branch from `develop`; PRs target `develop`
- Branch naming: `feature/<short-description>`, `fix/<short-description>`
- Keep commits focused; one logical change per commit
- All tests and type checks must pass before requesting review

## Docstring Expectations

Follow the pattern established in `foundry-agent-fastapi`:

- Every public class has a class-level docstring explaining its purpose and
  key behaviour
- Every public method or function has a docstring; private methods (leading
  `_`) do not require one unless the behaviour is non-obvious
- Pydantic models use `Field(description=...)` on every field
- Dataclass fields use inline comments or the class docstring for parameter
  documentation
- Docstrings explain *why* and *what*, not *how* — the code explains how
