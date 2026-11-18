# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for memory tool injection in StrandsAgentFactory.create_agent."""

import os
from unittest.mock import MagicMock, patch

import pytest

from foundry_strands_agent.config.models import AgentModelConfig, StrandsAgentConfig
from foundry_strands_agent.factory import StrandsAgentFactory, _memory_tool


@pytest.fixture
def container():
    return MagicMock()


@pytest.fixture
def base_patches():
    """Common patches for agent creation tests."""
    return patch.multiple(
        "foundry_strands_agent.factory",
        Agent=MagicMock(return_value=MagicMock()),
        BedrockModel=MagicMock(return_value=MagicMock()),
        SlidingWindowConversationManager=MagicMock(),
        AgentState=MagicMock(),
    )


def _tool_names(tools: list) -> list[str]:
    return [getattr(t, "tool_name", getattr(t, "__name__", None)) for t in tools]


class TestMemoryToolInjection:
    """Tests for conditional memory tool injection based on config."""

    @pytest.mark.asyncio
    async def test_memory_tool_injected_when_enabled_with_knowledge_base_id(self, container, base_patches):
        """A tool named 'memory' should be added when enable_memory=True and knowledge_base_id is set."""
        config = StrandsAgentConfig(
            model=AgentModelConfig(),
            enable_memory=True,
            knowledge_base_id="ABC123XYZ",
        )
        container.resolve.return_value = config
        factory = StrandsAgentFactory(container=container)

        with base_patches:
            with patch("foundry_strands_agent.factory.Agent") as mock_agent_cls:
                mock_agent_cls.return_value = MagicMock()
                await factory.create_agent()

                # The env var mutation is gone - the knowledge base id is bound directly.
                assert "STRANDS_KNOWLEDGE_BASE_ID" not in os.environ

                call_kwargs = mock_agent_cls.call_args
                tools = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools", [])

                assert "memory" in _tool_names(tools), "A 'memory' tool should be injected"

    @pytest.mark.asyncio
    async def test_memory_tool_does_not_bind_the_models_region(self, container, base_patches):
        """The memory tool must not inherit the Bedrock model's region.

        There is no separate knowledge-base-region config field. Binding the memory tool to
        `model.region_name` would force a cross-region model/KB setup onto the model's region
        instead of letting boto3's own region resolution reach the knowledge base.
        """
        config = StrandsAgentConfig(
            model=AgentModelConfig(region_name="us-east-1"),
            enable_memory=True,
            knowledge_base_id="ABC123XYZ",
        )
        container.resolve.return_value = config
        factory = StrandsAgentFactory(container=container)

        mock_memory = MagicMock(return_value={"status": "success"})
        with base_patches:
            with patch("strands_tools.memory.memory", mock_memory):
                with patch("foundry_strands_agent.factory.Agent") as mock_agent_cls:
                    mock_agent_cls.return_value = MagicMock()
                    await factory.create_agent()

                    call_kwargs = mock_agent_cls.call_args
                    tools = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools", [])
                    memory_tool = next(t for t in tools if getattr(t, "tool_name", None) == "memory")

                    memory_tool(action="list")

        assert mock_memory.call_args.kwargs["region_name"] is None

    @pytest.mark.asyncio
    async def test_memory_tool_not_injected_when_enable_memory_false(self, container, base_patches):
        """Memory tool should NOT be added when enable_memory=False."""
        config = StrandsAgentConfig(
            model=AgentModelConfig(),
            enable_memory=False,
            knowledge_base_id="ABC123XYZ",
        )
        container.resolve.return_value = config
        factory = StrandsAgentFactory(container=container)

        with base_patches:
            with patch("foundry_strands_agent.factory.Agent") as mock_agent_cls:
                mock_agent_cls.return_value = MagicMock()
                await factory.create_agent()

                call_kwargs = mock_agent_cls.call_args
                tools = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools", [])

                assert "memory" not in _tool_names(tools), "Memory tool should NOT be injected when enable_memory=False"

    @pytest.mark.asyncio
    async def test_memory_tool_not_injected_when_knowledge_base_id_missing(self, container, base_patches):
        """Memory tool should NOT be added when knowledge_base_id is not set."""
        config = StrandsAgentConfig(
            model=AgentModelConfig(),
            enable_memory=False,  # Config validation requires this to be False if no KB ID
            knowledge_base_id=None,
        )
        container.resolve.return_value = config
        factory = StrandsAgentFactory(container=container)

        with base_patches:
            with patch("foundry_strands_agent.factory.Agent") as mock_agent_cls:
                mock_agent_cls.return_value = MagicMock()
                await factory.create_agent()

                call_kwargs = mock_agent_cls.call_args
                tools = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools", [])

                assert "memory" not in _tool_names(tools), (
                    "Memory tool should NOT be injected without knowledge_base_id"
                )

    @pytest.mark.asyncio
    async def test_memory_tool_import_failure_is_non_fatal(self, container, base_patches, caplog):
        """Agent creation should continue if memory tool import fails."""
        config = StrandsAgentConfig(
            model=AgentModelConfig(),
            enable_memory=True,
            knowledge_base_id="ABC123XYZ",
        )
        container.resolve.return_value = config
        factory = StrandsAgentFactory(container=container)

        with base_patches:
            with patch("foundry_strands_agent.factory.Agent") as mock_agent_cls:
                mock_agent_cls.return_value = MagicMock()

                # Simulate import failure by making the import raise
                import builtins

                original_import = builtins.__import__

                def mock_import(name, *args, **kwargs):
                    if name == "strands_tools.memory" or (name == "strands_tools" and "memory" in str(args)):
                        raise ImportError("strands_tools.memory not available")
                    return original_import(name, *args, **kwargs)

                with patch.object(builtins, "__import__", mock_import):
                    # Should not raise - agent creation continues
                    agent = await factory.create_agent()
                    assert agent is not None

                # Warning should be logged
                assert any("Failed to import memory tool" in record.message for record in caplog.records)


class TestMemoryToolKbIdAndRegionAreNotModelSettable:
    """`_memory_tool` must bind the knowledge base id and region itself, not let the model choose.

    `strands_tools.memory.memory`'s own schema exposes `STRANDS_KNOWLEDGE_BASE_ID` and
    `region_name` as arguments a model call can set, overriding the operator's configured
    values. `_memory_tool` wraps it so neither is a parameter the model can supply.
    """

    def test_wrapper_schema_omits_kb_id_and_region(self):
        wrapped = _memory_tool("ABC123XYZ", "us-west-2")
        params = wrapped.tool_spec["inputSchema"]["json"]["properties"]

        assert "STRANDS_KNOWLEDGE_BASE_ID" not in params
        assert "region_name" not in params
        # The model-facing actions are still there.
        assert "action" in params
        assert "query" in params

    def test_wrapper_tool_name_is_unchanged(self):
        """Keeps the name 'memory' so existing prompts referencing it still work."""
        wrapped = _memory_tool("ABC123XYZ", "us-west-2")
        assert wrapped.tool_name == "memory"

    def test_wrapper_always_passes_the_bound_kb_id_and_region(self):
        """Calling the wrapper (as the model would, with no kb id/region) still binds both."""
        mock_memory = MagicMock(return_value={"status": "success"})
        with patch("strands_tools.memory.memory", mock_memory):
            wrapped = _memory_tool("ABC123XYZ", "us-west-2")
            wrapped(action="retrieve", query="hello")

        mock_memory.assert_called_once_with(
            action="retrieve",
            content=None,
            title=None,
            document_id=None,
            query="hello",
            STRANDS_KNOWLEDGE_BASE_ID="ABC123XYZ",
            max_results=None,
            next_token=None,
            min_score=None,
            region_name="us-west-2",
        )

    def test_wrapper_with_no_configured_region_passes_none(self):
        """No configured region_name means the underlying tool falls back to its own default."""
        mock_memory = MagicMock(return_value={"status": "success"})
        with patch("strands_tools.memory.memory", mock_memory):
            wrapped = _memory_tool("ABC123XYZ", None)
            wrapped(action="list")

        assert mock_memory.call_args.kwargs["region_name"] is None
        assert mock_memory.call_args.kwargs["STRANDS_KNOWLEDGE_BASE_ID"] == "ABC123XYZ"
