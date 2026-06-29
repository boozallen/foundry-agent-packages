# Agent Packages Monorepo - Development Commands
# Usage: just <command> [args]

default:
    @just --list

# ============================================================================
# Setup & Installation
# ============================================================================

# Install all packages in the workspace
install:
    uv sync --all-groups

# Setup development environment
setup: install
    uv tool install pre-commit --with pre-commit-uv
    uv run pre-commit install
    @echo "✓ Development environment ready"

# ============================================================================
# Quality Checks
# ============================================================================

# Run linting on all packages
lint:
    uv run ruff check packages/*/src packages/*/tests
    uv run bandit -c pyproject.toml -r packages -t B602,B603,B605,B607

# Run linting on a single package
lint-pkg pkg:
    uv run ruff check packages/{{pkg}}/src packages/{{pkg}}/tests
    uv run bandit -c pyproject.toml -r packages/{{pkg}}/src -t B602,B603,B605,B607

# Fix linting issues
lint-fix:
    uv run ruff check --fix packages/*/src packages/*/tests

# Check code formatting
format:
    uv run ruff format --check packages/*/src packages/*/tests

# Check code formatting for a single package
format-pkg pkg:
    uv run ruff format --check packages/{{pkg}}/src packages/{{pkg}}/tests

# Fix code formatting
format-fix:
    uv run ruff format packages/*/src packages/*/tests

# Run type checking on all packages
type-check:
    uv run basedpyright

# Run type checking on a single package
type-check-pkg pkg:
    uv run basedpyright packages/{{pkg}}/src

# Advisory dead-code scan with vulture. Not part of `check`/`ci` — expect false
# positives from the DI container, Protocol method definitions, and dynamic
# tool loading. Use as a periodic pre-refactor checklist, not a gate. The
# leading `-` makes just ignore the non-zero exit so findings don't break flow.
dead-code:
    -uv run vulture

# Run all quality checks
check: lint format type-check
    @echo "✓ All quality checks passed"

# Run all quality checks + tests for a single package
check-pkg pkg: (lint-pkg pkg) (format-pkg pkg) (type-check-pkg pkg) (test-pkg pkg)
    @echo "✓ All checks passed for {{pkg}}"

# ============================================================================
# Testing
# ============================================================================

# Run all tests
test:
    uv run pytest packages/*/tests -v

# Run tests for a specific package (uses the package's pytest + coverage config)
test-pkg pkg:
    cd packages/{{pkg}} && uv run pytest

# ============================================================================
# Building
# ============================================================================

# Build a specific package
build pkg:
    cd packages/{{pkg}} && uv build

# Build all packages
build-all:
    #!/usr/bin/env bash
    set -euo pipefail
    for pkg in packages/*/; do
        pkg_name=$(basename "$pkg")
        echo "Building $pkg_name..."
        (cd "$pkg" && uv build)
    done
    echo "✓ All packages built"

# Clean build artifacts and tooling caches
clean:
    rm -rf build/
    rm -rf dist/
    rm -rf htmlcov/
    rm -rf *.egg-info/
    rm -rf .pytest_cache/
    rm -rf .ruff_cache/
    rm -f .coverage
    rm -rf packages/*/dist packages/*/build packages/*/*.egg-info
    find . -type d -name __pycache__ -prune -exec rm -r {} +
    find . -type f -name "*.pyc" -delete
    @echo "✓ Cleaned build artifacts"

# Publish package to PyPI (requires PYPI_TOKEN env var)
publish pkg:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Publishing {{pkg}}..."
    cd packages/{{pkg}}
    uv build
    uv publish
    echo "✓ Published {{pkg}}"

# ============================================================================
# Version Management
# ============================================================================

# Show version of a package
version pkg:
    @uv run python scripts/bump_version.py {{pkg}} show

# Bump patch version (x.y.Z)
version-patch pkg:
    uv run python scripts/bump_version.py {{pkg}} patch

# Bump minor version (x.Y.0)
version-minor pkg:
    uv run python scripts/bump_version.py {{pkg}} minor

# Bump major version (X.0.0)
version-major pkg:
    uv run python scripts/bump_version.py {{pkg}} major

# Set explicit version
version-set pkg version:
    uv run python scripts/bump_version.py {{pkg}} set {{version}}

# ============================================================================
# Convenience Aliases
# ============================================================================

# Run all checks and tests (useful before creating PR)
ci: check test
    @echo "✓ CI checks passed"
