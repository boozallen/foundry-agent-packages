# Configuration

`StrandsAgentConfig` is the top-level configuration object.  It composes
`AgentModelConfig` for the inference backend and carries agent-level settings
for tools, sessions, and observability.

## AgentModelConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `provider` | `str` | `"bedrock"` | Inference provider. One of: `bedrock`, `ollama`, `llamacpp`, `nims`. |
| `model_id` | `str` | `"us.anthropic.claude-sonnet-4-20250514-v1:0"` | Model identifier passed to the provider. |
| `ollama_url` | `str \| None` | `None` | Base URL for Ollama. Required when `provider = "ollama"`. |
| `llamacpp_url` | `str \| None` | `None` | Base URL for LlamaCpp server. Required when `provider = "llamacpp"`. |
| `nims_base_url` | `str \| None` | `None` | Base URL for a NIMS or OpenAI-compatible endpoint. Required when `provider = "nims"`. |
| `nims_api_key` | `str \| None` | `None` | API key for the NIMS endpoint. |
| `temperature` | `float` | `0.3` | Sampling temperature. |
| `max_tokens` | `int \| None` | `None` | Maximum tokens to generate (`None` = model default). |
| `top_p` | `float \| None` | `None` | Nucleus sampling threshold (`None` = model default). |
| `streaming` | `bool` | `True` | Enable streaming inference. |
| `region_name` | `str \| None` | `None` | AWS region for Bedrock. Falls back to `AWS_DEFAULT_REGION`. |
| `guardrails` | `ModelGuardrailConfig \| None` | `None` | Optional Bedrock guardrail configuration. |

### ModelGuardrailConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `guardrail_id` | `str` | — | Bedrock guardrail resource ID. |
| `guardrail_version` | `str` | — | Version of the guardrail to apply. |
| `guardrail_trace` | `str \| None` | `"enabled"` | Guardrail trace mode (`"enabled"` or `"disabled"`). |

## StrandsAgentConfig

### Identity

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | `AgentModelConfig` | `AgentModelConfig()` | Inference backend configuration. |
| `agent_name` | `str` | `"strands-base-agent"` | Logical name for this agent instance. |
| `agent_description` | `str` | (see source) | Human-readable description. |
| `agent_version` | `str` | `"1.0"` | Semantic version string. |
| `agent_port` | `int \| None` | `None` | Port the agent listens on (used by host processes). |
| `system_prompt` | `str` | (see source) | System prompt prepended to every conversation. |

### Tools

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tools_modules` | `list[str]` | `[]` | Python module paths loaded as tools on startup. |
| `tools_files` | `list[str]` | `[]` | Filesystem paths to `.py` tool files loaded on startup. |

See [Tools](tools.md) for the full tool loading and security model.

### Conversation

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_conversation_length` | `int` | `10` | Maximum turns retained in an in-memory conversation. |
| `conversation_window_size` | `int` | `100` | Maximum messages in the sliding window sent to the model. |
| `conversation_truncate_results` | `bool` | `False` | Truncate tool results when the window is full. |
| `enable_memory` | `bool` | `False` | Enable knowledge-base memory integration. Requires `knowledge_base_id`. |
| `knowledge_base_id` | `str \| None` | `None` | Bedrock knowledge base ID. Required when `enable_memory = True`. |
| `agent_state_initial_values` | `dict` | `{}` | Seed values for agent state on creation. JSON-serialized size must be < 1 MB. |

### Session

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `session_id` | `str \| None` | `None` | Session identifier. |
| `session_type` | `StrandsSessionManagerType \| None` | `None` | Storage backend. One of: `"file"`, `"s3"`. |
| `session_storage_dir` | `str \| None` | `None` | Directory for file session storage. |
| `session_s3_bucket` | `str \| None` | `None` | S3 bucket name. Required when `session_type = "s3"`. |
| `session_s3_prefix` | `str \| None` | `None` | Key prefix for S3 session objects. |

See [Sessions](sessions.md) for session setup details.

### Infrastructure

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mcp_servers` | `list[dict]` | `[]` | MCP server configs (streamable HTTP transport). |
| `a2a_servers` | `list[dict]` | `[]` | A2A agent configs for agent-to-agent tool calls. |

### Observability

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `log_level` | `str` | `"INFO"` | Python logging level. |
| `max_query_length` | `int` | `2000` | Maximum characters in a user query. |
| `default_similarity_threshold` | `float` | `0.7` | Similarity threshold for knowledge-base lookups. |
| `max_response_time_ms` | `int` | `30000` | Default query timeout in milliseconds. |
| `observability_enabled` | `bool` | `False` | Enable Strands telemetry integration. |

## Provider Options

### bedrock (default)

```python
from foundry_strands_agent import StrandsAgentConfig, AgentModelConfig

config = StrandsAgentConfig(
    model=AgentModelConfig(
        provider="bedrock",
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        region_name="us-east-1",
    )
)
```

Credentials are resolved from the standard AWS credential chain
(environment variables, instance profile, `~/.aws/credentials`).

### ollama

```python
config = StrandsAgentConfig(
    model=AgentModelConfig(
        provider="ollama",
        model_id="llama3.1",
        ollama_url="http://localhost:11434",
    )
)
```

### llamacpp

```python
config = StrandsAgentConfig(
    model=AgentModelConfig(
        provider="llamacpp",
        llamacpp_url="http://localhost:8080",
    )
)
```

### nims

Connects to any OpenAI-compatible endpoint including NVIDIA NIM:

```python
config = StrandsAgentConfig(
    model=AgentModelConfig(
        provider="nims",
        model_id="meta/llama-3.1-8b-instruct",
        nims_base_url="http://localhost:8000/v1",
        nims_api_key="nvapi-...",  # omit for local endpoints
    )
)
```

## YAML Config File

Create a `config.yaml`:

```yaml
model:
  provider: bedrock
  model_id: us.anthropic.claude-sonnet-4-20250514-v1:0
  region_name: us-east-1
  temperature: 0.5
  streaming: true

agent_name: my-production-agent
log_level: INFO
max_query_length: 4000
session_type: s3
session_s3_bucket: my-sessions-bucket
session_s3_prefix: agents/
```

Load it in code:

```python
from pathlib import Path
from foundry_strands_agent import StrandsAgentConfig

config = StrandsAgentConfig.from_yaml(Path("config.yaml"))
```

## Environment Variable Overrides

Any field can be overridden at runtime using the `STRANDS__` prefix with
double-underscore nesting:

```bash
# Override provider and model
STRANDS__MODEL__PROVIDER=ollama
STRANDS__MODEL__MODEL_ID=llama3.1
STRANDS__MODEL__OLLAMA_URL=http://localhost:11434

# Set NIMS API key without putting it in the config file
STRANDS__MODEL__NIMS_API_KEY=nvapi-...

# Tune observability
STRANDS__LOG_LEVEL=DEBUG
STRANDS__OBSERVABILITY_ENABLED=true
```

Environment variables take precedence over YAML values — useful for secrets
and per-environment overrides in CI/CD pipelines.

### Legacy env-only loading

`StrandsAgentConfig.from_env()` reads the `STRANDS_*` flat environment
variables directly (no YAML required).  The preferred path is `from_yaml`
with env overrides.
