# Quickstart

Get a Strands agent running end-to-end in under five minutes.

## Prerequisites

- **uv** — package manager (`pip install uv` or see [uv docs](https://docs.astral.sh/uv/))
- One of the following inference backends:
  - **Amazon Bedrock** — AWS credentials with Bedrock access in your environment
  - **Ollama** — for local development without cloud credentials:
    ```bash
    ollama serve
    ollama pull llama3.1
    ```

## Install

```bash
uv add foundry-strands-agent
```

## Option A — Bedrock (default)

Bedrock is the default provider.  Set your AWS region and ensure credentials
are available (environment variables, instance profile, or `~/.aws/credentials`):

```bash
export AWS_DEFAULT_REGION=us-east-1
```

```python
import asyncio
from foundry_strands_agent import (
    AgentService,
    StrandsAgentConfig,
    StrandsAgentFactory,
    AgentToolRegistryManager,
    QueryOrchestrator,
    DefaultResponseProcessor,
    ChatHistorian,
    create_agent_service,
)
from foundry_agent_core import DependencyContainer, AgentRequest

async def main():
    config = StrandsAgentConfig()  # provider: bedrock, model: claude-sonnet-4
    container = DependencyContainer()
    container.register_instance(StrandsAgentConfig, config)

    service = create_agent_service(container)

    async with service.service_lifecycle():
        request = AgentRequest(session_id="my-session", query="What is 2 + 2?")
        response = await service.process_query(request)
        print(response.response_text)

asyncio.run(main())
```

`create_agent_service` resolves all protocol dependencies from the container.
See [Extending](extending.md) for manual wiring.

## Option B — Ollama

Override the provider in config:

```python
from foundry_strands_agent import StrandsAgentConfig, AgentModelConfig

config = StrandsAgentConfig(
    model=AgentModelConfig(
        provider="ollama",
        model_id="llama3.1",
        ollama_url="http://localhost:11434",
    )
)
```

## Send a Streaming Query

`process_query_stream` yields token and result events as an async generator:

```python
async with service.service_lifecycle():
    request = AgentRequest(session_id="demo", query="Explain recursion briefly.")

    async for event in service.process_query_stream(request):
        if event["type"] == "token":
            print(event["content"], end="", flush=True)
        elif event["type"] == "result":
            print()  # newline after streaming completes
```

## Next Steps

- [Configuration](configuration.md) — tune the model, session storage, and env vars
- [Tools](tools.md) — give the agent tools to call
- [Sessions](sessions.md) — persist conversation history with file or S3 backends
- [Observability](observability.md) — logging, health checks, retry policies
