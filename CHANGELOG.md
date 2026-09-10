# Changelog

Cross-package summary of changes across the `foundry-agent-packages` monorepo.
For per-package detail see each package's own `CHANGELOG.md`:

- [foundry-agent-core](packages/foundry-agent-core/CHANGELOG.md)
- [foundry-agent-config](packages/foundry-agent-config/CHANGELOG.md)
- [foundry-agent-fastapi](packages/foundry-agent-fastapi/CHANGELOG.md)
- [foundry-strands-agent](packages/foundry-strands-agent/CHANGELOG.md)

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Per-package versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-09-10

Updated public release. Includes a breaking change in `foundry-strands-agent`
(`AgentToolRegistry.load_tools_from_directory` is now async) — see its
CHANGELOG for detail.

## [1.0.0] - 2026-06-29

Initial public release.
