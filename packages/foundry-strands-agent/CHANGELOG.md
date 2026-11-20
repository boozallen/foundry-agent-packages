# Changelog

All notable changes to `foundry-strands-agent` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## 3.2.4 - 2026-11-18

### Features

- guard session restore against dangling tool_use

### Fixes

- replace the end-of-life default Bedrock model
- raise chunk_index ceiling to match max document size
- remove stale alpha status from docs and package metadata
- implement ${VAR} env-var interpolation for MCP server headers
- mask session identifiers and query content in agent logs
- drop dedup checks on tls warning
- list encrypted file and S3 chat sessions
- UTF-8 dict byte caps and public validate_bounded_dict
- reconnect shared MCP clients in place after a dropped connection
- make add_consumer/remove_consumer non-blocking during MCP reconnect
- never strand a queued MCP consumer change or mask a reconnect error
- recover a shared MCP client after a failed reconnect
- skip a TOOL_SPEC tool Strands can't load or would misname, and warn on same-named tools
- bind the memory tool's knowledge base id and region

### Maintenance

- Security and maintenance updates
- document tls warning volume change
- Add per-context agent builder for A2A agent_factory=
- Packaging and dependency updates

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
  `FOUNDRY_TLS_CLIENT_KEYFILE` env vars
- Fail-fast validation when configured cert/key files are missing
- Graceful degradation (warning) when only one of the two vars is set

### Changed

- STIG findings V-222532 and V-222534 updated from `not_applicable` to
  `meets_requirement` with outbound mTLS evidence

## [2.0.0] - 2026-07-08

### Changed

- **Breaking:** `ChatHistoryManager` and orchestrator session archival
  behavior

## [1.0.0] - 2026-06-29

Initial public release.
