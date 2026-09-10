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
- **`SESSION_ENCRYPTION_KEY`** — every example below passes a `session_id`,
  which defaults chat history to file-backed storage (encrypted at rest, AES-256-GCM,
  under `$TMPDIR/strands/sessions/` unless `session_storage_dir` is set). A
  64-character hex string (32 bytes):
  ```bash
  export SESSION_ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  ```
  Generate this once per shell session and reuse it - regenerating it on a
  later run raises `cryptography.exceptions.InvalidTag` when decrypting a
  session file an earlier run already wrote under the same `session_id` with
  the old key. Recover either by exporting the same key again or by deleting
  the stale file under `$TMPDIR/strands/sessions/`.

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
    StrandsAgentConfig,
    create_agent_service,
    create_default_container,
)
from foundry_agent_core import AgentRequest

async def main():
    config = StrandsAgentConfig()  # provider: bedrock, model: claude-sonnet-4
    container = create_default_container(config)

    service = create_agent_service(container)

    async with service.service_lifecycle():
        request = AgentRequest(session_id="my-session", query="What is 2 + 2?")
        response = await service.process_query(request)
        print(response.content)

asyncio.run(main())
```

`create_default_container` registers this package's default implementation for
every protocol `create_agent_service` resolves — `AgentFactory`,
`AgentToolRegistry`, `QueryProcessor`, `ChatHistoryManager`, and
`ResponseProcessor` — plus the config instance you pass it. Swap any one of
them with the matching keyword argument (for example
`create_default_container(config, query_processor=my_processor)`). See
[Extending](extending.md) if you need to wire the components yourself.

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

`process_query_stream` yields token and result events as an async generator.
This replaces the `response = await service.process_query(request)` line
inside the `main()` function from Option A or B above — it is not a
standalone script, since it reuses the same `service`:

```python
async with service.service_lifecycle():
    request = AgentRequest(session_id="demo-session-02", query="Explain recursion briefly.")

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
