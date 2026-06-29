# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Agent tool registry implementation with dependency injection integration.

This module provides the agent-layer implementation of tool registration and
management, integrating with the dependency injection container for Strands
Agent instances.
"""

import logging
from collections.abc import Sequence
from typing import Any

from foundry_agent_core import DependencyContainer, ToolLoadingError, ToolRegistrationError
from foundry_strands_agent._tool_factory import create_tool_registry
from foundry_strands_agent.protocols import ToolFunction, ToolMetadata

logger = logging.getLogger(__name__)


class AgentToolRegistryManager:
    """Manager for agent tool registry with dependency injection integration.

    This class provides agent-layer functionality for tool registration and
    integration with the dependency injection container, extending the base
    tool registry with agent-specific features.
    """

    def __init__(self, container: DependencyContainer) -> None:
        """Initialize tool registry manager with dependency container.

        Args:
            container: Dependency injection container for infrastructure components
        """
        self._container = container
        self._registry = create_tool_registry(container)

    def register_tool(
        self,
        tool_function: ToolFunction,
        metadata: ToolMetadata | None = None,
    ) -> None:
        """Register a tool function for use by agents.

        Args:
            tool_function: Tool following Strands patterns
            metadata: Optional metadata about the tool

        Raises:
            ToolRegistrationError: If tool registration fails
        """
        try:
            # Extract tool name for logging
            tool_name = self._extract_tool_name(tool_function, metadata)

            logger.debug(
                "Registering tool with agent registry",
                extra={"tool_name": tool_name},
            )

            # Register with underlying registry
            self._registry.register_tool(tool_function, metadata)

            logger.info(
                "Tool registered successfully",
                extra={
                    "tool_name": tool_name,
                    "has_metadata": metadata is not None,
                },
            )

        except Exception as e:
            if isinstance(e, ToolRegistrationError):
                raise
            tool_name = self._extract_tool_name(tool_function, metadata)
            raise ToolRegistrationError(
                tool_name,
                f"Agent registry registration failed: {e}",
                context={"error": str(e), "error_type": type(e).__name__},
            ) from e

    def register_tool_with_dependencies(
        self,
        tool_function: ToolFunction,
        dependencies: list[type],
        metadata: ToolMetadata | None = None,
    ) -> None:
        """Register a tool with dependency injection.

        Args:
            tool_function: Tool that will receive injected dependencies
            dependencies: List of dependency types to inject
            metadata: Optional metadata about the tool

        Raises:
            ToolRegistrationError: If tool registration fails
        """
        try:
            tool_name = self._extract_tool_name(tool_function, metadata)

            logger.debug(
                "Registering tool with dependencies",
                extra={
                    "tool_name": tool_name,
                    "dependencies": [dep.__name__ for dep in dependencies],
                },
            )

            # Validate dependencies are available
            validation_result = self._validate_dependencies(dependencies, tool_name)
            if not validation_result["valid"]:
                raise ToolRegistrationError(
                    tool_name,
                    f"Tool dependencies validation failed: {validation_result['issues']}",
                    context={
                        "dependencies": [dep.__name__ for dep in dependencies],
                        "validation_issues": validation_result["issues"],
                    },
                )

            # Register with underlying registry
            self._registry.register_tool_with_dependencies(tool_function, dependencies, metadata)

            logger.info(
                "Tool with dependencies registered successfully",
                extra={
                    "tool_name": tool_name,
                    "dependency_count": len(dependencies),
                },
            )

        except Exception as e:
            if isinstance(e, ToolRegistrationError):
                raise
            tool_name = self._extract_tool_name(tool_function, metadata)
            raise ToolRegistrationError(
                tool_name,
                f"Dependency registration failed: {e}",
                context={
                    "error": str(e),
                    "dependencies": [dep.__name__ for dep in dependencies],
                },
            ) from e

    def get_available_tools(self) -> Sequence[ToolFunction]:
        """Get list of all registered tools available for agents.

        Returns:
            List of tools that can be used by Strands Agents
        """
        try:
            tools = self._registry.get_available_tools()

            logger.debug(
                "Retrieved available tools",
                extra={"tools_count": len(tools)},
            )

            return tools

        except Exception as e:
            logger.error(
                "Failed to retrieve available tools",
                extra={"error": str(e)},
            )
            return []

    def load_tools_from_directory(self, directory_path: str) -> None:
        """Load tools from a directory following Strands hot-reload pattern.

        Args:
            directory_path: Path to directory containing tool definitions

        Raises:
            ToolLoadingError: If tool loading fails
        """
        try:
            logger.info(
                "Loading tools from directory",
                extra={"directory": directory_path},
            )

            # Use underlying registry to load tools
            self._registry.load_tools_from_directory(directory_path)

            logger.info(
                "Tools loaded successfully from directory",
                extra={
                    "directory": directory_path,
                    "total_tools": len(self._registry.get_available_tools()),
                },
            )

        except Exception as e:
            if isinstance(e, ToolLoadingError):
                raise
            raise ToolLoadingError(
                f"Agent registry tool loading failed: {e}",
                context={"directory": directory_path, "error": str(e)},
            ) from e

    def unregister_tool(self, tool_name: str) -> None:
        """Unregister a tool by name.

        Args:
            tool_name: Name of the tool to unregister

        Raises:
            ToolRegistrationError: If tool is not registered
        """
        try:
            logger.debug(
                "Unregistering tool",
                extra={"tool_name": tool_name},
            )

            # Unregister from underlying registry
            self._registry.unregister_tool(tool_name)

            logger.info(
                "Tool unregistered successfully",
                extra={"tool_name": tool_name},
            )

        except Exception as e:
            if isinstance(e, ToolRegistrationError):
                raise
            raise ToolRegistrationError(
                tool_name,
                f"Tool unregistration failed: {e}",
                context={"error": str(e)},
            ) from e

    def get_tool_metadata(self, tool_name: str) -> ToolMetadata:
        """Get metadata for a registered tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Metadata dictionary for the tool

        Raises:
            ToolRegistrationError: If tool is not registered
        """
        return self._registry.get_tool_metadata(tool_name)

    def get_tool_dependencies(self, tool_name: str) -> list[type]:
        """Get dependency types for a registered tool.

        Args:
            tool_name: Name of the tool

        Returns:
            List of dependency types used by the tool

        Raises:
            ToolRegistrationError: If tool is not registered
        """
        return self._registry.get_tool_dependencies(tool_name)

    def validate_tool_dependencies(self) -> dict[str, Any]:
        """Validate all tool dependencies are available in container.

        Returns:
            Dictionary with validation results
        """
        try:
            # Get base validation from underlying registry
            validation_results = self._registry.validate_tool_dependencies()

            # Check for agent-specific compatibility requirements
            agent_compatibility_issues = self._validate_agent_compatibility()
            if agent_compatibility_issues:
                enhanced_results = validation_results.copy()
                enhanced_results["agent_compatibility_issues"] = agent_compatibility_issues
                if enhanced_results.get("valid", True):
                    enhanced_results["valid"] = len(agent_compatibility_issues) == 0
                return enhanced_results

            return validation_results

        except Exception as e:
            logger.error(
                "Tool dependency validation failed",
                extra={"error": str(e)},
            )
            return {
                "valid": False,
                "error": str(e),
                "tools": {},
                "issues": [f"Validation error: {e}"],
            }

    def get_registry_statistics(self) -> dict[str, Any]:
        """Get statistics about the tool registry.

        Returns:
            Dictionary with registry statistics
        """
        try:
            available_tools = self._registry.get_available_tools()
            validation_results = self._registry.validate_tool_dependencies()

            return {
                "total_tools": len(available_tools),
                "tools_with_dependencies": len(
                    [
                        tool_name
                        for tool_name, deps in validation_results.get("tools", {}).items()
                        if deps.get("dependencies", [])
                    ]
                ),
                "dependency_validation_status": validation_results.get("valid", False),
            }

        except Exception as e:
            logger.error(
                "Failed to generate registry statistics",
                extra={"error": str(e)},
            )
            return {
                "error": str(e),
                "total_tools": 0,
                "status": "error",
            }

    def _extract_tool_name(self, tool_function: ToolFunction, metadata: ToolMetadata | None) -> str:
        """Extract tool name from tool or metadata."""
        # Try metadata first
        if metadata and "name" in metadata:
            name_value = metadata["name"]
            if isinstance(name_value, str):
                return name_value

        # Try function name
        if hasattr(tool_function, "__name__"):
            func_name = tool_function.__name__
            if isinstance(func_name, str):
                return func_name

        # Fallback to string representation
        return str(tool_function)

    def _validate_dependencies(self, dependencies: list[type], tool_name: str) -> dict[str, Any]:
        """Validate that dependencies are available in container."""
        validation_result: dict[str, Any] = {
            "valid": True,
            "issues": [],
        }

        try:
            registered_types = self._container.get_registered_types()

            for dep_type in dependencies:
                if dep_type not in registered_types:
                    validation_result["valid"] = False
                    validation_result["issues"].append(f"Dependency {dep_type.__name__} not registered in container")

        except Exception as e:
            validation_result["valid"] = False
            validation_result["issues"].append(f"Dependency validation error: {e}")

        return validation_result

    def _validate_agent_compatibility(self) -> list[str]:
        """Validate agent-specific compatibility requirements."""
        compatibility_issues: list[str] = []

        try:
            # Check for basic Strands compatibility requirements
            available_tools = self._registry.get_available_tools()

            for tool in available_tools:
                tool_name = self._extract_tool_name(tool, None)

                # Check if tool has proper Strands decorations or attributes
                if not (hasattr(tool, "__tool__") or hasattr(tool, "_tool_metadata") or callable(tool)):
                    compatibility_issues.append(f"Tool {tool_name} may not be compatible with Strands Agent framework")

        except Exception as e:
            compatibility_issues.append(f"Compatibility validation error: {e}")

        return compatibility_issues


def create_agent_tool_registry(
    container: DependencyContainer,
) -> AgentToolRegistryManager:
    """Factory function to create AgentToolRegistryManager instance.

    Args:
        container: Dependency injection container

    Returns:
        Configured AgentToolRegistryManager implementation
    """
    return AgentToolRegistryManager(container)
