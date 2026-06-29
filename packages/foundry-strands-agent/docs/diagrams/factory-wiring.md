# Factory Wiring

How `StrandsAgentFactory.create_agent` assembles a `strands.Agent`.

```mermaid
flowchart TD
    Config["StrandsAgentConfig"]
    ModelConfig["AgentModelConfig\n(provider, model_id, ...)"]
    ProviderReg["Provider Registry\nbedrock | ollama | llamacpp | nims"]
    Model["strands.Model"]
    SessionReg["Session Registry\nfile | s3"]
    Session["SessionManager\n(optional)"]
    MCP["MCPClient list\n(optional)"]
    A2A["A2AClientToolProvider\n(optional)"]
    Tools["Tool list\n(from AgentToolRegistry)"]
    ConvMgr["SlidingWindowConversationManager"]
    State["AgentState\n(initial_values)"]
    Agent["strands.Agent"]

    Config --> ModelConfig
    ModelConfig --> ProviderReg
    ProviderReg --> Model
    Config --> SessionReg
    SessionReg --> Session
    Config --> MCP
    Config --> A2A
    Tools --> Agent
    Model --> Agent
    Session --> Agent
    MCP --> Agent
    A2A --> Agent
    ConvMgr --> Agent
    State --> Agent
```

`create_agent` is the main entry point; `create_agent_with_tool_registry`
and `create_agent_with_mcp_clients` are convenience variants.  All three
delegate to the same internal assembly path.  Provider and session manager
factories are registered at class initialisation and can be extended via
`register_model_provider` and `register_session_manager`.
