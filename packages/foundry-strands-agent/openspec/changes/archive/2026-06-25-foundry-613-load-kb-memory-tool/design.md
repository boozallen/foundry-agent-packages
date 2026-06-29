## Context

The `StrandsAgentFactory.create_agent()` method currently loads tools from multiple sources:
1. Module-based tools (`tools_modules`)
2. File-based tools (`tools_files`)
3. MCP server tools (`mcp_servers`)
4. A2A agent tools (`a2a_servers`)

However, when `enable_memory=True` and `knowledge_base_id` is configured, the `memory` tool from `strands_tools` is never injected despite the config accepting these values. The config model even validates that `knowledge_base_id` is required when `enable_memory=True`, but the factory doesn't act on this configuration.

## Goals / Non-Goals

**Goals:**
- Inject the `memory` tool from `strands_tools.memory` when both `enable_memory=True` AND `knowledge_base_id` is set
- Pass `knowledge_base_id` explicitly to the memory tool rather than relying on environment variable fallback
- Maintain consistency with existing tool injection patterns (MCP, A2A)
- Add unit tests covering both enabled and disabled paths

**Non-Goals:**
- Adding new configuration options (existing config is sufficient)
- Changes to the memory tool itself (it's from `strands-agents-tools`)
- Supporting memory without a knowledge base ID (config validation already prevents this)

## Decisions

### Decision 1: Injection point after A2A tools, before telemetry

**Choice**: Add memory tool injection in `create_agent()` after A2A tool injection (line ~299) and before telemetry initialization (line ~301).

**Rationale**: This follows the existing pattern where tool integrations are grouped together before agent instantiation. MCP tools → A2A tools → memory tool is a logical progression.

**Alternative considered**: Inject during `_load_tools_from_modules()`. Rejected because memory is a built-in tool from `strands_tools`, not a user-configured module path.

### Decision 2: Pass knowledge_base_id explicitly

**Choice**: Pass `knowledge_base_id` as a keyword argument to the memory tool function.

**Rationale**: The `strands_tools.memory` tool accepts `STRANDS_KNOWLEDGE_BASE_ID` as a kwarg or falls back to environment variable. Passing explicitly from config is more reliable and aligns with Foundry's configuration-first principle.

### Decision 3: Guard with both enable_memory AND knowledge_base_id

**Choice**: Only inject when `base_config.enable_memory` is True AND `base_config.knowledge_base_id` is truthy.

**Rationale**: Config validation already ensures `knowledge_base_id` is required when `enable_memory=True`, but defensive coding in the factory prevents issues if validation is bypassed.

## Risks / Trade-offs

**Risk**: Memory tool import failure at runtime
→ **Mitigation**: Wrap import in try/except, log error but don't fail agent creation (consistent with how MCP/A2A failures are handled in discovery phase).

**Trade-off**: Additional conditional logic in `create_agent()`
→ **Accepted**: The method already has conditionals for MCP and A2A tools; this follows the established pattern.
