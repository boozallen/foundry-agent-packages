# Component Map

Internal structure of `foundry-strands-agent`.

```mermaid
graph TD
    SVC["AgentService"]
    Config["StrandsAgentConfig\n+ AgentModelConfig"]
    Factory["StrandsAgentFactory"]
    Registry["AgentToolRegistryManager"]
    Orchestrator["QueryOrchestrator"]
    Processor["DefaultResponseProcessor"]
    Historian["ChatHistorian"]
    Lifecycle["RequestLifecycleManager"]
    Agent["strands.Agent"]
    Model["strands.Model\n(Bedrock / Ollama / LlamaCpp / NIMS)"]
    Session["SessionManager\n(File / S3)"]
    MCP["MCPClient\n(streamable HTTP)"]
    A2A["A2AClientToolProvider"]
    ToolLoader["tool_loader\n(load_tool_from_module\nload_tool_from_file)"]

    Config --> Factory
    Config --> SVC
    SVC --> Factory
    SVC --> Registry
    SVC --> Orchestrator
    SVC --> Historian
    SVC --> Lifecycle
    Orchestrator --> Factory
    Orchestrator --> Processor
    Factory --> Model
    Factory --> Session
    Factory --> MCP
    Factory --> A2A
    Factory --> Agent
    Registry --> ToolLoader
    Agent --> Model
```

**Configuration** flows top-down: `StrandsAgentConfig` initialises
`StrandsAgentFactory`, which assembles a `strands.Agent` from the selected
model, session manager, MCP clients, and A2A providers.  `AgentService`
coordinates the full pipeline — it owns the lifecycle manager, delegates
query orchestration to `QueryOrchestrator`, and exposes chat history through
`ChatHistorian`.
