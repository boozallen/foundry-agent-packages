# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""StrandsAgentBackend — AgentBackend protocol implementation for Strands SDK.

This module provides the concrete AgentBackend implementation that bridges
the framework-agnostic protocol surface (AgentRequest/AgentResponse) to the
Strands-specific query orchestration pipeline.
"""

import logging
import time

from foundry_agent_config import ConfigurationError as ConfigConfigurationError
from foundry_agent_core import (
    AgentRequest,
    AgentResponse,
    DependencyContainer,
    QueryProcessingError,
    QueryProcessor,
    ResponseProcessor,
    mask_session_id,
)
from foundry_agent_core import (
    ConfigurationError as CoreConfigurationError,
)
from foundry_strands_agent.config.models import AgentConfig
from foundry_strands_agent.orchestrator import create_query_processor
from foundry_strands_agent.protocols import AgentFactory, AgentToolRegistry
from foundry_strands_agent.response_processor import create_response_processor

logger = logging.getLogger(__name__)


class StrandsAgentBackend:
    """AgentBackend implementation backed by the Strands SDK.

    Satisfies the AgentBackend protocol from foundry-agent-core via
    structural subtyping. Maps AgentRequest to internal QueryRequest,
    delegates to QueryOrchestrator, and returns AgentResponse.
    """

    def __init__(
        self,
        container: DependencyContainer,
        *,
        agent_name: str | None = None,
        agent_description: str | None = None,
    ) -> None:
        try:
            self._container = container

            config = container.resolve(AgentConfig)
            self._name = agent_name or config.agent_name
            self._description = agent_description or config.agent_description

            agent_factory = container.resolve(AgentFactory)
            tool_registry = container.resolve(AgentToolRegistry)
            response_processor: ResponseProcessor = create_response_processor()

            self._query_processor: QueryProcessor = create_query_processor(
                container, agent_factory, tool_registry, response_processor
            )
        except ConfigConfigurationError as e:
            raise CoreConfigurationError(
                e.message,
                context=e.context,
            ) from e

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def process_message(self, request: AgentRequest) -> AgentResponse:
        """Process an agent request through the Strands query pipeline.

        Args:
            request: Framework-agnostic agent request.

        Returns:
            Framework-agnostic agent response.

        Raises:
            QueryProcessingError: If query processing fails.
        """
        start_time = time.time()

        logger.info(
            "StrandsAgentBackend processing message",
            extra={
                "session_id": mask_session_id(request.session_id),
                "query_preview": request.query[:100] + "..." if len(request.query) > 100 else request.query,
            },
        )

        try:
            response = await self._query_processor.process_query(request)

            logger.info(
                "StrandsAgentBackend message processed",
                extra={
                    "session_id": mask_session_id(request.session_id),
                    "processing_time_ms": (time.time() - start_time) * 1000,
                },
            )

            return response

        except QueryProcessingError:
            raise
        except Exception as e:
            raise QueryProcessingError(
                f"StrandsAgentBackend processing failed: {e}",
                context={
                    "session_id": mask_session_id(request.session_id),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            ) from e
