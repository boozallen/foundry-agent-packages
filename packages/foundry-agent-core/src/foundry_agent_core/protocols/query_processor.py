# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Query processor protocol for agent query orchestration.

This module defines the QueryProcessor protocol for coordinating all services
to process user queries and generate responses using AWS Strands Agent framework.
"""

from abc import abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, Protocol

from foundry_agent_core.types import AgentRequest, AgentResponse


class QueryProcessor(Protocol):
    """Protocol for processing agent queries through the complete pipeline.

    This is the main orchestrator that coordinates infrastructure services
    to support autonomous agent execution and response generation.
    """

    @abstractmethod
    async def process_query(self, request: AgentRequest) -> AgentResponse:
        """Process a complete agent query from request to response.

        Args:
            request: User query request with parameters

        Returns:
            Complete query response with agent-generated answer and context

        Raises:
            QueryProcessingError: If query processing fails at any stage
        """

    @abstractmethod
    def process_query_stream(self, request: AgentRequest) -> AsyncGenerator[dict[str, Any]]:
        """
        Stream query output events from the agent pipeline.

        Yields events like:
        - {"type": "token", "content": "..."}
        - {"type": "done", "processing_time_ms": 123.4, "session_id": "..."}
        """
