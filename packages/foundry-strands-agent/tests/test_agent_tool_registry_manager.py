# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for AgentToolRegistryManager."""

from unittest.mock import MagicMock

import pytest

from foundry_agent_core import DependencyContainer, ToolLoadingError, ToolRegistrationError
from foundry_strands_agent.registry import AgentToolRegistryManager


@pytest.fixture
def container():
    """Create a mock dependency container."""
    c = MagicMock(spec=DependencyContainer)
    c.get_registered_types.return_value = []
    return c


@pytest.fixture
def manager(container):
    """Create an AgentToolRegistryManager instance."""
    return AgentToolRegistryManager(container)


class TestRegisterTool:
    """Test tool registration."""

    def test_register_tool_function(self, manager):
        """Test registering a tool function."""

        def my_tool():
            """A test tool."""
            pass

        my_tool.__tool__ = True  # type: ignore
        my_tool.__name__ = "my_tool"

        manager.register_tool(my_tool)
        tools = manager.get_available_tools()
        assert len(tools) == 1

    def test_register_tool_with_metadata(self, manager):
        """Test registering a tool with metadata."""

        def my_tool():
            pass

        my_tool.__tool__ = True  # type: ignore
        my_tool.__name__ = "my_tool"

        metadata = {"category": "test", "version": "1.0"}
        manager.register_tool(my_tool, metadata=metadata)
        tools = manager.get_available_tools()
        assert len(tools) == 1


class TestRegisterToolWithDependencies:
    """Test tool registration with dependencies."""

    def test_register_with_deps(self, manager, container):
        """Test registering a tool with dependencies."""
        container.get_registered_types.return_value = [str]

        def tool_fn():
            pass

        manager.register_tool_with_dependencies(
            tool_fn,
            dependencies=[str],
            metadata={"name": "dep_tool"},
        )
        tools = manager.get_available_tools()
        assert len(tools) == 1

    def test_register_duplicate_raises(self, manager, container):
        """Test that registering duplicate tool raises error."""
        container.get_registered_types.return_value = []

        def tool_fn():
            pass

        manager.register_tool_with_dependencies(
            tool_fn,
            dependencies=[],
            metadata={"name": "dup"},
        )

        with pytest.raises(ToolRegistrationError):
            manager.register_tool_with_dependencies(
                tool_fn,
                dependencies=[],
                metadata={"name": "dup"},
            )


class TestUnregisterTool:
    """Test tool unregistration."""

    def test_unregister_existing_tool(self, manager):
        """Test unregistering an existing tool."""

        def my_tool():
            pass

        my_tool.__tool__ = True  # type: ignore
        my_tool.__name__ = "removable"

        manager.register_tool(my_tool)
        assert len(manager.get_available_tools()) == 1

        manager.unregister_tool("removable")
        assert len(manager.get_available_tools()) == 0

    def test_unregister_nonexistent_raises(self, manager):
        """Test that unregistering nonexistent tool raises error."""
        with pytest.raises(ToolRegistrationError):
            manager.unregister_tool("does_not_exist")


class TestGetAvailableTools:
    """Test getting available tools."""

    def test_get_empty_tools(self, manager):
        """Test getting tools when none registered."""
        assert manager.get_available_tools() == []

    def test_get_multiple_tools(self, manager):
        """Test getting multiple registered tools."""

        def tool1():
            pass

        def tool2():
            pass

        tool1.__tool__ = True  # type: ignore
        tool1.__name__ = "tool1"
        tool2.__tool__ = True  # type: ignore
        tool2.__name__ = "tool2"

        manager.register_tool(tool1)
        manager.register_tool(tool2)

        tools = manager.get_available_tools()
        assert len(tools) == 2


class TestGetToolMetadata:
    """Test getting tool metadata."""

    def test_get_metadata_for_registered_tool(self, manager):
        """Test getting metadata for a registered tool."""

        def my_tool():
            pass

        my_tool.__tool__ = True  # type: ignore
        my_tool.__name__ = "my_tool"

        manager.register_tool(my_tool, metadata={"version": "1.0"})
        metadata = manager.get_tool_metadata("my_tool")

        assert metadata is not None
        assert "original_name" in metadata or "version" in metadata


class TestGetToolDependencies:
    """Test getting tool dependencies."""

    def test_get_dependencies_for_tool(self, manager, container):
        """Test getting dependencies for a tool."""
        container.get_registered_types.return_value = [str, int]

        def dep_tool():
            pass

        manager.register_tool_with_dependencies(
            dep_tool,
            dependencies=[str, int],
            metadata={"name": "dep_tool"},
        )

        deps = manager.get_tool_dependencies("dep_tool")
        assert str in deps
        assert int in deps


class TestValidateToolDependencies:
    """Test tool dependency validation."""

    def test_validate_empty_registry(self, manager):
        """Test validation with empty registry."""
        result = manager.validate_tool_dependencies()
        assert result["valid"] is True
        assert result["issues"] == []

    def test_validate_with_missing_deps(self, manager, container):
        """Test that registration fails when dependencies are missing."""
        container.get_registered_types.return_value = []

        def tool_fn():
            pass

        # Registration should fail due to missing dependencies
        with pytest.raises(ToolRegistrationError, match="dependencies validation failed"):
            manager.register_tool_with_dependencies(
                tool_fn,
                dependencies=[int],
                metadata={"name": "needs_int"},
            )

    def test_validate_with_satisfied_deps(self, manager, container):
        """Test validation when all dependencies are satisfied."""
        container.get_registered_types.return_value = [str, int]

        def tool_fn():
            pass

        manager.register_tool_with_dependencies(
            tool_fn,
            dependencies=[str],
            metadata={"name": "needs_str"},
        )

        result = manager.validate_tool_dependencies()
        assert result["valid"] is True


class TestLoadToolsFromDirectory:
    """Test loading tools from directory."""

    def test_load_tools_invalid_path_raises(self, manager):
        """Test that loading from invalid path raises error."""
        with pytest.raises(ToolLoadingError):
            manager.load_tools_from_directory("/nonexistent/path/to/tools")


class TestGetRegistryStatistics:
    """Test registry statistics."""

    def test_get_statistics_empty(self, manager):
        """Test getting statistics for empty registry."""
        stats = manager.get_registry_statistics()
        assert stats["total_tools"] == 0
        assert stats["tools_with_dependencies"] == 0

    def test_get_statistics_with_tools(self, manager, container):
        """Test getting statistics with registered tools."""
        container.get_registered_types.return_value = [str]

        def tool1():
            pass

        def tool2():
            pass

        tool1.__tool__ = True  # type: ignore
        tool1.__name__ = "tool1"

        manager.register_tool(tool1)
        manager.register_tool_with_dependencies(
            tool2,
            dependencies=[str],
            metadata={"name": "tool2"},
        )

        stats = manager.get_registry_statistics()
        assert stats["total_tools"] == 2
