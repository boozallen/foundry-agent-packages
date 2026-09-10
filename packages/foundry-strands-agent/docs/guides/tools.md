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
from foundry_agent_core import create_dependency_container

@tool
def web_search(query: str) -> str:
    """Search the web and return a text summary."""
    ...  # your implementation

container = create_dependency_container()
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

Every file in the directory is loaded through the same audited loader used by
module and file loading, so the checks below apply to each one.  Files whose name
starts with `_` are not treated as tools.  The directory itself must sit inside
the tools root the registry was built with — see [The Tools Root](#the-tools-root)
for how to pass it in.

A file that fails analysis is never executed and none of its tools are
registered.  It does not take the rest of the directory down with it: the
rejection is logged with the reason the loader gave, loading continues, and once
the directory has been walked a single warning names every rejected file.  Read
that warning — the agent is running with fewer tools than you configured:

```text
WARNING  Loaded 2 tool file(s) from /opt/agent/tools with 1 rejected:
         /opt/agent/tools/cwd.py: Dangerous import detected: os
```

The call raises `ToolLoadingError` when *no* tool loaded at all, and its context
carries every rejection reason, so a directory in which everything was rejected
is a hard failure rather than a silently empty registry.

## The Tools Root

All three loading routes are confined to a single tools root: a module, file, or
directory outside it is rejected before anything is read or executed.  The root
defaults to `/app/strands_base_agent/tools`, the tools location in the container
image, and is configurable — set it to wherever your tools actually live:

```yaml
# config.yaml
tools_dir: /opt/agent/tools
```

```python
config = StrandsAgentConfig(tools_dir="/opt/agent/tools")
```

Or from the environment — `STRANDS_TOOLS_DIR` when building config with
`StrandsAgentConfig.from_env()`, or `STRANDS__TOOLS_DIR` when using the generic
`load_config(...)` loader with the `STRANDS` prefix.  Leave it unset and the
default container path applies, so existing deployments are unaffected.

Module and file loading read `tools_dir` off the config object directly.
Directory loading takes its root from the registry instead, so the composition
root that builds the registry has to hand the same value over — set `tools_dir`
in config and nothing else, and `register_tools_from_directory` is still confined
to the default container path:

```python
registry = AgentToolRegistryManager(container, tools_dir=config.tools_dir)
# or, equivalently
from foundry_strands_agent.registry import create_agent_tool_registry

registry = create_agent_tool_registry(container, tools_dir=config.tools_dir)
```

The root is resolved to an absolute real path before every comparison, so `..`
segments and symlinks cannot escape it.  The root itself is operator-supplied at
deploy time and is trusted to the same level as the tool code it contains —
pointing it at a broad directory such as `/` widens what can be loaded.

## Security Model

`tool_loader.py` performs AST-based security analysis before executing any
tool module.  Module loading, file loading, and directory loading all go through
it, so the same constraints apply on every route with no exceptions:

| Check | Limit / Rule |
|-------|-------------|
| File size | 50 KB maximum |
| Line count | 1 000 lines maximum |
| Imports | Only whitelisted standard-library and Strands modules |
| Dangerous calls | `exec`, `eval`, `subprocess`, `os.system` are rejected |
| Obfuscation | `base64` decode, `hex` decode patterns are rejected |
| Containment | The target must resolve inside the configured tools root |
| Execution | Runs in a thread pool, never the event loop |

Tools that fail security analysis raise `ToolLoadingError` with details.  On the
directory route that error is caught per file, reported, and the file excluded —
see above.

### Verifying the checks

These five checks are easy to verify by hand. Write the file, then load it with
`load_tool_from_file`, which runs the same security analysis every loading route
uses.

The examples below write each file under `/opt/agent/tools/`, the default tools
root inside the container image. On a local machine (for example macOS), that
path usually is not writable. Write the file under a directory you do own
instead, such as `/tmp`, and pass that same directory as `tools_dir` so the
loader checks the file against the root it actually lives in:

```python
asyncio.run(load_tool_from_file("/tmp/bad_import.py", tools_dir="/tmp"))
```

If you skip `tools_dir` here, `load_tool_from_file` checks the file against the
default `/app/strands_base_agent/tools` root, the file path fails that
root check before the loader ever runs the import/call/obfuscation analysis,
and `ToolLoadingError` is raised for the wrong reason.

**Dangerous import detected**

```python
# /opt/agent/tools/bad_import.py
import os


def read_cwd():
    return os.getcwd()
```

```python
import asyncio
from foundry_strands_agent.tool_loader import load_tool_from_file

asyncio.run(load_tool_from_file("/opt/agent/tools/bad_import.py"))
```

**Expected**: `ToolLoadingError` is raised, naming `os` as the rejected import.

**Dangerous function call detected via AST inspection**

```python
# /opt/agent/tools/bad_call.py
def run_command(command: str):
    return eval(command)
```

**Expected**: `ToolLoadingError` is raised: `Dangerous function call: eval`. The
check walks the AST for the call expression itself, so it still catches a call
split across lines or wrapped in another expression — it is not a text search
for the word `eval`.

**Obfuscated code detected**

```python
# /opt/agent/tools/obfuscated.py
PAYLOAD_1 = "aW50ZXJuYWwgcGF5bG9hZCBzZWdtZW50IG51bWJlciAw"
PAYLOAD_2 = "aW50ZXJuYWwgcGF5bG9hZCBzZWdtZW50IG51bWJlciAx"
PAYLOAD_3 = "aW50ZXJuYWwgcGF5bG9hZCBzZWdtZW50IG51bWJlciAy"
PAYLOAD_4 = "aW50ZXJuYWwgcGF5bG9hZCBzZWdtZW50IG51bWJlciAz"
```

**Expected**: `ToolLoadingError` is raised: `Obfuscated code detected`. Four or
more strings that actually decode as base64 trip the check. Ordinary long
identifiers do not decode as base64, so they do not count — see the next check.

**Legitimate long API parameter names do not trigger a false positive**

```python
from strands import tool


@tool
def describe_instance(InstanceIdentifierWithLongCamelCaseName: str) -> str:
    """Look up an AWS-style resource by its full identifier name."""
    return f"described {InstanceIdentifierWithLongCamelCaseName}"
```

**Expected**: the module loads. `detect_obfuscation` returns `False` because
none of the long identifiers decode as base64.

**Identifiers ending in exec/eval-like letters do not trigger a false positive**

```python
from strands import tool


class Retrieval:
    def __init__(self, config: dict):
        self.config = config


@tool
def fetch(config: dict) -> str:
    retrieval = Retrieval(config)
    return str(retrieval.config)
```

**Expected**: the module loads. `Retrieval(config)` is a call to a class named
`Retrieval`, not a call to `eval`, so `analyze_dangerous_calls` does not flag it.

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
