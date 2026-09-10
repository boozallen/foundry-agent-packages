# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for FunctionalDependencyContainer."""

import pytest

from foundry_agent_core.container import FunctionalDependencyContainer, create_dependency_container
from foundry_agent_core.exceptions import ConfigurationError


class TestFunctionalDependencyContainer:
    def test_register_and_resolve(self) -> None:
        container = FunctionalDependencyContainer()
        container.register_factory(str, lambda: "hello", singleton=True)
        assert container.resolve(str) == "hello"

    def test_singleton_returns_same_instance(self) -> None:
        container = FunctionalDependencyContainer()
        container.register_factory(list, list, singleton=True)
        first = container.resolve(list)
        second = container.resolve(list)
        assert first is second

    def test_non_singleton_returns_new_instance(self) -> None:
        container = FunctionalDependencyContainer()
        container.register_factory(list, list, singleton=False)
        first = container.resolve(list)
        second = container.resolve(list)
        assert first is not second

    def test_resolve_unregistered_raises(self) -> None:
        container = FunctionalDependencyContainer()
        with pytest.raises(ConfigurationError):
            container.resolve(str)

    def test_get_registered_types(self) -> None:
        container = FunctionalDependencyContainer()
        container.register_factory(str, lambda: "a", singleton=True)
        container.register_factory(int, lambda: 1, singleton=True)
        types = container.get_registered_types()
        assert str in types
        assert int in types

    def test_validate_registrations(self) -> None:
        container = FunctionalDependencyContainer()
        container.register_factory(str, lambda: "a", singleton=True)
        result = container.validate_registrations()
        assert result["valid"] is True

    def test_register_factory_with_dependencies(self) -> None:
        container = FunctionalDependencyContainer()
        container.register_factory(str, lambda: "base", singleton=True)
        container.register_factory_with_dependencies(
            int,
            lambda s: len(s),
            dependencies=[str],
            singleton=True,
        )
        assert container.resolve(int) == 4

    def test_create_dependency_container(self) -> None:
        container = create_dependency_container()
        assert isinstance(container, FunctionalDependencyContainer)

    def test_scoped_container(self) -> None:
        container = FunctionalDependencyContainer()
        container.register_factory(str, lambda: "parent", singleton=True)
        with container.create_scope() as scoped:
            assert scoped.resolve(str) == "parent"
