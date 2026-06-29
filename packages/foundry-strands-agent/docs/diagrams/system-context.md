# System Context

Where `foundry-strands-agent` fits in your stack.

```mermaid
flowchart LR
    App["Your Application"]
    SVC["AgentService\n(foundry-strands-agent)"]
    Bedrock["Amazon Bedrock"]
    Ollama["Ollama\nlocalhost:11434"]
    NIMS["NIMS / OpenAI-compatible\nnims_base_url"]
    MCP["MCP Servers\nstreamable HTTP"]
    A2A["A2A Agents\nA2AClientToolProvider"]

    App -- "process_query(AgentRequest)" --> SVC
    SVC -- "provider: bedrock" --> Bedrock
    SVC -- "provider: ollama" --> Ollama
    SVC -- "provider: nims" --> NIMS
    SVC -- "tool calls" --> MCP
    SVC -- "tool calls" --> A2A
```

Your application calls `AgentService.process_query` with an `AgentRequest`.
The service creates a `strands.Agent` configured for the selected provider,
attaches all registered tools, and runs the autonomous agent loop.  Your
application never talks to the model endpoint or tool backends directly.
