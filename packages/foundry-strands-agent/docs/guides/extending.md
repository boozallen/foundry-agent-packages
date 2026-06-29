# Extending

`foundry-strands-agent` is built on protocols from `foundry-agent-core`.
Every component — factory, tool registry, chat historian, query processor,
response processor — is injected via the DI container, so you can swap
any of them by registering a different implementation.

## Adding a Custom Model Provider

`StrandsAgentFactory` uses a provider registry keyed by the `provider` string
in `AgentModelConfig`.  Register a new factory function to add a provider:

```python
from strands.models import Model
from foundry_strands_agent import StrandsAgentFactory, AgentModelConfig

def my_custom_model(config: AgentModelConfig) -> Model:
    from my_provider import MyModel
    return MyModel(endpoint=config.nims_base_url, api_key=config.nims_api_key)

factory = StrandsAgentFactory(container)
factory.register_model_provider("my-provider", my_custom_model)

config = StrandsAgentConfig(
    model=AgentModelConfig(provider="my-provider", nims_base_url="http://...")
)
```

The built-in providers are: `bedrock`, `ollama`, `llamacpp`, `nims`.

## Adding a Custom Session Manager

Session managers are registered under a `StrandsSessionManagerType` key:

```python
from strands.session import SessionManager

def my_redis_session_manager(session_id: str, **kwargs) -> SessionManager:
    from my_pkg import RedisSessionManager
    return RedisSessionManager(session_id=session_id, redis_url=kwargs["redis_url"])

factory.register_session_manager("redis", my_redis_session_manager)
```

Pass the name as `session_type` in your config (as a raw string).

## Replacing the Query Processor

Implement the `QueryProcessor` protocol from `foundry-agent-core` and register
it in the container before calling `create_agent_service`:

```python
from foundry_agent_core import QueryProcessor, AgentRequest, AgentResponse

class MyQueryProcessor:
    async def process_query(self, request: AgentRequest) -> AgentResponse:
        ...

container.register(QueryProcessor, MyQueryProcessor)
service = create_agent_service(container)
```

The same pattern applies to `AgentFactory`, `AgentToolRegistry`,
`ChatHistoryManager`, and `ResponseProcessor`.

## Replacing the Response Processor

Override `DefaultResponseProcessor` to change how agent output is transformed:

```python
from foundry_strands_agent import DefaultResponseProcessor
from foundry_agent_core import AgentRequest, AgentResponse

class MyResponseProcessor(DefaultResponseProcessor):
    async def process_response(self, agent_response, request, start_time, query_id):
        base = await super().process_response(agent_response, request, start_time, query_id)
        # Post-process: strip disclaimers, reformat, etc.
        base.response_text = my_cleanup(base.response_text)
        return base

container.register(ResponseProcessor, MyResponseProcessor)
```

## Manual Wiring (without create_agent_service)

`create_agent_service` is a convenience factory.  For fine-grained control,
wire components manually:

```python
from foundry_strands_agent import (
    AgentService,
    StrandsAgentFactory,
    AgentToolRegistryManager,
    QueryOrchestrator,
    DefaultResponseProcessor,
    ChatHistorian,
)

factory   = StrandsAgentFactory(container)
registry  = AgentToolRegistryManager(container)
historian = ChatHistorian(container)
processor = DefaultResponseProcessor()
orchestrator = QueryOrchestrator(container, factory, registry, processor)

service = AgentService(
    container=container,
    agent_factory=factory,
    tool_registry=registry,
    query_processor=orchestrator,
    chat_historian=historian,
    response_processor=processor,
)
```

## Agent State

Pass initial state values to seed the Strands `AgentState` on agent creation:

```python
config = StrandsAgentConfig(
    agent_state_initial_values={
        "user_name": "Alice",
        "preferred_language": "en",
    }
)
```

Values must be JSON-serializable and the total serialized size must be under
1 MB.  The agent can read and update state through the Strands SDK during a
turn.
