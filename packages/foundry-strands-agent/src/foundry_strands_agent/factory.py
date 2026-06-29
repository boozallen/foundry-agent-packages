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
from collections.abc import Sequence
from typing import Any

from botocore.config import Config
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.agent.state import AgentState
from strands.models import BedrockModel, Model
from strands.models.openai import OpenAIModel
from strands.session import S3SessionManager, SessionManager
from strands.tools.mcp import MCPClient
from strands_tools.a2a_client import A2AClientToolProvider

from foundry_agent_core import AgentCreationError, DependencyContainer, ExternalServiceError, mask_session_id
from foundry_strands_agent.config.models import AgentConfig, StrandsSessionManagerType
from foundry_strands_agent.encrypted_session import EncryptedFileSessionManager
from foundry_strands_agent.encryption import load_encryption_key
from foundry_strands_agent.protocols import (
    AgentFactory,
    AgentToolRegistry,
)
from foundry_strands_agent.protocols.agent_factory import ToolFunction
from foundry_strands_agent.tls import create_mcp_http_client, create_tls_context
from foundry_strands_agent.tool_loader import load_tool_from_file, load_tool_from_module

logger = logging.getLogger(__name__)


def _default_file_session_manager(
    session_id: str,
    storage_dir: str | None = None,
    **_kwargs: Any,
) -> SessionManager:
    encryption_key = load_encryption_key()
    session_manager = EncryptedFileSessionManager(
        encryption_key=encryption_key,
        session_id=session_id,
        storage_dir=storage_dir,
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
    **_kwargs: Any,
) -> SessionManager:
    if not s3_bucket:
        raise AgentCreationError(
            "session_s3_bucket is required for S3SessionManager",
            context={"session_type": "s3", "session_s3_bucket": s3_bucket},
        )
    session_manager = S3SessionManager(
        session_id=session_id,
        bucket=s3_bucket,
        prefix=s3_prefix or "",
        region=s3_region,
    )
    logger.info(
        "Created S3 session manager",
        extra={"session_type": "s3", "session_id": mask_session_id(session_id)},
    )
    return session_manager


def _default_bedrock_model(config: dict[str, Any]) -> Model:
    read_timeout = int(os.getenv("AWS_READ_TIMEOUT", 900))
    connect_timeout = int(os.getenv("AWS_CONNECT_TIMEOUT", 60))
    max_tokens = config["model"].get("max_tokens")
    if config.get("guardrail_config") is not None:
        return BedrockModel(
            model_id=config["model"]["model_id"],
            max_tokens=max_tokens,
            guardrail_id=config["guardrail_config"]["guardrail_id"],
            guardrail_version=config["guardrail_config"]["guardrail_version"],
            guardrail_trace=config["guardrail_config"]["guardrail_trace"],
            boto_client_config=Config(read_timeout=read_timeout, connect_timeout=connect_timeout),
        )
    return BedrockModel(
        model_id=config["model"]["model_id"],
        max_tokens=max_tokens,
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


class NIMSModel(OpenAIModel):  # type: ignore[misc]
    """OpenAI-compatible model for NVIDIA NIM endpoints.

    NVIDIA's API rejects ``tools: []`` (minItems: 1) and doesn't accept the
    OpenAI multi-modal content block array format. This subclass patches
    ``format_request`` to strip both before the request is sent.
    """

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
    import httpx

    base_url = config["model"].get("nims_base_url") or "https://integrate.api.nvidia.com/v1"
    api_key = config["model"].get("nims_api_key") or "no-key"
    return NIMSModel(
        client_args={
            "base_url": base_url,
            "api_key": api_key,
            "http_client": httpx.Client(verify=create_tls_context()),
        },
        model_id=config["model"]["model_id"],
    )


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
            if base_config.tools_modules:
                tools.extend(await self._load_tools_from_modules(base_config.tools_modules))
            if base_config.tools_files:
                tools.extend(await self._load_tools_from_files(base_config.tools_files))

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
            if base_config.a2a_servers:
                agent_urls = [config["url"] for config in base_config.a2a_servers]

                logger.info("A2A agents detected, adding client tools", extra={"agents_count": len(agent_urls)})

                a2a_provider = A2AClientToolProvider(
                    known_agent_urls=agent_urls,
                    httpx_client_args={"verify": create_tls_context()},
                )
                # A2A tools are DecoratedFunctionTool objects that are directly callable
                tools.extend(a2a_provider.tools)  # pyright: ignore[reportArgumentType]

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
                    from strands_tools.memory import memory

                    # Set env var for the memory tool to read (it checks STRANDS_KNOWLEDGE_BASE_ID)
                    os.environ["STRANDS_KNOWLEDGE_BASE_ID"] = base_config.knowledge_base_id
                    tools.append(memory)

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
                    logger.info("AWS Strands telemetry initialized successfully")
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

            # Create conversation manager with configured window size
            conversation_manager = SlidingWindowConversationManager(
                window_size=base_config.conversation_window_size,
                should_truncate_results=base_config.conversation_truncate_results,
            )

            # Create session manager if session configuration is provided
            # Delegates to _create_session_manager() which raises AgentCreationError on failure
            session_manager: SessionManager | None = None
            session_id = config_dict.get("session_id")
            session_type = config_dict.get("session_type") or (session_id and "file")
            if session_id and session_type:
                session_manager = self._create_session_manager(
                    session_id=session_id,
                    session_type=session_type,
                    storage_dir=config_dict.get("session_storage_dir"),
                    s3_bucket=config_dict.get("session_s3_bucket"),
                    s3_prefix=config_dict.get("session_s3_prefix"),
                    s3_region=config_dict.get("session_s3_region"),
                )

            strands_model = self.create_model(config_dict)

            # TODO: Remove type ignore when Strands Agent package is available for proper typing
            agent = Agent(
                model=strands_model,  # Uses model instance for Ollama, or model_id string for other models
                system_prompt=config_dict["system_prompt"],
                tools=tools,  # type: ignore[arg-type]
                session_manager=session_manager,
                conversation_manager=conversation_manager,
                state=AgentState(base_config.agent_state_initial_values),
            )

            logger.info(
                "Created Strands Agent instance",
                extra={
                    "provider": config_dict["model"]["provider"],
                    "model_id": config_dict["model"]["model_id"],
                    "tools_count": len(tools),
                    "agent_type": type(agent).__name__,
                    "agent_methods": [method for method in dir(agent) if not method.startswith("_")],
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

    async def _collect_mcp_clients(self, mcp_servers: list[dict[str, Any]]) -> list[MCPClient]:
        """Collect MCP clients from MCP servers.

        Connects to MCP servers using MCPClient and streamablehttp_client transport,
        creates an MCP client for each server.

        Args:
            mcp_servers: List of MCP server configurations with 'url' field

        Returns:
            List of MCP clients

        Raises:
            ExternalServiceError: If MCP server connection fails
        """
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

            # Prepare streamablehttp_client arguments per MCP configuration spec:
            server_kwargs: dict[str, Any] = {
                "url": validated_server_url,
                "headers": server_config.get("headers", None),
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
                mcp_client = MCPClient(lambda kwargs=server_kwargs: streamablehttp_client(**kwargs))
                mcp_clients.append(mcp_client)

            except Exception as e:
                raise ExternalServiceError(
                    f"Failed to create MCP client for server '{server_name}': {e}",
                    context={
                        "server_name": server_name,
                        "server_url": server_url,
                        "error": str(e),
                    },
                ) from e

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
            ExternalServiceError: If MCP server connection fails
        """
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

            # Prepare streamablehttp_client arguments per MCP configuration spec:
            server_kwargs: dict[str, Any] = {
                "url": validated_server_url,
                "headers": server_config.get("headers", None),
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

                logger.debug(
                    "Connected to MCP server and discovered tools",
                    extra={
                        "server_name": server_name,
                        "server_url": server_url,
                        "tools_count": len(tools_from_server),
                    },
                )

            except Exception as e:
                raise ExternalServiceError(
                    f"Failed to connect to MCP server '{server_name}': {e}",
                    context={
                        "server_name": server_name,
                        "server_url": server_url,
                        "error": str(e),
                    },
                ) from e

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
                    extra={"agents_count": len(agent_urls)},
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

            logger.info(
                "Created Strands Agent with MCP tools and A2A tools",
                extra={
                    "provider": config_dict["model"]["provider"],
                    "model_id": config_dict["model"]["model_id"],
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

            if not tools_modules and not tools_files:
                logger.info("No tools specified in STRANDS_TOOLS_MODULES or STRANDS_TOOLS_FILES, skipping tool loading")
                return

            loaded_tools: list[tuple[str, ToolFunction]] = []
            failed_tools: list[str] = []

            for module_path in tools_modules:
                try:
                    tool = await load_tool_from_module(module_path)
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
                    tool = await load_tool_from_file(file_path)

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

    async def _load_tools_from_modules(self, tools_modules: list[str]) -> list[ToolFunction]:
        """Load tools from modules."""
        tools = []
        for tool_module in tools_modules:
            try:
                loaded = await load_tool_from_module(tool_module)
                if hasattr(loaded, "TOOL_SPEC"):
                    tools.extend(getattr(loaded, "TOOL_SPEC", {}).get("tools", []))
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

    async def _load_tools_from_files(self, tools_files: list[str]) -> list[ToolFunction]:
        """Load tools from files."""
        tools = []
        for tool_path in tools_files:
            try:
                tool = await load_tool_from_file(tool_path)
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
