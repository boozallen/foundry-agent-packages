# Agent Loop

Full sequence from `process_query` call to final `AgentResponse`.

```mermaid
sequenceDiagram
    participant App
    participant SVC as AgentService
    participant Orch as QueryOrchestrator
    participant Factory as StrandsAgentFactory
    participant Agent as strands.Agent
    participant Model as Model Endpoint
    participant Tool as Tool Function

    App->>SVC: process_query(AgentRequest)
    SVC->>SVC: validate initialized, not shutting down
    SVC->>SVC: create ExecutionContext
    SVC->>Orch: process_query(AgentRequest)
    Orch->>Orch: validate query length, normalize
    Orch->>Factory: create_agent_with_tool_registry(registry)
    Factory->>Agent: strands.Agent(model, tools, session_manager, ...)
    Orch->>Agent: agent(query)

    loop Autonomous turns
        Agent->>Model: chat completion request
        Model-->>Agent: response

        alt model wants to call a tool
            Agent->>Tool: tool_function(args)
            Tool-->>Agent: tool result
            Agent->>Agent: append tool result to context
        else model returns final answer
            Agent-->>Orch: final text
        end
    end

    Orch->>Orch: DefaultResponseProcessor.process_response()
    Orch-->>SVC: AgentResponse
    SVC-->>App: AgentResponse
```

The agent loop is fully autonomous — `strands.Agent` decides which tools to
call and when it has enough context to return a final answer.  The orchestrator
applies a configurable timeout and hands the raw agent output to
`DefaultResponseProcessor`, which extracts text, scores confidence, and
normalises the response before returning it to the caller.
