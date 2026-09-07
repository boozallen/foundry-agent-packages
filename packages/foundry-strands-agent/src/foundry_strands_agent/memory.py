# SPDX-License-Identifier: Apache-2.0
"""Optional, scope-bound memory tools composed into a Foundry agent.

Clients belong to the composition root. Providers neither infer identity from a
chat session nor own the caller's network-client lifecycle.
"""

from collections.abc import Sequence
from importlib import import_module
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field, StringConstraints

from foundry_strands_agent.protocols.agent_factory import ToolFunction


class MemoryToolProvider(Protocol):
    """Supply memory tools already bound to a server-authorized memory scope.

    Implementations may share a client across agent instances. The composition
    root must keep that client alive until all agents using it have finished.
    """

    def get_tools(self) -> Sequence[ToolFunction]:
        """Return tools without performing memory reads or writes."""
        ...


class HindsightMemoryConfig(BaseModel):
    """Bounded, immutable capabilities for one authorized Hindsight bank.

    A bank may span multiple chat sessions. It must be selected by trusted
    application configuration or authorization logic, never by the model.
    """

    model_config = {"frozen": True, "extra": "forbid", "strict": True}

    bank_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")] = Field(
        description="Server-authorized bank, independent of the conversation session ID."
    )
    budget: Literal["low", "mid", "high"] = Field(default="low", description="Recall and reflection budget.")
    max_tokens: int = Field(default=2048, ge=1, le=32768, description="Maximum tokens returned by recall.")
    enable_retain: bool = Field(default=False, description="Explicitly allow the agent to write memories.")
    enable_reflect: bool = Field(default=True, description="Expose reflection as well as recall.")


class HindsightMemoryProvider:
    """Adapt Hindsight's official Strands tools to Foundry's provider contract.

    Install ``foundry-strands-agent[hindsight]`` to use this optional adapter.
    Pass a caller-owned client facade with thread-safe Hindsight methods.
    The locked upstream sync client needs thread affinity; see the live example. This provider does
    not close it, mutate Hindsight's global settings, or automatically retain
    conversations. Memory content is untrusted tool data, not system policy.
    """

    def __init__(self, config: HindsightMemoryConfig, *, client: Any) -> None:
        """Bind the official tools to an authorized bank and caller-owned client."""
        if client is None:
            raise ValueError("A caller-owned Hindsight client is required")
        try:
            integration = import_module("hindsight_strands")
        except ImportError as error:
            raise ImportError("Install foundry-strands-agent[hindsight] to enable Hindsight memory") from error
        # Explicit options prevent process-global Hindsight settings from
        # changing this provider's bank, capabilities, budget, or tag filters.
        self._tools: tuple[ToolFunction, ...] = tuple(
            integration.create_hindsight_tools(
                client=client,
                bank_id=config.bank_id,
                budget=config.budget,
                max_tokens=config.max_tokens,
                enable_retain=config.enable_retain,
                enable_recall=True,
                enable_reflect=config.enable_reflect,
                tags=[],
                recall_tags=[],
                recall_tags_match="any",
            )
        )

    def get_tools(self) -> Sequence[ToolFunction]:
        """Return the same bound tools without client allocation or network I/O."""
        return self._tools
