#!/usr/bin/env python3
# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Version management utility for monorepo packages.

Usage:
    python scripts/bump_version.py <package-name> <command> [version]

Commands:
    show        Show current version
    patch       Bump patch version (x.y.Z)
    minor       Bump minor version (x.Y.0)
    major       Bump major version (X.0.0)
    set <ver>   Set explicit version

Examples:
    python scripts/bump_version.py foundry-agent-core show
    python scripts/bump_version.py foundry-agent-core patch
    python scripts/bump_version.py foundry-strands-agent set 2.0.0
"""

import re
import sys
from pathlib import Path


def get_pyproject_path(package_name: str) -> Path:
    script_dir = Path(__file__).parent
    workspace_root = script_dir.parent
    pyproject_path = workspace_root / "packages" / package_name / "pyproject.toml"
    if not pyproject_path.exists():
        available = [p.name for p in (workspace_root / "packages").iterdir() if p.is_dir()]
        print(f"Error: Package '{package_name}' not found.", file=sys.stderr)
        print(f"Available packages: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)
    return pyproject_path


def get_version(pyproject_path: Path) -> str:
    content = pyproject_path.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        print(f"Error: Could not find version in {pyproject_path}", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def set_version(pyproject_path: Path, new_version: str) -> None:
    content = pyproject_path.read_text()
    updated = re.sub(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    pyproject_path.write_text(updated)


def bump_version(current: str, part: str) -> str:
    base_version = current.split("-")[0]
    parts = base_version.split(".")
    if len(parts) != 3:
        print(f"Error: Invalid version format '{current}'. Expected X.Y.Z", file=sys.stderr)
        sys.exit(1)
    try:
        major, minor, patch = map(int, parts)
    except ValueError:
        print(f"Error: Version parts must be integers: '{current}'", file=sys.stderr)
        sys.exit(1)
    if part == "major":
        return f"{major + 1}.0.0"
    elif part == "minor":
        return f"{major}.{minor + 1}.0"
    elif part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        print(f"Error: Unknown bump type '{part}'", file=sys.stderr)
        sys.exit(1)


def validate_version(version: str) -> bool:
    pattern = r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$"
    return bool(re.match(pattern, version))


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    package_name = sys.argv[1]
    command = sys.argv[2]
    pyproject_path = get_pyproject_path(package_name)
    current_version = get_version(pyproject_path)

    if command == "show":
        print(current_version)
        return

    if command in ("patch", "minor", "major"):
        new_version = bump_version(current_version, command)
        set_version(pyproject_path, new_version)
        print(f"{package_name}: {current_version} → {new_version}")
        return

    if command == "set":
        if len(sys.argv) < 4:
            print("Error: 'set' command requires a version argument", file=sys.stderr)
            sys.exit(1)
        new_version = sys.argv[3]
        if not validate_version(new_version):
            print(f"Error: Invalid version format '{new_version}'", file=sys.stderr)
            print("Expected: X.Y.Z or X.Y.Z-prerelease", file=sys.stderr)
            sys.exit(1)
        set_version(pyproject_path, new_version)
        print(f"{package_name}: {current_version} → {new_version}")
        return

    print(f"Error: Unknown command '{command}'", file=sys.stderr)
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    main()
