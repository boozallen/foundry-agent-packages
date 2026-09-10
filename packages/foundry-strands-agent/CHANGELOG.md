# Changelog

All notable changes to `foundry-strands-agent` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.6.0] - 2026-09-08

### Changed

- **BREAKING**: `AgentToolRegistry.load_tools_from_directory` is now async — callers must `await` it.
- Tools directory is now configurable.
- Fixed false positive security scans during tool loading.
- Fixed quickstart and guide examples that didn't run as written.
- Fixed model config pass through bug for `temperature`.
- Aligned request/response size limits with the shared package, and raised the maximum output-token ceiling.

## [2.1.0] - 2026-07-15

### Added

- Outbound mTLS support via `FOUNDRY_TLS_CLIENT_CERTFILE` and
  `FOUNDRY_TLS_CLIENT_KEYFILE` env vars (FOUNDRY-722)
- Fail-fast validation when configured cert/key files are missing
- Graceful degradation (warning) when only one of the two vars is set

### Changed

- STIG findings V-222532 and V-222534 updated from `not_applicable` to
  `meets_requirement` with outbound mTLS evidence

## [2.0.0] - 2026-07-08

### Changed

- **Breaking:** `ChatHistoryManager` and orchestrator session archival
  behavior (FOUNDRY-711)

## [1.0.0] - 2026-06-29

Initial public release.
