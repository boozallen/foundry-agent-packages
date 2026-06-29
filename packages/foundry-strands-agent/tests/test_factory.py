# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for StrandsAgentFactory — boost coverage on testable paths."""

from unittest.mock import MagicMock, patch

import pytest

from foundry_agent_core import AgentCreationError
from foundry_strands_agent.factory import (
    DEFAULT_MODEL_PROVIDER_FACTORIES,
    DEFAULT_SESSION_MANAGER_FACTORIES,
    NIMSModel,
    StrandsAgentFactory,
    _default_bedrock_model,
    _default_file_session_manager,
    _default_nims_model,
    _default_ollama_model,
    _default_s3_session_manager,
)


class TestDefaultSessionManagerFactories:
    def test_file_session_manager_creates(self, monkeypatch):
        import secrets

        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", secrets.token_hex(32))
        with patch("foundry_strands_agent.factory.EncryptedFileSessionManager") as mock_efsm:
            mock_efsm.return_value = MagicMock()
            _default_file_session_manager(session_id="test-session")
            mock_efsm.assert_called_once()
            call_kwargs = mock_efsm.call_args[1]
            assert call_kwargs["session_id"] == "test-session"
            assert call_kwargs["storage_dir"] is None
            assert len(call_kwargs["encryption_key"]) == 32

    def test_s3_session_manager_requires_bucket(self):
        with pytest.raises(AgentCreationError, match="session_s3_bucket is required"):
            _default_s3_session_manager(session_id="test-123", s3_bucket=None)

    def test_s3_session_manager_creates_with_bucket(self):
        with patch("foundry_strands_agent.factory.S3SessionManager") as mock_s3:
            mock_s3.return_value = MagicMock()
            _default_s3_session_manager(
                session_id="test-123",
                s3_bucket="my-bucket",
                s3_prefix="prefix/",
                s3_region="us-east-1",
            )
            mock_s3.assert_called_once_with(
                session_id="test-123",
                bucket="my-bucket",
                prefix="prefix/",
                region="us-east-1",
            )


class TestStrandsAgentFactoryInit:
    def test_default_factories(self):
        container = MagicMock()
        factory = StrandsAgentFactory(container=container)
        assert factory._session_manager_factories is DEFAULT_SESSION_MANAGER_FACTORIES
        assert factory._model_provider_factories is DEFAULT_MODEL_PROVIDER_FACTORIES

    def test_custom_session_factories(self):
        container = MagicMock()
        custom = {"custom": MagicMock()}
        factory = StrandsAgentFactory(container=container, session_manager_factories=custom)
        assert factory._session_manager_factories is custom

    def test_custom_model_factories(self):
        container = MagicMock()
        custom = {"custom": MagicMock()}
        factory = StrandsAgentFactory(container=container, model_provider_factories=custom)
        assert factory._model_provider_factories is custom


class TestCreateModel:
    def test_unsupported_provider_raises(self):
        container = MagicMock()
        factory = StrandsAgentFactory(container=container)
        with pytest.raises(AgentCreationError, match="Unsupported model provider"):
            factory.create_model({"model": {"provider": "nonexistent"}})

    def test_bedrock_provider_calls_factory(self):
        container = MagicMock()
        mock_bedrock = MagicMock(return_value=MagicMock())
        factory = StrandsAgentFactory(
            container=container,
            model_provider_factories={"bedrock": mock_bedrock},
        )
        config = {"model": {"provider": "bedrock", "model_id": "test"}}
        factory.create_model(config)
        mock_bedrock.assert_called_once_with(config)


class TestValidateAgentConfiguration:
    def test_valid_config(self):
        container = MagicMock()
        factory = StrandsAgentFactory(container=container)
        result = factory.validate_agent_configuration(
            {
                "model": {"provider": "bedrock", "model_id": "test"},
                "system_prompt": "hello",
            }
        )
        assert result["valid"] is True

    def test_missing_model(self):
        container = MagicMock()
        factory = StrandsAgentFactory(container=container)
        result = factory.validate_agent_configuration({"system_prompt": "hello"})
        assert result["valid"] is False
        assert any("model" in err for err in result["errors"])

    def test_invalid_temperature(self):
        container = MagicMock()
        factory = StrandsAgentFactory(container=container)
        result = factory.validate_agent_configuration(
            {
                "model": {"provider": "bedrock", "model_id": "test", "temperature": 5.0},
                "system_prompt": "hello",
            }
        )
        assert any("temperature" in w for w in result["errors"])

    def test_tools_not_list(self):
        container = MagicMock()
        factory = StrandsAgentFactory(container=container)
        result = factory.validate_agent_configuration(
            {
                "model": {"provider": "bedrock", "model_id": "test"},
                "system_prompt": "hello",
                "tools": "not-a-list",
            }
        )
        assert result["valid"] is False


class TestCreateSessionManager:
    def test_unsupported_type_raises(self):
        container = MagicMock()
        factory = StrandsAgentFactory(container=container)
        with pytest.raises(AgentCreationError, match="Unsupported session type"):
            factory._create_session_manager(session_id="session1", session_type="redis")

    def test_factory_invoked_for_file_type(self):
        mock_factory = MagicMock(return_value=MagicMock())
        container = MagicMock()
        factory = StrandsAgentFactory(
            container=container,
            session_manager_factories={"file": mock_factory},
        )
        factory._create_session_manager(session_id="session1", session_type="file")
        mock_factory.assert_called_once()

    def test_factory_exception_wrapped(self):
        def broken_factory(**kwargs):
            raise RuntimeError("boom")

        container = MagicMock()
        factory = StrandsAgentFactory(
            container=container,
            session_manager_factories={"file": broken_factory},
        )
        with pytest.raises(AgentCreationError, match="Failed to create session manager"):
            factory._create_session_manager(session_id="session1", session_type="file")


class TestNimsModel:
    """Tests for NIMSModel.format_request patches."""

    def _make_model(self) -> NIMSModel:
        return NIMSModel(
            client_args={"base_url": "http://nims:8000/v1", "api_key": "test-key"},
            model_id="meta/llama-3.1-8b-instruct",
        )

    def test_strips_empty_tools_and_tool_choice(self):
        model = self._make_model()
        base_request = {"messages": [{"role": "user", "content": "hi"}], "tools": [], "tool_choice": "auto"}
        with patch.object(type(model).__bases__[0], "format_request", return_value=base_request):
            result = model.format_request([])
        assert "tools" not in result
        assert "tool_choice" not in result

    def test_preserves_non_empty_tools(self):
        model = self._make_model()
        tool = {"type": "function", "function": {"name": "my_tool"}}
        base_request = {"messages": [], "tools": [tool], "tool_choice": "auto"}
        with patch.object(type(model).__bases__[0], "format_request", return_value=base_request):
            result = model.format_request([])
        assert result["tools"] == [tool]
        assert result["tool_choice"] == "auto"

    def test_flattens_content_block_list(self):
        model = self._make_model()
        base_request = {
            "messages": [{"role": "user", "content": [{"text": "hello"}, {"text": "world"}]}],
        }
        with patch.object(type(model).__bases__[0], "format_request", return_value=base_request):
            result = model.format_request([])
        assert result["messages"][0]["content"] == "hello world"

    def test_leaves_string_content_unchanged(self):
        model = self._make_model()
        base_request = {"messages": [{"role": "user", "content": "plain string"}]}
        with patch.object(type(model).__bases__[0], "format_request", return_value=base_request):
            result = model.format_request([])
        assert result["messages"][0]["content"] == "plain string"

    def test_skips_partial_text_blocks(self):
        """Mixed blocks (some without 'text') are left as-is."""
        model = self._make_model()
        mixed = [{"text": "hi"}, {"image_url": "..."}]
        base_request = {"messages": [{"role": "user", "content": mixed}]}
        with patch.object(type(model).__bases__[0], "format_request", return_value=base_request):
            result = model.format_request([])
        assert result["messages"][0]["content"] == mixed

    def test_empty_content_list_normalised_to_none(self):
        """Assistant message after a tool call has content: [] — NVIDIA rejects that, must be null."""
        model = self._make_model()
        base_request = {
            "messages": [
                {"role": "assistant", "content": [], "tool_calls": [{"id": "call_1", "function": {"name": "foo"}}]}
            ]
        }
        with patch.object(type(model).__bases__[0], "format_request", return_value=base_request):
            result = model.format_request([])
        assert result["messages"][0]["content"] is None

    def test_tool_call_roundtrip_strips_tools_and_normalises_content(self):
        """Combined: no tools available + assistant tool-call message in history."""
        model = self._make_model()
        base_request = {
            "messages": [
                {"role": "user", "content": "run the tool"},
                {"role": "assistant", "content": [], "tool_calls": [{"id": "c1", "function": {"name": "t"}}]},
                {"role": "tool", "content": "result", "tool_call_id": "c1"},
            ],
            "tools": [],
            "tool_choice": "auto",
        }
        with patch.object(type(model).__bases__[0], "format_request", return_value=base_request):
            result = model.format_request([])
        assert "tools" not in result
        assert "tool_choice" not in result
        assert result["messages"][1]["content"] is None
        assert result["messages"][2]["content"] == "result"


class TestNimsModelFactory:
    def test_default_nvidia_cloud_endpoint(self):
        with patch("foundry_strands_agent.factory.NIMSModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            _default_nims_model({"model": {"model_id": "meta/llama-3.1-8b-instruct"}})
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["model_id"] == "meta/llama-3.1-8b-instruct"
            assert call_kwargs["client_args"]["base_url"] == "https://integrate.api.nvidia.com/v1"
            assert call_kwargs["client_args"]["api_key"] == "no-key"
            assert call_kwargs["client_args"]["http_client"] is not None

    def test_explicit_self_hosted_cluster_url(self):
        with patch("foundry_strands_agent.factory.NIMSModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            _default_nims_model(
                {"model": {"model_id": "meta/llama-3.1-8b-instruct", "nims_base_url": "http://cluster:8000/v1"}}
            )
            assert mock_cls.call_args[1]["client_args"]["base_url"] == "http://cluster:8000/v1"

    def test_api_key_passthrough(self):
        with patch("foundry_strands_agent.factory.NIMSModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            _default_nims_model({"model": {"model_id": "meta/llama-3.1-8b-instruct", "nims_api_key": "nvapi-abc123"}})
            assert mock_cls.call_args[1]["client_args"]["api_key"] == "nvapi-abc123"


class TestNimsFactoryDispatch:
    def test_nims_provider_dispatches_to_factory(self):
        container = MagicMock()
        mock_nims = MagicMock(return_value=MagicMock())
        factory = StrandsAgentFactory(
            container=container,
            model_provider_factories={"nims": mock_nims},
        )
        config = {"model": {"provider": "nims", "model_id": "meta/llama-3.1-8b-instruct"}}
        factory.create_model(config)
        mock_nims.assert_called_once_with(config)


class TestBedrockModelMaxTokens:
    """Tests for _default_bedrock_model max_tokens passthrough."""

    def test_max_tokens_passed_to_bedrock_model(self):
        with patch("foundry_strands_agent.factory.BedrockModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            config = {"model": {"model_id": "us.anthropic.claude-sonnet-4-20250514-v1:0", "max_tokens": 16384}}
            _default_bedrock_model(config)
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["max_tokens"] == 16384

    def test_max_tokens_none_when_not_configured(self):
        with patch("foundry_strands_agent.factory.BedrockModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            _default_bedrock_model({"model": {"model_id": "us.anthropic.claude-sonnet-4-20250514-v1:0"}})
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["max_tokens"] is None

    def test_max_tokens_passed_with_guardrails(self):
        with patch("foundry_strands_agent.factory.BedrockModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            _default_bedrock_model(
                {
                    "model": {"model_id": "us.anthropic.claude-sonnet-4-20250514-v1:0", "max_tokens": 32000},
                    "guardrail_config": {
                        "guardrail_id": "gr-123",
                        "guardrail_version": "1",
                        "guardrail_trace": "enabled",
                    },
                }
            )
            call_kwargs = mock_cls.call_args[1]
            assert call_kwargs["max_tokens"] == 32000
            assert call_kwargs["guardrail_id"] == "gr-123"


class TestOllamaModelUrlFallback:
    """Tests for _default_ollama_model OLLAMA_URL env var fallback."""

    @pytest.fixture(autouse=True)
    def _mock_ollama_module(self, monkeypatch):
        """Inject a fake strands.models.ollama module since ollama isn't installed in test env."""
        import sys
        import types

        mock_module = types.ModuleType("strands.models.ollama")
        self.mock_ollama_cls = MagicMock(return_value=MagicMock())
        mock_module.OllamaModel = self.mock_ollama_cls
        monkeypatch.setitem(sys.modules, "strands.models.ollama", mock_module)

    def test_ollama_url_from_config(self):
        _default_ollama_model(
            {
                "model": {
                    "model_id": "llama3.2:3b",
                    "ollama_url": "http://my-host:11434",
                    "temperature": 0.3,
                },
            }
        )
        call_kwargs = self.mock_ollama_cls.call_args[1]
        assert call_kwargs["host"] == "http://my-host:11434"

    def test_ollama_url_falls_back_to_env_var(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "http://docker-host:11434")
        _default_ollama_model(
            {
                "model": {
                    "model_id": "llama3.2:3b",
                    "ollama_url": None,
                    "temperature": 0.3,
                },
            }
        )
        call_kwargs = self.mock_ollama_cls.call_args[1]
        assert call_kwargs["host"] == "http://docker-host:11434"

    def test_ollama_url_config_takes_precedence_over_env(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "http://env-host:11434")
        _default_ollama_model(
            {
                "model": {
                    "model_id": "llama3.2:3b",
                    "ollama_url": "http://yaml-host:11434",
                    "temperature": 0.3,
                },
            }
        )
        call_kwargs = self.mock_ollama_cls.call_args[1]
        assert call_kwargs["host"] == "http://yaml-host:11434"

    def test_ollama_url_none_when_neither_config_nor_env(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_URL", raising=False)
        _default_ollama_model(
            {
                "model": {
                    "model_id": "llama3.2:3b",
                    "ollama_url": None,
                    "temperature": 0.3,
                },
            }
        )
        call_kwargs = self.mock_ollama_cls.call_args[1]
        assert call_kwargs["host"] is None
