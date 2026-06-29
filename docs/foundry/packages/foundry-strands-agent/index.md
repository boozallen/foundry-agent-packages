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
    config = StrandsAgentConfig()  # default: bedrock + claude-sonnet-4
    container = create_dependency_container()
    container.register_factory(StrandsAgentConfig, lambda: config)

    service = create_agent_service(container)
    async with service.service_lifecycle():
        request = AgentRequest(session_id="demo-session-01", query="What is 2 + 2?")
        response = await service.process_query(request)
        print(response.content)

asyncio.run(main())
```

### Switching providers

```python
from foundry_strands_agent import StrandsAgentConfig, AgentModelConfig

config = StrandsAgentConfig(
    model=AgentModelConfig(
        provider="ollama",            # or "llamacpp", "nims"
        model_id="llama3.1",
        ollama_url="http://localhost:11434",
    )
)
```

### Streaming

```python
async for event in service.process_query_stream(request):
    if event["type"] == "token":
        print(event["content"], end="", flush=True)
```

## The agent loop

```mermaid
sequenceDiagram
    participant App
    participant SVC as AgentService
    participant Agent as strands.Agent
    participant Model
    participant Tool

    App->>SVC: process_query(AgentRequest)
    SVC->>Agent: agent(query)

    loop Autonomous turns
        Agent->>Model: chat completion
        Model-->>Agent: response

        alt model calls a tool
            Agent->>Tool: tool_function(args)
            Tool-->>Agent: tool result
        else model returns final answer
            Agent-->>SVC: final text
        end
    end

    SVC-->>App: AgentResponse
```

The agent decides which tools to call and when it has enough context to
return a final answer. The orchestrator applies a configurable timeout
and hands the raw agent output to `DefaultResponseProcessor`, which
extracts text, scores confidence, and normalizes the response.

## What's in the box

| Surface | Highlights |
|---------|------------|
| Services | `AgentService`, `create_agent_service`, `QueryOrchestrator`, `DefaultResponseProcessor` |
| Config | `StrandsAgentConfig`, `AgentModelConfig`, `ModelGuardrailConfig`, `StrandsSessionManagerType` |
| Factories | `StrandsAgentFactory`, `AgentToolRegistryManager`, `AgentFactory`, `AgentToolRegistry` |
| Sessions | `ChatHistorian`, `ChatHistoryManager`, `create_chat_history_manager` |
| Lifecycle | `RequestLifecycleManager`, `ExecutionStrategy`, `ExecutionContext`, `RetryPolicy`, `RetryContext` |
| Exceptions | `AgentServiceError`, `AgentServiceInitializationError`, `AgentServiceShutdownError` |

## Security

- **Session IDs** validated against `^[A-Za-z0-9_-]{8,128}$` (DISA STIG V-222609)
- **TLS 1.2+** enforced on all outbound HTTPS (NIMS, MCP, A2A, Bedrock) with `CERT_REQUIRED` (DISA STIG V-222596)
- **File-backed sessions** encrypted with AES-256-GCM via `SESSION_ENCRYPTION_KEY` (DISA STIG V-222588 / V-222589)
- **Session destruction** via `ChatHistoryManager.on_logoff(session_id)` (DISA STIG V-222578)

See the
[STIG checklist](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-strands-agent/security/stig_checklist.json)
for the full control list.

## Reference

- [README](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-strands-agent/README.md) — full field reference, tool loading, sessions, MCP, A2A, extending
- [Changelog](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-strands-agent/CHANGELOG.md)
- [Source](https://github.com/boozallen/foundry-agent-packages/tree/main/packages/foundry-strands-agent)
- [License (Apache-2.0)](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-strands-agent/LICENSE)
