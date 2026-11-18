#!/usr/bin/env python3
# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Bump the monorepo's synthetic root version from per-package version changes.

The root `pyproject.toml` version and root `CHANGELOG.md` are not released on
their own — they are a derived summary of whatever package versions changed
since the last release on `main`. This script computes that summary: it
compares every `packages/*/pyproject.toml` version against the same file on
a base ref (`origin/main` by default), classifies each changed package's
bump as major, minor or patch, and bumps the root version already on disk by
the highest severity found. A brand new package (absent from the base ref)
counts as a minor bump — additive, not breaking, but more than a patch. The
base ref is only used to detect which packages changed; the root version
itself is always bumped from what's currently committed, since the root
version at `base` can lag behind (e.g. a prior synthetic bump not yet
released to `main`).

Usage:
    python scripts/bump_synthetic_version.py [--base REF] [--check]

    --base REF   Git ref to diff package versions against (default: origin/main)
    --check      Do not write. Exit non-zero if the committed root
                 pyproject.toml / CHANGELOG.md are not already up to date,
                 printing the diff and the command to fix it. Used in CI.

Examples:
    python scripts/bump_synthetic_version.py
    python scripts/bump_synthetic_version.py --check
    python scripts/bump_synthetic_version.py --base origin/main --check
"""

import argparse
import re
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bump_version import bump_version, get_version  # noqa: E402

_GIT = shutil.which("git") or "git"

_SEVERITY_RANK = {"patch": 1, "minor": 2, "major": 3}
# Everything from the `## [Unreleased]` heading up to (not including) the next
# version heading, or end of file if there isn't one yet — the whole section,
# not just its heading line, since it may already carry hand-written notes.
_UNRELEASED_RE = re.compile(r"^## \[Unreleased\].*?(?=^## \[|\Z)", re.MULTILINE | re.DOTALL)


def workspace_root() -> Path:
    return Path(__file__).parent.parent


def package_dirs(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "packages").iterdir() if p.is_dir())


def version_at_ref(root: Path, ref: str, relative_path: str) -> str | None:
    """The version in `relative_path` as it was at `ref`.

    None if the file did not exist there yet — a package new since that ref.
    """
    # List args, no shell=True: `ref`/`relative_path` reach argv directly,
    # never a shell, so there is no injection sink here (STIG V-222604).
    result = subprocess.run(  # noqa: S603
        [_GIT, "show", f"{ref}:{relative_path}"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', result.stdout, re.MULTILINE)
    return match.group(1) if match else None


def version_tuple(version: str) -> tuple[int, int, int] | None:
    """(major, minor, patch) as ints, or None if not exactly 3 dotted parts."""
    parts = version.split("-")[0].split(".")
    if len(parts) != 3:
        return None
    try:
        major, minor, patch = (int(p) for p in parts)
    except ValueError:
        return None
    return major, minor, patch


def classify_bump(old: str | None, new: str) -> str | None:
    """major, minor or patch, or None if the version did not change.

    A package absent from the base ref is new, not changed — see the
    module docstring for why that counts as minor rather than patch or major.
    """
    if old is None:
        return "minor"
    old_parts = old.split("-")[0].split(".")
    new_parts = new.split("-")[0].split(".")
    if len(old_parts) != 3 or len(new_parts) != 3:
        return "patch" if old != new else None
    old_major, old_minor, _ = map(int, old_parts)
    new_major, new_minor, _ = map(int, new_parts)
    if old_major != new_major:
        return "major"
    if old_minor != new_minor:
        return "minor"
    if old != new:
        return "patch"
    return None


def changed_packages(root: Path, base: str) -> dict[str, tuple[str | None, str, str]]:
    """Package name to (old version or None, new version, bump severity).

    Covers every package whose version differs from `base`.
    """
    changed: dict[str, tuple[str | None, str, str]] = {}
    for package in package_dirs(root):
        relative_path = f"packages/{package}/pyproject.toml"
        new_version = get_version(root / relative_path)
        old_version = version_at_ref(root, base, relative_path)
        severity = classify_bump(old_version, new_version)
        if severity is not None:
            changed[package] = (old_version, new_version, severity)
    return changed


def render_changelog_section(version: str, changed: dict[str, tuple[str | None, str, str]], today: date) -> str:
    lines = [f"## [{version}] - {today.isoformat()}", "", "### Changed", ""]
    for package in sorted(changed):
        old_version, new_version, _ = changed[package]
        if old_version is None:
            lines.append(f"- {package}: initial public release at {new_version}")
        else:
            lines.append(f"- {package}: {old_version} to {new_version}")
    lines.append("")
    return "\n".join(lines)


def apply_changelog_section(changelog_text: str, version: str, section: str) -> str:
    """Insert `section` right after the whole `## [Unreleased]` section.

    Any hand-written notes already under Unreleased are left exactly where
    they are, above the new section — this only adds a new section after them.

    A no-op if `version` already has a heading — running this again against
    an already-bumped changelog (as `--check` does) must not insert a
    duplicate section.

    `section` already ends with its own trailing newline, so only one blank
    line is added on each side, regardless of how many blank lines originally
    separated `## [Unreleased]` from whatever came next.
    """
    if re.search(rf"^## \[{re.escape(version)}\]", changelog_text, re.MULTILINE):
        return changelog_text
    match = _UNRELEASED_RE.search(changelog_text)
    if not match:
        raise SystemExit("Could not find a '## [Unreleased]' heading in CHANGELOG.md")
    unreleased_block = match.group().rstrip("\n")
    before = changelog_text[: match.start()]
    after = changelog_text[match.end() :]
    return f"{before}{unreleased_block}\n\n{section}\n{after}"


def compute(root: Path, base: str, today: date) -> tuple[dict, str, str, str, str] | None:
    """Compute the bump, or None if nothing changed.

    Otherwise (changed, base_root_version, new_root_version,
    new_pyproject_text, new_changelog_text).
    """
    changed = changed_packages(root, base)
    if not changed:
        return None

    severity = max(changed.values(), key=lambda v: _SEVERITY_RANK[v[2]])[2]
    root_pyproject = root / "pyproject.toml"
    # Bumped from the root version already committed on disk, not from `base`:
    # `base` (origin/main) only tells us which packages changed, and its own
    # root version can legitimately lag behind develop's (e.g. a prior
    # synthetic bump that hasn't been released/merged to main yet).
    base_root_version = get_version(root_pyproject)
    new_root_version = bump_version(base_root_version, severity)

    pyproject_text = root_pyproject.read_text(encoding="utf-8")
    new_pyproject_text = re.sub(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{new_root_version}"',
        pyproject_text,
        count=1,
        flags=re.MULTILINE,
    )

    changelog_path = root / "CHANGELOG.md"
    section = render_changelog_section(new_root_version, changed, today)
    new_changelog_text = apply_changelog_section(changelog_path.read_text(encoding="utf-8"), new_root_version, section)

    return changed, base_root_version, new_root_version, new_pyproject_text, new_changelog_text


def check(root: Path, base: str) -> None:
    """Verify the root version/changelog were bumped for this change set.

    Deliberately does not recompute or require a specific value: it only
    checks that, whenever any package differs from `base`, the root version
    strictly increased from its value at `base`, and `CHANGELOG.md` has
    exactly one heading for the current root version. A manually-chosen
    version (overriding what `bump-synthetic-version` would have picked)
    still passes, as long as both files agree with each other — recomputing
    the exact bump here would always disagree with whatever's already been
    bumped once, since the bump is itself not idempotent.
    """
    changed = changed_packages(root, base)
    if not changed:
        print(f"No package version changes since {base} — nothing to check")
        return

    for package, (old_version, new_version, severity) in sorted(changed.items()):
        shown_old = old_version or "(new)"
        print(f"{package}: {shown_old} -> {new_version} ({severity})")

    root_pyproject = root / "pyproject.toml"
    current_version = get_version(root_pyproject)
    base_version = version_at_ref(root, base, "pyproject.toml")
    current_tuple = version_tuple(current_version)
    base_tuple = version_tuple(base_version) if base_version is not None else None

    if base_tuple is None or current_tuple is None or current_tuple <= base_tuple:
        print(
            f"\nroot version ({current_version}) did not increase from {base} ({base_version}).\n"
            "Run: just bump-synthetic-version\n",
            file=sys.stderr,
        )
        sys.exit(1)

    changelog_text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    heading_count = len(re.findall(rf"^## \[{re.escape(current_version)}\]", changelog_text, re.MULTILINE))
    if heading_count != 1:
        print(
            f"\nCHANGELOG.md has {heading_count} headings for the current root version "
            f"{current_version} (expected exactly 1).\nRun: just bump-synthetic-version\n",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"root: {base_version} -> {current_version} (ok)")
    print("Synthetic version and changelog are up to date")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    root = workspace_root()

    if args.check:
        check(root, args.base)
        return

    today = datetime.now(UTC).date()
    result = compute(root, args.base, today)

    if result is None:
        print(f"No package version changes since {args.base} — nothing to bump")
        return

    changed, base_root_version, new_root_version, new_pyproject_text, new_changelog_text = result

    for package, (old_version, new_version, severity) in sorted(changed.items()):
        shown_old = old_version or "(new)"
        print(f"{package}: {shown_old} -> {new_version} ({severity})")
    print(f"root: {base_root_version} -> {new_root_version}")

    (root / "pyproject.toml").write_text(new_pyproject_text, encoding="utf-8")
    (root / "CHANGELOG.md").write_text(new_changelog_text, encoding="utf-8")
    print("Wrote pyproject.toml and CHANGELOG.md")


if __name__ == "__main__":
    main()
