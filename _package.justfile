# Shared recipes for every package in this workspace.
#
# Each `packages/<pkg>/justfile` imports this file, so a recipe defined here is
# defined once and available in every package. All paths are relative (`src`,
# `tests/`), and `just` runs recipes with the invoking package directory as the
# working directory, so they resolve against whichever package you are in.
#
# Do not add package-specific recipes here. A package that needs to override a
# recipe declares `set allow-duplicate-recipes := true` in its own justfile and
# redefines it there; the local definition wins.

# `--all-packages --all-groups` is deliberate even though this recipe runs at
# package level: a uv workspace has a single root `.venv`, so a sync scoped to
# one member prunes everything else out of it - the other three members and the
# shared dev tooling (pytest, ruff, bandit, basedpyright) alike. Either flag
# alone prunes the same way; both are required. A root `uv run` does re-install
# what it needs here, because the root `[project]` declares all four members as
# dependencies, but the pruned state still breaks any `--no-sync` or non-uv
# invocation and churns ~100 packages on the next root command.

# Sync the shared workspace venv with the lockfile
sync:
    uv sync --all-packages --all-groups

# `-c ../../pyproject.toml` is required: `just` runs recipes with the invoking
# package directory as the working directory, so the workspace-root
# `[tool.bandit]` config lives two levels up. The overlap with ruff's
# S102/S307/S602-S607 rules is deliberate defense in depth.

# Run ruff lint + the bandit command-injection sink set for this package
lint:
    uv run ruff check src tests
    uv run bandit -c ../../pyproject.toml -r src \
        -t B602,B603,B605,B607

# Auto-fix lint issues with ruff
lint-fix:
    uv run ruff check src tests --fix

# Check formatting with ruff
format:
    uv run ruff format --check src tests

# Format code with ruff
format-fix:
    uv run ruff format src tests

# Type check with basedpyright
type-check:
    uv run basedpyright src

# The unit/integration split is by DIRECTORY (`tests/unit/`,
# `tests/integration/`), never by marker, so a test's tier cannot be forgotten.
# No recipe here passes `-m`; the `integration` marker stays declared as a trait
# tag but nothing selects on it. HTML coverage is always on, via this package's
# `--cov-report=html:htmlcov/<module>` addopt, never a recipe.

# Run this package's full suite: tests/unit/ plus tests/integration/
test:
    uv run pytest tests

# Run the unit tier only (tests/unit/)
test-unit:
    uv run pytest tests/unit

# Coverage is disabled here because an integration-only slice cannot represent
# overall coverage, and a package with no integration tests yet is not a
# failure: pytest exits 5 on a run that collects nothing, which this treats as
# success.
# Run the integration tier only (tests/integration/)
test-integration:
    #!/usr/bin/env bash
    set -uo pipefail
    uv run pytest tests/integration --no-cov --cov-fail-under=0
    status=$?
    if [ "$status" -eq 5 ]; then
        echo "No integration tests collected - not a failure."
        exit 0
    fi
    exit $status

# Run all quality checks (including tests)
check: lint format type-check test
