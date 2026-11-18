# foundry-strands-agent

![Python](https://img.shields.io/badge/python-3.13%2B-blue)

AWS Strands SDK adapter that implements the [`foundry-agent-core`](../foundry-agent-core/README.md)
protocol surface. The core feature is an autonomous agent loop:
`AgentService` receives a query, creates a `strands.Agent` with the
configured tools, and lets the agent decide which tools to call and when
to stop. Multiple model providers (Bedrock, Ollama, LlamaCpp, NIMS),
session persistence (file or S3), MCP server integration, and A2A
agent-to-agent communication are all wired through a single,
protocol-based factory.

## Install

Install a released wheel from this repo's
[GitHub Releases](https://github.com/boozallen/foundry-agent-packages/releases).
See [Adopting these packages](../../docs/foundry/releases/adopting.md)
for the full flow - pinning a release URL directly for evaluation, or
hosting the wheel in your own index for production, plus verifying the
SBOM/scan assets.

Requires AWS credentials (Bedrock), a running Ollama instance, a
LlamaCpp server, or a NIMS / OpenAI-compatible endpoint.

## Quickstart

```python
import asyncio
from foundry_strands_agent import (
    StrandsAgentConfig,
    create_agent_service,
    create_default_container,
)
from foundry_agent_core import AgentRequest

async def main():
    config = StrandsAgentConfig()
    container = create_default_container(config)

    service = create_agent_service(container)
    async with service.service_lifecycle():
        request = AgentRequest(session_id="demo-session-01", query="What is 2 + 2?")
        response = await service.process_query(request)
        print(response.content)

asyncio.run(main())
```

## What's in the box

| Surface | Highlights |
|---------|------------|
| Services | `AgentService`, `create_agent_service`, `create_default_container`, `QueryOrchestrator`, `DefaultResponseProcessor` |
| Config | `StrandsAgentConfig`, `AgentConfig`, `AgentModelConfig`, `ModelGuardrailConfig`, `StrandsSessionManagerType` |
| Factories | `StrandsAgentFactory`, `AgentToolRegistryManager`, `AgentFactory`, `AgentToolRegistry` |
| Sessions | `ChatHistorian`, `ChatHistoryManager`, `create_chat_history_manager` |
| Lifecycle | `RequestLifecycleManager`, `ExecutionStrategy`, `ExecutionContext`, `RetryPolicy`, `RetryContext` |
| Exceptions | `AgentServiceError`, `AgentServiceInitializationError`, `AgentServiceShutdownError` |

## Security

- **Session IDs** validated against `^[A-Za-z0-9_-]{8,128}$` (DISA STIG V-222609)
- **TLS 1.2+** enforced on all outbound HTTPS (NIMS, MCP, A2A, Bedrock) with `CERT_REQUIRED` (DISA STIG V-222596)
- **Outbound mTLS** supported via `FOUNDRY_TLS_CLIENT_CERTFILE` and `FOUNDRY_TLS_CLIENT_KEYFILE` env vars for agent-to-agent calls requiring mutual TLS (DISA STIG V-222532/V-222534)
- **File-backed sessions** encrypted with AES-256-GCM via `SESSION_ENCRYPTION_KEY` (DISA STIG V-222588/V-222589)
- **Session destruction** via `ChatHistoryManager.on_logoff(session_id)` (DISA STIG V-222578)
- **Dangling `tool_use` guard**: restoring a session (FILE or S3 backend) whose persisted history
  ends in an unresolved assistant `tool_use` block never lets that block execute without an
  intervening model turn - closes a gap left by the Strands SDK's own mitigation, which only
  covers resuming with a new prompt, not a bare `prompt=None` resume. Configurable via
  `session_restore_dangling_tool_use` (`STRANDS_SESSION_RESTORE_DANGLING_TOOL_USE`):
  `"sanitize"` (default - insert a synthetic `tool_result`) or `"reject"` (raise
  `AgentCreationError` instead). See `session_guard.py`.

## Security policy: transport encryption

All outbound HTTPS connections use `ssl.SSLContext` configured with a TLS 1.2
minimum version and certificate verification required. The context comes from
`create_tls_context()` in `tls.py`.

**Covered providers:**

| Provider | TLS enforcement |
|----------|------------------|
| NIMS / OpenAI-compatible | `create_tls_context()` on the model's `httpx.Client` |
| MCP servers | `create_mcp_http_client()` calls `create_tls_context()` |
| A2A agents | `create_tls_context()` passed as `httpx_client_args["verify"]` |
| Bedrock | Delegates to the AWS SDK. No custom `SSLContext` is injected. |
| Ollama / LlamaCpp | Localhost development endpoints. TLS is not enforced. |

**Development escape hatch:**

Set `FOUNDRY_TLS_VERIFY=false` to disable certificate verification against a
self-signed certificate in local development. The TLS 1.2 floor still applies
even with verification disabled.

```bash
export FOUNDRY_TLS_VERIFY=false
```

**Outbound mutual TLS (mTLS):**

Set both `FOUNDRY_TLS_CLIENT_CERTFILE` and `FOUNDRY_TLS_CLIENT_KEYFILE` to
present a client certificate on outbound connections.

```bash
export FOUNDRY_TLS_CLIENT_CERTFILE=/path/to/client.crt
export FOUNDRY_TLS_CLIENT_KEYFILE=/path/to/client.key
```

Setting only one of the two logs a warning and skips client certificate
loading; it does not raise an error. A path that does not exist at either
variable raises `FileNotFoundError` naming the missing file.

On POSIX platforms, the key file's permission bits are checked before it is
loaded: a `FOUNDRY_TLS_CLIENT_KEYFILE` readable or writable by group or other
logs a warning naming the offending bits (`chmod 600` to fix). This is a
detection aid, not enforcement — the key is still loaded either way, and the
check is skipped entirely on non-POSIX platforms (STIG V-222551).

## Documentation

| Guide | |
|-------|---|
| [Quickstart](docs/guides/quickstart.md) | End-to-end setup with Bedrock or Ollama |
| [Configuration](docs/guides/configuration.md) | YAML + env-var field reference |
| [Tools](docs/guides/tools.md) | Registering tools from modules, files, and MCP servers |
| [Sessions](docs/guides/sessions.md) | File / S3 session persistence, MCP, A2A |
| [Extending](docs/guides/extending.md) | Swapping providers, custom factories, DI patterns |
| [Observability](docs/guides/observability.md) | Logging, retries, execution strategies |
| [Diagrams](docs/diagrams/) | System context, component map, agent loop, factory wiring |
| [Changelog](CHANGELOG.md) | Release history |
| [Contributing](CONTRIBUTING.md) | Dev setup, testing, PR conventions |

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
