# SPDX-License-Identifier: Apache-2.0
"""Memory provider scoping, capabilities, and opt-in factory integration."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from foundry_agent_core import AgentCreationError
from foundry_strands_agent import (
    AgentModelConfig,
    HindsightMemoryConfig,
    HindsightMemoryProvider,
    StrandsAgentConfig,
    StrandsAgentFactory,
)


@pytest.mark.parametrize("bank", ["", "../other", "bank/other", "a" * 129, " bank", "bank\n"])
def test_invalid_scope_rejected(bank):
    with pytest.raises(ValidationError):
        HindsightMemoryConfig(bank_id=bank)


@pytest.mark.parametrize("settings", [{"max_tokens": 0}, {"max_tokens": 32769}, {"budget": "unlimited"}])
def test_unbounded_settings_rejected(settings):
    with pytest.raises(ValidationError):
        HindsightMemoryConfig(bank_id="team-alpha", **settings)


def test_optional_dependency_error_is_actionable():
    with patch("foundry_strands_agent.memory.import_module", side_effect=ImportError):
        with pytest.raises(ImportError, match=r"foundry-strands-agent\[hindsight\]"):
            HindsightMemoryProvider(HindsightMemoryConfig(bank_id="team-alpha"), client=object())


def test_client_required_before_optional_import():
    with pytest.raises(ValueError, match="caller-owned"):
        HindsightMemoryProvider(HindsightMemoryConfig(bank_id="team-alpha"), client=None)


def test_provider_binds_explicit_options_without_client_ownership():
    client = MagicMock()
    recall = MagicMock()
    integration = MagicMock()
    integration.create_hindsight_tools.return_value = [recall]
    with patch("foundry_strands_agent.memory.import_module", return_value=integration):
        provider = HindsightMemoryProvider(HindsightMemoryConfig(bank_id="team-alpha"), client=client)
    assert provider.get_tools() == (recall,)
    assert provider.get_tools() is provider.get_tools()
    integration.create_hindsight_tools.assert_called_once_with(
        client=client,
        bank_id="team-alpha",
        budget="low",
        max_tokens=2048,
        enable_retain=False,
        enable_recall=True,
        enable_reflect=True,
        tags=[],
        recall_tags=[],
        recall_tags_match="any",
    )
    assert not client.mock_calls


@pytest.mark.asyncio
async def test_factory_injects_provider_across_distinct_sessions_without_mutating_tools():
    container = MagicMock()
    container.resolve.return_value = StrandsAgentConfig(model=AgentModelConfig())
    memory_tool = MagicMock()
    provider = MagicMock()
    provider.get_tools.return_value = (memory_tool,)
    factory = StrandsAgentFactory(container, memory_provider=provider)
    existing_tool = MagicMock()
    supplied = [existing_tool]
    with patch.multiple(
        "foundry_strands_agent.factory",
        Agent=MagicMock(),
        BedrockModel=MagicMock(),
        SlidingWindowConversationManager=MagicMock(),
        AgentState=MagicMock(),
    ):
        with patch.object(factory, "_create_session_manager", return_value=None):
            from foundry_strands_agent.factory import Agent

            for session in ["conversation-one", "conversation-two"]:
                await factory.create_agent(tools=supplied, config_overrides={"session_id": session})
                assert Agent.call_args.kwargs["tools"] == [existing_tool, memory_tool]
    assert supplied == [existing_tool]
    assert provider.get_tools.call_count == 2
    provider.close.assert_not_called()


@pytest.mark.asyncio
async def test_provider_failure_does_not_silently_create_memoryless_agent():
    container = MagicMock()
    container.resolve.return_value = StrandsAgentConfig(model=AgentModelConfig())
    provider = MagicMock()
    provider.get_tools.side_effect = RuntimeError("sensitive backend details")
    factory = StrandsAgentFactory(container, memory_provider=provider)
    with pytest.raises(AgentCreationError, match="Failed to load configured memory provider") as error:
        await factory.create_agent()
    assert "sensitive backend details" not in str(error.value)


def test_official_adapter_keeps_banks_out_of_model_arguments():
    pytest.importorskip("hindsight_strands")
    client = MagicMock()
    client.recall.return_value = SimpleNamespace(results=[SimpleNamespace(text="Three bullets")])
    client.reflect.return_value = SimpleNamespace(text="Use three bullets")
    alpha = HindsightMemoryProvider(HindsightMemoryConfig(bank_id="team-alpha"), client=client)
    beta = HindsightMemoryProvider(HindsightMemoryConfig(bank_id="team-beta", enable_retain=True), client=client)
    alpha_tools = {tool.tool_name: tool for tool in alpha.get_tools()}
    beta_tools = {tool.tool_name: tool for tool in beta.get_tools()}
    assert set(alpha_tools) == {"hindsight_recall", "hindsight_reflect"}
    assert set(beta_tools) == {"hindsight_retain", "hindsight_recall", "hindsight_reflect"}
    assert alpha_tools["hindsight_recall"]("How should I update?") == "1. Three bullets"
    assert client.recall.call_args.kwargs["bank_id"] == "team-alpha"
    beta_tools["hindsight_retain"]("One next action")
    assert client.retain.call_args.kwargs["bank_id"] == "team-beta"
    alpha_tools["hindsight_reflect"]("How should I update?")
    assert client.reflect.call_args.kwargs["bank_id"] == "team-alpha"
    for tools in [alpha_tools, beta_tools]:
        for tool in tools.values():
            assert "bank_id" not in tool.tool_spec["inputSchema"]["json"]["properties"]
    client.close.assert_not_called()
    client.aclose.assert_not_called()


@pytest.mark.parametrize(
    "settings", [{"enable_retain": "true"}, {"enable_retain": 1}, {"max_tokens": True}, {"extra": 1}]
)
def test_config_rejects_coerced_capabilities_and_unknown_fields(settings):
    with pytest.raises(ValidationError):
        HindsightMemoryConfig(bank_id="team-alpha", **settings)


def test_config_is_immutable():
    config = HindsightMemoryConfig(bank_id="team-alpha")
    with pytest.raises(ValidationError):
        config.bank_id = "team-beta"


@pytest.mark.parametrize("max_tokens", [1, 32768])
def test_valid_config_boundaries(max_tokens):
    assert HindsightMemoryConfig(bank_id="a" * 128, max_tokens=max_tokens).max_tokens == max_tokens


@pytest.mark.parametrize("operation", ["recall", "reflect", "retain"])
def test_official_tool_failure_propagates_without_false_success(operation):
    pytest.importorskip("hindsight_strands")
    client = MagicMock()
    getattr(client, operation).side_effect = TimeoutError("service unavailable")
    provider = HindsightMemoryProvider(HindsightMemoryConfig(bank_id="team-alpha", enable_retain=True), client=client)
    tool = next(tool for tool in provider.get_tools() if tool.tool_name == f"hindsight_{operation}")
    with pytest.raises(Exception, match="service unavailable"):
        tool("fictional data")
    client.close.assert_not_called()
    client.aclose.assert_not_called()


def test_official_empty_results_and_reflection_disabled():
    pytest.importorskip("hindsight_strands")
    client = MagicMock()
    client.recall.return_value = SimpleNamespace(results=[])
    provider = HindsightMemoryProvider(HindsightMemoryConfig(bank_id="team-alpha", enable_reflect=False), client=client)
    assert len(provider.get_tools()) == 1
    assert provider.get_tools()[0]("unknown") == "No relevant memories found."
    client.create_bank.assert_not_called()
    client.retain.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_mcp_creation_path_honors_memory_provider(fails):
    container = MagicMock()
    container.resolve.return_value = StrandsAgentConfig(model=AgentModelConfig())
    provider = MagicMock()
    memory_tool = MagicMock()
    provider.get_tools.return_value = (memory_tool,)
    if fails:
        provider.get_tools.side_effect = RuntimeError("private details")
    factory = StrandsAgentFactory(container, memory_provider=provider)
    with patch.object(factory, "_collect_mcp_tools", return_value=[]), patch.object(factory, "create_model"):
        with patch("foundry_strands_agent.factory.Agent") as agent:
            if fails:
                with pytest.raises(AgentCreationError, match="Failed to load configured memory provider"):
                    await factory.create_agent_with_mcp_clients([])
                agent.assert_not_called()
            else:
                await factory.create_agent_with_mcp_clients([])
                assert agent.call_args.kwargs["tools"] == [memory_tool]


@pytest.mark.asyncio
async def test_provider_coexists_with_existing_bedrock_memory(monkeypatch):
    monkeypatch.delenv("STRANDS_KNOWLEDGE_BASE_ID", raising=False)
    container = MagicMock()
    container.resolve.return_value = StrandsAgentConfig(
        model=AgentModelConfig(), enable_memory=True, knowledge_base_id="ABC123XYZ"
    )
    provider = MagicMock()
    memory_tool = MagicMock()
    provider.get_tools.return_value = (memory_tool,)
    bedrock_memory = MagicMock()
    factory = StrandsAgentFactory(container, memory_provider=provider)
    with patch.dict("sys.modules", {"strands_tools.memory": SimpleNamespace(memory=bedrock_memory)}):
        with patch.object(factory, "create_model"), patch("foundry_strands_agent.factory.Agent") as agent:
            await factory.create_agent()
            assert agent.call_args.kwargs["tools"] == [memory_tool, bedrock_memory]


@pytest.fixture
def thread_bound_client_class():
    pytest.importorskip("hindsight_strands")
    import importlib.util
    from pathlib import Path

    example = Path(__file__).resolve().parents[3] / "examples" / "hindsight_memory.py"
    spec = importlib.util.spec_from_file_location("hindsight_example", example)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ThreadBoundClient


def test_example_client_serializes_concurrent_calls_and_cleanup(thread_bound_client_class):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor

    events = []

    class Client:
        def __init__(self):
            self.record()

        def record(self, **_kwargs):
            events.append((threading.get_ident(), id(asyncio.get_event_loop())))
            return "result"

        create_bank = retain = recall = reflect = close = record

    client = thread_bound_client_class(Client)
    with ThreadPoolExecutor(max_workers=4) as callers:
        futures = [
            callers.submit(getattr(client, method), bank_id="fictional")
            for method in ["create_bank", "retain", "recall", "reflect"] * 4
        ]
        assert all(future.result() == "result" for future in futures)
    client.close()
    assert len(events) == 18
    assert len(set(events)) == 1
    assert events[0][0] != threading.get_ident()


def test_example_client_closes_after_operation_failure(thread_bound_client_class):
    client_impl = MagicMock()
    client_impl.recall.side_effect = TimeoutError("unavailable")
    client = thread_bound_client_class(lambda: client_impl)
    try:
        with pytest.raises(TimeoutError, match="unavailable"):
            client.recall(bank_id="fictional")
    finally:
        client.close()
    client_impl.close.assert_called_once()


def test_example_client_constructor_failure_propagates(thread_bound_client_class):
    def unavailable():
        raise RuntimeError("construction failed")

    with pytest.raises(RuntimeError, match="construction failed"):
        thread_bound_client_class(unavailable)
