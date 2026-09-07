# Optional Hindsight memory

`foundry-strands-agent[hindsight]` adds the official `hindsight-strands` tools
through the `MemoryToolProvider` protocol. Normal installs do not import or
install Hindsight. Existing `enable_memory` / `knowledge_base_id` Bedrock memory
configuration continues to work independently, including alongside a provider.

## Compose a provider

Install the extra from your organization's wheel index, or for local development:

```sh
uv sync --all-packages --all-groups --extra hindsight
```

In a composition root such as `strands-base-agent/server.py`, create the client
at application startup and pass a bound provider to the factory registration:

```python
from foundry_strands_agent import (
    AgentFactory, HindsightMemoryConfig, HindsightMemoryProvider, StrandsAgentFactory,
)

# client is an application-owned, thread-safe facade over the official client.
# See ThreadBoundClient in examples/hindsight_memory.py for the tested recipe.
provider = HindsightMemoryProvider(
    HindsightMemoryConfig(bank_id=authorized_bank_id),
    client=client,
)
container.register_factory(
    AgentFactory,
    lambda: StrandsAgentFactory(container, memory_provider=provider),
    singleton=True,
)
# After all requests/agents finish: await asyncio.to_thread(client.close)
```

Foundry never closes the client. With the locked `hindsight-strands` 0.1.3 /
`hindsight-client` 0.9.2 pair, **do not share a raw Hindsight client across tool
worker threads or close it on the application's event loop**. Live testing found
cross-loop cleanup failure. The example's caller-owned `ThreadBoundClient` keeps
construction, I/O, and cleanup on a single thread with its own loop. It delegates
all operations to the official client; no HTTP protocol is reimplemented. Calls
are serialized per facade; size your application concurrency accordingly.

Both `create_agent` and `create_agent_with_mcp_clients` include provider tools;
registry creation delegates to `create_agent`. Custom providers implement
`get_tools()` returning a sequence of Strands-compatible callables, with no network
activity during tool collection. Collection errors abort agent creation rather
than silently dropping memory.

## Scope and capabilities

A provider is bound to one bank for its lifetime. Bank IDs must contain 1–128 ASCII
letters, digits, underscores or hyphens, starting with a letter or digit. Bank
validation checks syntax, **not authorization**. Select the bank after authenticating
and authorizing the principal. Never derive it from a prompt, model argument,
client-supplied session ID, or unverified request parameter. A singleton factory is
appropriate only when everyone using it is authorized for the same bank. For
multiple tenants, construct a scoped factory/provider after authorization.

Recall and reflect are enabled by default; retain is absent unless
`enable_retain=True`. Set `enable_reflect=False` for recall-only access. There is
no automatic transcript retention. Strict immutable configuration rejects coerced
booleans and unknown fields. Recall defaults to budget `low` and `max_tokens=2048`
(allowed range 1–32768). Reflection uses the budget but the upstream tool does not
forward `max_tokens` to reflection. Explicit tool options override global
Hindsight defaults; memory scope never becomes a model tool argument.

Treat retrieved memories as untrusted data, including possible stored prompt
injection. Application policy must control what may be retained, data minimization,
retention/deletion, and whose information may be recalled. The bank binding is not
a substitute for service-side authorization. Configure service credentials, HTTPS
outside loopback development, network access, encryption, and audit retention at
the deployment boundary. Session encryption does not encrypt the remote memory bank.

The official adapter can include upstream error details in exceptions and logs,
and Strands can return tool errors to the model. Deployments must redact sensitive
service errors/logs before exposure. Timeouts and failures propagate; Foundry adds
no retries or fallback storage. The official retain tool attempts bank creation
and suppresses creation errors before attempting retain; provision banks in trusted
application setup if creation permissions need to be restricted. A successful
retain tool response means the upstream call returned, not independently verified
durable storage. Set client timeouts and verify retrieval when persistence matters.

## Live example

From the monorepo root, configure `OPENAI_API_KEY` privately and point
`HINDSIGHT_BASE_URL` at a running service (default `http://127.0.0.1:18888`). The
service needs its own configured LLM/embedding credentials. Optionally set
`HINDSIGHT_API_KEY` and `OPENAI_MODEL` (default `gpt-4.1-mini`). Then run:

```sh
uv run --all-packages --extra hindsight python examples/hindsight_memory.py
```

The example uses Foundry's DI container, injected model/session factories, encrypted
temporary session storage, and the official tools. It stores fictional information
in a new `foundry-fictional-demo-*` bank from conversation one, then creates a
read-only conversation two with empty history and checks the recovered code.
The bank remains for inspection; delete it explicitly using your service's
administration tools when finished. This invokes paid model services if configured.
A passing run is evidence of this local service/model combination, not production
multi-tenant authorization, durability across service restarts, or load testing.

## Dependency licenses

Foundry remains Apache-2.0 with its existing notices. The optional lockfile additions
are `hindsight-strands` 0.1.3 (MIT), `hindsight-client` 0.9.2 (MIT), and
`aiohttp-retry` 2.9.1 (MIT), verified from installed distribution metadata. No
upstream client source is copied or vendored. Retain dependency license files when
redistributing dependencies; service/container licensing is a separate deployment
review. Existing dependency versions and security floors are unchanged.

Official integration reference: [Hindsight Strands documentation](https://hindsight.vectorize.io/sdks/integrations/strands).
