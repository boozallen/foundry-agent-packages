---
sidebar_position: 1
---

# Adopting these packages

`foundry-agent-packages` ships releases as **GitHub Releases**. Each release
attaches one wheel per changed package, a Syft SBOM, and a Grype vulnerability
scan. There is no public PyPI mirror yet — host the wheel in your own index
and point `uv` / `pip` at it.

This page covers the adopter-facing flow: download the artifacts, host them,
consume them.

## 1. Find the release

Each tagged release on this repo's
[Releases page](https://github.com/boozallen/foundry-agent-packages/releases)
includes:

- **Wheels:** one `foundry_agent_<pkg>-<version>-py3-none-any.whl` per
  package that changed at that tag (so a typical release attaches 1–4
  wheels, not always all four)
- **SBOM:** `foundry-agent-<pkg>-sbom.json` (one per wheel)
- **Scan report:** `foundry-agent-<pkg>-grype.json` (one per wheel, when present)

Tags follow the per-package version in each package's `pyproject.toml`. A
typical tag is `foundry-agent-core/v1.0.0`. Releases never re-publish an
existing version — every tag is monotonic per package.

## 2. Host the wheels in your own index

The wheels are vanilla PEP 427 artifacts; any tool that serves a PyPI-compatible
index works. The patterns we've validated:

- **JFrog Artifactory** — create a *generic remote* repo backed by the GitHub
  Releases URL, or a *local PyPI* repo and upload the wheel files.
- **AWS CodeArtifact** — `aws codeartifact publish-package-version` per wheel.
- **`devpi` / `pypiserver` / nginx auto-index** — point them at a local mirror
  directory you populate from `gh release download`.

The supported pattern is "fetch the wheel, host it on your side, pin against
your index". We do not maintain mirror metadata, sign release artifacts, or
guarantee URL stability for old releases.

## 3. Consume from your project

```toml
# pyproject.toml in the downstream agent
[project]
name = "my-agent"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = []

[[tool.uv.index]]
name = "my-index"
url = "https://<your-index>/simple"
explicit = true

[tool.uv.sources]
foundry-agent-core = { index = "my-index" }
foundry-strands-agent = { index = "my-index" }
```

```bash
uv add foundry-agent-core foundry-strands-agent
```

## 4. Verify what you're installing

Every wheel ships with an accompanying SBOM and Grype scan as separate
release assets. Before promoting a release to a production index:

1. `gh release download foundry-agent-core/v1.0.0 --pattern '*sbom*'`
2. Inspect the SBOM (Syft SPDX-JSON) to confirm the dependency set matches
   what your supply-chain policy allows.
3. Inspect `foundry-agent-<pkg>-grype.json` for any unresolved CVEs above
   your tolerance threshold.

Both files are emitted from the same CI run that built the wheel, so they
describe the exact bits in the artifact — not a separately-resolved view.

## 5. Stay current

- **Watch the repo** for releases — GitHub will email new tags to watchers.
- **Pin against your own index**, not against `develop` or any moving ref
  here. Pre-release channels (`rcN`, `.devN`) documented in
  [release-channels.md](./release-channels.md) are for internal validation
  cycles and are not part of the OSS adoption flow.
- **Read the relevant package CHANGELOG** at upgrade time. The root
  [`CHANGELOG.md`](https://github.com/boozallen/foundry-agent-packages/blob/main/CHANGELOG.md)
  cross-references each package's per-package changelog under
  `packages/<pkg>/CHANGELOG.md`.

## When to file an issue

- The wheel installs but imports fail → file an issue with the `pip`/`uv`
  resolution output and the Python version
- The SBOM or scan asset is missing for a release → file an issue
- A CVE you care about is unresolved in the scan → file an issue with the
  CVE ID, the affected package version, and your remediation deadline

Security advisories should go through the private flow described in
[`SECURITY.md`](https://github.com/boozallen/foundry-agent-packages/blob/main/SECURITY.md),
not the public issue tracker.
