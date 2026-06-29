# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Dependency injection container protocol.

This module defines the DependencyContainer protocol for managing infrastructure
lifecycle and dependency resolution using higher-order functions.
"""

from abc import abstractmethod
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol, Self, TypeVar

# Type variables for dependency injection
T = TypeVar("T")
Factory = Callable[[], T]
FactoryWithDeps = Callable[..., T]


class DependencyContainer(Protocol):
    """Protocol for managing infrastructure lifecycle through dependency injection.

    This container manages dependency registration, resolution, and lifecycle
    using higher-order functions rather than global state.
    """

    @abstractmethod
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

    @abstractmethod
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

    @abstractmethod
    def resolve(self, interface_type: type[T]) -> T:
        """Resolve an instance of the requested interface type.

        Args:
            interface_type: The protocol/interface type to resolve

        Returns:
            Instance implementing the requested interface

        Raises:
            ConfigurationError: If type not registered or resolution fails
        """

    @abstractmethod
    def create_scope(self) -> AbstractContextManager[Self]:
        """Create a new dependency scope for request-scoped instances.

        Returns:
            Context manager for scoped dependency resolution

        Raises:
            ConfigurationError: If scope creation fails
        """

    @abstractmethod
    def validate_registrations(self) -> dict[str, Any]:
        """Validate all registered dependencies for completeness and cycles.

        Returns:
            Dictionary with validation results and any issues found

        Raises:
            ConfigurationError: If critical dependency issues are found
        """

    @abstractmethod
    def get_registered_types(self) -> list[type]:
        """Get list of all registered interface types.

        Returns:
            List of registered protocol/interface types
        """

    @abstractmethod
    def clear_singletons(self) -> None:
        """Clear all cached singleton instances, useful for testing.

        Raises:
            ConfigurationError: If clearing fails
        """
