## Why

When `enable_memory=True` and `knowledge_base_id` is configured, the agent factory accepts these values but never actually adds the `memory` tool from `strands_tools` to the agent's tool set. Users configure memory access expecting KB retrieval to work, but the agent has no tool to access it.

## What Changes

- Add conditional memory tool injection to `StrandsAgentFactory.create_agent()` when `enable_memory=True` AND `knowledge_base_id` is set
- Import and inject `memory` tool from `strands_tools.memory`, passing `knowledge_base_id` explicitly
- Add unit tests covering both enabled and disabled paths for memory tool injection

## Capabilities

### New Capabilities

(none - this is a bug fix adding missing behavior to an existing capability)

### Modified Capabilities

- `strands-agent-factory`: Add requirement for conditional memory tool injection based on config

## Impact

- **Code**: `foundry_strands_agent/factory.py` - add memory tool injection logic after MCP/A2A tool loading
- **Dependencies**: Uses existing `strands-agents-tools` dependency (no pyproject.toml change)
- **Tests**: New unit tests in factory tests covering memory tool injection scenarios

## Acceptance Criteria

- [ ] Given `enable_memory=True` and a valid `knowledge_base_id`, when the agent is created, then the `memory` tool from `strands_tools.memory` is present in the agent's tool set
- [ ] Given `enable_memory=False` or no `knowledge_base_id`, when the agent is created, then the `memory` tool is NOT injected
- [ ] Given the memory tool is loaded, when a user queries via `/api/v1/query`, then the agent can retrieve and respond with KB data
- [ ] Given the memory tool is loaded in A2A mode, then KB access also works
- [ ] Unit test covers conditional tool injection (enabled and disabled paths)

## References

- FOUNDRY-613
- [GH #253](https://github.com/boozallen/TBD)
