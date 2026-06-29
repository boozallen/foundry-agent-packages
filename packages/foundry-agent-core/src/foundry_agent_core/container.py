# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Dependency injection container using higher-order functions.

This module implements the DependencyContainer protocol using functional composition
and higher-order functions, avoiding global state and supporting flexible dependency
lifecycle management.
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, Self, TypeVar, cast

from foundry_agent_core.exceptions import ConfigurationError
from foundry_agent_core.protocols import DependencyContainer

# Type variables for dependency injection
T = TypeVar("T")
Factory = Callable[[], T]
FactoryWithDeps = Callable[..., T]


class FunctionalDependencyContainer(DependencyContainer):
    """Implementation of DependencyContainer using higher-order functions.

    This container manages dependencies through factory functions and composition,
    avoiding global state and supporting flexible lifecycle management.
    """

    def __init__(self) -> None:
        """Initialize empty dependency container."""
        self._factories: dict[type, Factory[Any]] = {}
        self._singletons: dict[type, Any] = {}
        self._singleton_flags: dict[type, bool] = {}
        self._dependency_graph: dict[type, list[type]] = {}

    def register_factory(
        self,
        interface_type: type,
        factory: Factory[T],
        *,
        singleton: bool = True,
    ) -> None:
        """Register a factory function for creating instances of an interface.

        Args:
            interface_type: The protocol/interface type to register
            factory: Factory function that creates instances
            singleton: Whether to cache instances (default True)

        Raises:
            ConfigurationError: If registration fails or conflicts
        """
        if interface_type in self._factories:
            raise ConfigurationError(
                f"Interface {interface_type.__name__} is already registered",
                context={"interface": interface_type.__name__},
            )

        self._factories[interface_type] = factory
        self._singleton_flags[interface_type] = singleton
        self._dependency_graph[interface_type] = []

    def register_factory_with_dependencies(
        self,
        interface_type: type,
        factory: FactoryWithDeps[T],
        dependencies: list[type],
        *,
        singleton: bool = True,
    ) -> None:
        """Register a factory with explicit dependencies.

        Args:
            interface_type: The protocol/interface type to register
            factory: Factory function that takes dependencies as arguments
            dependencies: List of dependency types to inject
            singleton: Whether to cache instances (default True)

        Raises:
            ConfigurationError: If registration fails or circular dependencies detected
        """
        if interface_type in self._factories:
            raise ConfigurationError(
                f"Interface {interface_type.__name__} is already registered",
                context={"interface": interface_type.__name__},
            )

        # Check for circular dependencies
        self._check_circular_dependencies(interface_type, dependencies)

        # Create a wrapper factory that resolves dependencies
        def dependency_resolving_factory() -> T:
            resolved_deps: list[T] = [self.resolve(dep_type) for dep_type in dependencies]
            return factory(*resolved_deps)

        self._factories[interface_type] = dependency_resolving_factory
        self._singleton_flags[interface_type] = singleton
        self._dependency_graph[interface_type] = dependencies.copy()

    def resolve(self, interface_type: type[T]) -> T:
        """Resolve an instance of the requested interface type.

        Args:
            interface_type: The protocol/interface type to resolve

        Returns:
            Instance implementing the requested interface

        Raises:
            ConfigurationError: If type not registered or resolution fails
        """
        if interface_type not in self._factories:
            raise ConfigurationError(
                f"No factory registered for interface {interface_type.__name__}",
                context={
                    "interface": interface_type.__name__,
                    "available": list(self._factories.keys()),
                },
            )

        # Return cached singleton if available
        if self._singleton_flags[interface_type] and interface_type in self._singletons:
            return cast(T, self._singletons[interface_type])

        try:
            # Create new instance using factory
            factory = self._factories[interface_type]
            instance = factory()

            # Cache if singleton
            if self._singleton_flags[interface_type]:
                self._singletons[interface_type] = instance

            return cast(T, instance)

        except Exception as e:
            raise ConfigurationError(
                f"Failed to resolve {interface_type.__name__}: {e}",
                context={
                    "interface": interface_type.__name__,
                    "error": str(e),
                    "dependencies": self._dependency_graph.get(interface_type, []),
                },
            ) from e

    @contextmanager
    def create_scope(self) -> Generator[Self]:
        """Create a new dependency scope for request-scoped instances.

        Yields:
            FunctionalDependencyContainer: Scoped container for dependency resolution

        Raises:
            ConfigurationError: If scope creation fails
        """
        # Create a new container that inherits factories but has separate singleton cache
        scoped_container = self.__class__()
        scoped_container._factories = self._factories.copy()
        scoped_container._singleton_flags = self._singleton_flags.copy()
        scoped_container._dependency_graph = self._dependency_graph.copy()
        # Note: scoped_container._singletons starts empty for scope isolation

        try:
            yield scoped_container
        finally:
            scoped_container._singletons.clear()

    def validate_registrations(self) -> dict[str, Any]:
        """Validate all registered dependencies for completeness and cycles.

        Returns:
            Dictionary with validation results and any issues found

        Raises:
            ConfigurationError: If critical dependency issues are found
        """
        issues = []
        warnings = []

        # Check for missing dependencies
        for interface_type, deps in self._dependency_graph.items():
            for dep in deps:
                if dep not in self._factories:
                    issues.append(f"{interface_type.__name__} depends on unregistered {dep.__name__}")

        # Check for circular dependencies (more comprehensive)
        try:
            self._validate_all_cycles()
        except ConfigurationError as e:
            issues.append(f"Circular dependency detected: {e.message}")

        # Check for unused registrations
        used_types = set()
        for deps in self._dependency_graph.values():
            used_types.update(deps)

        for registered_type in self._factories.keys():
            if registered_type not in used_types and len(self._dependency_graph[registered_type]) > 0:
                warnings.append(f"{registered_type.__name__} is registered but not used as dependency")

        result = {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "registered_count": len(self._factories),
            "dependency_count": sum(len(deps) for deps in self._dependency_graph.values()),
        }

        if issues:
            raise ConfigurationError(
                f"Dependency validation failed: {len(issues)} issues found",
                context=result,
            )

        return result

    def get_registered_types(self) -> list[type]:
        """Get list of all registered interface types.

        Returns:
            List of registered protocol/interface types
        """
        return list(self._factories.keys())

    def clear_singletons(self) -> None:
        """Clear all cached singleton instances, useful for testing.

        Raises:
            ConfigurationError: If clearing fails
        """
        try:
            self._singletons.clear()
        except Exception as e:
            raise ConfigurationError(f"Failed to clear singletons: {e}", context={"error": str(e)}) from e

    def _check_circular_dependencies(self, interface_type: type, dependencies: list[type]) -> None:
        """Check for circular dependencies in the dependency graph."""
        # Simple immediate circular dependency check
        if interface_type in dependencies:
            raise ConfigurationError(
                f"Circular dependency: {interface_type.__name__} depends on itself",
                context={
                    "interface": interface_type.__name__,
                    "dependencies": dependencies,
                },
            )

        # Check for existing cycles that would be created
        for dep in dependencies:
            if dep in self._dependency_graph:
                self._check_cycle_path(interface_type, dep, set())

    def _check_cycle_path(self, start_type: type, current_type: type, visited: set[type]) -> None:
        """Recursively check for cycles in dependency path."""
        if current_type == start_type:
            raise ConfigurationError(
                f"Circular dependency detected: {start_type.__name__} -> ... -> {current_type.__name__}",
                context={
                    "start": start_type.__name__,
                    "current": current_type.__name__,
                },
            )

        if current_type in visited:
            return  # Already explored this path

        visited.add(current_type)

        # Check dependencies of current type
        for dep in self._dependency_graph.get(current_type, []):
            self._check_cycle_path(start_type, dep, visited.copy())

    def _validate_all_cycles(self) -> None:
        """Comprehensive cycle detection across all registrations."""
        for interface_type in self._factories.keys():
            visited: set[type] = set()
            self._detect_cycles_from(interface_type, visited, set())

    def _detect_cycles_from(self, current_type: type, visited: set[type], path: set[type]) -> None:
        """Detect cycles starting from a specific type."""
        if current_type in path:
            cycle_path = " -> ".join(t.__name__ for t in path) + f" -> {current_type.__name__}"
            raise ConfigurationError(
                f"Circular dependency cycle detected: {cycle_path}",
                context={"cycle_path": cycle_path},
            )

        if current_type in visited:
            return

        visited.add(current_type)
        path.add(current_type)

        for dep in self._dependency_graph.get(current_type, []):
            self._detect_cycles_from(dep, visited, path.copy())

        path.discard(current_type)


def create_dependency_container() -> DependencyContainer:
    """Factory function to create a new dependency container instance.

    Returns:
        New DependencyContainer instance ready for registration and resolution
    """
    return FunctionalDependencyContainer()
