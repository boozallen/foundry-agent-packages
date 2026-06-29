# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Extended config tests — spec: strands-agent-config."""

import pytest
from pydantic import ValidationError

from foundry_agent_core import InvalidConfigurationError
from foundry_strands_agent.config.models import (
    AgentModelConfig,
    ModelGuardrailConfig,
    StrandsAgentConfig,
    StrandsSessionManagerType,
)


class TestS3SessionTypeRequiresBucket:
    """Scenario: S3 session type requires bucket."""

    def test_s3_without_bucket_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(
                model=AgentModelConfig(),
                session_type=StrandsSessionManagerType.S3,
                session_s3_bucket=None,
            )

    def test_s3_with_empty_bucket_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(
                model=AgentModelConfig(),
                session_type=StrandsSessionManagerType.S3,
                session_s3_bucket="",
            )

    def test_s3_with_valid_bucket_passes(self):
        config = StrandsAgentConfig(
            model=AgentModelConfig(),
            session_type=StrandsSessionManagerType.S3,
            session_s3_bucket="my-bucket",
        )
        assert config.session_s3_bucket == "my-bucket"


class TestGuardrailConfig:
    """Scenario: Guardrail config."""

    def test_guardrail_fields_accessible(self):
        guardrail = ModelGuardrailConfig(
            guardrail_id="gd-123",
            guardrail_version="1",
            guardrail_trace="enabled",
        )
        assert guardrail.guardrail_id == "gd-123"
        assert guardrail.guardrail_version == "1"
        assert guardrail.guardrail_trace == "enabled"

    def test_model_config_with_guardrail(self):
        guardrail = ModelGuardrailConfig(guardrail_id="gd-456", guardrail_version="2")
        model = AgentModelConfig(provider="bedrock", guardrails=guardrail)
        assert model.guardrails is not None
        assert model.guardrails.guardrail_id == "gd-456"

    def test_model_config_without_guardrail(self):
        model = AgentModelConfig(provider="bedrock")
        assert model.guardrails is None


class TestBedrockModelConfig:
    """Scenario: Bedrock model config."""

    def test_bedrock_default_model(self):
        model = AgentModelConfig(provider="bedrock")
        assert model.provider == "bedrock"
        assert "anthropic" in model.model_id

    def test_custom_model_id(self):
        model = AgentModelConfig(provider="bedrock", model_id="custom-model-v1")
        assert model.model_id == "custom-model-v1"


class TestConfigFieldValidation:
    """Scenario: Field validation."""

    def test_empty_session_id_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(model=AgentModelConfig(), session_id="")

    def test_whitespace_session_id_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(model=AgentModelConfig(), session_id="   ")

    def test_negative_conversation_window_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(model=AgentModelConfig(), conversation_window_size=-1)

    def test_zero_conversation_window_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(model=AgentModelConfig(), conversation_window_size=0)

    def test_enable_memory_without_kb_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(model=AgentModelConfig(), enable_memory=True, knowledge_base_id=None)

    def test_enable_memory_with_kb_passes(self):
        config = StrandsAgentConfig(
            model=AgentModelConfig(),
            enable_memory=True,
            knowledge_base_id="kb-123",
        )
        assert config.enable_memory is True
        assert config.knowledge_base_id == "kb-123"

    def test_session_id_too_long_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(model=AgentModelConfig(), session_id="x" * 129)

    def test_max_query_length_out_of_range_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(model=AgentModelConfig(), max_query_length=8193)

    def test_agent_state_too_many_keys_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(
                model=AgentModelConfig(),
                agent_state_initial_values={f"k{i}": i for i in range(129)},
            )


class TestConfigFromEnv:
    """Scenario: Load from environment variables."""

    def test_from_env_with_custom_vars(self, monkeypatch):
        monkeypatch.setenv("STRANDS_MODEL_PROVIDER", "bedrock")
        monkeypatch.setenv("STRANDS_MODEL_ID", "custom-model")
        monkeypatch.setenv("STRANDS_TEMPERATURE", "0.5")
        monkeypatch.setenv("STRANDS_AGENT_NAME", "test-agent")

        config = StrandsAgentConfig.from_env()
        assert config.model.provider == "bedrock"
        assert config.model.model_id == "custom-model"
        assert config.model.temperature == 0.5
        assert config.agent_name == "test-agent"

    def test_from_env_invalid_temperature_raises(self, monkeypatch):
        monkeypatch.setenv("STRANDS_TEMPERATURE", "not-a-number")
        with pytest.raises(ValueError):
            StrandsAgentConfig.from_env()

    def test_from_env_invalid_mcp_json_raises(self, monkeypatch):
        import json

        monkeypatch.setenv("STRANDS_MCP_SERVERS", "not-json")
        with pytest.raises(json.JSONDecodeError):
            StrandsAgentConfig.from_env()
