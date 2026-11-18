# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Agent factory implementation for Strands Agent creation and configuration.

This module implements the AgentFactory protocol, providing concrete functionality
for creating and configuring Strands Agent instances with proper tool registration
and dependency injection integration.

Environment-configured tools (``STRANDS_TOOLS_MODULES`` / ``STRANDS_TOOLS_FILES``) are
registered via :meth:`StrandsAgentFactory.load_configured_tools` during
:class:`~foundry_strands_agent.service.AgentService` startup.
"""

import asyncio
import logging
import os
import re
import types
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit

import httpx
from botocore.config import Config
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands import tool as strands_tool
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.agent.state import AgentState
from strands.models import BedrockModel, Model
from strands.models.openai import OpenAIModel
from strands.session import SessionManager
from strands.tools.loader import load_tools_from_module as strands_load_tools_from_module
from strands.tools.mcp import MCPClient
from strands.types.tools import AgentTool
from strands_tools.a2a_client import A2AClientToolProvider

from foundry_agent_core import AgentCreationError, DependencyContainer, ExternalServiceError, mask_session_id
from foundry_agent_core.encryption import load_encryption_key
from foundry_strands_agent.config.models import _MAX_SESSION_ID_LEN, AgentConfig, StrandsSessionManagerType
from foundry_strands_agent.encrypted_session import EncryptedFileSessionManager
from foundry_strands_agent.exceptions import raise_with_correlation_id
from foundry_strands_agent.mcp_reconnect import ReconnectingMCPClient
from foundry_strands_agent.protocols import (
    AgentFactory,
    AgentToolRegistry,
)
from foundry_strands_agent.protocols.agent_factory import ToolFunction
from foundry_strands_agent.s3_session import GuardedS3SessionManager
from foundry_strands_agent.session_guard import DanglingToolUseMode
from foundry_strands_agent.tls import create_mcp_http_client, create_tls_context
from foundry_strands_agent.tool_loader import load_tool_from_file, load_tool_from_module

logger = logging.getLogger(__name__)


def _default_file_session_manager(
    session_id: str,
    storage_dir: str | None = None,
    dangling_tool_use_mode: DanglingToolUseMode = "sanitize",
    **_kwargs: Any,
) -> SessionManager:
    encryption_key = load_encryption_key()
    session_manager = EncryptedFileSessionManager(
        encryption_key=encryption_key,
        session_id=session_id,
        storage_dir=storage_dir,
        dangling_tool_use_mode=dangling_tool_use_mode,
    )
    logger.info(
        "Created encrypted file session manager",
        extra={"session_type": "file", "session_id": mask_session_id(session_id)},
    )
    return session_manager


def _default_s3_session_manager(
    session_id: str,
    s3_bucket: str | None = None,
    s3_prefix: str | None = None,
    s3_region: str | None = None,
    dangling_tool_use_mode: DanglingToolUseMode = "sanitize",
    **_kwargs: Any,
) -> SessionManager:
    if not s3_bucket:
        raise AgentCreationError(
            "session_s3_bucket is required for S3SessionManager",
            context={"session_type": "s3", "session_s3_bucket": s3_bucket},
        )
    session_manager = GuardedS3SessionManager(
        session_id=session_id,
        bucket=s3_bucket,
        prefix=s3_prefix or "",
        region_name=s3_region,
        dangling_tool_use_mode=dangling_tool_use_mode,
    )
    logger.info(
        "Created S3 session manager",
        extra={"session_type": "s3", "session_id": mask_session_id(session_id)},
    )
    return session_manager


# Model-ID substrings for model families that reject any non-default temperature/top_p/top_k on
# every request. Claude entries confirmed via Anthropic's docs, platform.claude.com/docs/en/
# build-with-claude/thinking. GPT-5.6 confirmed live against real Bedrock (all three variants):
# ValidationException "This model doesn't support the temperature field. Remove temperature and
# try again." Deliberately scoped to what's confirmed, not speculative about untested models.
# A more general per-model-family constraint registry is tracked separately.
_BEDROCK_TEMPERATURE_REJECTING_MODEL_SUBSTRINGS = (
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-5",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-mythos-preview",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "gpt-5.6",
)


# Digit-boundary check after each substring, so "claude-opus-5" doesn't also match a
# hypothetical distinct future model like "claude-opus-50" - substrings in the reject set are
# always followed by "-"/end-of-string in real Bedrock model IDs, never directly by another digit.
def _compile_temperature_reject_pattern(substrings: Sequence[str]) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(s.lower()) + r"(?!\d)" for s in substrings))


_BEDROCK_TEMPERATURE_REJECTING_PATTERN = _compile_temperature_reject_pattern(
    _BEDROCK_TEMPERATURE_REJECTING_MODEL_SUBSTRINGS
)


# Checks model_id against the built-in reject set, plus any operator-configured additions
# (StrandsAgentConfig.model.bedrock_temperature_rejecting_models / STRANDS_BEDROCK_TEMPERATURE_
# REJECTING_MODELS), which extend rather than replace the built-in set.
def _bedrock_model_rejects_temperature(model_id: str, extra_reject_models: Sequence[str] = ()) -> bool:
    lowered = model_id.lower()
    if _BEDROCK_TEMPERATURE_REJECTING_PATTERN.search(lowered):
        return True
    if not extra_reject_models:
        return False
    return bool(_compile_temperature_reject_pattern(extra_reject_models).search(lowered))


_ENV_VAR_REFERENCE_PATTERN = re.compile(r"\$\{(\w+)\}")

# AgentBuilder.build() session ids can come from untrusted callers (an A2A
# context id) and become a storage path segment. The id is used as is, so
# destroy_session() and chat history lookups find the session by the same id.
# Only ids that are a valid path segment on every OS are allowed:
# - Only characters valid in file names on every OS.
# - No trailing ".", because Windows strips it, so "a." and "a" would collide.
# - At most 128 characters, the same cap as StrandsAgentConfig.session_id, so
#   any id create_agent() accepts by length also works here. With the default
#   storage directory that keeps the session file path under Windows MAX_PATH
#   (260), but a long session_storage_dir can still exceed it.
# Ids that differ only in letter case share a directory on case-insensitive
# file systems (macOS and Windows defaults). That is accepted: reaching a
# session that way requires already knowing its id, and S3 is case-sensitive.
_BUILD_SESSION_ID_MAX_LEN = _MAX_SESSION_ID_LEN
_BUILD_SESSION_ID_PATTERN = re.compile(rf"[A-Za-z0-9._-]{{0,{_BUILD_SESSION_ID_MAX_LEN - 1}}}[A-Za-z0-9_-]")

# The context id strands' A2AServer passes to agent_factory when it builds the
# agent-card agent at server construction (strands.multiagent.a2a.server
# _AGENT_CARD_CONTEXT_ID). Kept as a literal because importing the SDK's A2A
# server here would load its whole HTTP stack for every factory user; a unit
# test pins it to the SDK value.
_A2A_AGENT_CARD_CONTEXT_ID = "__agent_card__"


def _interpolate_env_vars(headers: dict[str, str] | None) -> dict[str, str] | None:
    """Substitute ${VAR} references in MCP header values with the matching environment variable.

    Raises ExternalServiceError on an unresolved reference so a missing variable fails loudly
    instead of sending the literal "${VAR}" string to the MCP server.
    """
    if headers is None:
        return None

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        value = os.environ.get(var_name)
        if value is None:
            raise ExternalServiceError(
                f"MCP header references undefined environment variable '{var_name}'",
                context={"env_var": var_name},
            )
        return value

    return {key: _ENV_VAR_REFERENCE_PATTERN.sub(_replace, value) for key, value in headers.items()}


def _destination_host(url: str) -> str:
    """Return `scheme://host[:port]` for a connection destination, for logging.

    Strips userinfo, path, query, and fragment so a credential embedded in a
    server url (`http://user:pass@host`) or in its path/query is never logged,  # trufflehog:ignore
    per SRG-APP-000095 (log destination IP addresses / hosts of outbound
    connections) without becoming a new credential-leak sink.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "invalid-url"
    if not parts.hostname:
        return "invalid-url"
    host = parts.hostname if not parts.port else f"{parts.hostname}:{parts.port}"
    return f"{parts.scheme}://{host}" if parts.scheme else host


def _raise_mcp_error(log_message: str, *, server_name: str, server_url: str) -> NoReturn:
    """Raise an ExternalServiceError for an MCP server failure via raise_with_correlation_id.

    A secret (e.g. an interpolated MCP header value echoed back by the HTTP transport) may be
    present in the real exception's message; server_name/server_url are the only safe context
    carried into the raised error, per raise_with_correlation_id's contract.
    """
    raise_with_correlation_id(
        ExternalServiceError,
        log_message,
        logger=logger,
        context={"server_name": server_name, "server_url": server_url},
    )


def _default_bedrock_model(config: dict[str, Any]) -> Model:
    read_timeout = int(os.getenv("AWS_READ_TIMEOUT", 900))
    connect_timeout = int(os.getenv("AWS_CONNECT_TIMEOUT", 60))
    model_id = config["model"]["model_id"]
    max_tokens = config["model"].get("max_tokens")
    extra_reject_models = config["model"].get("bedrock_temperature_rejecting_models") or []
    temperature = (
        None
        if _bedrock_model_rejects_temperature(model_id, extra_reject_models)
        else config["model"].get("temperature")
    )
    if config.get("guardrail_config") is not None:
        return BedrockModel(
            model_id=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            guardrail_id=config["guardrail_config"]["guardrail_id"],
            guardrail_version=config["guardrail_config"]["guardrail_version"],
            guardrail_trace=config["guardrail_config"]["guardrail_trace"],
            boto_client_config=Config(read_timeout=read_timeout, connect_timeout=connect_timeout),
        )
    return BedrockModel(
        model_id=model_id,
        max_tokens=max_tokens,
        temperature=temperature,
        boto_client_config=Config(read_timeout=read_timeout, connect_timeout=connect_timeout),
    )


def _default_ollama_model(config: dict[str, Any]) -> Model:
    from strands.models.ollama import OllamaModel

    return OllamaModel(
        host=config["model"].get("ollama_url") or os.getenv("OLLAMA_URL"),
        model_id=config["model"]["model_id"],
        temperature=config["model"]["temperature"],
        max_tokens=config["model"].get("max_tokens"),
    )


def _default_llamacpp_model(config: dict[str, Any]) -> Model:
    from strands.models.llamacpp import LlamaCppModel

    return LlamaCppModel(
        base_url=config["model"].get("llamacpp_url", "http://localhost:8080"),
        model_id=config["model"]["model_id"],
        params={
            "temperature": config["model"]["temperature"],
            "max_tokens": config["model"].get("max_tokens"),
            "top_p": config["model"].get("top_p"),
        },
    )


def _fresh_tls_httpx_async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(verify=create_tls_context())


class NIMSModel(OpenAIModel):  # type: ignore[misc]
    """OpenAI-compatible model for NVIDIA NIM endpoints.

    NVIDIA's API rejects ``tools: []`` (minItems: 1) and doesn't accept the
    OpenAI multi-modal content block array format. This subclass patches
    ``format_request`` to strip both before the request is sent.
    """

    def _resolve_client_args(self) -> dict[str, Any]:
        # OpenAIModel._get_client() calls this fresh on every stream() invocation and
        # constructs a new AsyncOpenAI(**_resolve_client_args()) each time, closing the
        # underlying client on exit - so client_args must carry a brand-new async client
        # on every call, not one built once and reused, or the second request fails with
        # "client has been closed".
        return {**self.client_args, "http_client": _fresh_tls_httpx_async_client()}

    def format_request(
        self,
        messages: Any,
        tool_specs: Any = None,
        system_prompt: Any = None,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        request = super().format_request(messages, tool_specs, system_prompt, tool_choice, **kwargs)
        # Strip tools/tool_choice when empty — NVIDIA rejects tools: [] (minItems: 1)
        if not request.get("tools"):
            request.pop("tools", None)
            request.pop("tool_choice", None)
        # Normalize content for NVIDIA endpoints which require a string, not a content block array
        for msg in request.get("messages", []):
            content = msg.get("content")
            if isinstance(content, list):
                if not content:
                    # Empty list (e.g. assistant message with only tool_calls) — use None
                    msg["content"] = None
                else:
                    text_parts = [block["text"] for block in content if isinstance(block, dict) and "text" in block]
                    if text_parts and len(text_parts) == len(content):
                        msg["content"] = " ".join(text_parts)
        return request


def _default_nims_model(config: dict[str, Any]) -> Model:
    base_url = config["model"].get("nims_base_url") or "https://integrate.api.nvidia.com/v1"
    api_key = config["model"].get("nims_api_key") or "no-key"
    return NIMSModel(
        client_args={
            "base_url": base_url,
            "api_key": api_key,
        },
        model_id=config["model"]["model_id"],
    )


def _memory_tool(knowledge_base_id: str, region_name: str | None) -> AgentTool:
    """Build a `memory` tool bound to one knowledge base and region.

    `strands_tools.memory.memory`'s own schema exposes `STRANDS_KNOWLEDGE_BASE_ID` and
    `region_name` as arguments the model can set, so a model-chosen value overrides the
    operator's configured knowledge base or region (`memory.py`: `kb_id =
    STRANDS_KNOWLEDGE_BASE_ID or os.getenv(...)`) - the configured value is only a
    fallback, not an enforced one. This wrapper's own schema omits both; they are bound
    here from `StrandsAgentConfig` instead, so the model has no parameter to set them
    with. Calling the decorated `memory` function directly, as below, invokes the
    original function (bypassing agent tool-invocation), per
    `DecoratedFunctionTool.__call__`.
    """
    from strands_tools.memory import memory as strands_memory

    @strands_tool(name="memory")
    def memory_tool(
        action: str,
        content: str | None = None,
        title: str | None = None,
        document_id: str | None = None,
        query: str | None = None,
        max_results: int | None = None,
        next_token: str | None = None,
        min_score: float | None = None,
    ) -> dict[str, Any]:
        """Manage content in a Bedrock Knowledge Base (store, delete, list, get, or retrieve).

        This tool provides a user-friendly interface for managing knowledge base content
        with built-in safety measures for mutative operations. For operations that modify
        data (store, delete), users will be shown a preview and asked for explicit
        confirmation before changes are made, unless the BYPASS_TOOL_CONSENT environment
        variable is set to "true".

        Args:
            action: The action to perform ('store', 'delete', 'list', 'get', or 'retrieve').
            content: The text content to store in the knowledge base (required for 'store').
            title: Optional title for the content when storing. Defaults to a timestamp.
            document_id: The ID of the document to delete or get (required for 'delete' and
                'get').
            query: The search query for semantic search (required for 'retrieve').
            max_results: Maximum number of results for 'list' or 'retrieve' (default: 50,
                max: 1000).
            next_token: Token for pagination in 'list' or 'retrieve' (optional).
            min_score: Minimum relevance score threshold (0.0-1.0) for 'retrieve'. Default
                is 0.4.

        Returns:
            A dictionary containing the result of the operation.
        """
        return strands_memory(
            action=action,
            content=content,
            title=title,
            document_id=document_id,
            query=query,
            STRANDS_KNOWLEDGE_BASE_ID=knowledge_base_id,
            max_results=max_results,  # pyright: ignore[reportArgumentType]
            next_token=next_token,
            min_score=min_score,  # pyright: ignore[reportArgumentType]
            region_name=region_name,  # pyright: ignore[reportArgumentType]
        )

    return memory_tool


DEFAULT_SESSION_MANAGER_FACTORIES: dict[str, Any] = {
    "file": _default_file_session_manager,
    "s3": _default_s3_session_manager,
}

DEFAULT_MODEL_PROVIDER_FACTORIES: dict[str, Any] = {
    "bedrock": _default_bedrock_model,
    "ollama": _default_ollama_model,
    "llamacpp": _default_llamacpp_model,
    "nims": _default_nims_model,
}


@dataclass(repr=False)
class AgentBuilder:
    """Prepared, shareable pieces for building fresh Strands Agent instances.

    Returned by :meth:`StrandsAgentFactory.create_agent_builder`, which does the
    expensive one-time setup (tool loading, MCP client construction, A2A
    discovery, model creation) once. :meth:`build` is synchronous and returns a
    fresh ``Agent`` per call, so a caller invoked once per conversation (such as
    an A2A per-context ``agent_factory=``) does not repeat that setup.

    Shared across every agent built from this builder: the model client, the
    ``MCPClient`` objects, and loaded tools. A2A client tools are the exception.
    Their provider caches every agent card a conversation discovers, including
    a card for a URL a client asked for, so each built agent gets its own
    provider. It starts with a copy of the cards discovered for the configured
    A2A servers, so no conversation repeats that discovery unless startup
    discovery timed out, in which case each conversation retries it. The MCP clients are constructed
    here but not connected. Strands connects an MCP client when the first
    agent using it is constructed, so MCP connection errors surface from
    :meth:`build`, not from ``create_agent_builder()``. The connection is
    reference-counted per agent: it stays open while at least one built agent
    holds the client, and is stopped once the last such agent is garbage
    collected. A later ``build()`` then reconnects. A caller that wants one
    long-lived connection must keep at least one built agent alive.

    The repr is disabled because the stored config carries credentials (model
    API keys, MCP ``Authorization`` headers).

    Per agent, never shared: message history, ``AgentState``, the
    conversation manager instance, the session manager, and the A2A client
    tool provider. Each ``build()``
    call gets its own conversation manager and, when a session type is
    configured, its own per-session session manager — two agents built from
    the same builder never see each other's history or state.
    """

    _factory: "StrandsAgentFactory"
    _base_config: AgentConfig
    _config_dict: dict[str, Any]
    _tools: list[Any]
    _model: Model
    _a2a_provider: A2AClientToolProvider | None = None
    _a2a_httpx_client_args: dict[str, Any] | None = None

    def build(self, session_id: str | None = None) -> Agent:
        """Build a fresh Strands Agent, synchronously.

        Args:
            session_id: Session identifier for this conversation. When a
                session type is configured and session_id is provided, a
                per-session session manager is created via the factory's
                existing session-manager registry (honours
                session_manager_factories, encryption, S3 guard, dangling
                tool-use mode). A different session_id persists to its own,
                independent session. When no session type is configured,
                session_id is ignored and the agent is not persisted, so an
                untrusted id (such as an A2A context id) never creates
                session storage. When a session type is configured, the id
                must be 1-128 characters of letters, digits, ``.``, ``_``, or
                ``-``, not ending in ``.``, so it is a valid storage path
                segment on every OS. The id ``__agent_card__``, which
                strands' ``A2AServer`` uses to build its agent-card agent at
                startup, never creates a session, so server construction
                does no session I/O and no client can share that agent's
                session.

        Returns:
            A new Agent with its own message history and AgentState.

        Raises:
            AgentCreationError: If session_id is invalid, or if session
                manager, MCP connection, or agent construction fails.
        """
        session_type = self._config_dict.get("session_type")
        if session_id == _A2A_AGENT_CARD_CONTEXT_ID:
            # The SDK's startup agent-card agent never needs persistence.
            session_id = None
        if session_id and session_type and not _BUILD_SESSION_ID_PATTERN.fullmatch(session_id):
            # The id is untrusted, so it is not echoed into the error.
            raise AgentCreationError(
                f"Invalid session_id: use 1-{_BUILD_SESSION_ID_MAX_LEN} letters, digits, '.', '_', or '-', "
                "not ending in '.'",
                context={"session_id_length": len(session_id)},
            )
        return self._build(session_id, session_type)

    def _build(self, session_id: str | None, session_type: str | None) -> Agent:
        """Build a fresh Strands Agent using an explicit session type."""
        try:
            # Create conversation manager with configured window size.
            # A fresh instance per call: this holds per-conversation mutable
            # state, so sharing one across agents built from this builder
            # would leak history between them.
            conversation_manager = SlidingWindowConversationManager(
                window_size=self._base_config.conversation_window_size,
                should_truncate_results=self._base_config.conversation_truncate_results,
            )

            # Create session manager if session configuration is provided
            # Delegates to _create_session_manager() which raises AgentCreationError on failure
            session_manager: SessionManager | None = None
            if session_id and session_type:
                session_manager = self._factory._create_session_manager(
                    session_id=session_id,
                    session_type=session_type,
                    storage_dir=self._config_dict.get("session_storage_dir"),
                    s3_bucket=self._config_dict.get("session_s3_bucket"),
                    s3_prefix=self._config_dict.get("session_s3_prefix"),
                    s3_region=self._config_dict.get("session_s3_region"),
                    dangling_tool_use_mode=self._config_dict.get("session_restore_dangling_tool_use", "sanitize"),
                )

            # A fresh list per agent, so the shared builder tools are never mutated.
            tools = [*self._tools, *self._a2a_tools()]

            # TODO: Remove type ignore when Strands Agent package is available for proper typing
            agent = Agent(
                model=self._model,  # Uses model instance for Ollama, or model_id string for other models
                # A2AServer reads its agent card name and description from the agent.
                name=self._base_config.agent_name,
                description=self._base_config.agent_description,
                system_prompt=self._config_dict["system_prompt"],
                tools=tools,
                session_manager=session_manager,
                conversation_manager=conversation_manager,
                state=AgentState(self._base_config.agent_state_initial_values),
            )

            # Log from typed config (not config_dict) to avoid CodeQL taint.
            # Safe because config_overrides only sets session_id today — never model fields.
            logger.info(
                "Created Strands Agent instance",
                extra={
                    "provider": self._base_config.model.provider,
                    "model_id": self._base_config.model.model_id,
                    "tools_count": len(tools),
                    "agent_type": type(agent).__name__,
                },
            )

            return agent

        except Exception as e:
            if isinstance(e, (AgentCreationError, ExternalServiceError)):
                raise
            raise AgentCreationError(
                f"Failed to create Strands Agent: {e}",
                context={"error": str(e), "error_type": type(e).__name__},
            ) from e

    def _a2a_tools(self) -> list[Any]:
        """Return A2A client tools from a fresh provider, so agents never share discovered cards."""
        if self._a2a_provider is None:
            return []
        provider = A2AClientToolProvider(
            known_agent_urls=list(self._a2a_provider._known_agent_urls),  # pyright: ignore[reportPrivateUsage]
            httpx_client_args=dict(self._a2a_httpx_client_args or {}),
        )
        # Copy the cards the builder discovered for the configured servers, so a
        # new conversation does not repeat that discovery. If startup discovery
        # timed out, the copied flag is False and each conversation retries it.
        # A test pins these
        # strands-agents-tools attributes.
        provider._discovered_agents = dict(self._a2a_provider._discovered_agents)  # pyright: ignore[reportPrivateUsage]
        provider._initial_discovery_done = self._a2a_provider._initial_discovery_done  # pyright: ignore[reportPrivateUsage]
        return list(provider.tools)


class StrandsAgentFactory(AgentFactory):
    """Implementation of AgentFactory for creating Strands Agent instances.

    This factory manages agent creation with proper configuration, model initialization,
    and tool registration following Strands patterns and framework conventions.

    Session Management:
        All session manager creation is handled by `_create_session_manager()`, which
        provides a unified error contract: session creation failures raise
        `AgentCreationError` rather than silently returning None. Callers that need
        graceful degradation should catch `AgentCreationError` explicitly.
    """

    def __init__(
        self,
        container: DependencyContainer,
        session_manager_factories: dict[str, Any] | None = None,
        model_provider_factories: dict[str, Any] | None = None,
    ) -> None:
        """Initialize agent factory with dependency container and optional registries.

        Args:
            container: Dependency injection container for infrastructure components
            session_manager_factories: Registry of session manager factory functions keyed by type string.
                Defaults to built-in file and S3 factories.
            model_provider_factories: Registry of model provider factory functions keyed by provider string.
                Defaults to built-in bedrock, ollama, and llamacpp factories.
        """
        self._container = container
        self._config: AgentConfig | None = None
        self._session_manager_factories = session_manager_factories or DEFAULT_SESSION_MANAGER_FACTORIES
        self._model_provider_factories = model_provider_factories or DEFAULT_MODEL_PROVIDER_FACTORIES

    async def create_agent(
        self,
        tools: Sequence[ToolFunction] | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> Agent:
        """Create a configured Strands Agent instance.

        A thin wrapper over :meth:`create_agent_builder` + :meth:`AgentBuilder.build`
        kept for backward compatibility and for callers that only need one agent.
        A caller that needs one agent per conversation (such as an A2A per-context
        ``agent_factory=``) should call :meth:`create_agent_builder` once and then
        :meth:`AgentBuilder.build` per conversation instead, to avoid repeating the
        one-time setup (tool loading, MCP clients, A2A discovery) on every call.

        Args:
            tools: Optional list of tools to provide to the agent.
            tools=[] means "no tools available"
            tools=None means "all tools available"
            config_overrides: Optional configuration overrides

        Returns:
            Configured Strands Agent ready for query processing

        Raises:
            AgentCreationError: If agent creation or configuration fails
        """
        builder = await self.create_agent_builder(tools, config_overrides)
        session_id = builder._config_dict.get("session_id")
        # create_agent() keeps its historical default of a file session when a
        # session_id is given without a session type. build() does not, because
        # its session_id may come from an untrusted caller.
        session_type = builder._config_dict.get("session_type") or (session_id and "file")
        return builder._build(session_id, session_type)

    async def create_agent_builder(
        self,
        tools: Sequence[ToolFunction] | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> AgentBuilder:
        """Run the one-time agent setup once and return a builder for per-conversation agents.

        Does everything :meth:`create_agent` used to do except construct the
        session manager and the ``Agent`` itself: config load and override
        merge, tool loading from modules/files, MCP client collection, A2A
        client tool setup and eager discovery, memory tool injection,
        telemetry init, and model creation. Those pieces are shared by every
        agent built from the returned :class:`AgentBuilder`; see its
        docstring for exactly what is shared vs. per-agent.

        Args:
            tools: Optional list of tools to provide to built agents.
            tools=[] means "no tools available"
            tools=None means "all tools available"
            config_overrides: Optional configuration overrides

        Returns:
            An AgentBuilder ready to build one Agent per conversation via
            AgentBuilder.build(session_id).

        Raises:
            AgentCreationError: If setup fails (tool loading, MCP client
                configuration, telemetry initialization, or configuration
                resolution). MCP connection errors surface later, from
                AgentBuilder.build().
        """
        try:
            # Load base configuration
            base_config = self._get_base_config()

            # Apply configuration overrides if provided
            if config_overrides:
                config_dict = self._merge_config_overrides(base_config, config_overrides)
                logger.debug(
                    "Applied configuration overrides",
                    extra={"overrides_count": len(config_overrides)},
                )
            else:
                config_dict = self._config_to_dict(base_config)

            # Initialize tools list
            tools = list[Any](tools or [])  # create a new list to not mutate `tools` argument

            # Load tools from modules and files
            tools_dir = base_config.tools_dir
            if base_config.tools_modules:
                tools.extend(await self._load_tools_from_modules(base_config.tools_modules, tools_dir))
            if base_config.tools_files:
                tools.extend(await self._load_tools_from_files(base_config.tools_files, tools_dir))
            tools = _drop_repeated_tool_spec_modules(tools)
            tools = _drop_tool_spec_modules_strands_cannot_load(tools)
            _warn_about_tool_name_overwrites(tools)

            # Add MCP tools if MCP servers are configured
            if base_config.mcp_servers:
                logger.info(
                    "MCP servers detected, connecting to MCP servers",
                    extra={"mcp_servers_count": len(base_config.mcp_servers)},
                )
                mcp_clients = await self._collect_mcp_clients(base_config.mcp_servers)

                # by extending the tools list with MCPClient objects, strands will handle
                # the connection lifecycle for each client
                tools.extend(mcp_clients)
                logger.debug("Added MCP tools", extra={"mcp_clients_count": len(mcp_clients)})

            # Add A2A client tools if configured
            a2a_provider: A2AClientToolProvider | None = None
            a2a_httpx_client_args: dict[str, Any] | None = None
            if base_config.a2a_servers:
                agent_urls = [config["url"] for config in base_config.a2a_servers]

                logger.info(
                    "A2A agents detected, adding client tools",
                    extra={
                        "agents_count": len(agent_urls),
                        "destination_hosts": [_destination_host(url) for url in agent_urls],
                    },
                )

                a2a_httpx_client_args = {"verify": create_tls_context()}
                a2a_provider = A2AClientToolProvider(
                    known_agent_urls=agent_urls,
                    httpx_client_args=dict(a2a_httpx_client_args),
                )
                # build() gives each agent its own provider seeded from this one,
                # so the A2A tools are not added to the shared tools list.
                logger.debug("Added A2A client tools", extra={"a2a_tools_count": len(a2a_provider.tools)})

                # Eagerly discover A2A agent cards at startup so LLM knows capabilities immediately
                # NOTE: Strands should handle this automatically but doesn't; see Issue #220
                timeout_seconds = 10
                try:
                    logger.debug("Eagerly discovering A2A agent capabilities...")
                    # Use public API to fetch and cache all known agent cards
                    await asyncio.wait_for(a2a_provider.a2a_list_discovered_agents(), timeout=timeout_seconds)  # pyright: ignore[reportCallIssue]
                    logger.debug("A2A agent cards discovered and cached")
                except TimeoutError:
                    logger.warning("A2A agent discovery timed out after %s seconds", timeout_seconds)
                except Exception as e:
                    logger.warning("Failed to eagerly discover A2A agents: %s", e)

            # Add memory tool if memory is enabled and knowledge_base_id is configured
            if base_config.enable_memory and base_config.knowledge_base_id:
                try:
                    # `region_name` is the Bedrock model's region (AgentModelConfig.region_name),
                    # not necessarily the knowledge base's - there's no separate KB-region field.
                    # A fixed None, like the pre-fix code, lets strands_tools.memory resolve its own
                    # region (the AWS_REGION env var, defaulting to "us-west-2" if unset), instead
                    # of forcing a cross-region model/KB setup onto the model's region.
                    tools.append(_memory_tool(base_config.knowledge_base_id, None))

                    logger.info(
                        "Memory tool injected",
                        extra={"knowledge_base_id": base_config.knowledge_base_id},
                    )
                except ImportError as e:
                    logger.warning("Failed to import memory tool from strands_tools: %s", e)
                except Exception as e:
                    logger.warning("Failed to add memory tool: %s", e)

            # Initialize telemetry if enabled
            if base_config.observability_enabled:
                try:
                    from strands.telemetry import StrandsTelemetry

                    # Use AWS Strands built-in OTLP exporter with environment variables
                    StrandsTelemetry().setup_otlp_exporter()
                    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
                    logger.info(
                        "AWS Strands telemetry initialized successfully",
                        extra={
                            "destination_host": _destination_host(otlp_endpoint) if otlp_endpoint else "unconfigured"
                        },
                    )
                except Exception as e:
                    logger.exception("Telemetry initialization failed: %s", e)
                    raise AgentCreationError(
                        f"Telemetry initialization failed: {e}",
                        context={
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "observability_enabled": True,
                            "message": "Observability is enabled but telemetry initialization failed."
                            " Check Langfuse connection and configuration.",
                        },
                    ) from e

            strands_model = self.create_model(config_dict)

            return AgentBuilder(
                _factory=self,
                _base_config=base_config,
                _config_dict=config_dict,
                _tools=tools,
                _model=strands_model,
                _a2a_provider=a2a_provider,
                _a2a_httpx_client_args=a2a_httpx_client_args,
            )

        except Exception as e:
            if isinstance(e, (AgentCreationError, ExternalServiceError)):
                raise
            raise AgentCreationError(
                f"Failed to create Strands Agent: {e}",
                context={"error": str(e), "error_type": type(e).__name__},
            ) from e

    async def _collect_mcp_clients(self, mcp_servers: list[dict[str, Any]]) -> list[MCPClient]:
        """Collect MCP clients from MCP servers.

        Connects to MCP servers using MCPClient and streamablehttp_client transport,
        creates an MCP client for each server.

        Args:
            mcp_servers: List of MCP server configurations with 'url' field

        Returns:
            List of MCP clients

        Raises:
            InvalidConfigurationError: If a server entry would send a credential over plaintext http
            ExternalServiceError: If MCP server connection fails
        """
        # The plaintext-credential guard, enforced where MCP connections are opened, so
        # it also covers servers that never passed through StrandsAgentConfig's validators.
        self._get_base_config().check_mcp_server_credentials(mcp_servers)
        mcp_clients: list[Any] = []
        for server_config in mcp_servers:
            server_url = server_config["url"]  # raise if missing
            server_name = server_config.get("name", server_url)

            if not server_url:
                raise ExternalServiceError(
                    f"Missing 'url' configuration for MCP server '{server_name}'",
                    context={"server_name": server_name, "server_config": server_config},
                )

            # After validation, server_url is guaranteed to be a string
            validated_server_url: str = server_url

            try:
                interpolated_headers = _interpolate_env_vars(server_config.get("headers", None))
            except ExternalServiceError:
                _raise_mcp_error("MCP header interpolation failed", server_name=server_name, server_url=server_url)

            # Prepare streamablehttp_client arguments per MCP configuration spec:
            server_kwargs: dict[str, Any] = {
                "url": validated_server_url,
                "headers": interpolated_headers,
                "httpx_client_factory": create_mcp_http_client,
            }
            # The below arguments are optional but have hard-coded defaults:
            if timeout := server_config.get("timeout"):
                server_kwargs["timeout"] = timeout
            if sse_read_timeout := server_config.get("sse_read_timeout"):
                server_kwargs["sse_read_timeout"] = sse_read_timeout
            if terminate_on_close := server_config.get("terminate_on_close"):
                server_kwargs["terminate_on_close"] = terminate_on_close

            try:
                # Shared by every agent built from the builder, so it reconnects in place.
                mcp_client = ReconnectingMCPClient(
                    lambda kwargs=server_kwargs: streamablehttp_client(**kwargs),
                    server_name=server_name,
                    destination_host=_destination_host(validated_server_url),
                )
                mcp_clients.append(mcp_client)
                logger.info(
                    "MCP client configured",
                    extra={"server_name": server_name, "destination_host": _destination_host(validated_server_url)},
                )

            except Exception:
                _raise_mcp_error("Failed to create MCP client", server_name=server_name, server_url=server_url)

        return mcp_clients

    async def _collect_mcp_tools(self, mcp_servers: list[dict[str, Any]]) -> list[Any]:
        """Collect tools from MCP servers.

        Connects to MCP servers using MCPClient and streamablehttp_client transport,
        discovers available tools, and creates an agent with aggregated MCP tools.

        Args:
            mcp_servers: List of MCP server configurations with 'url' field

        Returns:
            List of MCP tools discovered from all servers

        Raises:
            InvalidConfigurationError: If a server entry would send a credential over plaintext http
            ExternalServiceError: If MCP server connection fails
        """
        # Same connection-time plaintext-credential guard as _collect_mcp_clients.
        self._get_base_config().check_mcp_server_credentials(mcp_servers)
        mcp_tools: list[Any] = []
        for server_config in mcp_servers:
            server_url = server_config["url"]  # raise if missing
            server_name = server_config.get("name", server_url)

            if not server_url:
                raise ExternalServiceError(
                    f"Missing 'url' configuration for MCP server '{server_name}'",
                    context={"server_name": server_name, "server_config": server_config},
                )

            # After validation, server_url is guaranteed to be a string
            validated_server_url: str = server_url

            try:
                interpolated_headers = _interpolate_env_vars(server_config.get("headers", None))
            except ExternalServiceError:
                _raise_mcp_error("MCP header interpolation failed", server_name=server_name, server_url=server_url)

            # Prepare streamablehttp_client arguments per MCP configuration spec:
            server_kwargs: dict[str, Any] = {
                "url": validated_server_url,
                "headers": interpolated_headers,
                "httpx_client_factory": create_mcp_http_client,
            }
            # The below arguments are optional but have hard-coded defaults:
            if timeout := server_config.get("timeout"):
                server_kwargs["timeout"] = timeout
            if sse_read_timeout := server_config.get("sse_read_timeout"):
                server_kwargs["sse_read_timeout"] = sse_read_timeout
            if terminate_on_close := server_config.get("terminate_on_close"):
                server_kwargs["terminate_on_close"] = terminate_on_close

            try:
                # Create transport callable factory for the MCP server
                # MCPClient expects a callable that returns the transport when called
                # Use default argument to capture server_url by value (not reference)
                def transport_callable():
                    return streamablehttp_client(**server_kwargs)  # noqa: B023

                # Connect to MCP server using synchronous context manager
                client = MCPClient(transport_callable)
                # this will open a thread to keep the client connection alive.
                # Refer to the strands documentation for more details.
                client.start()
                # Discover available tools from the server
                tools_response = client.list_tools_sync()
                # tools_response is a PaginatedList, which is iterable
                tools_from_server = list(tools_response) if tools_response else []

                logger.debug(
                    "MCP tools discovered: %s tools from %s, response_type=%s",
                    len(tools_from_server),
                    server_name,
                    type(tools_response).__name__,
                )

                mcp_tools.extend(tools_from_server)

                logger.info(
                    "Connected to MCP server and discovered tools",
                    extra={
                        "server_name": server_name,
                        "destination_host": _destination_host(validated_server_url),
                        "tools_count": len(tools_from_server),
                    },
                )

            except Exception:
                _raise_mcp_error("Failed to connect to MCP server", server_name=server_name, server_url=server_url)

        return mcp_tools

    async def create_agent_with_mcp_clients(
        self,
        mcp_servers: list[dict[str, Any]],
        config_overrides: dict[str, Any] | None = None,
    ) -> Agent:
        """Create agent with Model Context Protocol (MCP) tools.

        Connects to MCP servers using MCPClient and streamablehttp_client transport,
        discovers available tools, and creates an agent with aggregated MCP tools.

        Args:
            mcp_servers: List of MCP server configurations with 'url' field
            config_overrides: Optional configuration overrides

        Returns:
            Configured Strands Agent with MCP tools integrated

        Raises:
            AgentCreationError: If agent creation fails
            ExternalServiceError: If MCP server connection fails
        """
        try:
            # Load base configuration
            base_config = self._get_base_config()

            # Apply configuration overrides if provided
            if config_overrides:
                config_dict = self._merge_config_overrides(base_config, config_overrides)
            else:
                config_dict = self._config_to_dict(base_config)

            # Use helper method to collect MCP tools
            tools = await self._collect_mcp_tools(mcp_servers)

            # Add A2A client tools if configured (works alongside MCP tools)
            if base_config.a2a_servers:
                agent_urls = [config["url"] for config in base_config.a2a_servers]

                logger.info(
                    "A2A agents detected, adding client tools alongside MCP tools",
                    extra={
                        "agents_count": len(agent_urls),
                        "destination_hosts": [_destination_host(url) for url in agent_urls],
                    },
                )

                a2a_provider = A2AClientToolProvider(
                    known_agent_urls=agent_urls,
                    httpx_client_args={"verify": create_tls_context()},
                )
                # A2A tools are DecoratedFunctionTool objects that are directly callable
                tools.extend(a2a_provider.tools)

                logger.debug(
                    "Added A2A client tools",
                    extra={"a2a_tools_count": len(a2a_provider.tools)},
                )

            # Create conversation manager with configured window size
            conversation_manager = SlidingWindowConversationManager(
                window_size=base_config.conversation_window_size,
                should_truncate_results=base_config.conversation_truncate_results,
            )

            strands_model = self.create_model(config_dict)

            # Create agent with aggregated MCP tools and A2A tools
            agent = Agent(
                model=strands_model,
                system_prompt=config_dict["system_prompt"],
                tools=tools,
                conversation_manager=conversation_manager,
                state=AgentState(base_config.agent_state_initial_values),
            )

            # Log from typed config (not config_dict) to avoid CodeQL taint.
            # Safe because config_overrides only sets session_id today — never model fields.
            logger.info(
                "Created Strands Agent with MCP tools and A2A tools",
                extra={
                    "provider": base_config.model.provider,
                    "model_id": base_config.model.model_id,
                    "mcp_servers_count": len(mcp_servers),
                    "a2a_servers_count": len(base_config.a2a_servers) if base_config.a2a_servers else 0,
                    "total_tools": len(tools),
                },
            )

            return agent

        except Exception as e:
            if isinstance(e, AgentCreationError | ExternalServiceError):
                raise
            raise AgentCreationError(
                f"Failed to create Strands Agent with MCP clients: {e}",
                context={"error": str(e), "error_type": type(e).__name__},
            ) from e

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
        try:
            # Get tools from registry
            available_tools = tool_registry.get_available_tools()

            # Validate tool dependencies
            validation_results = tool_registry.validate_tool_dependencies()
            if not validation_results.get("all_valid", True):
                logger.warning(
                    "Some tool dependencies are not available",
                    extra={"validation_results": validation_results},
                )

            logger.info(
                "Retrieved tools from registry",
                extra={
                    "tools_count": len(available_tools),
                    "tools_list": [str(tool) for tool in available_tools],
                    "tools_types": [type(tool).__name__ for tool in available_tools],
                },
            )

            # Create agent with registry tools
            agent_result = await self.create_agent(
                tools=available_tools,
                config_overrides=config_overrides,
            )

            logger.info(
                "Agent created with tool registry",
                extra={
                    "agent_type": type(agent_result).__name__,
                    "agent_str": str(agent_result)[:100],
                },
            )

            return agent_result

        except Exception as e:
            if isinstance(e, AgentCreationError):
                raise
            raise AgentCreationError(
                f"Failed to create Strands Agent with tool registry: {e}",
                context={"error": str(e), "error_type": type(e).__name__},
            ) from e

    def create_model(self, config: dict[str, Any]) -> Model:
        """Create a model based on the configuration using the provider registry.

        Args:
            config: Configuration dictionary to create the model

        Returns:
            Model instance
        """
        provider = config["model"]["provider"]
        factory_fn = self._model_provider_factories.get(provider)
        if not factory_fn:
            raise AgentCreationError(
                f"Unsupported model provider: {provider}",
                context={"provider": provider, "supported_providers": list(self._model_provider_factories.keys())},
            )
        try:
            return factory_fn(config)
        except AgentCreationError:
            raise
        except Exception as e:
            raise AgentCreationError(
                f"Failed to create model: {e}", context={"error": str(e), "error_type": type(e).__name__}
            ) from e

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
        validation_results: dict[str, Any] = {
            "valid": True,
            "errors": [],
            "warnings": [],
        }

        try:
            # Validate required model configuration
            if "model" not in config:
                validation_results["errors"].append("Missing 'model' configuration")
                validation_results["valid"] = False
            else:
                model_config = config["model"]

                # Check required model fields
                required_fields = ["provider", "model_id"]
                for field in required_fields:
                    if field not in model_config:
                        validation_results["errors"].append(f"Missing model.{field}")
                        validation_results["valid"] = False

                # Validate provider
                supported_providers = {
                    "bedrock",
                }
                if model_config.get("provider") not in supported_providers:
                    validation_results["warnings"].append(
                        f"Provider '{model_config.get('provider')}' may not be supported"
                    )

                # Validate temperature range
                temperature = model_config.get("temperature")
                if temperature is not None and not (0.0 <= temperature <= 2.0):
                    validation_results["errors"].append("temperature must be between 0.0 and 2.0")
                    validation_results["valid"] = False

            # Validate system prompt
            if "system_prompt" not in config or not config["system_prompt"].strip():
                validation_results["warnings"].append("Empty or missing system_prompt, using default")

            # Validate tools if provided
            tools = config.get("tools", [])
            if not isinstance(tools, list):
                validation_results["errors"].append("'tools' must be a list")
                validation_results["valid"] = False

            logger.debug(
                "Validated agent configuration",
                extra={
                    "valid": validation_results["valid"],
                    "errors_count": len(validation_results["errors"]),
                    "warnings_count": len(validation_results["warnings"]),
                },
            )

            return validation_results

        except Exception as e:
            raise AgentCreationError(
                f"Failed to validate agent configuration: {e}",
                context={"error": str(e), "config": config},
            ) from e

    def _get_base_config(self) -> AgentConfig:
        """Get base agent configuration from dependency container."""
        return self._container.resolve(AgentConfig)

    def _config_to_dict(self, config: AgentConfig) -> dict[str, Any]:
        """Convert AgentConfig to dictionary format for Strands Agent."""
        # map guardrail configuration to dictionary
        if hasattr(config, "model") and hasattr(config.model, "guardrails") and config.model.guardrails is not None:
            guardrail_config = {
                "guardrail_id": config.model.guardrails.guardrail_id,
                "guardrail_version": config.model.guardrails.guardrail_version,
                "guardrail_trace": config.model.guardrails.guardrail_trace,
            }
        else:
            guardrail_config = None

        # Defensive access for a2a_servers attribute
        a2a_servers = getattr(config, "a2a_servers", [])

        return {
            "model": {
                "provider": config.model.provider,
                "model_id": config.model.model_id,
                "ollama_url": config.model.ollama_url,
                "llamacpp_url": config.model.llamacpp_url,
                "nims_base_url": config.model.nims_base_url,
                "nims_api_key": config.model.nims_api_key,
                "temperature": config.model.temperature,
                "max_tokens": config.model.max_tokens,
                "top_p": config.model.top_p,
                "bedrock_temperature_rejecting_models": config.model.bedrock_temperature_rejecting_models,
                "streaming": config.model.streaming,
                "region_name": config.model.region_name,
            },
            "guardrail_config": guardrail_config,
            "system_prompt": config.system_prompt,
            "tools_modules": config.tools_modules,
            "tools_files": config.tools_files,
            "max_conversation_length": config.max_conversation_length,
            "enable_memory": config.enable_memory,
            "knowledge_base_id": config.knowledge_base_id,
            "mcp_servers": config.mcp_servers,
            "a2a_servers": a2a_servers,
            "conversation_window_size": config.conversation_window_size,
            "conversation_truncate_results": config.conversation_truncate_results,
            "agent_state_initial_values": config.agent_state_initial_values,
            "session_id": config.session_id,
            "session_type": config.session_type,
            "session_storage_dir": config.session_storage_dir,
            "session_s3_bucket": config.session_s3_bucket,
            "session_s3_prefix": config.session_s3_prefix,
            "session_s3_region": getattr(config, "session_s3_region", None),
            "session_restore_dangling_tool_use": config.session_restore_dangling_tool_use,
        }

    def _create_session_repository(self, config: AgentConfig) -> SessionManager | None:
        """Create session repository based on configuration.

        Delegates to `_create_session_manager()` for actual creation.

        Args:
            config: Agent configuration containing session settings

        Returns:
            Configured session manager instance, or None if no session_id

        Raises:
            AgentCreationError: If session repository creation fails
        """
        if not config.session_id:
            return None

        if not config.session_type:
            logger.debug("No session_type configured, skipping session repository creation")
            return None

        return self._create_session_manager(
            session_id=config.session_id,
            session_type=config.session_type,
            storage_dir=config.session_storage_dir,
            s3_bucket=config.session_s3_bucket,
            s3_prefix=config.session_s3_prefix,
            s3_region=getattr(config, "session_s3_region", None),
            dangling_tool_use_mode=config.session_restore_dangling_tool_use,
        )

    def _merge_config_overrides(self, base_config: AgentConfig, overrides: dict[str, Any]) -> dict[str, Any]:
        """Merge configuration overrides with base configuration."""
        config_dict = self._config_to_dict(base_config)

        # Deep merge model configuration if provided
        if "model" in overrides:
            model_overrides = overrides["model"]
            if isinstance(model_overrides, dict):
                config_dict["model"].update(model_overrides)
            overrides = overrides.copy()
            del overrides["model"]

        # Merge top-level overrides
        config_dict.update(overrides)

        return config_dict

    def _create_session_manager(
        self,
        session_id: str,
        session_type: str | StrandsSessionManagerType,
        storage_dir: str | None = None,
        s3_bucket: str | None = None,
        s3_prefix: str | None = None,
        s3_region: str | None = None,
        dangling_tool_use_mode: DanglingToolUseMode = "sanitize",
    ) -> SessionManager:
        """Create a session manager instance based on the specified type.

        This is the single source of truth for session manager creation. All session
        creation paths delegate to this method, ensuring consistent error handling
        and validation.

        Args:
            session_id: Unique identifier for the session
            session_type: Type of session manager ("file" or "s3")
            storage_dir: Directory for file-based sessions (required for "file" type)
            s3_bucket: S3 bucket name (required for "s3" type)
            s3_prefix: S3 key prefix (optional for "s3" type)
            s3_region: AWS region for S3 (optional for "s3" type)
            dangling_tool_use_mode: Restore-time remediation mode for a session whose
                restored history ends in an unresolved `tool_use` block

        Returns:
            Configured SessionManager instance

        Raises:
            AgentCreationError: If session manager creation fails for any reason,
                including unsupported session types, missing required configuration,
                or runtime failures.
        """
        # Normalize session_type to string for comparison
        session_type_str = session_type.value if isinstance(session_type, StrandsSessionManagerType) else session_type

        factory_fn = self._session_manager_factories.get(session_type_str)
        if not factory_fn:
            raise AgentCreationError(
                f"Unsupported session type: {session_type_str}",
                context={
                    "session_type": session_type_str,
                    "supported_types": list(self._session_manager_factories.keys()),
                },
            )

        try:
            return factory_fn(
                session_id=session_id,
                storage_dir=storage_dir,
                s3_bucket=s3_bucket,
                s3_prefix=s3_prefix,
                s3_region=s3_region,
                dangling_tool_use_mode=dangling_tool_use_mode,
            )

        except AgentCreationError:
            raise
        except Exception as e:
            raise AgentCreationError(
                f"Failed to create session manager: {e}",
                context={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "session_id": mask_session_id(session_id),
                    "session_type": session_type_str,
                },
            ) from e

    def destroy_session(self, session_id: str, config_overrides: dict[str, Any] | None = None) -> None:
        """Destroy all persisted state for the given session.

        Caller is responsible for invoking on logoff or browser-close events.

        Args:
            session_id: The session identifier to destroy.
            config_overrides: Optional configuration overrides for session manager creation.

        Raises:
            AgentCreationError: If session destruction fails.
        """
        base_config = self._get_base_config()
        if config_overrides:
            config_dict = self._merge_config_overrides(base_config, config_overrides)
        else:
            config_dict = self._config_to_dict(base_config)

        session_type = config_dict.get("session_type") or "file"
        session_manager = self._create_session_manager(
            session_id=session_id,
            session_type=session_type,
            storage_dir=config_dict.get("session_storage_dir"),
            s3_bucket=config_dict.get("session_s3_bucket"),
            s3_prefix=config_dict.get("session_s3_prefix"),
            s3_region=config_dict.get("session_s3_region"),
            dangling_tool_use_mode=config_dict.get("session_restore_dangling_tool_use", "sanitize"),
        )
        try:
            # delete_session is on FileSessionManager/S3SessionManager, not the abstract base
            session_manager.delete_session(session_id)  # pyright: ignore[reportAttributeAccessIssue]
        except Exception as e:
            raise AgentCreationError(
                f"Failed to destroy session: {e}",
                context={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "session_id": mask_session_id(session_id),
                },
            ) from e
        logger.info(
            "Session destroyed",
            extra={"session_id": mask_session_id(session_id)},
        )

    def create_session_repository(self, config_overrides: dict[str, Any] | None = None) -> SessionManager | None:
        """Create session repository based on configuration.

        Delegates to `_create_session_manager()` for actual creation. Returns None
        only when no session_id is configured (session persistence is optional).

        Args:
            config_overrides: Optional configuration overrides

        Returns:
            Configured session manager instance, or None if no session_id configured

        Raises:
            AgentCreationError: If session repository creation fails due to invalid
                configuration, unsupported session type, or runtime errors.
        """
        # Load base configuration
        base_config = self._get_base_config()

        # Apply configuration overrides if provided
        if config_overrides:
            config_dict = self._merge_config_overrides(base_config, config_overrides)
            logger.debug(
                "Applied configuration overrides",
                extra={"overrides_count": len(config_overrides)},
            )
        else:
            config_dict = self._config_to_dict(base_config)

        # Return None if no session_id configured (session persistence is optional)
        session_id = config_dict.get("session_id") or "default"
        session_type = config_dict.get("session_type")

        if not session_type:
            logger.debug("No session_type configured, skipping session repository creation")
            return None

        # Delegate to unified session manager creation
        return self._create_session_manager(
            session_id=session_id,
            session_type=session_type,
            storage_dir=config_dict.get("session_storage_dir"),
            s3_bucket=config_dict.get("session_s3_bucket"),
            s3_prefix=config_dict.get("session_s3_prefix"),
            s3_region=config_dict.get("session_s3_region"),
            dangling_tool_use_mode=config_dict.get("session_restore_dangling_tool_use", "sanitize"),
        )

    async def load_configured_tools(
        self,
        config: AgentConfig,
        tool_registry: AgentToolRegistry,
    ) -> None:
        """Load tools from ``AgentConfig`` and register them on the tool registry.

        Loads tools from module paths (``STRANDS_TOOLS_MODULES``) and file paths
        (``STRANDS_TOOLS_FILES``). Logs errors but continues with remaining tools if
        individual tools fail to load. Does not raise exceptions, so service
        initialization can complete without configured tools when loading fails.

        Args:
            config: Agent configuration containing tool module and file paths.
            tool_registry: Registry to register successfully loaded tools.
        """
        try:
            tools_modules = config.tools_modules
            tools_files = config.tools_files
            tools_dir = config.tools_dir

            if not tools_modules and not tools_files:
                logger.info("No tools specified in STRANDS_TOOLS_MODULES or STRANDS_TOOLS_FILES, skipping tool loading")
                return

            loaded_tools: list[tuple[str, ToolFunction]] = []
            failed_tools: list[str] = []

            for module_path in tools_modules:
                try:
                    tool = await load_tool_from_module(module_path, tools_dir=tools_dir)
                    loaded_tools.append((module_path, tool))

                    tool_name, tool_format = self._get_tool_name(tool)

                    logger.info(
                        "Successfully loaded tool from module",
                        extra={
                            "module_path": module_path,
                            "tool_name": tool_name,
                            "tool_format": tool_format,
                        },
                    )
                except Exception as e:
                    failed_tools.append(module_path)
                    logger.error(
                        "Failed to load tool module",
                        extra={
                            "module_path": module_path,
                            "error": str(e),
                            "error_type": type(e).__name__,
                        },
                    )

            for file_path in tools_files:
                try:
                    tool = await load_tool_from_file(file_path, tools_dir=tools_dir)

                    if isinstance(tool, list):
                        for t in tool:
                            loaded_tools.append((file_path, t))
                            tool_name, tool_format = self._get_tool_name(t)
                            logger.info(
                                "Successfully loaded tool from file",
                                extra={
                                    "file_path": file_path,
                                    "tool_name": tool_name,
                                    "tool_format": tool_format,
                                },
                            )
                    else:
                        loaded_tools.append((file_path, tool))
                        tool_name, tool_format = self._get_tool_name(tool)
                        logger.info(
                            "Successfully loaded tool from file",
                            extra={
                                "file_path": file_path,
                                "tool_name": tool_name,
                                "tool_format": tool_format,
                            },
                        )
                except Exception as e:
                    failed_tools.append(file_path)
                    logger.error(
                        "Failed to load tool file",
                        extra={
                            "file_path": file_path,
                            "error": str(e),
                            "error_type": type(e).__name__,
                        },
                    )

            if loaded_tools:
                self._register_loaded_tools(loaded_tools, tools_modules, tool_registry)

            total_tools = len(tools_modules) + len(tools_files)
            logger.info(
                "Completed tool loading",
                extra={
                    "successful": len(loaded_tools),
                    "failed": len(failed_tools),
                    "total": total_tools,
                    "modules_loaded": len(tools_modules),
                    "files_loaded": len(tools_files),
                },
            )

            if failed_tools:
                logger.warning("Some tools failed to load", extra={"failed_tools": failed_tools})

        except Exception as e:
            logger.error(
                "Failed to load configured tools",
                extra={"error": str(e), "error_type": type(e).__name__},
            )

    @staticmethod
    def _get_tool_name(tool: ToolFunction) -> tuple[str, str]:
        """Derive a display name and format label for a loaded tool object."""
        tool_name = "unknown"
        tool_format = "unknown"
        if hasattr(tool, "TOOL_SPEC"):
            tool_name = tool.TOOL_SPEC.get("name", "unknown")  # pyright: ignore[reportFunctionMemberAccess]
            tool_format = "TOOL_SPEC module"
        elif hasattr(tool, "__name__"):
            tool_name = tool.__name__
            tool_format = "@tool decorated function"
        return tool_name, tool_format

    def _register_loaded_tools(
        self,
        loaded_tools: list[tuple[str, ToolFunction]],
        tools_modules: list[str],
        tool_registry: AgentToolRegistry,
    ) -> None:
        """Register loaded tools with the registry (used by ``load_configured_tools``)."""
        for tool_spec, tool in loaded_tools:
            try:
                source_type = "module" if tool_spec in tools_modules else "file"

                original_name, _ = self._get_tool_name(tool)

                metadata = {
                    "source": tool_spec,
                    "source_type": source_type,
                    "original_name": original_name,
                }

                tool_registry.register_tool(tool, metadata=metadata)

                logger.info(
                    "Registered tool with registry",
                    extra={
                        "tool_spec": tool_spec,
                        "original_name": original_name,
                        "source_type": source_type,
                    },
                )
            except Exception as e:
                logger.error(
                    "Failed to register tool with registry",
                    extra={"tool_spec": tool_spec, "error": str(e)},
                )

    async def _load_tools_from_modules(
        self,
        tools_modules: list[str],
        tools_dir: str | None = None,
    ) -> list[ToolFunction]:
        """Load tools from modules, confined to ``tools_dir`` when configured."""
        tools = []
        for tool_module in tools_modules:
            try:
                # load_tool_from_module validates the module (tools_dir confinement, source analysis,
                # tool shape) before returning it; a TOOL_SPEC module comes back as the module itself.
                loaded = await load_tool_from_module(tool_module, tools_dir=tools_dir)
                spec = getattr(loaded, "TOOL_SPEC", None)
                tools_list = spec.get("tools") if isinstance(spec, dict) else None
                if isinstance(tools_list, (list, tuple)):  # a TOOL_SPEC's own "tools", loaded as before 3.2.2
                    tools.extend(tools_list)
                else:
                    tools.append(loaded)
            except Exception as e:
                logger.error(
                    "Failed to load tool module",
                    extra={
                        "tool_module": tool_module,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
        return tools

    async def _load_tools_from_files(
        self,
        tools_files: list[str],
        tools_dir: str | None = None,
    ) -> list[ToolFunction]:
        """Load tools from files, confined to ``tools_dir`` when configured."""
        tools = []
        for tool_path in tools_files:
            try:
                tool = await load_tool_from_file(tool_path, tools_dir=tools_dir)
                tools.append(tool)
            except Exception as e:
                logger.error(
                    "Failed to load tool file",
                    extra={
                        "tool_path": tool_path,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
        return tools


def _drop_repeated_tool_spec_modules(tools: list[Any]) -> list[Any]:
    """Keep the first TOOL_SPEC module loaded from each file, and warn about any later copy.

    Before 3.2.2, a TOOL_SPEC module listed in ``tools_modules`` was dropped, so a tool listed in
    ``tools_files`` as well loaded once. It now loads from both, so a second copy of the same file
    is skipped to keep giving the agent the tool once. Files are compared by resolved path, so two
    different files are both kept and passed to Strands, which names each after its file. Two
    different files with the same file name get the same name there, and Strands keeps the later one,
    as before 3.2.2.
    """
    seen: set[str] = set()
    kept: list[Any] = []
    for tool in tools:
        is_tool_spec = isinstance(tool, types.ModuleType) and hasattr(tool, "TOOL_SPEC")
        source = getattr(tool, "__file__", None) if is_tool_spec else None
        if isinstance(source, str):
            path = os.path.normcase(str(Path(source).resolve()))
            if path in seen:
                spec = getattr(tool, "TOOL_SPEC", None)
                logger.warning(
                    "Skipping a second copy of TOOL_SPEC tool %s from %s (the file is listed more than once "
                    "in tools_modules and tools_files)",
                    spec.get("name") if isinstance(spec, dict) else tool.__name__,
                    path,
                )
                continue
            seen.add(path)
        kept.append(tool)
    return kept


def _drop_tool_spec_modules_strands_cannot_load(tools: list[Any]) -> list[Any]:
    """Skip, with an error, a TOOL_SPEC module that Strands would reject or misname.

    Strands 1.57.0 loads a module tool under its module's file name (strands.tools.registry
    process_tools) and runs it through strands.tools.loader.load_tools_from_module. The loader here
    checks for a function named after TOOL_SPEC["name"] instead, so two problems pass it:

    - Strands rejects the module (for example, no function named after the file, or an empty
      TOOL_SPEC), and that fails Agent() for every tool.
    - Strands loads it, but registers it under the file name while telling the model it is called
      TOOL_SPEC["name"]. When the names differ, every call the model makes is "tool not found".

    Each module is run through Strands' own loader, so its rules aren't copied here, and kept only
    if every tool it yields is registered under the name its spec gives. Skipping just that module
    keeps the agent starting, as it did before 3.2.2, when such a module was dropped.
    """
    kept: list[Any] = []
    for tool in tools:
        # Strands only loads a module with a file as a module tool; everything else passes through.
        if isinstance(tool, types.ModuleType) and hasattr(tool, "TOOL_SPEC") and hasattr(tool, "__file__"):
            strands_name = tool.__name__.split(".")[-1]
            try:
                strands_tools = strands_load_tools_from_module(tool, strands_name)
            except Exception as e:
                logger.error(
                    "Skipping tool module %s from %s: Strands cannot load it (%s)",
                    strands_name,
                    tool.__file__,
                    e,
                )
                continue
            misnamed = [t for t in strands_tools if t.tool_name != t.tool_spec.get("name")]
            if misnamed:
                logger.error(
                    "Skipping TOOL_SPEC tool %s from %s: Strands names it %r after its file, so the file "
                    'name, TOOL_SPEC["name"] and its function must all match. Rename the file to %s.py, '
                    'or set TOOL_SPEC["name"] and the function name to %r',
                    misnamed[0].tool_spec.get("name"),
                    tool.__file__,
                    strands_name,
                    misnamed[0].tool_spec.get("name"),
                    strands_name,
                )
                continue
        kept.append(tool)
    return kept


def _strands_tool_names(tool: Any) -> list[tuple[str, str]]:
    """The names Strands will register for ``tool``, each with where it came from.

    A module with a file is named the way Strands names it (strands.tools.loader); an AgentTool,
    which covers @tool functions, under its tool_name; a list or tuple, item by item. Anything else
    (path strings, dicts) is left to Strands and not reported.
    """
    if isinstance(tool, list | tuple):
        return [named for item in tool for named in _strands_tool_names(item)]
    if isinstance(tool, types.ModuleType) and hasattr(tool, "__file__"):
        try:
            loaded = strands_load_tools_from_module(tool, tool.__name__.split(".")[-1])
        except Exception:
            return []  # not a tool module Strands loads; nothing to name
        path = os.path.normcase(str(Path(str(tool.__file__)).resolve()))
        return [(t.tool_name, path) for t in loaded]
    if isinstance(tool, AgentTool):
        return [(tool.tool_name, f"{getattr(tool, '__module__', type(tool).__name__)}.{tool.tool_name}")]
    return []


def _warn_about_tool_name_overwrites(tools: list[Any]) -> None:
    """Warn when two tools get the same name, which Strands resolves by keeping the later one.

    Strands 1.57.0 lets a later tool replace an earlier one with the same name (module tools and
    @tool functions support hot reload, strands.tools.registry.register_tool), with only a debug
    log. The factory keeps that behavior, so nothing that loads changes, and logs which copy is lost.
    """
    sources_by_name: dict[str, list[str]] = {}
    for tool in tools:
        for name, source in _strands_tool_names(tool):
            sources = sources_by_name.setdefault(name, [])
            # The same tool reached twice (for example from the registry and from config) is one tool,
            # but it now comes later, and Strands keeps the last one: move it to the end.
            if source in sources:
                sources.remove(source)
            sources.append(source)
    for name, sources in sources_by_name.items():
        if len(sources) > 1:
            logger.warning(
                "Tool name %r comes from %s. Strands keeps only the last one (%s); rename the others "
                "so each tool has its own name",
                name,
                ", ".join(sources),
                sources[-1],
            )
