# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Extended config tests — spec: strands-agent-config."""

import json
from datetime import date

import pytest
from pydantic import ValidationError

from foundry_agent_core import _MAX_QUERY_LEN, InvalidConfigurationError
from foundry_strands_agent.config.models import (
    _MAX_AGENT_STATE_BYTES,
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


class TestSessionRestoreDanglingToolUse:
    """Scenario: configurable dangling-`tool_use` remediation mode."""

    def test_defaults_to_sanitize(self):
        config = StrandsAgentConfig(model=AgentModelConfig())
        assert config.session_restore_dangling_tool_use == "sanitize"

    def test_accepts_reject(self):
        config = StrandsAgentConfig(model=AgentModelConfig(), session_restore_dangling_tool_use="reject")
        assert config.session_restore_dangling_tool_use == "reject"

    def test_coerces_case(self):
        config = StrandsAgentConfig(model=AgentModelConfig(), session_restore_dangling_tool_use="REJECT")
        assert config.session_restore_dangling_tool_use == "reject"

    def test_invalid_value_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(model=AgentModelConfig(), session_restore_dangling_tool_use="delete")


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
        """The default is an active Bedrock model, not the end-of-life Claude Sonnet 4."""
        model = AgentModelConfig(provider="bedrock")
        assert model.provider == "bedrock"
        assert model.model_id == "us.anthropic.claude-haiku-5-5"

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
            StrandsAgentConfig(model=AgentModelConfig(), max_query_length=_MAX_QUERY_LEN + 1)

    def test_max_query_length_between_old_and_new_bound_succeeds(self):
        config = StrandsAgentConfig(model=AgentModelConfig(), max_query_length=100_000)
        assert config.max_query_length == 100_000

    def test_agent_state_too_many_keys_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(
                model=AgentModelConfig(),
                agent_state_initial_values={f"k{i}": i for i in range(129)},
            )

    @pytest.mark.parametrize("char", ["λ", "😀"])
    def test_agent_state_non_ascii_at_byte_cap_passes(self, char, utf8_sized_dict):
        r"""The agent-state byte cap counts UTF-8 bytes, not ``\uXXXX`` escapes."""
        state = utf8_sized_dict(char, _MAX_AGENT_STATE_BYTES)
        assert len(json.dumps(state, ensure_ascii=False).encode("utf-8")) == _MAX_AGENT_STATE_BYTES
        assert len(json.dumps(state)) > _MAX_AGENT_STATE_BYTES
        config = StrandsAgentConfig(model=AgentModelConfig(), agent_state_initial_values=state)
        assert config.agent_state_initial_values == state

    @pytest.mark.parametrize("char", ["λ", "😀"])
    def test_agent_state_non_ascii_over_byte_cap_raises(self, char, utf8_sized_dict):
        """Non-ASCII agent state one UTF-8 byte over the cap is rejected by the size bound."""
        with pytest.raises(InvalidConfigurationError, match="serializes above"):
            StrandsAgentConfig(
                model=AgentModelConfig(),
                agent_state_initial_values=utf8_sized_dict(char, _MAX_AGENT_STATE_BYTES + 1),
            )

    @pytest.mark.parametrize(
        "extra",
        [
            {f"k{i}": 0 for i in range(129)},  # too many keys
            {"x" * 129: 0},  # key too long
            {"pad": "x" * 1_048_576},  # too large
        ],
        ids=["keys", "key_length", "size"],
    )
    def test_agent_state_error_never_includes_values(self, extra):
        """A rejected agent state is redacted to its shape, never rendered into the error."""
        state = {"api_token": "SECRET-VALUE", **extra}
        with pytest.raises(InvalidConfigurationError) as excinfo:
            StrandsAgentConfig(model=AgentModelConfig(), agent_state_initial_values=state)
        assert "SECRET-VALUE" not in str(excinfo.value)
        assert "api_token" not in str(excinfo.value)
        assert excinfo.value.config_value == f"<redacted: {len(state)} top-level keys>"

    @pytest.mark.parametrize("bad", ["api_token=SECRET-VALUE", ["SECRET-VALUE"]], ids=["string", "list"])
    def test_agent_state_type_error_never_includes_input(self, bad):
        """Pydantic's own type error for agent state doesn't render the rejected input either."""
        with pytest.raises(ValidationError) as excinfo:
            StrandsAgentConfig(model=AgentModelConfig(), agent_state_initial_values=bad)
        assert "SECRET-VALUE" not in str(excinfo.value)

    def test_model_config_error_never_includes_api_key(self, monkeypatch):
        """AgentModelConfig is built on its own by from_env(), and its errors omit input values too."""
        monkeypatch.setenv("NIMS_API_KEY", "SECRET-VALUE" + "x" * 300)
        with pytest.raises(ValidationError) as excinfo:
            StrandsAgentConfig.from_env()
        assert "SECRET-VALUE" not in str(excinfo.value)

    def test_agent_state_json_cannot_encode_raises_config_error(self):
        """A nested key JSON can't encode, such as a date key from YAML, is a config error, not a TypeError."""
        state = {"api_token": "SECRET-VALUE", "a": {date(2024, 1, 1): "x"}}
        with pytest.raises(InvalidConfigurationError, match="is not JSON-serializable") as excinfo:
            StrandsAgentConfig(model=AgentModelConfig(), agent_state_initial_values=state)
        assert "SECRET-VALUE" not in str(excinfo.value)

    def test_agent_state_lone_surrogate_passes(self):
        """A lone surrogate is sized rather than rejected."""
        config = StrandsAgentConfig(model=AgentModelConfig(), agent_state_initial_values={"k": "\ud83d"})
        assert config.agent_state_initial_values == {"k": "\ud83d"}

    def test_max_tokens_at_ceiling_passes(self):
        model = AgentModelConfig(max_tokens=131_072)
        assert model.max_tokens == 131_072

    def test_max_tokens_above_ceiling_raises(self):
        with pytest.raises(ValidationError):
            AgentModelConfig(max_tokens=131_073)


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

    def test_from_env_default_model(self, monkeypatch):
        """Without STRANDS_MODEL_ID, from_env() falls back to the same default as AgentModelConfig."""
        monkeypatch.delenv("STRANDS_MODEL_ID", raising=False)
        assert StrandsAgentConfig.from_env().model.model_id == "us.anthropic.claude-haiku-5-5"

    def test_from_env_invalid_temperature_raises(self, monkeypatch):
        monkeypatch.setenv("STRANDS_TEMPERATURE", "not-a-number")
        with pytest.raises(ValueError):
            StrandsAgentConfig.from_env()

    def test_from_env_invalid_mcp_json_raises(self, monkeypatch):
        import json

        monkeypatch.setenv("STRANDS_MCP_SERVERS", "not-json")
        with pytest.raises(json.JSONDecodeError):
            StrandsAgentConfig.from_env()


class TestToolsDirField:
    """Scenarios: tools_dir defaults to None; tools_dir is bounded."""

    def test_tools_dir_defaults_to_none(self):
        config = StrandsAgentConfig(model=AgentModelConfig())
        assert config.tools_dir is None

    def test_tools_dir_accepted(self):
        config = StrandsAgentConfig(model=AgentModelConfig(), tools_dir="/srv/agent/tools")
        assert config.tools_dir == "/srv/agent/tools"

    def test_tools_dir_stripped(self):
        config = StrandsAgentConfig(model=AgentModelConfig(), tools_dir="  /srv/agent/tools  ")
        assert config.tools_dir == "/srv/agent/tools"

    def test_tools_dir_too_long_raises(self):
        with pytest.raises((InvalidConfigurationError, ValidationError)):
            StrandsAgentConfig(model=AgentModelConfig(), tools_dir="/" + "x" * 1024)


class TestToolsDirFromEnv:
    """Scenarios: STRANDS_TOOLS_DIR is read; STRANDS_TOOLS_DIR absent."""

    def test_from_env_reads_tools_dir(self, monkeypatch):
        monkeypatch.setenv("STRANDS_TOOLS_DIR", "/srv/agent/tools")

        config = StrandsAgentConfig.from_env()
        assert config.tools_dir == "/srv/agent/tools"

    def test_from_env_without_tools_dir_is_none(self, monkeypatch):
        monkeypatch.delenv("STRANDS_TOOLS_DIR", raising=False)

        config = StrandsAgentConfig.from_env()
        assert config.tools_dir is None

    def test_from_env_empty_tools_dir_is_none(self, monkeypatch):
        monkeypatch.setenv("STRANDS_TOOLS_DIR", "")

        config = StrandsAgentConfig.from_env()
        assert config.tools_dir is None


class TestBedrockTemperatureRejectingModelsFromEnv:
    """Scenarios: STRANDS_BEDROCK_TEMPERATURE_REJECTING_MODELS is read; absent defaults to []."""

    def test_from_env_reads_bedrock_temperature_rejecting_models(self, monkeypatch):
        monkeypatch.setenv("STRANDS_BEDROCK_TEMPERATURE_REJECTING_MODELS", "xai.grok-4.6, custom.my-model ")

        config = StrandsAgentConfig.from_env()
        assert config.model.bedrock_temperature_rejecting_models == ["xai.grok-4.6", "custom.my-model"]

    def test_from_env_without_bedrock_temperature_rejecting_models_is_empty(self, monkeypatch):
        monkeypatch.delenv("STRANDS_BEDROCK_TEMPERATURE_REJECTING_MODELS", raising=False)

        config = StrandsAgentConfig.from_env()
        assert config.model.bedrock_temperature_rejecting_models == []
