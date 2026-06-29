# Sessions, MCP, and A2A

## Session Persistence

`StrandsAgentFactory` creates a `SessionManager` when `session_type` is
configured.  The session manager is passed to `strands.Agent` so conversation
history survives across requests.

### File Sessions

Store sessions on the local filesystem:

```python
from foundry_strands_agent import StrandsAgentConfig, StrandsSessionManagerType

config = StrandsAgentConfig(
    session_id="user-123",
    session_type=StrandsSessionManagerType.FILE,
    session_storage_dir="/tmp/agent-sessions",
)
```

Sessions are stored as `session.json` files under `session_storage_dir`.

### S3 Sessions

Store sessions in an S3 bucket:

```python
config = StrandsAgentConfig(
    session_id="user-123",
    session_type=StrandsSessionManagerType.S3,
    session_s3_bucket="my-sessions-bucket",
    session_s3_prefix="agents/",
)
```

`session_s3_bucket` is required when `session_type = "s3"`.  AWS credentials
are resolved from the standard credential chain.

### Reading Session History

`ChatHistorian` implements the `ChatHistoryManager` protocol and exposes
session history directly:

```python
from foundry_strands_agent import ChatHistorian
from foundry_agent_core import DependencyContainer

historian = ChatHistorian(container)

# List all sessions
sessions = await historian.get_chat_sessions_history(limit=20, offset=0)

# List messages in a session
messages = await historian.get_chat_session_messages_history(
    session_id="user-123",
    limit=50,
    offset=0,
)

# Create a new session record
session = await historian.create_chat_session_messages_history("user-456")

# Delete a session and its messages
await historian.delete_chat_session_messages_history("user-123")
```

Alternatively, access the historian through `AgentService.chat_history` after
the service is initialized:

```python
async with service.service_lifecycle():
    sessions = await service.chat_history.get_chat_sessions_history()
```

### Session ID Masking (STIG V-222577)

To satisfy STIG control V-222577 ("The application must not expose session
IDs"), raw `session_id` values are never written to logs or serialized model
output. The masking utility lives in `foundry-agent-core` so every Foundry
package shares one implementation: `foundry_agent_core.mask_session_id()`
produces a deterministic, non-reversible token (`sid:<hex>`) that is emitted in
place of the raw identifier, and `foundry_agent_core.redact_session_ids()`
scrubs `session_id` values out of serialized blobs before they are logged. The
in-memory value is preserved for session persistence and lookup.

Masking works with no configuration — it uses a fixed built-in salt. Because
the token is deterministic, the same session masks to the same value
everywhere, preserving the ability to correlate log lines for one session
without disclosing the raw identifier. `QueryRequest` applies
`mask_session_id` through a Pydantic `field_serializer`, so any
`model_dump()`/`model_dump_json()` that reaches a log is redacted automatically.

## MCP Servers

`StrandsAgentFactory` connects to MCP servers over streamable HTTP transport
and exposes their tools to the agent automatically.

Configure servers in `StrandsAgentConfig`:

```python
config = StrandsAgentConfig(
    mcp_servers=[
        {
            "url": "http://localhost:9000/mcp",
            "headers": {"Authorization": "Bearer token"},
        },
        {
            "url": "http://tools-service:9001/mcp",
        },
    ]
)
```

Or in YAML:

```yaml
mcp_servers:
  - url: http://localhost:9000/mcp
    headers:
      Authorization: "Bearer token"
  - url: http://tools-service:9001/mcp
```

Each server's tools are merged into the agent's tool set alongside any
registered local tools.

## A2A Agents

Agent-to-agent (A2A) integration uses `A2AClientToolProvider` from
`strands_tools` to expose remote agents as callable tools.  The factory
performs eager capability discovery on startup so the agent knows each
remote agent's available actions.

```python
config = StrandsAgentConfig(
    a2a_servers=[
        {
            "url": "http://specialist-agent:8080",
            "name": "specialist",
            "description": "A domain-specialist agent for complex queries",
        },
    ]
)
```

Or in YAML:

```yaml
a2a_servers:
  - url: http://specialist-agent:8080
    name: specialist
    description: "A domain-specialist agent for complex queries"
```

The remote agent appears as a tool named after its `name` field.  The calling
agent routes subtasks to it exactly as it would any local tool.
