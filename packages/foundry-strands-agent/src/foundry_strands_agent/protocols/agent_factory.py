# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Agent factory protocols for Strands Agent creation and tool management.

This module defines protocols for creating Strands Agent instances and managing
tool registration following the framework's patterns and conventions.
"""

from abc import abstractmethod
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from strands.session import SessionManager

ToolFunction = Callable[..., Any]
ToolMetadata = dict[str, Any]


class AgentToolRegistry(Protocol):
    """Protocol for managing and providing tools to Strands Agents.

    Implementations will handle registration, discovery, and provision
    of tools following Strands Agent framework patterns.
    """

    @abstractmethod
    def register_tool(
        self,
        tool_function: ToolFunction,
        metadata: ToolMetadata | None = None,
    ) -> None:
        """Register a tool for use by agents.

        Args:
            tool_function: Function decorated with @tool, ToolProvider, or AgentTool following Strands patterns
            metadata: Optional metadata about the tool

        Raises:
            ToolRegistrationError: If tool registration fails
        """

    @abstractmethod
    def get_available_tools(self) -> Sequence[ToolFunction]:
        """Get list of all registered tools available for agents.

        Returns:
            List of tools that can be used by Strands Agents
        """

    @abstractmethod
    def load_tools_from_directory(self, directory_path: str) -> None:
        """Load tools from a directory following Strands hot-reload pattern.

        Args:
            directory_path: Path to directory containing tool definitions

        Raises:
            ToolLoadingError: If tool loading fails
        """

    @abstractmethod
    def unregister_tool(self, tool_name: str) -> None:
        """Unregister a tool by name.

        Args:
            tool_name: Name of the tool to unregister

        Raises:
            ToolRegistrationError: If tool is not registered
        """

    @abstractmethod
    def get_tool_metadata(self, tool_name: str) -> ToolMetadata:
        """Get metadata for a registered tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Metadata dictionary for the tool

        Raises:
            ToolRegistrationError: If tool is not registered
        """

    @abstractmethod
    def register_tool_with_dependencies(
        self,
        tool_function: ToolFunction,
        dependencies: list[type],
        metadata: ToolMetadata | None = None,
    ) -> None:
        """Register a tool with dependency injection.

        Args:
            tool_function: Function, ToolProvider, or AgentTool that will receive injected dependencies
            dependencies: List of dependency types to inject
            metadata: Optional metadata about the tool

        Raises:
            ToolRegistrationError: If tool registration fails
        """

    @abstractmethod
    def validate_tool_dependencies(self) -> dict[str, Any]:
        """Validate all tool dependencies are available in container.

        Returns:
            Dictionary with validation results
        """

    @abstractmethod
    def get_tool_dependencies(self, tool_name: str) -> list[type]:
        """Get dependency types for a registered tool.

        Args:
            tool_name: Name of the tool

        Returns:
            List of dependency types used by the tool

        Raises:
            ToolRegistrationError: If tool is not registered
        """

    @abstractmethod
    def get_registry_statistics(self) -> dict[str, Any]:
        """Get statistics about the tool registry.

        Returns:
            Dictionary with registry statistics including tool counts,
            dependency validation status, and lifecycle information
        """


class AgentFactory(Protocol):
    """Protocol for creating and configuring Strands Agent instances.

    Implementations will handle agent creation with proper configuration,
    model initialization, and tool registration following Strands patterns.
    """

    @abstractmethod
    async def create_agent(
        self,
        tools: Sequence[ToolFunction] | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> Any:
        """Create a configured Strands Agent instance.

        Args:
            tools: Optional list of tools to provide to the agent
            config_overrides: Optional configuration overrides

        Returns:
            Configured Strands Agent ready for query processing

        Raises:
            AgentCreationError: If agent creation or configuration fails
        """

    @abstractmethod
    async def create_agent_with_mcp_clients(
        self,
        mcp_servers: list[dict[str, Any]],
        config_overrides: dict[str, Any] | None = None,
    ) -> Any:
        """Create agent with Model Context Protocol (MCP) tools.

        Args:
            mcp_servers: List of MCP server connection configurations with 'url' field
            config_overrides: Optional configuration overrides

        Returns:
            Configured Strands Agent with MCP tools integrated

        Raises:
            AgentCreationError: If agent creation fails
            ExternalServiceError: If MCP server connection fails
        """

    @abstractmethod
    async def create_agent_with_tool_registry(
        self,
        tool_registry: AgentToolRegistry,
        config_overrides: dict[str, Any] | None = None,
    ) -> Any:
        """Create agent using tools from a tool registry.

        Args:
            tool_registry: Registry containing available tools
            config_overrides: Optional configuration overrides

        Returns:
            Configured Strands Agent with registry tools

        Raises:
            AgentCreationError: If agent creation fails
        """

    @abstractmethod
    def validate_agent_configuration(
        self,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate agent configuration before creation.

        Args:
            config: Configuration dictionary to validate

        Returns:
            Validation results with any issues found

        Raises:
            AgentCreationError: If configuration is invalid
        """

    @abstractmethod
    def destroy_session(self, session_id: str, config_overrides: dict[str, Any] | None = None) -> None:
        """Destroy all persisted state for the given session.

        Args:
            session_id: The session identifier to destroy.
            config_overrides: Optional configuration overrides for session manager creation.
        """

    @abstractmethod
    def create_session_repository(self, config_overrides: dict[str, Any] | None = None) -> SessionManager | None:
        """Create session repository based on configuration.

        Args:
            config_overrides: Optional configuration overrides

        Returns:
            Configured session manager instance or None if not configured

        Raises:
            AgentCreationError: If session manager creation fails.
        """
