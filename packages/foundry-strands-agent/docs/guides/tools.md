# Tools

Tools let the agent take actions — web searches, database lookups, calculations
— that are executed and fed back as context for the next turn.  The agent
autonomously decides which tools to call and when to stop.

## What is a Tool?

A tool is any Python function decorated with `@tool` from the Strands SDK, or
a module that exposes a `TOOL_SPEC` attribute.  The agent receives the tool's
name, description, and parameter schema; it returns a structured call that
`StrandsAgentFactory` dispatches and appends to the conversation.

## Registering Tools Programmatically

`AgentToolRegistryManager` is the concrete implementation of the
`AgentToolRegistry` protocol.

```python
from strands import tool
from foundry_strands_agent import AgentToolRegistryManager
from foundry_agent_core import DependencyContainer

@tool
def web_search(query: str) -> str:
    """Search the web and return a text summary."""
    ...  # your implementation

container = DependencyContainer()
registry = AgentToolRegistryManager(container)
registry.register_tool(web_search)
```

### Registering with Dependencies

If your tool needs a database connection or other dependency:

```python
registry.register_tool_with_dependencies(
    web_search,
    dependencies=["http_client"],  # dependency names in the container
)
```

### Unregistering

```python
registry.unregister_tool("web_search")
```

## Loading Tools from Modules

Configure module paths in `StrandsAgentConfig` and they are loaded
automatically during `AgentService.initialize()`:

```yaml
# config.yaml
tools_modules:
  - myapp.tools.search
  - myapp.tools.calculator
```

Or inline:

```python
from foundry_strands_agent import StrandsAgentConfig

config = StrandsAgentConfig(
    tools_modules=["myapp.tools.search", "myapp.tools.calculator"],
)
```

Each module must either export a `TOOL_SPEC` attribute or define a function
decorated with `@tool`.

## Loading Tools from Files

Filesystem paths to `.py` files are also supported:

```yaml
# config.yaml
tools_files:
  - /opt/agent/tools/search.py
  - /opt/agent/tools/calculator.py
```

```python
config = StrandsAgentConfig(
    tools_files=["/opt/agent/tools/search.py"],
)
```

### Hot-Loading from a Directory

Load all tool files from a directory at runtime:

```python
await service.register_tools_from_directory("/opt/agent/tools/")
```

## Security Model

`tool_loader.py` performs AST-based security analysis before executing any
tool module.  The following constraints apply:

| Check | Limit / Rule |
|-------|-------------|
| File size | 50 KB maximum |
| Line count | 1 000 lines maximum |
| Imports | Only whitelisted standard-library and Strands modules |
| Dangerous calls | `exec`, `eval`, `subprocess`, `os.system` are rejected |
| Obfuscation | `base64` decode, `hex` decode patterns are rejected |
| Execution | Runs in a thread pool, never the event loop |

Tools that fail security analysis raise `ToolRegistrationError` with details.

## Tool Definition Patterns

### @tool decorator

```python
from strands import tool

@tool
def get_weather(city: str, unit: str = "celsius") -> str:
    """Fetch current weather for a city.

    Args:
        city: City name (e.g. "San Francisco")
        unit: Temperature unit, "celsius" or "fahrenheit"
    """
    ...
```

### TOOL_SPEC module

For tools that need class-based structure or custom schema control:

```python
# tools/search.py
TOOL_SPEC = {
    "name": "web_search",
    "description": "Search the web and return a text summary.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        }
    },
}

async def web_search(query: str) -> str:
    ...
```

## Registry Statistics

Inspect registered tools at runtime:

```python
stats = registry.get_registry_statistics()
# {
#   "total_tools": 3,
#   "validated": True,
#   "tool_names": ["web_search", "get_weather", "calculator"],
# }
```

Validate that all declared dependencies are present in the container:

```python
registry.validate_tool_dependencies()
```
