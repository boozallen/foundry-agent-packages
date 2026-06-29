# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Query orchestration implementation for agent-driven query processing.

This module implements the QueryProcessor protocol, providing orchestration
for agent-driven autonomous execution with infrastructure coordination
and response handling.
"""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from strands import Agent

from foundry_agent_core import (
    AgentRequest,
    AgentResponse,
    DependencyContainer,
    QueryProcessingError,
    QueryProcessor,
    QueryTimeoutError,
    ResponseProcessor,
    mask_session_id,
)
from foundry_strands_agent.config.models import StrandsAgentConfig
from foundry_strands_agent.protocols import (
    AgentFactory,
    AgentToolRegistry,
)
from foundry_strands_agent.types import QueryRequest

logger = logging.getLogger(__name__)


class QueryOrchestrator(QueryProcessor):
    """Implementation of QueryProcessor for agent-driven query processing.

    This orchestrator coordinates infrastructure support for autonomous agent execution,
    manages query preprocessing, agent interaction, and response handling while
    respecting agent autonomy over tool selection and execution decisions.
    """

    def __init__(
        self,
        container: DependencyContainer,
        agent_factory: AgentFactory,
        tool_registry: AgentToolRegistry,
        response_processor: ResponseProcessor,
    ) -> None:
        """Initialize query orchestrator with dependencies.

        Args:
            container: Dependency injection container for infrastructure components
            agent_factory: Factory for creating configured agent instances
            tool_registry: Registry containing available tools for agents
            response_processor: Processor for transforming agent responses
        """
        self._container = container
        self._agent_factory = agent_factory
        self._tool_registry = tool_registry
        self._response_processor = response_processor
        self._config = StrandsAgentConfig.from_env()

    async def process_query(self, request: AgentRequest) -> AgentResponse:
        """Process a complete query from request to response.

        Coordinates infrastructure support for agent autonomous execution:
        1. Validates and preprocesses the query request
        2. Creates agent with registered tools (agent maintains autonomy)
        3. Executes agent processing with infrastructure support
        4. Handles response validation and transformation

        Args:
            request: Agent request with query parameters

        Returns:
            Agent response with generated answer and metadata

        Raises:
            QueryProcessingError: If query processing fails at any stage
        """
        start_time = time.time()
        query_id = f"query_{int(start_time * 1000)}"

        logger.info(
            "Starting query processing",
            extra={
                "session_id": mask_session_id(request.session_id),
                "query_id": query_id,
                "query": (request.query[:100] + "..." if len(request.query) > 100 else request.query),
            },
        )

        try:
            # Step 1: Map AgentRequest to internal QueryRequest for preprocessing
            internal_request = self._to_internal_request(request)
            validated_request = await self._preprocess_query(internal_request, query_id)

            # Step 2: Create agent with infrastructure context
            async with self._create_agent_context(validated_request, query_id) as agent:
                # Step 3: Execute agent processing (agent maintains full autonomy)
                agent_response = await self._execute_agent_processing(agent, validated_request, query_id)

                # Step 4: Process response via injected processor
                result = await self._response_processor.process_response(agent_response, request, start_time, query_id)

            processing_time = (time.time() - start_time) * 1000
            logger.info(
                "Query processing completed",
                extra={
                    "session_id": mask_session_id(request.session_id),
                    "query_id": query_id,
                    "processing_time_ms": processing_time,
                },
            )

            return result

        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            logger.error(
                "Query processing failed",
                extra={
                    "session_id": mask_session_id(request.session_id),
                    "query_id": query_id,
                    "processing_time_ms": processing_time,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

            if isinstance(e, QueryProcessingError | QueryTimeoutError):
                raise
            raise QueryProcessingError(
                f"Query processing failed: {e}",
                context={
                    "session_id": mask_session_id(request.session_id),
                    "query_id": query_id,
                    "request": {**request.model_dump(), "session_id": mask_session_id(request.session_id)},
                    "processing_time_ms": processing_time,
                    "error": str(e),
                },
            ) from e

    async def process_query_stream(self, request: AgentRequest) -> AsyncGenerator[dict[str, Any]]:
        start_time = time.time()
        query_id = f"query_{int(start_time * 1000)}"

        internal_request = self._to_internal_request(request)
        validated_request = await self._preprocess_query(internal_request, query_id)

        async with self._create_agent_context(validated_request, query_id) as agent:
            collected_chunks: list[str] = []
            emitted_result = False

            try:
                async for event in agent.stream_async(validated_request.query):
                    if isinstance(event, dict) and event.get("type") == "error":
                        raise QueryProcessingError(
                            event.get("message", "Streaming failed"),
                            context={
                                "session_id": mask_session_id(validated_request.session_id),
                                "query_id": query_id,
                                "event": event,
                                "retryable": event.get("retryable", True),
                            },
                        )

                    if not isinstance(event, dict):
                        continue

                    # Stream only model text chunks (skip tool/reasoning/meta events)
                    if isinstance(event.get("data"), str) and event["data"]:
                        text = event["data"]
                        collected_chunks.append(text)
                        yield {"type": "token", "content": text}

                    # Emit explicit final result event
                    if "result" in event:
                        final_text = self._extract_result_text(event["result"]) or "".join(collected_chunks)
                        yield {
                            "type": "result",
                            "content": final_text,
                            "session_id": validated_request.session_id,
                            "query_id": query_id,
                        }
                        emitted_result = True

                if not emitted_result:
                    # Fallback if SDK stream ended without explicit result event
                    yield {
                        "type": "result",
                        "content": "".join(collected_chunks),
                        "session_id": validated_request.session_id,
                        "query_id": query_id,
                    }

                yield {
                    "type": "done",
                    "processing_time_ms": (time.time() - start_time) * 1000,
                    "session_id": validated_request.session_id,
                    "query_id": query_id,
                }

            except Exception as e:
                if isinstance(e, QueryProcessingError):
                    raise
                raise QueryProcessingError(
                    f"Agent stream processing failed: {e}",
                    context={
                        "session_id": mask_session_id(validated_request.session_id),
                        "query_id": query_id,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                ) from e

    def _extract_result_text(self, result: Any) -> str:
        if result is None:
            return ""

        if isinstance(result, str):
            return result

        for attr in ("text", "content", "output"):
            val = getattr(result, attr, None)
            if isinstance(val, str) and val:
                return val

        return str(result)

    def _to_internal_request(self, request: AgentRequest) -> QueryRequest:
        return QueryRequest(
            query=request.query,
            session_id=request.session_id,
            context=request.context,
        )

    async def _preprocess_query(self, request: QueryRequest, query_id: str) -> QueryRequest:
        """Validate and preprocess the query request.

        Args:
            request: Original query request
            query_id: Unique identifier for this query

        Returns:
            Validated and potentially modified query request

        Raises:
            QueryProcessingError: If query validation fails
        """
        try:
            # Validate query length
            if len(request.query) > self._config.max_query_length:
                raise QueryProcessingError(
                    f"Query exceeds maximum length of {self._config.max_query_length} characters",
                    context={
                        "session_id": mask_session_id(request.session_id),
                        "query_id": query_id,
                        "query_length": len(request.query),
                        "max_length": self._config.max_query_length,
                    },
                )

            # Normalize query parameters if needed
            similarity_threshold = (
                request.similarity_threshold
                if request.similarity_threshold is not None
                else self._config.default_similarity_threshold
            )

            # Create normalized request
            normalized_request = QueryRequest(
                session_id=request.session_id,
                query=request.query.strip(),
                context=request.context,
                max_results=min(request.max_results, 100),  # Enforce reasonable limit
                similarity_threshold=similarity_threshold,
                timestamp=request.timestamp,
            )

            logger.debug(
                "Query preprocessing completed",
                extra={
                    "session_id": mask_session_id(request.session_id),
                    "query_id": query_id,
                    "original_query_length": len(request.query),
                    "normalized_query_length": len(normalized_request.query),
                    "max_results": normalized_request.max_results,
                    "similarity_threshold": normalized_request.similarity_threshold,
                },
            )

            return normalized_request

        except Exception as e:
            if isinstance(e, QueryProcessingError):
                raise
            raise QueryProcessingError(
                f"Failed to preprocess query: {e}",
                context={"session_id": mask_session_id(request.session_id), "query_id": query_id, "error": str(e)},
            ) from e

    @asynccontextmanager
    async def _create_agent_context(self, request: QueryRequest, query_id: str) -> AsyncGenerator[Any]:
        """Create and manage agent lifecycle for query processing.

        Args:
            request: Validated query request
            query_id: Unique identifier for this query

        Yields:
            Configured agent instance ready for autonomous execution

        Raises:
            QueryProcessingError: If agent creation fails
        """
        agent = None
        session_id = request.session_id or None
        try:
            logger.debug(
                "Creating agent for query processing",
                extra={"session_id": mask_session_id(session_id), "query_id": query_id},
            )

            # Create agent with tools from registry (agent maintains autonomy over usage)
            config_overrides = {"session_id": session_id} if session_id else {}
            agent = await self._agent_factory.create_agent_with_tool_registry(
                tool_registry=self._tool_registry, config_overrides=config_overrides or None
            )

            logger.info(
                "Agent created successfully - about to yield",
                extra={
                    "session_id": mask_session_id(session_id),
                    "query_id": query_id,
                    "agent_type": type(agent).__name__,
                    "agent_has_stream": hasattr(agent, "stream"),
                    "agent_has_stream_async": hasattr(agent, "stream_async"),
                    "agent_callable": callable(agent),
                },
            )

            yield agent

        except Exception as e:
            logger.error(
                "Failed to create agent",
                extra={
                    "session_id": mask_session_id(session_id),
                    "query_id": query_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise QueryProcessingError(
                f"Failed to create agent for query processing: {e}",
                context={"session_id": mask_session_id(session_id), "query_id": query_id, "error": str(e)},
            ) from e
        finally:
            # Agent cleanup (if needed by Strands framework)
            if agent is not None:
                try:
                    # Attempt graceful cleanup if agent supports it
                    if hasattr(agent, "close"):
                        await agent.close()
                    logger.debug(
                        "Agent cleanup completed",
                        extra={"session_id": mask_session_id(session_id), "query_id": query_id},
                    )
                except Exception as cleanup_error:
                    logger.warning(
                        "Agent cleanup warning",
                        extra={
                            "session_id": mask_session_id(session_id),
                            "query_id": query_id,
                            "cleanup_error": str(cleanup_error),
                        },
                    )

    async def _execute_agent_processing(self, agent: Agent, request: QueryRequest, query_id: str) -> Any:
        """Execute agent processing with timeout and error handling.

        This method provides infrastructure support for agent autonomous execution
        but does not control or interfere with the agent's tool selection decisions.

        Args:
            agent: Configured Strands Agent instance
            request: Validated query request
            query_id: Unique identifier for this query

        Returns:
            Agent response from autonomous execution

        Raises:
            QueryTimeoutError: If processing exceeds timeout
            QueryProcessingError: If agent processing fails
        """
        try:
            logger.debug(
                "Starting agent autonomous execution",
                extra={"session_id": mask_session_id(request.session_id), "query_id": query_id},
            )

            # Execute agent with timeout (agent maintains full autonomy)
            try:
                logger.info(
                    "About to execute agent",
                    extra={
                        "session_id": mask_session_id(request.session_id),
                        "query_id": query_id,
                        "agent_type": type(agent).__name__,
                        "agent_is_dict": isinstance(agent, dict),
                        "agent_str": str(agent)[:100],
                    },
                )

                agent_result = await agent.invoke_async(request.query)

                # The agent_result should be an AgentResult object with content and metrics
                # Create a response structure that matches our expected format
                agent_response = type(
                    "AgentResponse",
                    (),
                    {
                        "content": str(agent_result) if hasattr(agent_result, "__str__") else str(agent_result),
                        "sources": [],  # Will be populated by tools if available
                        "chunks": [],  # Will be populated by tools if available
                        "confidence": 0.8,  # Default confidence, could extract from agent_result.metrics if available
                        "metadata": {"agent_result_type": type(agent_result).__name__},
                    },
                )()
            except TimeoutError as timeout_err:
                raise QueryTimeoutError(
                    self._config.max_response_time_ms,
                    context={
                        "session_id": mask_session_id(request.session_id),
                        "query_id": query_id,
                        "query": request.query,
                    },
                ) from timeout_err

            logger.debug(
                "Agent autonomous execution completed",
                extra={
                    "session_id": mask_session_id(request.session_id),
                    "query_id": query_id,
                    "response_available": agent_response is not None,
                },
            )

            return agent_response

        except Exception as e:
            if isinstance(e, QueryTimeoutError):
                raise
            raise QueryProcessingError(
                f"Agent processing failed: {e}",
                context={
                    "session_id": mask_session_id(request.session_id),
                    "query_id": query_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            ) from e


def create_query_processor(
    container: DependencyContainer,
    agent_factory: AgentFactory,
    tool_registry: AgentToolRegistry,
    response_processor: ResponseProcessor,
) -> QueryProcessor:
    """Factory function to create QueryOrchestrator instance.

    Args:
        container: Dependency injection container
        agent_factory: Factory for creating agents
        tool_registry: Registry containing available tools
        response_processor: Processor for transforming agent responses

    Returns:
        Configured QueryOrchestrator implementation
    """
    return QueryOrchestrator(container, agent_factory, tool_registry, response_processor)
