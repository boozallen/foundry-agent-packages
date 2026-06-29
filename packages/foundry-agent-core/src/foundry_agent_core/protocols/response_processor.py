# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Response processor protocol for agent response transformation.

This module defines the ResponseProcessor protocol for transforming raw
agent responses into domain AgentResponse objects.
"""

from abc import abstractmethod
from typing import Any, Protocol

from foundry_agent_core.types import AgentRequest, AgentResponse


class ResponseProcessor(Protocol):
    """Protocol for processing raw agent responses into domain objects.

    Teams can implement this protocol to customize response processing:
    - Response text extraction and cleaning
    - Source/chunk extraction from agent metadata
    - Confidence scoring algorithms

    For quality validation, use agent-evals scorers instead.

    Example (swapping implementation):
        container.register_factory(
            ResponseProcessor,
            lambda: MyCustomResponseProcessor()
        )
    """

    @abstractmethod
    async def process_response(
        self,
        agent_response: Any,
        request: AgentRequest,
        start_time: float,
        query_id: str,
    ) -> AgentResponse:
        """Transform raw agent response into AgentResponse.

        Args:
            agent_response: Raw response from agent framework
            request: Original agent request
            start_time: Processing start time (for timing)
            query_id: Unique identifier for this query

        Returns:
            AgentResponse with content, processing time, metadata
        """
        ...
