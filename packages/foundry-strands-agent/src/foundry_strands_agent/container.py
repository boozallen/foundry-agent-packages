# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Default dependency-container assembly for the Strands adapter.

This module provides :func:`create_default_container`, which returns a
:class:`~foundry_agent_core.DependencyContainer` with every default this
package ships already registered against its protocol key. It exists so the
documented quickstart works verbatim: :func:`create_agent_service` resolves
five protocols, and before this factory existed an adopter had to know and
register all five by hand before their first query could run.

Registration happens only when :func:`create_default_container` is called.
Importing this module (or the package) registers nothing and mutates no
container.

For fine-grained control, construct the components directly and pass them to
:class:`~foundry_strands_agent.service.AgentService` — see
``docs/guides/extending.md``.
"""

from collections.abc import Callable
from typing import TypeVar

from foundry_agent_core import (
    DependencyContainer,
    QueryProcessor,
    ResponseProcessor,
    create_dependency_container,
)
from foundry_strands_agent.chat_historian import create_chat_history_manager
from foundry_strands_agent.config.models import StrandsAgentConfig
from foundry_strands_agent.factory import StrandsAgentFactory
from foundry_strands_agent.orchestrator import create_query_processor
from foundry_strands_agent.protocols import AgentFactory, AgentToolRegistry, ChatHistoryManager
from foundry_strands_agent.registry import create_agent_tool_registry
from foundry_strands_agent.response_processor import create_response_processor

T = TypeVar("T")


def _factory_for(override: T | None, build: Callable[[], T]) -> Callable[[], T]:
    """Return a zero-arg factory yielding ``override`` when supplied, else ``build``.

    Keeping this lazy matters: the container resolves factories on first use,
    so a default that depends on sibling registrations does not care what order
    the registrations happened in.

    Args:
        override: Caller-supplied instance, or None to use the default.
        build: Factory producing this package's default implementation.

    Returns:
        Factory function suitable for ``DependencyContainer.register_factory``.
    """
    if override is not None:
        return lambda: override
    return build


def create_default_container(
    config: StrandsAgentConfig,
    *,
    agent_factory: AgentFactory | None = None,
    tool_registry: AgentToolRegistry | None = None,
    query_processor: QueryProcessor | None = None,
    chat_history_manager: ChatHistoryManager | None = None,
    response_processor: ResponseProcessor | None = None,
) -> DependencyContainer:
    """Create a container with this package's default implementations registered.

    Registers ``StrandsAgentConfig`` plus the five protocols that
    :func:`~foundry_strands_agent.service.create_agent_service` resolves:

    ================================ =========================================
    Protocol                         Default implementation
    ================================ =========================================
    ``AgentFactory``                 ``StrandsAgentFactory``
    ``AgentToolRegistry``            ``AgentToolRegistryManager``
    ``QueryProcessor``               ``QueryOrchestrator``
    ``ChatHistoryManager``           ``ChatHistorian``
    ``ResponseProcessor``            ``DefaultResponseProcessor``
    ================================ =========================================

    Every keyword argument overrides the corresponding default. Overrides take
    **concrete instances**, not factory functions — an adopter who needs lazy
    construction of a replacement should register it on a bare
    :func:`~foundry_agent_core.create_dependency_container` themselves, or wire
    ``AgentService`` directly (see ``docs/guides/extending.md``).

    ``AgentConfig`` is an alias of ``StrandsAgentConfig``, so the single config
    registration serves components resolving either name.

    Args:
        config: Agent configuration registered on the container and passed to
            the default chat history manager.
        agent_factory: Replaces the default ``StrandsAgentFactory``.
        tool_registry: Replaces the default ``AgentToolRegistryManager``.
        query_processor: Replaces the default ``QueryOrchestrator``.
        chat_history_manager: Replaces the default ``ChatHistorian``.
        response_processor: Replaces the default ``DefaultResponseProcessor``.

    Returns:
        Container ready to pass to
        :func:`~foundry_strands_agent.service.create_agent_service`.

    Example:
        >>> config = StrandsAgentConfig()
        >>> container = create_default_container(config)
        >>> service = create_agent_service(container)  # doctest: +SKIP
    """
    container = create_dependency_container()

    container.register_factory(StrandsAgentConfig, lambda: config)

    container.register_factory(
        AgentFactory,
        _factory_for(agent_factory, lambda: StrandsAgentFactory(container)),
    )
    container.register_factory(
        AgentToolRegistry,
        _factory_for(tool_registry, lambda: create_agent_tool_registry(container, config.tools_dir)),
    )
    container.register_factory(
        ResponseProcessor,
        _factory_for(response_processor, create_response_processor),
    )
    container.register_factory(
        QueryProcessor,
        _factory_for(
            query_processor,
            lambda: create_query_processor(
                container,
                container.resolve(AgentFactory),
                container.resolve(AgentToolRegistry),
                container.resolve(ResponseProcessor),
            ),
        ),
    )
    container.register_factory(
        ChatHistoryManager,
        _factory_for(
            chat_history_manager,
            lambda: create_chat_history_manager(container.resolve(AgentFactory), config),
        ),
    )

    return container
