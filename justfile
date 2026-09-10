# Agent Packages Monorepo - Development Commands
# Usage: just <command> [args]

# Show all available recipes
default:
    @just --list

# ============================================================================
# Setup & Dependencies
# ============================================================================

# Sync the workspace virtual environment with the lockfile
sync:
    uv sync --all-packages --all-groups

# Set up the local development environment (workspace + pre-commit hooks)
setup: sync
    uv tool install pre-commit --with pre-commit-uv
    uv run pre-commit install
    @echo "Development environment ready"

# Add a runtime dependency to the workspace
add-package package:
    uv add "{{package}}"
    uv lock

# Add a development dependency to the workspace
add-dev-package package:
    uv add --dev "{{package}}"
    uv lock

# ============================================================================
# Code Quality
# ============================================================================

# Run ruff lint + the bandit command-injection sink set across all packages
lint:
    uv run ruff check packages/*/src packages/*/tests
    uv run bandit -c pyproject.toml -r packages -t B602,B603,B605,B607

# Auto-fix ruff lint findings across all packages
lint-fix:
    uv run ruff check --fix packages/*/src packages/*/tests

# Check formatting across all packages
format:
    uv run ruff format --check packages/*/src packages/*/tests

# Reformat all packages
format-fix:
    uv run ruff format packages/*/src packages/*/tests

# Run basedpyright type checking across all packages
type-check:
    uv run basedpyright packages/*/src

# Run every quality gate: lint, format, type-check, test
check: lint format type-check test
    @echo "All quality checks passed"

# Run ruff lint + bandit on a single package
lint-pkg pkg:
    uv run ruff check packages/{{pkg}}/src packages/{{pkg}}/tests
    uv run bandit -c pyproject.toml -r packages/{{pkg}}/src -t B602,B603,B605,B607

# Check formatting for a single package
format-pkg pkg:
    uv run ruff format --check packages/{{pkg}}/src packages/{{pkg}}/tests

# Run basedpyright type checking on a single package
type-check-pkg pkg:
    uv run basedpyright packages/{{pkg}}/src

# Run every quality gate plus tests for a single package
check-pkg pkg: (lint-pkg pkg) (format-pkg pkg) (type-check-pkg pkg) (test-pkg pkg)
    @echo "All checks passed for {{pkg}}"

# Advisory dead-code scan with vulture. Not part of `check` - expect false
# positives from the DI container, Protocol method definitions, and dynamic
# tool loading. Use as a periodic pre-refactor checklist, not a gate. The
# leading `-` makes just ignore the non-zero exit so findings don't break flow.

# Advisory vulture dead-code scan (not gated; expect false positives)
dead-code:
    -uv run vulture

# ============================================================================
# Testing
# ============================================================================
#
# The unit/integration split is by DIRECTORY, not by marker: `tests/unit/` and
# `tests/integration/` in every package. `test` runs both tiers, `test-unit`
# runs `tests/unit/` only, `test-integration` runs `tests/integration/` only.
# No recipe passes `-m`; the `integration` marker stays declared as a trait tag
# but nothing selects on it.
#
# All three share one internal `_test-loop` recipe, parameterized by the test
# directory. It runs pytest once per package (never a single glob across
# `packages/*/tests`) so each package's own pytest + coverage config in its
# pyproject.toml is honored, and prints a real per-package pass/fail/count
# summary table. It runs from the workspace root without `cd`, so `uv run`
# always resolves the workspace's [dependency-groups] and pytest is guaranteed
# to be installed even on a fresh/cold .venv.
#
# Coverage note: each package's own pyproject.toml carries a package-relative
# `--cov=src/<module>` addopt, which only resolves when pytest's cwd is inside
# that package. Because these recipes run from the workspace root, they must
# override `--cov` on the command line with a workspace-root-relative path
# (`packages/<pkg>/src/<module>`); a CLI `--cov` takes precedence over the
# addopts value. Without the override coverage measures nothing and every
# package spuriously fails the 70% gate at 0%. HTML coverage is always on, via
# each package's `--cov-report=html:htmlcov/<module>` addopt, never a recipe;
# it is keyed by module name so per-package runs write to distinct directories
# instead of overwriting one flat `htmlcov/`.
#
# See openspec/changes/foundry-850-standardize-testing/design.md for rationale.

# Coverage is disabled for the integration slice (`--no-cov --cov-fail-under=0`):
# an integration-only slice cannot represent overall coverage, and no package
# has integration tests today, so a coverage gate would fail spuriously. For
# that slice exit code 5 (no tests collected) is reported as SKIP, not FAIL. A
# package with no such test directory is also a SKIP.

# Internal: loop pytest per package over one test directory + summary table
_test-loop test_dir treat_empty_as_pass:
    #!/usr/bin/env bash
    set -uo pipefail
    pkg_names=()
    pkg_status=()
    pkg_counts=()
    overall_failed=0
    for pkg_dir in packages/*/; do
        pkg_name=$(basename "$pkg_dir")
        pkg_mod="${pkg_name//-/_}"
        if [[ ! -d "${pkg_dir}{{test_dir}}" ]]; then
            echo "Skipping ${pkg_name} (no {{test_dir}} directory)"
            pkg_names+=("$pkg_name")
            pkg_status+=("SKIP")
            pkg_counts+=("no {{test_dir}} directory")
            continue
        fi
        cov_args=(--cov="${pkg_dir}src/${pkg_mod}")
        if [[ "{{treat_empty_as_pass}}" == "true" ]]; then
            cov_args=(--no-cov --cov-fail-under=0)
        fi
        echo "Testing ${pkg_name} ({{test_dir}})..."
        output=$(uv run pytest "${pkg_dir}{{test_dir}}" \
            "${cov_args[@]}" --color=yes 2>&1) && rc=0 || rc=$?
        echo "$output"
        count=$(echo "$output" | grep -Eo '[0-9]+ (passed|failed|error|skipped)' | paste -sd, - || true)
        [[ -z "$count" ]] && count="0 tests"
        pkg_names+=("$pkg_name")
        if [[ $rc -eq 5 && "{{treat_empty_as_pass}}" == "true" ]]; then
            pkg_status+=("SKIP")
            pkg_counts+=("0 collected")
        elif [[ $rc -eq 0 ]]; then
            pkg_status+=("PASS")
            pkg_counts+=("$count")
        else
            pkg_status+=("FAIL")
            pkg_counts+=("$count")
            overall_failed=1
        fi
    done
    echo ""
    echo "=========================================================="
    echo " Package Test Summary ({{test_dir}})"
    echo "=========================================================="
    printf "%-28s %-6s %s\n" "PACKAGE" "STATUS" "COUNTS"
    for i in "${!pkg_names[@]}"; do
        printf "%-28s %-6s %s\n" "${pkg_names[$i]}" "${pkg_status[$i]}" "${pkg_counts[$i]}"
    done
    echo "=========================================================="
    if [[ $overall_failed -ne 0 ]]; then
        echo "Tests failed - see FAIL rows above"
        exit 1
    fi
    echo "All package tests passed"

# Run every package's full suite: tests/unit/ plus tests/integration/
test: (_test-loop "tests" "false")

# Run the unit tier only (tests/unit/) for every package
test-unit: (_test-loop "tests/unit" "false")

# Run the integration tier only (tests/integration/); 0 collected is not a failure
test-integration: (_test-loop "tests/integration" "true")

# Run one package's full suite (same root-relative --cov override as the loop)
test-pkg pkg:
    #!/usr/bin/env bash
    set -euo pipefail
    pkg_mod="$(echo '{{pkg}}' | tr '-' '_')"
    uv run pytest "packages/{{pkg}}/tests" \
        --cov="packages/{{pkg}}/src/${pkg_mod}"

# ============================================================================
# Building & Release
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
    echo "All packages built"

# Publish package to PyPI (requires PYPI_TOKEN env var)
publish pkg:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Publishing {{pkg}}..."
    cd packages/{{pkg}}
    uv build
    uv publish
    echo "✓ Published {{pkg}}"

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

# Clean build artifacts and tooling caches
clean:
    rm -rf dist packages/*/dist packages/*/build packages/*/*.egg-info
    rm -rf htmlcov/ packages/*/htmlcov
    rm -f .coverage packages/*/.coverage
    find . -path ./.venv -prune -o -type d \( -name .pytest_cache -o -name .ruff_cache -o -name __pycache__ \) -prune -exec rm -rf {} +
    find . -path ./.venv -prune -o -type f -name "*.pyc" -exec rm -f {} +
    @echo "Cleaned build artifacts"
