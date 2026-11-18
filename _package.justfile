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

# All seven packages share one workspace `.venv`. Sync and run commands use
# `--all-packages --all-groups` so root and package-local recipes install the
# same development dependencies, including dependencies declared by members.

# Sync the shared workspace venv with the lockfile
sync:
    uv sync --all-packages --all-groups

# `-c ../../pyproject.toml` is required: `just` runs recipes with the invoking
# package directory as the working directory, so the workspace-root
# `[tool.bandit]` config lives two levels up. The overlap with ruff's
# S102/S307/S602-S607 rules is deliberate defense in depth.

# Run ruff lint + the bandit command-injection sink set for this package
lint:
    uv run --all-packages --all-groups ruff check src tests
    uv run --all-packages --all-groups bandit -c ../../pyproject.toml -r src \
        -t B602,B603,B605,B607

# Auto-fix lint issues with ruff
lint-fix:
    uv run --all-packages --all-groups ruff check src tests --fix

# Check formatting with ruff
format:
    uv run --all-packages --all-groups ruff format --check src tests

# Format code with ruff
format-fix:
    uv run --all-packages --all-groups ruff format src tests

# Type check with basedpyright
type-check:
    uv run --all-packages --all-groups basedpyright src

# The unit/integration split is by DIRECTORY (`tests/unit/`,
# `tests/integration/`), never by marker, so a test's tier cannot be forgotten.
# No recipe here passes `-m`; the `integration` marker stays declared as a trait
# tag but nothing selects on it. HTML coverage is always on, via this package's
# `--cov-report=html:htmlcov/<module>` addopt, never a recipe.

# Run this package's full suite: tests/unit/ plus tests/integration/
test:
    uv run --all-packages --all-groups pytest tests

# Run the unit tier only (tests/unit/)
test-unit:
    uv run --all-packages --all-groups pytest tests/unit

# Coverage is disabled here because an integration-only slice cannot represent
# overall coverage, and a package with no integration tests yet is not a
# failure: pytest exits 5 on a run that collects nothing, which this treats as
# success.
# Run the integration tier only (tests/integration/)
test-integration:
    #!/usr/bin/env bash
    set -uo pipefail
    uv run --all-packages --all-groups pytest tests/integration --no-cov --cov-fail-under=0
    status=$?
    if [ "$status" -eq 5 ]; then
        echo "No integration tests collected - not a failure."
        exit 0
    fi
    exit $status

# Run all quality checks (including tests)
check: sync lint format type-check test
