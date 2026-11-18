# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for StrandsAgentFactory.create_agent_builder and AgentBuilder.build.

Covers a per-context agent builder so a caller invoked once per
conversation (such as an A2A per-context agent_factory=) does not repeat the
one-time setup (tool loading, MCP clients, A2A discovery) for every conversation.
"""

import inspect
import secrets
from unittest.mock import MagicMock, patch

import pytest
from strands_tools.a2a_client import A2AClientToolProvider

from foundry_agent_core import AgentCreationError
from foundry_strands_agent.config.models import AgentModelConfig, StrandsAgentConfig
from foundry_strands_agent.factory import AgentBuilder, StrandsAgentFactory


@pytest.fixture
def factory():
    container = MagicMock()
    config = StrandsAgentConfig(model=AgentModelConfig())
    container.resolve.return_value = config
    return StrandsAgentFactory(container=container)


def _stateless_model() -> MagicMock:
    """A mock model that real Agent objects accept (stateful models reject a conversation manager)."""
    return MagicMock(stateful=False)


@pytest.fixture
def session_factory():
    """A factory whose config has file-backed sessions configured."""
    container = MagicMock()
    config = StrandsAgentConfig(
        model=AgentModelConfig(),
        session_type="file",
        session_storage_dir="/tmp/sessions",
    )
    container.resolve.return_value = config
    return StrandsAgentFactory(container=container)


class TestCreateAgentBuilder:
    @pytest.mark.asyncio
    async def test_build_is_synchronous(self, factory):
        """AgentBuilder.build() is not a coroutine function - no await needed."""
        with patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock:
            mock_bedrock.return_value = MagicMock()
            builder = await factory.create_agent_builder()

            assert isinstance(builder, AgentBuilder)
            assert not inspect.iscoroutinefunction(builder.build)

    @pytest.mark.asyncio
    async def test_create_agent_builder_does_not_construct_agent(self, factory):
        """create_agent_builder() does the one-time setup but never calls Agent()."""
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
        ):
            mock_bedrock.return_value = MagicMock()
            await factory.create_agent_builder()

            mock_agent_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_each_create_agent_builder_call_repeats_the_setup(self, factory):
        """Each create_agent_builder() call is a complete setup, so MCP client collection runs every time."""
        factory._container.resolve.return_value = StrandsAgentConfig(
            model=AgentModelConfig(),
            mcp_servers=[{"url": "https://mcp.example.test"}],
        )
        with (
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch.object(StrandsAgentFactory, "_collect_mcp_clients", return_value=[]) as mock_collect_mcp_clients,
        ):
            mock_bedrock.return_value = MagicMock()
            await factory.create_agent_builder()
            await factory.create_agent_builder()

            assert mock_collect_mcp_clients.call_count == 2

    @pytest.mark.asyncio
    async def test_repr_does_not_expose_credentials(self):
        """The builder repr omits the stored config, which carries model API keys and MCP headers."""
        container = MagicMock()
        container.resolve.return_value = StrandsAgentConfig(
            model=AgentModelConfig(provider="nims", model_id="test-model", nims_api_key="nims-secret-value"),
            mcp_servers=[{"url": "https://mcp.example.test", "headers": {"Authorization": "Bearer mcp-secret-value"}}],
        )
        factory = StrandsAgentFactory(container=container)
        with patch.object(StrandsAgentFactory, "_collect_mcp_clients", return_value=[]):
            builder = await factory.create_agent_builder()

        assert "nims-secret-value" not in repr(builder)
        assert "mcp-secret-value" not in repr(builder)


class TestBuildIsolation:
    @pytest.mark.asyncio
    async def test_real_agents_do_not_share_messages_or_state(self, factory):
        """Two real Agent objects built from one builder keep independent history and AgentState."""
        with patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock:
            mock_bedrock.return_value = _stateless_model()
            builder = await factory.create_agent_builder()
            first = builder.build()
            second = builder.build()

        first.messages.append({"role": "user", "content": [{"text": "only in the first agent"}]})
        first.state.set("marker", "first")

        assert second.messages == []
        assert second.state.get("marker") is None

    @pytest.mark.asyncio
    async def test_two_builds_share_no_conversation_state(self, factory):
        """Two agents built from the same builder get independent state and conversation managers."""
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch("foundry_strands_agent.factory.SlidingWindowConversationManager") as mock_conv_mgr_cls,
            patch("foundry_strands_agent.factory.AgentState") as mock_state_cls,
        ):
            mock_bedrock.return_value = MagicMock()
            mock_agent_cls.side_effect = [MagicMock(), MagicMock()]
            mock_conv_mgr_cls.side_effect = [MagicMock(), MagicMock()]
            mock_state_cls.side_effect = [MagicMock(), MagicMock()]

            builder = await factory.create_agent_builder()
            builder.build()
            builder.build()

            # A fresh conversation manager and a fresh AgentState per build() call -
            # sharing either instance across builds would leak conversation state.
            assert mock_conv_mgr_cls.call_count == 2
            assert mock_state_cls.call_count == 2

            first_call, second_call = mock_agent_cls.call_args_list
            assert first_call.kwargs["conversation_manager"] is not second_call.kwargs["conversation_manager"]
            assert first_call.kwargs["state"] is not second_call.kwargs["state"]

    @pytest.mark.asyncio
    async def test_two_builds_do_not_share_the_tools_list_object(self, factory):
        """Each build() gets its own tools list, so mutating one agent's tools can't affect another's."""
        mock_tool = MagicMock()
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch("foundry_strands_agent.factory.SlidingWindowConversationManager"),
            patch("foundry_strands_agent.factory.AgentState"),
        ):
            mock_bedrock.return_value = MagicMock()
            mock_agent_cls.side_effect = [MagicMock(), MagicMock()]

            builder = await factory.create_agent_builder(tools=[mock_tool])
            builder.build()
            builder.build()

            first_call, second_call = mock_agent_cls.call_args_list
            first_tools = first_call.kwargs["tools"]
            second_tools = second_call.kwargs["tools"]
            assert first_tools is not second_tools
            assert first_tools == second_tools == [mock_tool]


class TestBuildPerSessionPersistence:
    @pytest.mark.asyncio
    async def test_different_session_ids_create_separate_session_managers(self, session_factory):
        """build('a') and build('b') each get their own session manager, keyed on their own session_id."""
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch("foundry_strands_agent.factory.SlidingWindowConversationManager"),
            patch("foundry_strands_agent.factory.AgentState"),
            patch.object(
                StrandsAgentFactory, "_create_session_manager", side_effect=[MagicMock(), MagicMock()]
            ) as mock_create_session_manager,
        ):
            mock_bedrock.return_value = MagicMock()
            mock_agent_cls.side_effect = [MagicMock(), MagicMock()]

            builder = await session_factory.create_agent_builder()
            builder.build(session_id="a")
            builder.build(session_id="b")

            assert mock_create_session_manager.call_count == 2
            first_call, second_call = mock_create_session_manager.call_args_list
            assert first_call.kwargs["session_id"] == "a"
            assert second_call.kwargs["session_id"] == "b"

            first_agent_call, second_agent_call = mock_agent_cls.call_args_list
            assert first_agent_call.kwargs["session_manager"] is not second_agent_call.kwargs["session_manager"]

    @pytest.mark.asyncio
    async def test_no_session_id_builds_without_a_session_manager(self, session_factory):
        """build() with no session_id does not create a session manager, even when a session type is configured."""
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch("foundry_strands_agent.factory.SlidingWindowConversationManager"),
            patch("foundry_strands_agent.factory.AgentState"),
            patch.object(StrandsAgentFactory, "_create_session_manager") as mock_create_session_manager,
        ):
            mock_bedrock.return_value = MagicMock()
            mock_agent_cls.return_value = MagicMock()

            builder = await session_factory.create_agent_builder()
            builder.build()

            mock_create_session_manager.assert_not_called()
            assert mock_agent_cls.call_args.kwargs["session_manager"] is None

    @pytest.mark.asyncio
    async def test_session_id_without_session_type_creates_no_session_manager(self, factory, monkeypatch):
        """build(session_id) with no session type configured does not persist, even without an encryption key.

        A2AServer calls the factory with client-supplied context ids, so build() must
        not fall back to a file session the way create_agent() does.
        """
        monkeypatch.delenv("SESSION_ENCRYPTION_KEY", raising=False)
        with (
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch.object(StrandsAgentFactory, "_create_session_manager") as mock_create_session_manager,
        ):
            mock_bedrock.return_value = _stateless_model()
            builder = await factory.create_agent_builder()
            agent = builder.build(session_id="0b4a7c1e-5f2d-4e8a-9c3b-1d6e2f7a8b90")

        mock_create_session_manager.assert_not_called()
        assert agent._session_manager is None

    @pytest.mark.asyncio
    async def test_real_file_sessions_persist_to_separate_directories(self, monkeypatch, tmp_path):
        """build('a') and build('b') with real file sessions write two separate session directories."""
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", secrets.token_hex(32))
        container = MagicMock()
        container.resolve.return_value = StrandsAgentConfig(
            model=AgentModelConfig(),
            session_type="file",
            session_storage_dir=str(tmp_path),
        )
        factory = StrandsAgentFactory(container=container)
        with patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock:
            mock_bedrock.return_value = _stateless_model()
            builder = await factory.create_agent_builder()
            builder.build(session_id="a")
            builder.build(session_id="b")

        assert sorted(p.name for p in tmp_path.iterdir()) == ["session_a", "session_b"]


class TestBuildSessionIdValidation:
    @pytest.mark.parametrize(
        "session_id",
        [
            "a:b",  # Windows reads "a:" as a drive, so the SDK basename check fails
            "a?b",  # reserved in Windows file names
            "a<b",
            "a|b",
            "a/b",
            "a b",
            "a.",  # Windows strips the trailing dot, colliding with "a"
            "\udc80x",  # lone surrogate, which cannot be encoded as a file name
            "x" * 129,  # longer than the StrandsAgentConfig.session_id cap
        ],
    )
    @pytest.mark.asyncio
    async def test_unsafe_session_id_is_rejected_before_session_creation(self, session_factory, session_id):
        """With a session type configured, build() rejects ids that are not a portable path segment."""
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch.object(StrandsAgentFactory, "_create_session_manager") as mock_create_session_manager,
        ):
            mock_bedrock.return_value = MagicMock()
            builder = await session_factory.create_agent_builder()

            with pytest.raises(AgentCreationError, match="Invalid session_id") as exc_info:
                builder.build(session_id=session_id)

        assert session_id not in str(exc_info.value)
        mock_create_session_manager.assert_not_called()
        mock_agent_cls.assert_not_called()

    @pytest.mark.parametrize(
        "session_id",
        [
            "0b4a7c1e-5f2d-4e8a-9c3b-1d6e2f7a8b90",
            "0B4A7C1E-5F2D-4E8A-9C3B-1D6E2F7A8B90",  # uppercase UUID, as some A2A clients send
            "session.1",
            "a_b-c",
            "x" * 128,
            "__agent_card",
        ],
    )
    @pytest.mark.asyncio
    async def test_portable_session_id_is_used_unchanged(self, session_factory, session_id):
        """Portable ids reach the session manager unchanged, so destroy_session() finds them by the same id."""
        with (
            patch("foundry_strands_agent.factory.Agent"),
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch.object(StrandsAgentFactory, "_create_session_manager") as mock_create_session_manager,
        ):
            mock_bedrock.return_value = MagicMock()
            builder = await session_factory.create_agent_builder()
            builder.build(session_id=session_id)

        assert mock_create_session_manager.call_args.kwargs["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_unsafe_session_id_is_ignored_without_a_session_type(self, factory):
        """With no session type configured, the id never becomes a path, so it is not validated."""
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
        ):
            mock_bedrock.return_value = MagicMock()
            builder = await factory.create_agent_builder()
            builder.build(session_id="a:b")

        assert mock_agent_cls.call_args.kwargs["session_manager"] is None

    @pytest.mark.asyncio
    async def test_built_session_is_destroyed_by_its_context_id(self, monkeypatch, tmp_path):
        """destroy_session() with the same uppercase id removes the session build() created."""
        monkeypatch.setenv("SESSION_ENCRYPTION_KEY", secrets.token_hex(32))
        container = MagicMock()
        container.resolve.return_value = StrandsAgentConfig(
            model=AgentModelConfig(),
            session_type="file",
            session_storage_dir=str(tmp_path),
        )
        factory = StrandsAgentFactory(container=container)
        session_id = "0B4A7C1E-5F2D-4E8A-9C3B-1D6E2F7A8B90"
        with patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock:
            mock_bedrock.return_value = _stateless_model()
            builder = await factory.create_agent_builder()
            builder.build(session_id=session_id)
            assert [p.name for p in tmp_path.iterdir()] == [f"session_{session_id}"]

            factory.destroy_session(session_id)

        assert list(tmp_path.iterdir()) == []


class TestBuildA2AProviderIsolation:
    """Each built agent gets its own A2A client tool provider, seeded from the builder's discovery."""

    @staticmethod
    async def _fake_discover(provider, url):
        card = MagicMock(name=url)
        provider._discovered_agents[url] = card
        return card

    @staticmethod
    def _provider_of(agent):
        """The provider bound to this agent's registered a2a_send_message tool."""
        return agent.tool_registry.registry["a2a_send_message"]._tool_func.__self__

    async def _build_two(self):
        container = MagicMock()
        container.resolve.return_value = StrandsAgentConfig(
            model=AgentModelConfig(), a2a_servers=[{"url": "https://peer.example/a2a"}]
        )
        factory = StrandsAgentFactory(container=container)
        real_provider_cls = A2AClientToolProvider
        created: list[A2AClientToolProvider] = []

        def record(*args, **kwargs):
            provider = real_provider_cls(*args, **kwargs)
            created.append(provider)
            return provider

        with (
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch("foundry_strands_agent.factory.A2AClientToolProvider", side_effect=record),
            patch.object(
                real_provider_cls, "_discover_agent_card", autospec=True, side_effect=self._fake_discover
            ) as mock_discover,
        ):
            mock_bedrock.return_value = _stateless_model()
            builder = await factory.create_agent_builder()
            agents = [builder.build(), builder.build()]
            discover_calls_after_builds = mock_discover.call_count
        return created, agents, discover_calls_after_builds

    @pytest.mark.asyncio
    async def test_built_agents_have_separate_providers_seeded_with_configured_cards(self):
        """Each agent's provider is new, has the builder's cards, and does not repeat discovery."""
        created, agents, discover_calls = await self._build_two()

        builder_provider = created[0]
        first, second = (self._provider_of(agent) for agent in agents)
        assert first is not second
        assert builder_provider not in (first, second)
        for provider in (first, second):
            assert list(provider._discovered_agents) == ["https://peer.example/a2a"]
            assert provider._discovered_agents is not builder_provider._discovered_agents
            assert provider._initial_discovery_done is True
            # The TLS context from create_tls_context() reaches every agent's provider.
            assert provider._httpx_client_args["verify"] is builder_provider._httpx_client_args["verify"]
        assert discover_calls == 1

    @pytest.mark.asyncio
    async def test_a_card_discovered_in_one_conversation_is_not_seen_by_another(self):
        """A URL a client gets its agent to discover stays in that agent's provider only."""
        created, agents, _ = await self._build_two()
        builder_provider = created[0]
        first, second = (self._provider_of(agent) for agent in agents)

        await self._fake_discover(first, "https://attacker.example")

        configured = "https://peer.example/a2a"
        assert set(first._discovered_agents) == {configured, "https://attacker.example"}
        assert set(second._discovered_agents) == {configured}
        assert set(builder_provider._discovered_agents) == {configured}

    def test_provider_private_attributes_still_exist(self):
        """build() seeds providers through these strands-agents-tools attributes."""
        provider = A2AClientToolProvider(known_agent_urls=["https://peer.example/a2a"])

        assert provider._known_agent_urls == ["https://peer.example/a2a"]
        assert provider._discovered_agents == {}
        assert provider._initial_discovery_done is False


class TestA2AAgentCardContext:
    def test_agent_card_context_id_matches_the_sdk(self):
        """The local literal must track the id strands' A2AServer passes for its agent-card agent."""
        from strands.multiagent.a2a import server as a2a_server

        from foundry_strands_agent.factory import _A2A_AGENT_CARD_CONTEXT_ID

        assert a2a_server._AGENT_CARD_CONTEXT_ID == _A2A_AGENT_CARD_CONTEXT_ID

    @pytest.mark.asyncio
    async def test_agent_card_id_creates_no_session_manager(self, session_factory):
        """With a session type configured, build('__agent_card__') still builds an agent without a session."""
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch.object(StrandsAgentFactory, "_create_session_manager") as mock_create_session_manager,
        ):
            mock_bedrock.return_value = MagicMock()
            builder = await session_factory.create_agent_builder()
            builder.build(session_id="__agent_card__")

        mock_create_session_manager.assert_not_called()
        assert mock_agent_cls.call_args.kwargs["session_manager"] is None

    @pytest.mark.asyncio
    async def test_a2a_server_startup_does_no_session_io(self, monkeypatch, tmp_path):
        """A2AServer(agent_factory=builder.build) starts with file sessions configured and no encryption key.

        The SDK builds its agent-card agent at construction. That agent must not
        need SESSION_ENCRYPTION_KEY or write a session directory.
        """
        from strands.multiagent.a2a import A2AServer

        monkeypatch.delenv("SESSION_ENCRYPTION_KEY", raising=False)
        container = MagicMock()
        container.resolve.return_value = StrandsAgentConfig(
            model=AgentModelConfig(),
            session_type="file",
            session_storage_dir=str(tmp_path),
            agent_name="claims-triage-agent",
            agent_description="Classifies insurance claims by urgency",
        )
        factory = StrandsAgentFactory(container=container)
        with patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock:
            mock_bedrock.return_value = _stateless_model()
            builder = await factory.create_agent_builder()
            server = A2AServer(agent_factory=builder.build)

        assert server.strands_agent._session_manager is None
        assert list(tmp_path.iterdir()) == []
        # The card comes from the configured name and description, not the Strands defaults.
        card = server.public_agent_card
        assert card.name == "claims-triage-agent"
        assert card.description == "Classifies insurance claims by urgency"


class TestCreateAgentWrapper:
    @pytest.mark.asyncio
    async def test_session_id_override_defaults_to_a_file_session(self, factory):
        """create_agent() keeps its historical file-session default when only a session_id is given."""
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch.object(StrandsAgentFactory, "_create_session_manager") as mock_create_session_manager,
        ):
            mock_bedrock.return_value = MagicMock()
            session_manager = MagicMock()
            mock_create_session_manager.return_value = session_manager

            await factory.create_agent(config_overrides={"session_id": "session1"})

            call_kwargs = mock_create_session_manager.call_args.kwargs
            assert call_kwargs["session_id"] == "session1"
            assert call_kwargs["session_type"] == "file"
            assert call_kwargs["dangling_tool_use_mode"] == "sanitize"
            assert mock_agent_cls.call_args.kwargs["session_manager"] is session_manager

    @pytest.mark.asyncio
    async def test_configured_session_settings_are_passed_through(self, session_factory):
        """create_agent() forwards the configured session type, storage dir, and dangling tool-use mode."""
        with (
            patch("foundry_strands_agent.factory.Agent"),
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch.object(StrandsAgentFactory, "_create_session_manager") as mock_create_session_manager,
        ):
            mock_bedrock.return_value = MagicMock()

            await session_factory.create_agent(
                config_overrides={"session_id": "session1", "session_restore_dangling_tool_use": "reject"}
            )

            call_kwargs = mock_create_session_manager.call_args.kwargs
            assert call_kwargs["session_type"] == "file"
            assert call_kwargs["storage_dir"] == "/tmp/sessions"  # noqa: S108
            assert call_kwargs["dangling_tool_use_mode"] == "reject"

    @pytest.mark.asyncio
    async def test_no_session_id_creates_no_session_manager(self, factory):
        """create_agent() without a session_id builds an agent without a session manager."""
        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch.object(StrandsAgentFactory, "_create_session_manager") as mock_create_session_manager,
        ):
            mock_bedrock.return_value = MagicMock()

            await factory.create_agent()

            mock_create_session_manager.assert_not_called()
            assert mock_agent_cls.call_args.kwargs["session_manager"] is None


class TestBuildReusesMcpClients:
    @pytest.mark.asyncio
    async def test_mcp_clients_created_once_and_reused_across_builds(self, factory):
        """MCP client setup is one-time: the same client objects are reused by every build() call."""
        mcp_clients = [MagicMock(), MagicMock()]
        factory_config = StrandsAgentConfig(
            model=AgentModelConfig(),
            mcp_servers=[{"url": "https://mcp.example.test"}],
        )
        factory._container.resolve.return_value = factory_config

        with (
            patch("foundry_strands_agent.factory.Agent") as mock_agent_cls,
            patch("foundry_strands_agent.factory.BedrockModel") as mock_bedrock,
            patch("foundry_strands_agent.factory.SlidingWindowConversationManager"),
            patch("foundry_strands_agent.factory.AgentState"),
            patch.object(
                StrandsAgentFactory, "_collect_mcp_clients", return_value=mcp_clients
            ) as mock_collect_mcp_clients,
        ):
            mock_bedrock.return_value = MagicMock()
            mock_agent_cls.side_effect = [MagicMock(), MagicMock()]

            builder = await factory.create_agent_builder()
            builder.build()
            builder.build()

            # Collected once, during create_agent_builder() - not once per build().
            mock_collect_mcp_clients.assert_called_once()

            first_call, second_call = mock_agent_cls.call_args_list
            for client in mcp_clients:
                assert client in first_call.kwargs["tools"]
                assert client in second_call.kwargs["tools"]
