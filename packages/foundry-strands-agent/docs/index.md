# foundry-strands-agent

A Strands SDK adapter that implements the `foundry-agent-core` protocol surface.

## Guides

| Guide | Description |
|-------|-------------|
| [Quickstart](guides/quickstart.md) | End-to-end setup with Bedrock or Ollama |
| [Configuration](guides/configuration.md) | `StrandsAgentConfig` and `AgentModelConfig` field reference, YAML + env vars |
| [Tools](guides/tools.md) | Registering tools, loading from modules and files, security model |
| [Sessions](guides/sessions.md) | File and S3 session persistence, MCP servers, A2A agents |
| [Extending](guides/extending.md) | Swapping providers, custom factories, DI container patterns |
| [Observability](guides/observability.md) | Logging, health checks, execution strategies, retry policies |

## Diagrams

| Diagram | Description |
|---------|-------------|
| [System Context](diagrams/system-context.md) | Where the package fits in your stack |
| [Component Map](diagrams/component.md) | Internal package structure |
| [Agent Loop](diagrams/agent-loop.md) | Full query-to-response sequence |
| [Factory Wiring](diagrams/factory-wiring.md) | How `StrandsAgentFactory` assembles a `strands.Agent` |
