# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for AgentToolRegistryManager — spec: strands-tool-registry."""

from unittest.mock import MagicMock

import pytest

from foundry_agent_core import ToolRegistrationError
from foundry_strands_agent._tool_factory import DependencyInjectedToolRegistry


@pytest.fixture
def container():
    c = MagicMock()
    c.get_registered_types.return_value = []
    return c


@pytest.fixture
def registry(container):
    return DependencyInjectedToolRegistry(container)


class TestRegisterAndRetrieveTool:
    """Scenario: Register and retrieve tool."""

    def test_register_tool_spec_module(self, registry):
        import types

        module = types.ModuleType("calc_tool")
        module.TOOL_SPEC = {"name": "calculator", "description": "A calculator", "inputSchema": {}}  # type: ignore[attr-defined]

        def calculator():
            pass

        module.calculator = calculator  # type: ignore[attr-defined]

        registry.register_tool(module)
        tools = registry.get_available_tools()
        assert len(tools) == 1
        assert tools[0] is module

    def test_register_decorated_function(self, registry):
        def my_tool():
            pass

        my_tool.__tool__ = True  # type: ignore[attr-defined]
        my_tool.__name__ = "my_tool"

        registry.register_tool(my_tool)
        tools = registry.get_available_tools()
        assert len(tools) == 1

    def test_get_available_tools_empty(self, registry):
        assert registry.get_available_tools() == []


class TestRegisterToolWithDependencies:
    """Scenario: Register tool with dependencies."""

    def test_register_with_deps(self, registry):
        def tool_fn():
            pass

        registry.register_tool_with_dependencies(
            tool_fn,
            dependencies=[str],
            metadata={"name": "dep_tool"},
        )
        tools = registry.get_available_tools()
        assert len(tools) == 1

    def test_duplicate_registration_raises(self, registry):
        def tool_fn():
            pass

        registry.register_tool_with_dependencies(tool_fn, dependencies=[], metadata={"name": "dup"})
        with pytest.raises(ToolRegistrationError):
            registry.register_tool_with_dependencies(tool_fn, dependencies=[], metadata={"name": "dup"})


class TestValidateToolDependencies:
    """Scenario: Validate tool dependencies."""

    def test_validation_passes_empty_registry(self, registry):
        result = registry.validate_tool_dependencies()
        assert result["valid"] is True

    def test_validation_fails_missing_dep(self, registry, container):
        container.get_registered_types.return_value = []

        def tool_fn():
            pass

        registry.register_tool_with_dependencies(tool_fn, dependencies=[int], metadata={"name": "needs_int"})
        result = registry.validate_tool_dependencies()
        assert result["valid"] is False
        assert len(result["issues"]) > 0


class TestUnregisterTool:
    """Scenario: Unregister tool."""

    def test_unregister_removes_tool(self, registry):
        def my_tool():
            pass

        my_tool.__tool__ = True  # type: ignore[attr-defined]
        my_tool.__name__ = "removable"

        registry.register_tool(my_tool)
        assert len(registry.get_available_tools()) == 1

        registry.unregister_tool("removable")
        assert len(registry.get_available_tools()) == 0

    def test_unregister_nonexistent_raises(self, registry):
        with pytest.raises(ToolRegistrationError):
            registry.unregister_tool("does_not_exist")


class TestRegistryStatistics:
    """Scenario: Registry statistics — tested via AgentToolRegistryManager."""

    def test_get_tool_metadata(self, registry):
        import types

        module = types.ModuleType("stat_tool")
        module.TOOL_SPEC = {"name": "stat_tool", "description": "Stats", "inputSchema": {}}  # type: ignore[attr-defined]

        def stat_tool():
            pass

        module.stat_tool = stat_tool  # type: ignore[attr-defined]

        registry.register_tool(module, metadata={"source": "test"})
        meta = registry.get_tool_metadata("stat_tool")
        assert "original_name" in meta

    def test_get_tool_dependencies(self, registry):
        def dep_tool():
            pass

        registry.register_tool_with_dependencies(dep_tool, dependencies=[str, int], metadata={"name": "dep_tool"})
        deps = registry.get_tool_dependencies("dep_tool")
        assert str in deps
        assert int in deps
