# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Additional factory tests for coverage — config-to-dict, merge overrides, session repo."""

from unittest.mock import MagicMock

import pytest

from foundry_strands_agent.config.models import AgentModelConfig, StrandsAgentConfig
from foundry_strands_agent.factory import StrandsAgentFactory


@pytest.fixture
def factory_with_config():
    container = MagicMock()
    config = StrandsAgentConfig(model=AgentModelConfig())
    container.resolve.return_value = config
    factory = StrandsAgentFactory(container=container)
    return factory, container, config


class TestGetBaseConfig:
    def test_resolves_from_container(self, factory_with_config):
        factory, container, config = factory_with_config
        factory._get_base_config()
        container.resolve.assert_called()


class TestConfigToDict:
    def test_converts_config_to_dict(self, factory_with_config):
        factory, _, config = factory_with_config
        result = factory._config_to_dict(config)
        assert result["model"]["provider"] == "bedrock"
        assert result["system_prompt"] == config.system_prompt
        assert result["max_conversation_length"] == 10
        assert result["conversation_window_size"] == 100

    def test_includes_session_fields(self, factory_with_config):
        factory, _, _ = factory_with_config
        config = StrandsAgentConfig(model=AgentModelConfig(), session_id="session1", session_type="file")
        result = factory._config_to_dict(config)
        assert result["session_id"] == "session1"
        assert result["session_type"] == "file"


class TestMergeConfigOverrides:
    def test_merges_top_level(self, factory_with_config):
        factory, _, config = factory_with_config
        overrides = {"system_prompt": "override prompt"}
        result = factory._merge_config_overrides(config, overrides)
        assert result["system_prompt"] == "override prompt"

    def test_deep_merges_model(self, factory_with_config):
        factory, _, config = factory_with_config
        overrides = {"model": {"temperature": 0.9}}
        result = factory._merge_config_overrides(config, overrides)
        assert result["model"]["temperature"] == 0.9
        assert result["model"]["provider"] == "bedrock"


class TestCreateSessionRepository:
    def test_returns_none_when_no_session_type(self, factory_with_config):
        factory, container, _ = factory_with_config
        config = StrandsAgentConfig(model=AgentModelConfig())
        container.resolve.return_value = config
        result = factory.create_session_repository()
        assert result is None

    def test_returns_session_manager_when_configured(self, factory_with_config):
        factory, container, _ = factory_with_config
        config = StrandsAgentConfig(model=AgentModelConfig(), session_type="file")
        container.resolve.return_value = config

        mock_sm = MagicMock()
        factory._session_manager_factories = {"file": lambda **kwargs: mock_sm}

        result = factory.create_session_repository()
        assert result is mock_sm


class TestGetToolName:
    def test_tool_spec_format(self):
        tool = MagicMock()
        tool.TOOL_SPEC = {"name": "calculator"}
        name, fmt = StrandsAgentFactory._get_tool_name(tool)
        assert name == "calculator"
        assert fmt == "TOOL_SPEC module"

    def test_decorated_function_format(self):
        def my_tool():
            pass

        name, fmt = StrandsAgentFactory._get_tool_name(my_tool)
        assert name == "my_tool"
        assert fmt == "@tool decorated function"

    def test_unknown_format(self):
        tool = object()
        name, fmt = StrandsAgentFactory._get_tool_name(tool)
        assert name == "unknown"
        assert fmt == "unknown"
