# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for FOUNDRY-416: Wire load_config into StrandsAgentConfig."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from foundry_agent_config import ConfigurationError as ConfigConfigurationError
from foundry_agent_config import load_config
from foundry_agent_core import ConfigurationError as CoreConfigurationError
from foundry_strands_agent.config.models import StrandsAgentConfig


@pytest.fixture
def yaml_config(tmp_path: Path) -> Path:
    config = {
        "model": {
            "provider": "bedrock",
            "model_id": "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "temperature": 0.5,
        },
        "agent_name": "test-agent",
        "system_prompt": "You are a test agent.",
        "max_query_length": 5000,
    }
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(yaml.dump(config))
    return yaml_path


@pytest.fixture
def minimal_yaml(tmp_path: Path) -> Path:
    config = {"model": {"provider": "bedrock"}}
    yaml_path = tmp_path / "minimal.yaml"
    yaml_path.write_text(yaml.dump(config))
    return yaml_path


class TestAC1ImportWithConfig:
    """AC1: StrandsAgentConfig import succeeds with foundry-agent-config installed."""

    def test_import_from_package(self):
        from foundry_strands_agent import StrandsAgentConfig

        assert StrandsAgentConfig is not None

    def test_import_from_config_module(self):
        from foundry_strands_agent.config.models import StrandsAgentConfig

        assert StrandsAgentConfig is not None

    def test_load_config_importable(self):
        from foundry_agent_config import load_config

        assert load_config is not None


class TestAC2LoadConfigWithYAML:
    """AC2: load_config(StrandsAgentConfig, yaml_path, "STRANDS") returns validated config."""

    def test_load_from_yaml(self, yaml_config: Path):
        config = load_config(StrandsAgentConfig, yaml_config, "STRANDS")

        assert isinstance(config, StrandsAgentConfig)
        assert config.model.provider == "bedrock"
        assert config.model.temperature == 0.5
        assert config.agent_name == "test-agent"
        assert config.system_prompt == "You are a test agent."
        assert config.max_query_length == 5000

    def test_load_from_minimal_yaml(self, minimal_yaml: Path):
        config = load_config(StrandsAgentConfig, minimal_yaml, "STRANDS")

        assert isinstance(config, StrandsAgentConfig)
        assert config.model.provider == "bedrock"
        assert config.agent_name == "strands-base-agent"

    def test_env_overrides_yaml(self, yaml_config: Path, monkeypatch):
        monkeypatch.setenv("STRANDS__AGENT_NAME", "overridden-agent")
        monkeypatch.setenv("STRANDS__MODEL__TEMPERATURE", "0.9")

        config = load_config(StrandsAgentConfig, yaml_config, "STRANDS")

        assert config.agent_name == "overridden-agent"
        assert config.model.temperature == 0.9

    def test_from_yaml_convenience(self, yaml_config: Path):
        config = StrandsAgentConfig.from_yaml(yaml_config)

        assert isinstance(config, StrandsAgentConfig)
        assert config.agent_name == "test-agent"

    def test_invalid_yaml_raises(self, tmp_path: Path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text(": invalid: yaml: [")

        with pytest.raises(ConfigConfigurationError):
            load_config(StrandsAgentConfig, bad_yaml, "STRANDS")

    def test_missing_yaml_raises(self, tmp_path: Path):
        with pytest.raises(ConfigConfigurationError):
            load_config(StrandsAgentConfig, tmp_path / "nonexistent.yaml", "STRANDS")


class TestAC3ShimRemoved:
    """AC3: grep for '# temporary-config-shim' returns zero hits."""

    def test_no_shim_marker_in_package(self):
        src_dir = Path(__file__).resolve().parents[2] / "src"
        hits = [p for p in src_dir.rglob("*.py") if "temporary-config-shim" in p.read_text()]
        assert not hits, f"Shim marker still present in:\n{[str(p) for p in hits]}"


class TestErrorBoundary:
    """Error boundary: foundry_agent_config.ConfigurationError → foundry_agent_core.ConfigurationError."""

    def test_config_error_translated(self):
        from foundry_strands_agent.backend import StrandsAgentBackend

        container = MagicMock()
        container.resolve.side_effect = ConfigConfigurationError(
            "bad config",
            context={"key": "value"},
        )

        with pytest.raises(CoreConfigurationError) as exc_info:
            StrandsAgentBackend(container)

        assert "bad config" in str(exc_info.value)
        assert exc_info.value.context["key"] == "value"

    def test_error_chain_preserved(self):
        from foundry_strands_agent.backend import StrandsAgentBackend

        original = ConfigConfigurationError("original error")
        container = MagicMock()
        container.resolve.side_effect = original

        with pytest.raises(CoreConfigurationError) as exc_info:
            StrandsAgentBackend(container)

        assert exc_info.value.__cause__ is original


class TestFromEnvBackwardCompat:
    """from_env() still works without YAML file."""

    def test_from_env_defaults(self):
        config = StrandsAgentConfig.from_env()

        assert config.model.provider == "bedrock"
        assert config.agent_name == "strands-base-agent"
        assert config.max_query_length == 2000

    def test_from_env_with_custom_vars(self, monkeypatch):
        monkeypatch.setenv("STRANDS_MODEL_PROVIDER", "ollama")
        monkeypatch.setenv("STRANDS_AGENT_NAME", "custom-agent")
        monkeypatch.setenv("STRANDS_TEMPERATURE", "0.8")

        config = StrandsAgentConfig.from_env()

        assert config.model.provider == "ollama"
        assert config.agent_name == "custom-agent"
        assert config.model.temperature == 0.8

    def test_from_env_with_mcp_servers(self, monkeypatch):
        monkeypatch.setenv("STRANDS_MCP_SERVERS", '[{"url": "http://localhost:8080"}]')

        config = StrandsAgentConfig.from_env()

        assert len(config.mcp_servers) == 1
        assert config.mcp_servers[0]["url"] == "http://localhost:8080"


class TestNimsFromEnv:
    def test_nims_env_vars_populated(self, monkeypatch):
        monkeypatch.setenv("NIMS_BASE_URL", "http://cluster:8000")
        monkeypatch.setenv("NIMS_API_KEY", "nvapi-x")

        config = StrandsAgentConfig.from_env()

        assert config.model.nims_base_url == "http://cluster:8000"
        assert config.model.nims_api_key == "nvapi-x"

    def test_nims_env_vars_absent(self, monkeypatch):
        monkeypatch.delenv("NIMS_BASE_URL", raising=False)
        monkeypatch.delenv("NIMS_API_KEY", raising=False)

        config = StrandsAgentConfig.from_env()

        assert config.model.nims_base_url is None
        assert config.model.nims_api_key is None
