## ADDED Requirements

### Requirement: Memory tool injection when knowledge base is configured
`StrandsAgentFactory` SHALL inject the `memory` tool from `strands_tools.memory` when both `enable_memory=True` AND `knowledge_base_id` is configured.

#### Scenario: Memory tool injected when enabled with knowledge base ID
- **WHEN** `create_agent()` is called with config where `enable_memory=True` AND `knowledge_base_id` is set
- **THEN** the `memory` tool from `strands_tools.memory` SHALL be present in the agent's tool set
- **AND** the tool SHALL receive `knowledge_base_id` as an explicit parameter

#### Scenario: Memory tool not injected when enable_memory is False
- **WHEN** `create_agent()` is called with config where `enable_memory=False`
- **THEN** the `memory` tool SHALL NOT be present in the agent's tool set

#### Scenario: Memory tool not injected when knowledge_base_id is missing
- **WHEN** `create_agent()` is called with config where `enable_memory=True` but `knowledge_base_id` is not set
- **THEN** the `memory` tool SHALL NOT be present in the agent's tool set

#### Scenario: Memory tool works in A2A mode
- **WHEN** an agent is created with memory tool enabled
- **AND** the agent receives requests via A2A protocol
- **THEN** the memory tool SHALL be available for knowledge base retrieval

#### Scenario: Memory tool import failure is non-fatal
- **WHEN** `create_agent()` is called with memory enabled
- **AND** the `strands_tools.memory` import fails
- **THEN** agent creation SHALL continue without the memory tool
- **AND** a warning SHALL be logged
