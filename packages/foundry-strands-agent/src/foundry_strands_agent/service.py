# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""High-level agent service interface and query processing entry point.

This module provides the primary service interface for external consumers,
coordinating agent processing components to process queries through
the complete pipeline from request to response.

The AgentService uses constructor injection - all protocol dependencies are
passed via the constructor rather than resolved internally. This enables
teams to swap implementations by changing factory registrations.

Configured tools are loaded via :meth:`foundry_strands_agent.factory.StrandsAgentFactory.load_configured_tools`
during :meth:`initialize`. Chat history access uses :attr:`chat_history` (``ChatHistoryManager``).
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Self, cast

from foundry_agent_core import (
    AgentRequest,
    AgentResponse,
    DependencyContainer,
    QueryProcessingError,
    QueryProcessor,
    ResponseProcessor,
    ToolRegistrationError,
    mask_session_id,
)
from foundry_strands_agent.config.models import AgentConfig
from foundry_strands_agent.exceptions import (
    AgentServiceError,
    AgentServiceInitializationError,
    AgentServiceShutdownError,
)
from foundry_strands_agent.factory import StrandsAgentFactory
from foundry_strands_agent.lifecycle import (
    ExecutionContext,
    ExecutionStrategy,
    create_request_lifecycle_manager,
)
from foundry_strands_agent.protocols import (
    AgentFactory,
    AgentToolRegistry,
    ChatHistoryManager,
)

logger = logging.getLogger(__name__)


class AgentService:
    """High-level agent service providing query processing interface.

    This service coordinates all agent processing components to provide
    a clean, high-level interface for processing queries through the complete
    agent-driven pipeline while maintaining agent autonomy over tool usage.

    Uses constructor injection for all protocol dependencies. Dependencies are
    resolved from the DI container at creation time via :func:`create_agent_service`.
    Teams can swap implementations by changing registrations in ``application/factory.py``.

    Use :attr:`chat_history` for session and message history operations
    (:class:`~foundry_strands_agent.protocols.ChatHistoryManager`).
    """

    def __init__(
        self,
        container: DependencyContainer,
        agent_factory: AgentFactory,
        tool_registry: AgentToolRegistry,
        query_processor: QueryProcessor,
        chat_historian: ChatHistoryManager,
        response_processor: ResponseProcessor,
    ) -> None:
        """Initialize agent service with injected dependencies.

        All protocol dependencies are injected via constructor, enabling teams
        to swap implementations by changing factory registrations.

        Args:
            container: Dependency container (for config access and scoping)
            agent_factory: Factory for creating agent instances
            tool_registry: Registry for tool management
            query_processor: Processor for query orchestration
            chat_historian: Manager for chat history
            response_processor: Processor for response transformation
        """
        self._container = container
        self._agent_factory = agent_factory
        self._tool_registry = tool_registry
        self._query_orchestrator = query_processor
        self._chat_historian = chat_historian
        self._response_processor = response_processor

        # Internal components (not protocols - created internally)
        self._lifecycle_manager = create_request_lifecycle_manager(container)

        # State
        self._initialized = False
        self._shutdown_event = asyncio.Event()
        self._active_queries: dict[str, asyncio.Task[AgentResponse]] = {}

    async def initialize(self) -> None:
        """Initialize async components of the agent service.

        This method performs async initialization that cannot be done in the
        constructor, primarily loading tools from configured paths. All protocol
        dependencies are already injected via the constructor.

        Raises:
            AgentServiceInitializationError: If service initialization fails
        """
        if self._initialized:
            logger.warning("Agent service is already initialized")
            return

        try:
            logger.info("Initializing agent service")

            # Load tools from environment configuration (async operation)
            config = self._container.resolve(AgentConfig)
            assert self._tool_registry is not None  # Set in constructor
            await cast(StrandsAgentFactory, self._agent_factory).load_configured_tools(
                config,
                self._tool_registry,
            )

            self._initialized = True
            logger.info("Agent service initialized successfully")

        except Exception as e:
            logger.error(
                "Agent service initialization failed",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise AgentServiceInitializationError(
                f"Failed to initialize agent service: {e}",
                context={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            ) from e

    @property
    def chat_history(self) -> ChatHistoryManager:
        """Access chat history operations via :class:`~foundry_strands_agent.protocols.ChatHistoryManager`."""
        if not self._initialized:
            raise AgentServiceError(
                "Agent service is not initialized. Call initialize() first.",
                context={"service_state": "not_initialized"},
            )
        if self._shutdown_event.is_set():
            raise AgentServiceError(
                "Agent service is shutting down, cannot process new queries",
                context={"service_state": "shutting_down"},
            )
        assert self._chat_historian is not None  # Guaranteed by initialization check
        return self._chat_historian

    async def _wait_for_active_queries(self) -> None:
        """Wait for in-flight queries with a bounded grace period, then cancel stragglers."""
        if not self._active_queries:
            return

        logger.info(
            "Waiting for active queries to complete",
            extra={"queries_count": len(self._active_queries)},
        )

        try:
            await asyncio.wait_for(
                asyncio.gather(*self._active_queries.values(), return_exceptions=True),
                timeout=30.0,  # 30 second grace period
            )
        except TimeoutError:
            logger.warning("Some queries did not complete within grace period")

        for query_id, task in self._active_queries.items():
            if not task.done():
                logger.warning(
                    "Cancelling active query",
                    extra={"query_id": query_id},
                )
                task.cancel()

    async def shutdown(self) -> None:
        """Gracefully shut down the agent service.

        This method ensures all active queries are completed or cancelled
        and performs necessary cleanup of service components.

        Raises:
            AgentServiceShutdownError: If service shutdown fails
        """
        if not self._initialized:
            logger.warning("Agent service is not initialized, skipping shutdown")
            return

        try:
            logger.info(
                "Starting agent service shutdown",
                extra={"active_queries_count": len(self._active_queries)},
            )

            # Signal shutdown
            self._shutdown_event.set()

            await self._wait_for_active_queries()

            # Clean up components
            self._agent_factory = None
            self._tool_registry = None
            self._query_orchestrator = None
            self._chat_historian = None
            self._response_processor = None
            self._lifecycle_manager = None

            self._initialized = False
            logger.info("Agent service shutdown completed")

        except Exception as e:
            logger.error(
                "Agent service shutdown failed",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise AgentServiceShutdownError(
                f"Failed to shutdown agent service: {e}",
                context={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            ) from e

    async def process_query(
        self,
        request: AgentRequest,
        execution_strategy: ExecutionStrategy = ExecutionStrategy.STANDARD,
    ) -> AgentResponse:
        """Process a complete query from request to response.

        This is the primary interface for query processing, coordinating all
        service components to handle the request through the agent-driven pipeline.

        Args:
            request: User query request with parameters
            execution_strategy: Strategy for execution resilience and error handling

        Returns:
            Complete query response with generated answer and sources

        Raises:
            AgentServiceError: If service is not initialized
            QueryProcessingError: If query processing fails at any stage
        """
        if not self._initialized:
            raise AgentServiceError(
                "Agent service is not initialized. Call initialize() first.",
                context={"service_state": "not_initialized"},
            )

        if self._shutdown_event.is_set():
            raise AgentServiceError(
                "Agent service is shutting down, cannot process new queries",
                context={"service_state": "shutting_down"},
            )

        query_id = f"query_{hash(request.query)}_{int(time.time() * 1000)}"

        logger.info(
            "Processing query request",
            extra={
                "session_id": mask_session_id(request.session_id),
                "query_id": query_id,
                "execution_strategy": execution_strategy.value,
                "query_preview": (request.query[:100] + "..." if len(request.query) > 100 else request.query),
            },
        )

        try:
            # Ensure session exists if session management is configured
            if self._chat_historian is not None and self._agent_factory is not None:
                try:
                    # Check if session repository is configured
                    session_repository = self._agent_factory.create_session_repository()
                    if session_repository is not None:
                        config = self._container.resolve(AgentConfig)
                        session_id = config.session_id or "default"
                        # Create session if it doesn't exist (idempotent)
                        await self._chat_historian.create_chat_session_messages_history(session_id)
                        logger.debug(
                            "Ensured session exists for query processing",
                            extra={"session_id": mask_session_id(session_id)},
                        )
                except Exception as session_error:
                    # Log but don't fail query processing if session creation fails
                    logger.warning(
                        "Failed to ensure session exists, continuing without session",
                        extra={
                            "error": str(session_error),
                            "error_type": type(session_error).__name__,
                        },
                    )

            # Create execution context for this query
            if self._lifecycle_manager is None:
                raise AgentServiceError(
                    "Lifecycle manager is not initialized",
                    context={"service_state": "invalid_lifecycle_manager"},
                )
            async with self._lifecycle_manager.create_execution_context(
                request=request,
                strategy=execution_strategy,
                timeout_ms=30000,  # 30 second default timeout
            ) as execution_context:
                # Track active query
                query_task = asyncio.create_task(self._execute_query_processing(request, execution_context))
                self._active_queries[query_id] = query_task

                try:
                    # Execute query processing with workflow coordination
                    response = await query_task

                    logger.info(
                        "Query processing completed successfully",
                        extra={
                            "session_id": mask_session_id(request.session_id),
                            "query_id": query_id,
                            "processing_time_ms": response.processing_time_ms,
                        },
                    )

                    return response

                finally:
                    # Clean up active query tracking
                    self._active_queries.pop(query_id, None)

        except Exception as e:
            # Clean up active query tracking on error
            self._active_queries.pop(query_id, None)

            logger.error(
                "Query processing failed",
                extra={
                    "session_id": mask_session_id(request.session_id),
                    "query_id": query_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

            if isinstance(e, QueryProcessingError):
                raise
            raise QueryProcessingError(
                f"Query processing failed: {e}",
                context={
                    "session_id": mask_session_id(request.session_id),
                    "query_id": query_id,
                    "request": {**request.model_dump(), "session_id": mask_session_id(request.session_id)},
                    "error": str(e),
                },
            ) from e

    async def _execute_query_processing(
        self,
        request: AgentRequest,
        execution_context: ExecutionContext,
    ) -> AgentResponse:
        """Execute the core query processing workflow.

        Args:
            request: Query request to process
            execution_context: Execution context for workflow management

        Returns:
            Query response from processing
        """
        # Use the query processor to handle the complete processing
        if self._query_orchestrator is None:
            raise QueryProcessingError(
                "Query processor is not initialized",
                context={"execution_context": execution_context},
            )
        result = await self._query_orchestrator.process_query(request)
        return cast(AgentResponse, result)

    async def process_query_stream(
        self,
        request: AgentRequest,
        execution_strategy: ExecutionStrategy = ExecutionStrategy.STANDARD,
    ) -> AsyncGenerator[dict[str, Any]]:
        if not self._initialized:
            raise AgentServiceError(
                "Agent service is not initialized. Call initialize() first.",
                context={"service_state": "not_initialized"},
            )

        if self._shutdown_event.is_set():
            raise AgentServiceError(
                "Agent service is shutting down, cannot process new queries",
                context={"service_state": "shutting_down"},
            )

        query_id = f"query_stream_{hash(request.query)}_{int(time.time() * 1000)}"

        logger.info(
            "Processing streaming query request",
            extra={
                "session_id": mask_session_id(request.session_id),
                "query_id": query_id,
                "execution_strategy": execution_strategy.value,
            },
        )

        if self._lifecycle_manager is None:
            raise AgentServiceError(
                "Lifecycle manager is not initialized",
                context={"service_state": "invalid_lifecycle_manager"},
            )

        async with self._lifecycle_manager.create_execution_context(
            request=request,
            strategy=execution_strategy,
            timeout_ms=30000,
        ):
            if self._query_orchestrator is None:
                raise QueryProcessingError(
                    "Query processor is not initialized",
                    context={"query_id": query_id},
                )

            async for event in self._query_orchestrator.process_query_stream(request):
                yield event

    async def get_service_health(self) -> dict[str, Any]:
        """Get health status of the agent service and its components.

        Returns:
            Dictionary with service health information
        """
        try:
            health_status = {
                "service_initialized": self._initialized,
                "shutdown_requested": self._shutdown_event.is_set(),
                "active_queries_count": len(self._active_queries),
                "components": {},
            }

            if self._initialized:
                # Check component health
                health_status["components"] = {
                    "agent_factory": self._agent_factory is not None,
                    "tool_registry": self._tool_registry is not None,
                    "query_processor": self._query_orchestrator is not None,
                    "chat_history_manager": self._chat_historian is not None,
                    "response_processor": self._response_processor is not None,
                    "lifecycle_manager": self._lifecycle_manager is not None,
                }

                # Add tool registry statistics if available
                if self._tool_registry:
                    try:
                        # Check if the registry has statistics method
                        if hasattr(self._tool_registry, "get_registry_statistics"):
                            registry_stats = self._tool_registry.get_registry_statistics()
                            health_status["tool_registry_stats"] = registry_stats
                        else:
                            # Fallback to basic registry info
                            tools = self._tool_registry.get_available_tools()
                            health_status["tool_registry_stats"] = {
                                "total_tools": len(tools),
                                "status": "basic_stats",
                            }
                    except Exception as e:
                        health_status["tool_registry_error"] = str(e)

            return health_status

        except Exception as e:
            logger.error(
                "Failed to get service health",
                extra={"error": str(e)},
            )
            return {
                "error": str(e),
                "service_initialized": self._initialized,
                "status": "health_check_failed",
            }

    async def register_tools_from_directory(self, directory_path: str) -> None:
        """Register tools from a directory for use by agents.

        Args:
            directory_path: Path to directory containing tool definitions

        Raises:
            AgentServiceError: If service is not initialized
            ToolRegistrationError: If tool registration fails
        """
        if not self._initialized:
            raise AgentServiceError(
                "Agent service is not initialized. Call initialize() first.",
                context={"service_state": "not_initialized"},
            )

        try:
            logger.info(
                "Loading tools from directory",
                extra={"directory": directory_path},
            )

            if self._tool_registry is None:
                raise AgentServiceError(
                    "Tool registry is not initialized",
                    context={"service_state": "invalid_tool_registry"},
                )
            await asyncio.to_thread(
                self._tool_registry.load_tools_from_directory,
                directory_path,
            )

            logger.info(
                "Tools loaded successfully from directory",
                extra={"directory": directory_path},
            )

        except Exception as e:
            logger.error(
                "Failed to load tools from directory",
                extra={
                    "directory": directory_path,
                    "error": str(e),
                },
            )
            if isinstance(e, ToolRegistrationError):
                raise
            raise ToolRegistrationError(
                "directory_loading",
                f"Failed to load tools from directory: {e}",
                context={"directory": directory_path, "error": str(e)},
            ) from e

    @asynccontextmanager
    async def service_lifecycle(self) -> AsyncGenerator[Self]:
        """Context manager for service lifecycle management.

        This provides automatic initialization and cleanup of the service.
        """
        try:
            await self.initialize()
            yield self
        finally:
            await self.shutdown()


def create_agent_service(container: DependencyContainer) -> AgentService:
    """Factory function to create AgentService with dependencies from container.

    Resolves all protocol dependencies from the container and injects them
    into AgentService via constructor. This enables teams to swap implementations
    by changing registrations in ``application/factory.py``.

    Args:
        container: Dependency injection container with registered protocols

    Returns:
        Configured AgentService instance ready for initialization

    Note:
        The returned service requires :meth:`AgentService.initialize` to be called
        before processing queries. Use :meth:`AgentService.service_lifecycle` for
        automatic lifecycle management.
    """
    return AgentService(
        container=container,
        agent_factory=container.resolve(AgentFactory),
        tool_registry=container.resolve(AgentToolRegistry),
        query_processor=container.resolve(QueryProcessor),
        chat_historian=container.resolve(ChatHistoryManager),
        response_processor=container.resolve(ResponseProcessor),
    )
