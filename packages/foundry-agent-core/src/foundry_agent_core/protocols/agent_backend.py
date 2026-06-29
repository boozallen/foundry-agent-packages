# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Agent backend protocol for pluggable agent implementations.

This module defines the AgentBackend protocol — the central abstraction
enabling any agent framework to plug into shared infrastructure.
"""

from abc import abstractmethod
from typing import Protocol

from foundry_agent_core.types import AgentRequest, AgentResponse


class AgentBackend(Protocol):
    """Protocol for agent backend implementations.

    Session ownership is stateless: session_id is passed per call on
    AgentRequest; the backend handles lookup and creation internally.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    async def process_message(
        self,
        request: AgentRequest,
    ) -> AgentResponse: ...
