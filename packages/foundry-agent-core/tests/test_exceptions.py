# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for exception hierarchy."""

from foundry_agent_core.exceptions import (
    AgentCreationError,
    ConfigurationError,
    DomainError,
    ExternalServiceError,
    InvalidConfigurationError,
    QueryProcessingError,
    QueryTimeoutError,
    ResourceNotFoundError,
    ToolExecutionError,
    ToolLoadingError,
    ToolRegistrationError,
    ValidationError,
)


class TestDomainError:
    def test_message_and_context(self) -> None:
        err = DomainError("test error", context={"key": "val"})
        assert err.message == "test error"
        assert err.context == {"key": "val"}

    def test_str_with_context(self) -> None:
        err = DomainError("fail", context={"a": 1})
        assert "fail" in str(err)
        assert "a=1" in str(err)

    def test_str_without_context(self) -> None:
        err = DomainError("simple")
        assert str(err) == "simple"

    def test_default_context_empty(self) -> None:
        err = DomainError("test")
        assert err.context == {}


class TestSpecificExceptions:
    def test_resource_not_found(self) -> None:
        err = ResourceNotFoundError(["id1", "id2"])
        assert "id1" in str(err)
        assert err.resource_ids == ["id1", "id2"]

    def test_invalid_configuration(self) -> None:
        err = InvalidConfigurationError("key", "bad_val", "must be int")
        assert err.config_key == "key"
        assert err.config_value == "bad_val"
        assert "must be int" in str(err)

    def test_tool_registration_error(self) -> None:
        err = ToolRegistrationError("my_tool", "invalid signature")
        assert err.tool_name == "my_tool"
        assert err.reason == "invalid signature"

    def test_validation_error(self) -> None:
        err = ValidationError("field", "val", "too short")
        assert err.field_name == "field"
        assert err.field_value == "val"
        assert "too short" in str(err)

    def test_query_timeout_error(self) -> None:
        err = QueryTimeoutError(5000)
        assert err.timeout_ms == 5000
        assert "5000ms" in str(err)

    def test_external_service_error(self) -> None:
        err = ExternalServiceError("connection failed")
        assert isinstance(err, DomainError)

    def test_tool_execution_error(self) -> None:
        err = ToolExecutionError("tool crashed")
        assert isinstance(err, DomainError)

    def test_configuration_error(self) -> None:
        err = ConfigurationError("missing key")
        assert isinstance(err, DomainError)

    def test_agent_creation_error(self) -> None:
        err = AgentCreationError("factory failed")
        assert isinstance(err, DomainError)

    def test_tool_loading_error(self) -> None:
        err = ToolLoadingError("import failed")
        assert isinstance(err, DomainError)

    def test_query_processing_error(self) -> None:
        err = QueryProcessingError("pipeline failed")
        assert isinstance(err, DomainError)
