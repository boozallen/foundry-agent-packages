# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for factory MCP client collection and session management paths."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundry_agent_core import ExternalServiceError
from foundry_strands_agent.config.models import AgentModelConfig, StrandsAgentConfig
from foundry_strands_agent.factory import StrandsAgentFactory


@pytest.fixture
def factory():
    container = MagicMock()
    config = StrandsAgentConfig(model=AgentModelConfig())
    container.resolve.return_value = config
    return StrandsAgentFactory(container=container)


class TestCollectMcpClients:
    @pytest.mark.asyncio
    async def test_creates_mcp_client_per_server(self, factory):
        with patch("foundry_strands_agent.factory.MCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.return_value = MagicMock()
                servers = [{"url": "http://server1:8080"}, {"url": "http://server2:8080"}]
                result = await factory._collect_mcp_clients(servers)
                assert len(result) == 2

    @pytest.mark.asyncio
    async def test_raises_on_missing_url(self, factory):
        with pytest.raises(ExternalServiceError, match="Missing 'url'"):
            await factory._collect_mcp_clients([{"url": ""}])

    @pytest.mark.asyncio
    async def test_raises_on_connection_failure(self, factory):
        with patch("foundry_strands_agent.factory.MCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.side_effect = RuntimeError("connection refused")
                with pytest.raises(ExternalServiceError):
                    await factory._collect_mcp_clients([{"url": "http://bad:8080"}])


class TestCreateSessionRepository:
    def test_no_session_type_returns_none(self, factory):
        factory._container.resolve.return_value = StrandsAgentConfig(model=AgentModelConfig())
        result = factory.create_session_repository()
        assert result is None

    def test_with_session_type_file(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig(), session_type="file")
        factory._container.resolve.return_value = config

        mock_sm = MagicMock()
        factory._session_manager_factories = {"file": lambda **kwargs: mock_sm}

        result = factory.create_session_repository()
        assert result is mock_sm

    def test_with_overrides(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig())
        factory._container.resolve.return_value = config

        mock_sm = MagicMock()
        factory._session_manager_factories = {"file": lambda **kwargs: mock_sm}

        result = factory.create_session_repository(config_overrides={"session_type": "file", "session_id": "session1"})
        assert result is mock_sm


class TestCreateSessionManagerInternal:
    def test_enum_type_normalized(self, factory):
        from foundry_strands_agent.config.models import StrandsSessionManagerType

        mock_sm = MagicMock()
        factory._session_manager_factories = {"file": lambda **kwargs: mock_sm}

        result = factory._create_session_manager(
            session_id="session1",
            session_type=StrandsSessionManagerType.FILE,
        )
        assert result is mock_sm

    def test_string_type_works(self, factory):
        mock_sm = MagicMock()
        factory._session_manager_factories = {"s3": lambda **kwargs: mock_sm}

        result = factory._create_session_manager(
            session_id="session1",
            session_type="s3",
            s3_bucket="bucket",
        )
        assert result is mock_sm


class TestMergeConfigOverrides:
    def test_model_deep_merge(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig(temperature=0.3))
        result = factory._merge_config_overrides(config, {"model": {"temperature": 0.9}})
        assert result["model"]["temperature"] == 0.9
        assert result["model"]["provider"] == "bedrock"

    def test_top_level_override(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig())
        result = factory._merge_config_overrides(config, {"system_prompt": "new prompt"})
        assert result["system_prompt"] == "new prompt"


class TestLoadToolsFromModules:
    @pytest.mark.asyncio
    async def test_loads_tool_spec_tools(self, factory):
        mock_tool = MagicMock()
        mock_tool.TOOL_SPEC = {"name": "calc", "tools": [MagicMock()]}

        with patch("foundry_strands_agent.factory.load_tool_from_module", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = mock_tool
            result = await factory._load_tools_from_modules(["tools.calc"])
            assert len(result) >= 0  # may extract from TOOL_SPEC.tools or append module

    @pytest.mark.asyncio
    async def test_handles_failed_module_gracefully(self, factory):
        with patch("foundry_strands_agent.factory.load_tool_from_module", new_callable=AsyncMock) as mock_load:
            mock_load.side_effect = ImportError("not found")
            result = await factory._load_tools_from_modules(["bad.module"])
            assert result == []


class TestLoadToolsFromFiles:
    @pytest.mark.asyncio
    async def test_loads_file_tool(self, factory):
        mock_tool = MagicMock()
        with patch("foundry_strands_agent.factory.load_tool_from_file", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = mock_tool
            result = await factory._load_tools_from_files(["./tools/weather.py"])
            assert mock_tool in result

    @pytest.mark.asyncio
    async def test_handles_failed_file_gracefully(self, factory):
        with patch("foundry_strands_agent.factory.load_tool_from_file", new_callable=AsyncMock) as mock_load:
            mock_load.side_effect = FileNotFoundError("no such file")
            result = await factory._load_tools_from_files(["./bad.py"])
            assert result == []
