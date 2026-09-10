# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for create_default_container — the documented quickstart wiring path.

These tests gate a regression where the published quickstart used to raise
``ConfigurationError: No factory registered for interface AgentFactory``
because ``create_agent_service`` resolves five protocols that nothing
registered. The test named ``test_documented_quickstart_sequence`` executes the
exact sequence the README and ``docs/guides/quickstart.md`` publish, so a
regression that re-breaks the documented journey fails CI.

No model provider is exercised: ``AgentService.initialize`` only loads
configured tools, and no test here calls ``process_query`` against a real
model, so nothing reaches Bedrock, Ollama, LlamaCpp, or NIMS. The
``_isolate_tool_env`` fixture strips the tool-discovery environment variables so
a developer's local ``STRANDS_TOOLS_*`` settings cannot leak into the wiring.
"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest

import foundry_strands_agent
from foundry_agent_core import (
    AgentRequest,
    AgentResponse,
    QueryProcessor,
    ResponseProcessor,
    create_dependency_container,
)
from foundry_strands_agent import (
    AgentToolRegistryManager,
    ChatHistorian,
    DefaultResponseProcessor,
    QueryOrchestrator,
    StrandsAgentConfig,
    StrandsAgentFactory,
    create_agent_service,
    create_default_container,
)
from foundry_strands_agent.protocols import AgentFactory, AgentToolRegistry, ChatHistoryManager

# Every protocol create_agent_service resolves, plus the config the defaults need.
_REQUIRED_KEYS = {
    StrandsAgentConfig,
    AgentFactory,
    AgentToolRegistry,
    QueryProcessor,
    ChatHistoryManager,
    ResponseProcessor,
}


@pytest.fixture(autouse=True)
def _isolate_tool_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip tool-discovery env vars so wiring tests never load a developer's tools."""
    for name in ("STRANDS_TOOLS_MODULES", "STRANDS_TOOLS_FILES", "STRANDS_TOOLS_DIR"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def config() -> StrandsAgentConfig:
    """Return the default config the documented quickstart constructs."""
    return StrandsAgentConfig()


class StubQueryProcessor:
    """Minimal QueryProcessor stand-in that records the requests it receives."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def process_query(self, request: AgentRequest) -> AgentResponse:
        """Record the query and return a marker response."""
        self.seen.append(request.query)
        return AgentResponse(
            content="stub-response",
            session_id=request.session_id,
            processing_time_ms=0.0,
        )

    async def process_query_stream(self, request: AgentRequest) -> AsyncGenerator[dict[str, Any]]:
        """Yield a single done event so the streaming protocol is satisfied."""
        self.seen.append(request.query)
        yield {"type": "done", "session_id": request.session_id}


def test_import_from_package_root() -> None:
    """The factory is importable from the package root and listed in __all__."""
    assert callable(create_default_container)
    assert "create_default_container" in foundry_strands_agent.__all__


def test_factory_registers_all_five_protocols_and_config(config: StrandsAgentConfig) -> None:
    """The returned container carries every key create_agent_service resolves."""
    container = create_default_container(config)

    assert set(container.get_registered_types()) >= _REQUIRED_KEYS


def test_caller_supplied_config_is_the_resolved_instance(config: StrandsAgentConfig) -> None:
    """Resolving StrandsAgentConfig yields the exact instance the caller passed in."""
    container = create_default_container(config)

    assert container.resolve(StrandsAgentConfig) is config


def test_create_agent_service_succeeds_from_default_container(config: StrandsAgentConfig) -> None:
    """create_agent_service resolves cleanly — the crash is gone."""
    service = create_agent_service(create_default_container(config))

    assert service is not None


@pytest.mark.asyncio
async def test_documented_quickstart_sequence(config: StrandsAgentConfig) -> None:
    """Run the published quickstart verbatim: factory -> service -> lifecycle enter."""
    container = create_default_container(config)
    service = create_agent_service(container)

    async with service.service_lifecycle() as running:
        assert running is service


@pytest.mark.asyncio
async def test_override_kwargs_win_over_defaults(config: StrandsAgentConfig) -> None:
    """A supplied override resolves instead of the default, and the service uses it."""
    stub = StubQueryProcessor()
    container = create_default_container(config, query_processor=stub)

    assert container.resolve(QueryProcessor) is stub

    service = create_agent_service(container)
    async with service.service_lifecycle():
        response = await service.process_query(AgentRequest(session_id="override-test", query="ping"))

    assert response.content == "stub-response"
    assert stub.seen == ["ping"]


def test_non_overridden_protocols_still_use_defaults(config: StrandsAgentConfig) -> None:
    """Overriding one protocol leaves the other four on this package's defaults."""
    container = create_default_container(config, query_processor=StubQueryProcessor())

    # The container is handed to create_agent_service, as the documented flow does, so
    # the assertions below cover the objects the service was actually injected with:
    # registrations are singletons, so each resolve returns the instance the service got.
    assert create_agent_service(container) is not None

    assert isinstance(container.resolve(AgentFactory), StrandsAgentFactory)
    assert isinstance(container.resolve(AgentToolRegistry), AgentToolRegistryManager)
    assert isinstance(container.resolve(ChatHistoryManager), ChatHistorian)
    assert isinstance(container.resolve(ResponseProcessor), DefaultResponseProcessor)


def test_default_query_processor_is_the_orchestrator(config: StrandsAgentConfig) -> None:
    """With no override, QueryProcessor resolves to QueryOrchestrator."""
    container = create_default_container(config)

    assert isinstance(container.resolve(QueryProcessor), QueryOrchestrator)


def test_import_does_not_mutate_a_fresh_container() -> None:
    """Importing the package registers nothing — registration is an explicit call only."""
    container = create_dependency_container()

    assert container.get_registered_types() == []


def test_factory_returns_independent_containers(config: StrandsAgentConfig) -> None:
    """Each call returns its own container; overriding one does not affect the other."""
    first = create_default_container(config, query_processor=StubQueryProcessor())
    second = create_default_container(config)

    assert first is not second
    assert first.resolve(QueryProcessor) is not second.resolve(QueryProcessor)
    assert isinstance(second.resolve(QueryProcessor), QueryOrchestrator)
