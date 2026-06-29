# Observability

## Logging

Control verbosity via `StrandsAgentConfig.log_level` (default `INFO`):

```python
from foundry_strands_agent import StrandsAgentConfig

config = StrandsAgentConfig(log_level="DEBUG")
```

Or via environment variable:

```bash
STRANDS__LOG_LEVEL=DEBUG
```

Key log events and the fields they carry:

| Event | Extra fields |
|-------|-------------|
| Query received | `session_id`, `query_id`, `execution_strategy`, `query_preview` |
| Query completed | `session_id`, `query_id`, `processing_time_ms` |
| Query failed | `session_id`, `query_id`, `error`, `error_type` |
| Tool loaded | `tool_name`, `source` |
| Tool load failed | `tool_path`, `error` |
| Service initialized | — |
| Service shutdown | `active_queries_count` |

## Strands Telemetry

Enable the Strands SDK's built-in telemetry to emit OTel spans:

```python
config = StrandsAgentConfig(observability_enabled=True)
```

Configure an OTel exporter before creating the service and spans will flow to
any OTLP-compatible backend (Jaeger, Tempo, Honeycomb, Langfuse, etc.):

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
```

## Health Checks

`AgentService.get_service_health()` returns a snapshot of all component states:

```python
async with service.service_lifecycle():
    health = await service.get_service_health()
    print(health)
```

```python
{
    "service_initialized": True,
    "shutdown_requested": False,
    "active_queries_count": 0,
    "components": {
        "agent_factory": True,
        "tool_registry": True,
        "query_processor": True,
        "chat_history_manager": True,
        "response_processor": True,
        "lifecycle_manager": True,
    },
    "tool_registry_stats": {
        "total_tools": 3,
        "validated": True,
        "tool_names": ["web_search", "get_weather", "calculator"],
    },
}
```

## Execution Strategies

Pass an `ExecutionStrategy` to `process_query` to control how the lifecycle
manager handles errors and timeouts:

```python
from foundry_strands_agent import ExecutionStrategy

response = await service.process_query(request, ExecutionStrategy.RESILIENT)
```

| Strategy | Behaviour |
|----------|-----------|
| `STANDARD` | Single attempt; raises on any error. |
| `RESILIENT` | Retries transient errors with the configured retry policy. |
| `HIGH_AVAILABILITY` | Retries with circuit-breaker protection; fails fast when the breaker is open. |

## Retry Policies

`RetryPolicy` controls backoff behaviour under `RESILIENT` and
`HIGH_AVAILABILITY` strategies:

| Policy | Behaviour |
|--------|-----------|
| `NONE` | No retries. |
| `LINEAR` | Fixed delay between retries. |
| `EXPONENTIAL` | Delay doubles each attempt. |
| `CIRCUIT_BREAKER` | Stops retrying after `consecutive_failures` threshold; auto-resets after a timeout. |

`RetryContext` tracks attempt count, consecutive failures, and circuit-breaker
state across a single query execution.

## Query Timeout

The default query timeout is 30 seconds.  Override `max_response_time_ms` in
config to adjust:

```python
config = StrandsAgentConfig(max_response_time_ms=60000)  # 60 seconds
```

Queries that exceed the timeout raise `QueryProcessingError` and are cleaned up
from the active-query tracker.

## Graceful Shutdown

`AgentService.shutdown()` signals the shutdown event and waits up to 30 seconds
for in-flight queries to complete before cancelling stragglers:

```python
await service.shutdown()
```

Use the `service_lifecycle()` context manager to get automatic init and
shutdown in a single block:

```python
async with service.service_lifecycle():
    ...
```
