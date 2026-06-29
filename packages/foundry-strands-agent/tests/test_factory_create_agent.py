# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for StrandsAgentFactory.create_agent and tool loading paths."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundry_agent_core import AgentCreationError
from foundry_strands_agent.config.models import AgentModelConfig, StrandsAgentConfig
from foundry_strands_agent.factory import StrandsAgentFactory


@pytest.fixture
def factory():
    container = MagicMock()
    config = StrandsAgentConfig(model=AgentModelConfig())
    container.resolve.return_value = config
    return StrandsAgentFactory(container=container)


class TestCreateAgent:
    @pytest.mark.asyncio
    async def test_creates_agent_with_defaults(self, factory):
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch("foundry_strands_agent.factory.SlidingWindowConversationManager"),
            patch("foundry_strands_agent.factory.AgentState"),
        ):
            mock_bedrock.return_value = MagicMock()
            mock_agent_cls.return_value = MagicMock()

            await factory.create_agent()
            mock_agent_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_agent_with_tools(self, factory):
        mock_tool = MagicMock()
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch("foundry_strands_agent.factory.SlidingWindowConversationManager"),
            patch("foundry_strands_agent.factory.AgentState"),
        ):
            mock_bedrock.return_value = MagicMock()
            mock_agent_cls.return_value = MagicMock()

            await factory.create_agent(tools=[mock_tool])
            call_kwargs = mock_agent_cls.call_args
            assert mock_tool in call_kwargs.kwargs["tools"] or mock_tool in call_kwargs[1].get("tools", [])

    @pytest.mark.asyncio
    async def test_raises_agent_creation_error_on_failure(self, factory):
        with patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock:
            mock_bedrock.side_effect = RuntimeError("model init failed")

            with pytest.raises(AgentCreationError):
                await factory.create_agent()

    @pytest.mark.asyncio
    async def test_config_overrides_applied(self, factory):
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch("foundry_strands_agent.factory.SlidingWindowConversationManager"),
            patch("foundry_strands_agent.factory.AgentState"),
        ):
            mock_bedrock.return_value = MagicMock()
            mock_agent_cls.return_value = MagicMock()

            await factory.create_agent(config_overrides={"system_prompt": "custom"})
            mock_agent_cls.assert_called_once()


class TestCreateAgentWithToolRegistry:
    @pytest.mark.asyncio
    async def test_gets_tools_from_registry(self, factory):
        mock_registry = MagicMock()
        mock_registry.get_available_tools.return_value = [MagicMock()]
        mock_registry.validate_tool_dependencies.return_value = {"all_valid": True}

        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch("foundry_strands_agent.factory.SlidingWindowConversationManager"),
            patch("foundry_strands_agent.factory.AgentState"),
        ):
            mock_bedrock.return_value = MagicMock()
            mock_agent_cls.return_value = MagicMock()

            await factory.create_agent_with_tool_registry(tool_registry=mock_registry)
            mock_registry.get_available_tools.assert_called_once()


class TestLoadConfiguredTools:
    @pytest.mark.asyncio
    async def test_no_tools_configured(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig())
        registry = MagicMock()
        await factory.load_configured_tools(config, registry)
        registry.register_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_module_tool_loaded(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig(), tools_modules=["tools.calc"])
        registry = MagicMock()

        mock_tool = MagicMock()
        mock_tool.TOOL_SPEC = {"name": "calc"}

        with patch("foundry_strands_agent.factory.load_tool_from_module", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = mock_tool
            await factory.load_configured_tools(config, registry)
            mock_load.assert_called_once_with("tools.calc")

    @pytest.mark.asyncio
    async def test_file_tool_loaded(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig(), tools_files=["./tools/weather.py"])
        registry = MagicMock()

        mock_tool = MagicMock()
        mock_tool.__name__ = "weather"

        with patch("foundry_strands_agent.factory.load_tool_from_file", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = mock_tool
            await factory.load_configured_tools(config, registry)
            mock_load.assert_called_once_with("./tools/weather.py")

    @pytest.mark.asyncio
    async def test_failed_module_continues(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig(), tools_modules=["bad.module", "good.module"])
        registry = MagicMock()

        mock_tool = MagicMock()
        mock_tool.TOOL_SPEC = {"name": "good"}

        async def side_effect(path):
            if "bad" in path:
                raise ImportError("no such module")
            return mock_tool

        with patch("foundry_strands_agent.factory.load_tool_from_module", new_callable=AsyncMock) as mock_load:
            mock_load.side_effect = side_effect
            await factory.load_configured_tools(config, registry)


class TestDefaultModelFactories:
    def test_bedrock_model_factory(self, factory):
        with patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            config = {"model": {"provider": "bedrock", "model_id": "test-model"}, "guardrail_config": None}
            factory.create_model(config)
            mock_bedrock.assert_called_once()

    def test_ollama_model_factory(self, factory):
        with patch("foundry_strands_agent.factory.OllamaModel", create=True) as mock_ollama:
            mock_ollama.return_value = MagicMock()
            factory._model_provider_factories["ollama"] = lambda cfg: mock_ollama(model_id=cfg["model"]["model_id"])
            config = {"model": {"provider": "ollama", "model_id": "llama3", "temperature": 0.3}}
            factory.create_model(config)
            mock_ollama.assert_called_once()
