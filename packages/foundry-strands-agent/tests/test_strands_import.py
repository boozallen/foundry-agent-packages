# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for foundry-strands-agent package — acceptance criteria validation."""

import difflib
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import foundry_strands_agent


def test_import():
    """Smoke test: package imports without error."""
    assert foundry_strands_agent is not None


class TestAC1ImportStrandsAgentBackend:
    """AC1: StrandsAgentBackend import succeeds."""

    def test_import_from_package(self):
        from foundry_strands_agent import StrandsAgentBackend

        assert StrandsAgentBackend is not None

    def test_import_from_module(self):
        from foundry_strands_agent.backend import StrandsAgentBackend

        assert StrandsAgentBackend is not None


class TestAC2ProtocolConformance:
    """AC2: StrandsAgentBackend satisfies AgentBackend protocol."""

    def test_has_name_property(self):
        from foundry_strands_agent.backend import StrandsAgentBackend

        assert hasattr(StrandsAgentBackend, "name")

    def test_has_description_property(self):
        from foundry_strands_agent.backend import StrandsAgentBackend

        assert hasattr(StrandsAgentBackend, "description")

    def test_has_process_message_method(self):
        from foundry_strands_agent.backend import StrandsAgentBackend

        assert hasattr(StrandsAgentBackend, "process_message")
        assert inspect.iscoroutinefunction(StrandsAgentBackend.process_message)

    def test_process_message_signature(self):
        from foundry_strands_agent.backend import StrandsAgentBackend

        sig = inspect.signature(StrandsAgentBackend.process_message)
        params = list(sig.parameters.keys())
        assert "request" in params

    def test_structural_subtyping(self):
        """Verify StrandsAgentBackend structurally matches AgentBackend protocol."""
        from foundry_strands_agent.backend import StrandsAgentBackend

        backend_methods = {"name", "description", "process_message"}
        for method_name in backend_methods:
            assert hasattr(StrandsAgentBackend, method_name), f"Missing: {method_name}"


class TestAC3ToolLoaderFrozen:
    """AC3: tool_loader.py diff shows only import path changes."""

    def test_tool_loader_diff_only_imports(self):
        original = Path(__file__).parents[5] / "strands-base-agent/strands_base_agent/agent/tool_loader.py"
        extracted = Path(__file__).parents[1] / "src/foundry_strands_agent/tool_loader.py"

        if not original.exists():
            pytest.skip("Original tool_loader.py not available for diff comparison")

        original_lines = original.read_text().splitlines()
        extracted_lines = extracted.read_text().splitlines()

        diff = list(difflib.unified_diff(original_lines, extracted_lines, lineterm=""))

        non_import_changes = []
        for line in diff:
            if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
                continue
            if not (line.startswith("+") or line.startswith("-")):
                continue

            content = line[1:].strip()
            if not content:
                continue

            if content.startswith("from ") or content.startswith("import "):
                continue

            non_import_changes.append(line)

        assert non_import_changes == [], "tool_loader.py has non-import changes:\n" + "\n".join(non_import_changes)


class TestAC4CustomSessionManagerFactories:
    """AC4: Custom session_manager_factories are invoked."""

    def test_custom_session_factory_stored(self):
        from foundry_strands_agent.factory import StrandsAgentFactory

        custom_factories = {"custom": MagicMock()}
        container = MagicMock()

        factory = StrandsAgentFactory(
            container=container,
            session_manager_factories=custom_factories,
        )

        assert factory._session_manager_factories is custom_factories

    def test_default_session_factories_when_none_provided(self):
        from foundry_strands_agent.factory import DEFAULT_SESSION_MANAGER_FACTORIES, StrandsAgentFactory

        container = MagicMock()
        factory = StrandsAgentFactory(container=container)

        assert factory._session_manager_factories is DEFAULT_SESSION_MANAGER_FACTORIES

    def test_custom_model_provider_factories(self):
        from foundry_strands_agent.factory import StrandsAgentFactory

        custom_providers = {"custom_provider": MagicMock()}
        container = MagicMock()

        factory = StrandsAgentFactory(
            container=container,
            model_provider_factories=custom_providers,
        )

        assert factory._model_provider_factories is custom_providers


class TestConfigValidation:
    """Additional tests for StrandsAgentConfig."""

    def test_config_construction(self):
        from foundry_strands_agent.config.models import AgentModelConfig, StrandsAgentConfig

        config = StrandsAgentConfig(model=AgentModelConfig())
        assert config.model.provider == "bedrock"
        assert config.agent_name == "strands-base-agent"

    def test_config_frozen(self):
        from pydantic import ValidationError

        from foundry_strands_agent.config.models import AgentModelConfig, StrandsAgentConfig

        config = StrandsAgentConfig(model=AgentModelConfig())
        with pytest.raises(ValidationError):
            config.agent_name = "changed"  # type: ignore[misc]

    def test_config_from_env(self):
        from foundry_strands_agent.config.models import StrandsAgentConfig

        config = StrandsAgentConfig.from_env()
        assert config.model.provider == "bedrock"

    def test_session_type_coercion(self):
        from foundry_strands_agent.config.models import AgentModelConfig, StrandsAgentConfig, StrandsSessionManagerType

        config = StrandsAgentConfig(model=AgentModelConfig(), session_type="file")  # pyright: ignore[reportArgumentType]
        assert config.session_type is StrandsSessionManagerType.FILE


class TestExceptionHierarchy:
    """Tests for agent-specific exceptions."""

    def test_agent_service_error_is_query_processing_error(self):
        from foundry_agent_core import QueryProcessingError
        from foundry_strands_agent.exceptions import AgentServiceError

        assert issubclass(AgentServiceError, QueryProcessingError)

    def test_init_error_is_service_error(self):
        from foundry_strands_agent.exceptions import AgentServiceError, AgentServiceInitializationError

        assert issubclass(AgentServiceInitializationError, AgentServiceError)

    def test_shutdown_error_is_service_error(self):
        from foundry_strands_agent.exceptions import AgentServiceError, AgentServiceShutdownError

        assert issubclass(AgentServiceShutdownError, AgentServiceError)

    def test_exception_context(self):
        from foundry_strands_agent.exceptions import AgentServiceError

        err = AgentServiceError("test", context={"key": "value"})
        assert err.context["key"] == "value"


class TestTypeConstruction:
    """Tests for Strands-specific types."""

    def test_query_request(self):
        from foundry_strands_agent.types import QueryRequest

        req = QueryRequest(query="hello")
        assert req.query == "hello"
        assert req.max_results == 10
        assert req.similarity_threshold == 0.7

    def test_query_request_frozen(self):
        from pydantic import ValidationError

        from foundry_strands_agent.types import QueryRequest

        req = QueryRequest(query="hello")
        with pytest.raises(ValidationError):
            req.query = "changed"  # type: ignore[misc]

    def test_query_request_validation(self):
        from pydantic import ValidationError

        from foundry_strands_agent.types import QueryRequest

        with pytest.raises(ValidationError):
            QueryRequest(query="")

    def test_search_result(self):
        from foundry_strands_agent.types import SearchResult

        result = SearchResult(
            document_id="doc1",
            content_preview="preview",
            similarity_score=0.9,
            metadata={"key": "value"},
        )
        assert result.document_id == "doc1"
        assert result.similarity_score == 0.9
