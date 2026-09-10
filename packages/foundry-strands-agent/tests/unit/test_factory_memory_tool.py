# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for memory tool injection in StrandsAgentFactory.create_agent."""

import os
from unittest.mock import MagicMock, patch

import pytest

from foundry_strands_agent.config.models import AgentModelConfig, StrandsAgentConfig
from foundry_strands_agent.factory import StrandsAgentFactory


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


class TestMemoryToolInjection:
    """Tests for conditional memory tool injection based on config."""

    @pytest.mark.asyncio
    async def test_memory_tool_injected_when_enabled_with_knowledge_base_id(self, container, base_patches):
        """Memory tool should be added when enable_memory=True and knowledge_base_id is set."""
        config = StrandsAgentConfig(
            model=AgentModelConfig(),
            enable_memory=True,
            knowledge_base_id="ABC123XYZ",
        )
        container.resolve.return_value = config
        factory = StrandsAgentFactory(container=container)

        mock_memory = MagicMock()
        mock_memory.__name__ = "memory"
        mock_memory.__doc__ = "Memory tool docstring"

        with base_patches:
            mock_modules = {
                "strands_tools": MagicMock(),
                "strands_tools.memory": MagicMock(memory=mock_memory),
            }
            with patch.dict("sys.modules", mock_modules):
                with patch("foundry_strands_agent.factory.Agent") as mock_agent_cls:
                    mock_agent_cls.return_value = MagicMock()
                    await factory.create_agent()

                    # Verify env var was set
                    assert os.environ.get("STRANDS_KNOWLEDGE_BASE_ID") == "ABC123XYZ"

                    # Check that Agent was called with tools containing the memory tool
                    call_kwargs = mock_agent_cls.call_args
                    tools = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools", [])

                    # The memory tool should be directly in the tools list (not wrapped)
                    assert mock_memory in tools, "Memory tool should be injected"

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

        mock_memory = MagicMock()
        mock_memory.__name__ = "memory"

        with base_patches:
            mock_modules = {
                "strands_tools": MagicMock(),
                "strands_tools.memory": MagicMock(memory=mock_memory),
            }
            with patch.dict("sys.modules", mock_modules):
                with patch("foundry_strands_agent.factory.Agent") as mock_agent_cls:
                    mock_agent_cls.return_value = MagicMock()
                    await factory.create_agent()

                    call_kwargs = mock_agent_cls.call_args
                    tools = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools", [])

                    # Memory tool should NOT be in the tools list
                    assert mock_memory not in tools, "Memory tool should NOT be injected when enable_memory=False"

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

        mock_memory = MagicMock()
        mock_memory.__name__ = "memory"

        with base_patches:
            mock_modules = {
                "strands_tools": MagicMock(),
                "strands_tools.memory": MagicMock(memory=mock_memory),
            }
            with patch.dict("sys.modules", mock_modules):
                with patch("foundry_strands_agent.factory.Agent") as mock_agent_cls:
                    mock_agent_cls.return_value = MagicMock()
                    await factory.create_agent()

                    call_kwargs = mock_agent_cls.call_args
                    tools = call_kwargs.kwargs.get("tools") or call_kwargs[1].get("tools", [])

                    # Memory tool should NOT be in the tools list
                    assert mock_memory not in tools, "Memory tool should NOT be injected without knowledge_base_id"

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
