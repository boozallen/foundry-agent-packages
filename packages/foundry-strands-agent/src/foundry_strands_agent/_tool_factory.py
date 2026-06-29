# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tool factory functions with dependency injection following Strands patterns.

This module extends tool creation patterns with dependency injection support,
enabling tools to be configured with injected dependencies while maintaining
compatibility with Strands Agent framework conventions.
"""

import importlib
import inspect
import logging
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from foundry_agent_core import DependencyContainer, ToolLoadingError, ToolRegistrationError
from foundry_strands_agent.protocols import (
    AgentToolRegistry,
    ToolFunction,
    ToolMetadata,
)

logger = logging.getLogger(__name__)


class DependencyInjectedToolRegistry:
    """Implementation of AgentToolRegistry with dependency injection support."""

    def __init__(self, container: DependencyContainer) -> None:
        self._container = container
        self._tools: dict[str, ToolFunction] = {}
        self._metadata: dict[str, ToolMetadata] = {}
        self._tool_dependencies: dict[str, list[type[Any]]] = {}

    def register_tool(
        self,
        tool: ToolFunction | Any,
        metadata: ToolMetadata | None = None,
    ) -> None:
        tool_name = "unknown"
        try:
            if hasattr(tool, "TOOL_SPEC"):
                tool_spec = tool.TOOL_SPEC  # pyright: ignore[reportFunctionMemberAccess]
                if not isinstance(tool_spec, dict) or "name" not in tool_spec:
                    raise ToolRegistrationError(
                        "unknown",
                        "Invalid TOOL_SPEC format",
                        context={"tool_spec": str(tool_spec)},
                    )

                original_name = tool_spec["name"]

                source = metadata.get("source") if metadata else None
                source_type = metadata.get("source_type") if metadata else None
                tool_name = self._generate_prefixed_tool_name(original_name, source, source_type)

                if tool_name != original_name:
                    if not isinstance(tool, types.ModuleType):
                        raise ToolRegistrationError(tool_name, "TOOL_SPEC tool must be a Python module")

                    tool.TOOL_SPEC = {**tool_spec, "name": tool_name}  # pyright: ignore[reportAttributeAccessIssue]

                    if hasattr(tool, original_name):
                        setattr(tool, tool_name, getattr(tool, original_name))

                self._tools[tool_name] = tool  # pyright: ignore[reportArgumentType]
                self._metadata[tool_name] = {
                    **(metadata or {}),
                    "original_name": original_name,
                    "prefixed_name": tool_name,
                }
                self._tool_dependencies[tool_name] = []

            elif callable(tool) and (
                hasattr(tool, "__tool__") or hasattr(tool, "tool_spec") or hasattr(tool, "_tool_metadata")
            ):
                original_name = tool.__name__

                source = metadata.get("source") if metadata else None
                source_type = metadata.get("source_type") if metadata else None
                tool_name = self._generate_prefixed_tool_name(original_name, source, source_type)

                self._tools[tool_name] = tool
                self._metadata[tool_name] = {
                    **(metadata or {}),
                    "original_name": original_name,
                    "prefixed_name": tool_name,
                }
                self._tool_dependencies[tool_name] = []

        except Exception as e:
            if isinstance(e, ToolRegistrationError):
                raise
            raise ToolRegistrationError(
                tool_name or "unknown",
                f"Registration failed: {e}",
                context={"error": str(e)},
            ) from e

    def register_tool_with_dependencies(
        self,
        tool_function: ToolFunction,
        dependencies: list[type],
        metadata: ToolMetadata | None = None,
    ) -> None:
        tool_name = "unknown"
        try:
            tool_name = self._extract_tool_name(tool_function, metadata)

            if tool_name in self._tools:
                raise ToolRegistrationError(
                    tool_name,
                    "Tool is already registered",
                    context={"existing_tool": tool_name},
                )

            def dependency_injected_tool(*args: Any, **kwargs: Any) -> Any:
                resolved_deps: list[Any] = [self._container.resolve(dep_type) for dep_type in dependencies]
                return tool_function(*resolved_deps, *args, **kwargs)  # pyright:ignore[reportCallIssue]

            dependency_injected_tool.__name__ = getattr(tool_function, "__name__", tool_name)
            dependency_injected_tool.__doc__ = tool_function.__doc__

            self._tools[tool_name] = dependency_injected_tool
            self._metadata[tool_name] = metadata or {}
            self._tool_dependencies[tool_name] = dependencies.copy()

        except Exception as e:
            if isinstance(e, ToolRegistrationError):
                raise
            raise ToolRegistrationError(
                tool_name,
                f"Dependency injection registration failed: {e}",
                context={"error": str(e), "dependencies": dependencies},
            ) from e

    def get_available_tools(self) -> list[ToolFunction]:
        return list(self._tools.values())

    def load_tools_from_directory(self, directory_path: str) -> None:
        try:
            directory = Path(directory_path)
            if not directory.exists():
                raise ToolLoadingError(
                    f"Tool directory does not exist: {directory_path}",
                    context={"directory": directory_path},
                )

            if not directory.is_dir():
                raise ToolLoadingError(
                    f"Path is not a directory: {directory_path}",
                    context={"directory": directory_path},
                )

            python_files = list(directory.glob("**/*.py"))
            loaded_count = 0

            for py_file in python_files:
                if py_file.name.startswith("_"):
                    continue

                try:
                    self._load_tools_from_file(py_file)
                    loaded_count += 1
                except Exception as e:
                    logger.warning("Warning: Failed to load tools from %s: %s", py_file, e)

            if loaded_count == 0:
                raise ToolLoadingError(
                    f"No tools loaded from directory: {directory_path}",
                    context={
                        "directory": directory_path,
                        "files_found": len(python_files),
                    },
                )

        except Exception as e:
            if isinstance(e, ToolLoadingError):
                raise
            raise ToolLoadingError(
                f"Failed to load tools from directory: {e}",
                context={"directory": directory_path, "error": str(e)},
            ) from e

    def unregister_tool(self, tool_name: str) -> None:
        if tool_name not in self._tools:
            raise ToolRegistrationError(
                tool_name,
                "Tool is not registered",
                context={"available_tools": list(self._tools.keys())},
            )

        del self._tools[tool_name]
        del self._metadata[tool_name]
        del self._tool_dependencies[tool_name]

    def get_tool_metadata(self, tool_name: str) -> ToolMetadata:
        if tool_name not in self._metadata:
            raise ToolRegistrationError(
                tool_name,
                "Tool is not registered",
                context={"available_tools": list(self._tools.keys())},
            )

        return self._metadata[tool_name].copy()

    def get_tool_dependencies(self, tool_name: str) -> list[type]:
        if tool_name not in self._tool_dependencies:
            raise ToolRegistrationError(
                tool_name,
                "Tool is not registered",
                context={"available_tools": list(self._tools.keys())},
            )

        return self._tool_dependencies[tool_name].copy()

    def validate_tool_dependencies(self) -> dict[str, Any]:
        validation_results: dict[str, Any] = {
            "valid": True,
            "tools": {},
            "issues": [],
            "warnings": [],
        }

        registered_types = self._container.get_registered_types()

        for tool_name, dependencies in self._tool_dependencies.items():
            tool_issues = []

            for dep_type in dependencies:
                if dep_type not in registered_types:
                    tool_issues.append(f"Dependency {dep_type.__name__} not registered in container")

            validation_results["tools"][tool_name] = {
                "valid": len(tool_issues) == 0,
                "dependencies": [dep.__name__ for dep in dependencies],
                "issues": tool_issues,
            }

            if tool_issues:
                validation_results["valid"] = False
                validation_results["issues"].extend([f"{tool_name}: {issue}" for issue in tool_issues])

        return validation_results

    def _generate_prefixed_tool_name(self, tool_name: str, source: str | None, source_type: str | None) -> str:
        if not source or not source_type:
            return tool_name

        if source_type == "module":
            return tool_name

        elif source_type == "file":
            path = Path(source)
            path_no_ext = path.with_suffix("")
            parts = path_no_ext.parts
            parts = [p for p in parts if p and p != "."]
            if len(parts) >= 2:
                return "__".join(parts[-2:]) + "__" + tool_name
            elif len(parts) == 1:
                return parts[0] + "__" + tool_name
            else:
                return path_no_ext.name + "__" + tool_name

        return tool_name

    def _extract_tool_name(self, tool_function: ToolFunction, metadata: ToolMetadata | None) -> str:
        if metadata and "name" in metadata:
            name_value = metadata["name"]
            if isinstance(name_value, str):
                return name_value

        if hasattr(tool_function, "__name__"):
            func_name = tool_function.__name__
            if isinstance(func_name, str):
                return func_name

        return str(tool_function)

    def _validate_tool_function(self, tool_function: ToolFunction, tool_name: str) -> None:
        if not callable(tool_function):
            raise ToolRegistrationError(
                tool_name,
                "Tool must be callable",
                context={"tool_type": type(tool_function).__name__},
            )

        try:
            sig = inspect.signature(tool_function)
            if len(sig.parameters) == 0:
                pass
        except (ValueError, TypeError):
            pass

    def _load_tools_from_file(self, file_path: Path) -> None:
        try:
            module_name = self._file_path_to_module_name(file_path)
            module = importlib.import_module(module_name)

            for name in dir(module):
                obj = getattr(module, name)

                if callable(obj) and self._is_tool_function(obj):
                    try:
                        metadata = self._extract_tool_metadata(obj)
                        self.register_tool(obj, metadata)
                    except ToolRegistrationError:
                        pass

        except ImportError as e:
            raise ToolLoadingError(
                f"Failed to import module from {file_path}: {e}",
                context={"file": str(file_path), "error": str(e)},
            ) from e

    def _file_path_to_module_name(self, file_path: Path) -> str:
        parts = file_path.with_suffix("").parts
        return ".".join(parts)

    def _is_tool_function(self, obj: Any) -> bool:
        return callable(obj) and (
            hasattr(obj, "__tool__")
            or hasattr(obj, "_tool_metadata")
            or getattr(obj, "__name__", "").startswith("tool_")
            or "tool" in getattr(obj, "__doc__", "").lower()
        )

    def _extract_tool_metadata(self, tool_function: ToolFunction) -> ToolMetadata:
        metadata: ToolMetadata = {}

        if hasattr(tool_function, "_tool_metadata"):
            metadata.update(tool_function._tool_metadata)  # pyright:ignore[reportCallIssue,reportAttributeAccessIssue,reportFunctionMemberAccess]
        if hasattr(tool_function, "__doc__") and tool_function.__doc__:
            metadata["description"] = tool_function.__doc__.strip()

        if hasattr(tool_function, "__name__"):
            metadata["name"] = tool_function.__name__

        return metadata


def create_tool_registry(container: DependencyContainer) -> AgentToolRegistry:
    """Factory function to create a new tool registry with dependency injection."""
    return cast(AgentToolRegistry, DependencyInjectedToolRegistry(container))


def create_tool_factory(
    container: DependencyContainer,
    registry: AgentToolRegistry | None = None,
) -> Callable[[ToolFunction, list[type] | None, ToolMetadata | None], ToolFunction]:
    """Create a higher-order function for creating dependency-injected tools."""

    def tool_factory(
        tool_function: ToolFunction,
        dependencies: list[type] | None = None,
        metadata: ToolMetadata | None = None,
    ) -> ToolFunction:
        if dependencies is None or len(dependencies) == 0:
            configured_tool = tool_function
        else:

            def dependency_injected_tool(*args: Any, **kwargs: Any) -> Any:
                resolved_deps: list[Any] = [container.resolve(dep_type) for dep_type in dependencies]
                return tool_function(*resolved_deps, *args, **kwargs)  # pyright:ignore[reportCallIssue]

            dependency_injected_tool.__name__ = getattr(tool_function, "__name__", "tool")
            dependency_injected_tool.__doc__ = tool_function.__doc__

            configured_tool = dependency_injected_tool

        if registry is not None:
            if isinstance(registry, DependencyInjectedToolRegistry) and dependencies:
                registry.register_tool_with_dependencies(tool_function, dependencies, metadata)
            else:
                registry.register_tool(configured_tool, metadata)

        return configured_tool

    return tool_factory
