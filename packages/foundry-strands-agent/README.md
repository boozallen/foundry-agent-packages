# foundry-strands-agent

![Status: Available](https://img.shields.io/badge/status-available-brightgreen)
![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

AWS Strands SDK adapter that implements the `foundry-agent-core`
protocol surface. The core feature is an autonomous agent loop:
`AgentService` receives a query, creates a `strands.Agent` with the
configured tools, and lets the agent decide which tools to call and when
to stop. Multiple model providers (Bedrock, Ollama, LlamaCpp, NIMS),
session persistence (file or S3), MCP server integration, and A2A
agent-to-agent communication are all wired through a single,
protocol-based factory.

## Install

```bash
uv add foundry-strands-agent
# or
pip install foundry-strands-agent
```

Requires AWS credentials (Bedrock), a running Ollama instance, a
LlamaCpp server, or a NIMS / OpenAI-compatible endpoint.

## Quickstart

```python
import asyncio
from foundry_strands_agent import StrandsAgentConfig, create_agent_service
from foundry_agent_core import create_dependency_container, AgentRequest

async def main():
    config = StrandsAgentConfig()
    container = create_dependency_container()
    container.register_factory(StrandsAgentConfig, lambda: config)

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
| Services | `AgentService`, `create_agent_service`, `QueryOrchestrator`, `DefaultResponseProcessor` |
| Config | `StrandsAgentConfig`, `AgentConfig`, `AgentModelConfig`, `ModelGuardrailConfig`, `StrandsSessionManagerType` |
| Factories | `StrandsAgentFactory`, `AgentToolRegistryManager`, `AgentFactory`, `AgentToolRegistry` |
| Sessions | `ChatHistorian`, `ChatHistoryManager`, `create_chat_history_manager` |
| Lifecycle | `RequestLifecycleManager`, `ExecutionStrategy`, `ExecutionContext`, `RetryPolicy`, `RetryContext` |
| Exceptions | `AgentServiceError`, `AgentServiceInitializationError`, `AgentServiceShutdownError` |

## Security

- **Session IDs** validated against `^[A-Za-z0-9_-]{8,128}$` (DISA STIG V-222609)
- **TLS 1.2+** enforced on all outbound HTTPS (NIMS, MCP, A2A, Bedrock) with `CERT_REQUIRED` (DISA STIG V-222596)
- **File-backed sessions** encrypted with AES-256-GCM via `SESSION_ENCRYPTION_KEY` (DISA STIG V-222588/V-222589)
- **Session destruction** via `ChatHistoryManager.on_logoff(session_id)` (DISA STIG V-222578)

See [`security/stig_checklist.json`](security/stig_checklist.json) for the full control list.

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
