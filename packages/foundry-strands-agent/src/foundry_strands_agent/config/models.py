# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Agent configuration data models.

This module provides data model classes for agent configuration.
Config loading is powered by `foundry-agent-config`'s `load_config`,
which supports YAML files with environment variable overrides.
"""

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Self

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from foundry_agent_config import load_config
from foundry_agent_core import InvalidConfigurationError

_MAX_NAME_LEN = 128
_MAX_DESCRIPTION_LEN = 1024
_MAX_VERSION_LEN = 32
_MAX_PROVIDER_LEN = 32
_MAX_MODEL_ID_LEN = 256
_MAX_URL_LEN = 512
_MAX_API_KEY_LEN = 256
_MAX_REGION_LEN = 64
_MAX_PROMPT_LEN = 16384
_MAX_MODULES = 64
_MAX_PATHS = 64
_MAX_ENTRY_LEN = 512
_MAX_KB_ID_LEN = 128
_MAX_SESSION_ID_LEN = 128
_MAX_BUCKET_LEN = 128
_MAX_PREFIX_LEN = 256
_MAX_SERVERS = 32
_MAX_LOG_LEVEL_LEN = 16
_MAX_PORT = 65535
_MAX_CONVERSATION_LENGTH = 1000
_MAX_CONVERSATION_WINDOW_SIZE = 1000
_MAX_QUERY_LENGTH = 8192
_MAX_RESPONSE_TIME_MS = 86_400_000  # 24h
_MAX_AGENT_STATE_KEYS = 128
_MAX_AGENT_STATE_KEY_LEN = 128
_MAX_AGENT_STATE_BYTES = 1_048_576

_BoundedName = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_NAME_LEN, strip_whitespace=True)]
_BoundedDescription = Annotated[
    str, StringConstraints(min_length=1, max_length=_MAX_DESCRIPTION_LEN, strip_whitespace=True)
]
_BoundedVersion = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_VERSION_LEN, strip_whitespace=True)]
_BoundedUrl = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_URL_LEN, strip_whitespace=True)]
_BoundedOptionalUrl = _BoundedUrl | None


class StrandsSessionManagerType(StrEnum):
    FILE = "file"
    S3 = "s3"


class ModelGuardrailConfig(BaseModel):
    """Configuration for model guardrail settings."""

    model_config = {"frozen": True}

    guardrail_id: Annotated[str, StringConstraints(min_length=1, max_length=128, strip_whitespace=True)]
    guardrail_version: Annotated[str, StringConstraints(min_length=1, max_length=64, strip_whitespace=True)]
    guardrail_trace: Annotated[str, StringConstraints(min_length=1, max_length=32, strip_whitespace=True)] | None = (
        "enabled"
    )


class AgentModelConfig(BaseModel):
    """Configuration for Strands Agent model settings."""

    model_config = {"frozen": True}

    provider: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_PROVIDER_LEN, strip_whitespace=True)] = (
        "bedrock"
    )
    model_id: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_MODEL_ID_LEN, strip_whitespace=True)] = (
        "us.anthropic.claude-sonnet-4-20250514-v1:0"
    )
    ollama_url: _BoundedOptionalUrl = None
    llamacpp_url: _BoundedOptionalUrl = None
    nims_base_url: _BoundedOptionalUrl = None
    nims_api_key: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_API_KEY_LEN, strip_whitespace=True)] | None
    ) = None
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32_768)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    streaming: bool = True
    region_name: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_REGION_LEN, strip_whitespace=True)] | None
    ) = None
    guardrails: ModelGuardrailConfig | None = None


class StrandsAgentConfig(BaseModel):
    """Complete configuration for Strands Agent instances.

    Contains model settings, system prompt, tool configuration, and
    environment-specific settings for agent query processing.

    Load via `load_config(StrandsAgentConfig, yaml_path, "STRANDS")` for
    YAML+env configuration, or `StrandsAgentConfig.from_env()` for
    environment-only backward compatibility.
    """

    model_config = {"frozen": True}

    model: AgentModelConfig = Field(default_factory=AgentModelConfig)

    agent_name: _BoundedName = "strands-base-agent"
    agent_description: _BoundedDescription = "A general-purpose AI agent powered by AWS Strands Agent framework"
    agent_version: _BoundedVersion = "1.0"
    agent_port: int | None = Field(default=None, ge=1, le=_MAX_PORT)

    system_prompt: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_PROMPT_LEN)] = (
        "You are a helpful AI assistant powered by the AWS Strands Agent framework. "
        "You assist users by leveraging available tools and capabilities to provide "
        "accurate, helpful responses to their queries and tasks."
    )
    tools_modules: list[
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_ENTRY_LEN, strip_whitespace=True)]
    ] = Field(default_factory=list, max_length=_MAX_MODULES)
    tools_files: list[
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_ENTRY_LEN, strip_whitespace=True)]
    ] = Field(default_factory=list, max_length=_MAX_PATHS)
    max_conversation_length: int = Field(default=10, ge=1, le=_MAX_CONVERSATION_LENGTH)
    enable_memory: bool = False
    knowledge_base_id: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_KB_ID_LEN, strip_whitespace=True)] | None
    ) = None

    session_id: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_SESSION_ID_LEN, strip_whitespace=True)] | None
    ) = None
    session_type: StrandsSessionManagerType | None = None
    session_storage_dir: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_ENTRY_LEN, strip_whitespace=True)] | None
    ) = None
    session_s3_bucket: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_BUCKET_LEN, strip_whitespace=True)] | None
    ) = None
    session_s3_prefix: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_PREFIX_LEN, strip_whitespace=True)] | None
    ) = None

    conversation_window_size: int = Field(default=100, ge=1, le=_MAX_CONVERSATION_WINDOW_SIZE)
    conversation_truncate_results: bool = False
    agent_state_initial_values: dict[str, Any] = Field(default_factory=dict)

    mcp_servers: list[dict[str, Any]] = Field(default_factory=list, max_length=_MAX_SERVERS)
    a2a_servers: list[dict[str, Any]] = Field(default_factory=list, max_length=_MAX_SERVERS)

    log_level: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_LOG_LEVEL_LEN, strip_whitespace=True)] = (
        "INFO"
    )
    max_query_length: int = Field(default=2000, ge=1, le=_MAX_QUERY_LENGTH)
    default_similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_response_time_ms: int = Field(default=30000, ge=1, le=_MAX_RESPONSE_TIME_MS)
    observability_enabled: bool = False

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str | None) -> str | None:
        if v is not None and v.strip() == "":
            raise InvalidConfigurationError("session_id", v, "cannot be empty or whitespace")
        return v

    @field_validator("session_type", mode="before")
    @classmethod
    def coerce_session_type(cls, v: Any) -> StrandsSessionManagerType | None:
        if v is None:
            return None
        if isinstance(v, StrandsSessionManagerType):
            return v
        try:
            return StrandsSessionManagerType(str(v).lower())
        except ValueError as e:
            raise InvalidConfigurationError("session_type", v, "must be one of: 'file', 's3'") from e

    @field_validator("conversation_window_size")
    @classmethod
    def validate_conversation_window_size(cls, v: int) -> int:
        if v <= 0:
            raise InvalidConfigurationError(
                "conversation_window_size", v, "conversation_window_size must be a positive integer"
            )
        return v

    @field_validator("agent_state_initial_values")
    @classmethod
    def validate_agent_state_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > _MAX_AGENT_STATE_KEYS:
            raise InvalidConfigurationError(
                "agent_state_initial_values",
                v,
                f"agent_state_initial_values exceeds {_MAX_AGENT_STATE_KEYS} top-level keys",
            )
        for key in v:
            if len(key) > _MAX_AGENT_STATE_KEY_LEN:
                raise InvalidConfigurationError(
                    "agent_state_initial_values",
                    v,
                    f"agent_state_initial_values key exceeds {_MAX_AGENT_STATE_KEY_LEN} characters",
                )

        state_json_size = len(json.dumps(v, default=str).encode("utf-8"))
        if state_json_size > _MAX_AGENT_STATE_BYTES:
            size_error = (
                f"agent_state_initial_values JSON size ({state_json_size} bytes) exceeds {_MAX_AGENT_STATE_BYTES} bytes"
            )
            raise InvalidConfigurationError(
                "agent_state_initial_values",
                v,
                size_error,
            )
        return v

    @model_validator(mode="after")
    def validate_cross_field_constraints(self) -> Self:
        if self.enable_memory and not self.knowledge_base_id:
            raise InvalidConfigurationError(
                "knowledge_base_id", None, "knowledge_base_id is required when enable_memory is True"
            )
        if self.session_type is StrandsSessionManagerType.S3:
            if not self.session_s3_bucket or self.session_s3_bucket.strip() == "":
                raise InvalidConfigurationError(
                    "session_s3_bucket",
                    self.session_s3_bucket,
                    "session_s3_bucket is required when session_type is 's3'",
                )
        return self

    @classmethod
    def from_env(cls) -> Self:
        """Create config from environment variables (backward compatibility).

        Constructs a StrandsAgentConfig using STRANDS_* environment variables
        with sensible defaults. No YAML file required.
        """
        model = AgentModelConfig(
            provider=os.getenv("STRANDS_MODEL_PROVIDER", "bedrock").lower(),
            model_id=os.getenv("STRANDS_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"),
            ollama_url=os.getenv("OLLAMA_URL", "http://host.docker.internal:11434"),
            llamacpp_url=os.getenv("LLAMACPP_URL", "http://localhost:8080"),
            nims_base_url=os.getenv("NIMS_BASE_URL"),
            nims_api_key=os.getenv("NIMS_API_KEY"),
            temperature=float(os.getenv("STRANDS_TEMPERATURE", "0.3")),
            max_tokens=int(v) if (v := os.getenv("STRANDS_MAX_TOKENS")) else None,
            top_p=float(v) if (v := os.getenv("STRANDS_TOP_P")) else None,
            streaming=os.getenv("STRANDS_STREAMING", "true").lower() == "true",
            region_name=os.getenv("AWS_DEFAULT_REGION"),
            guardrails=ModelGuardrailConfig(
                guardrail_id=os.getenv("STRANDS_GUARDRAIL_ID", ""),
                guardrail_version=os.getenv("STRANDS_GUARDRAIL_VERSION", ""),
                guardrail_trace=os.getenv("STRANDS_GUARDRAIL_TRACE"),
            )
            if os.getenv("STRANDS_GUARDRAIL_ID")
            else None,
        )

        tools_modules_env = os.getenv("STRANDS_TOOLS_MODULES", "")
        tools_files_env = os.getenv("STRANDS_TOOLS_FILES", "")

        mcp_servers: list[dict[str, Any]] = []
        if mcp_env := os.getenv("STRANDS_MCP_SERVERS"):
            mcp_servers = json.loads(mcp_env)

        a2a_servers: list[dict[str, Any]] = []
        if a2a_env := os.getenv("STRANDS_A2A_AGENTS"):
            a2a_servers = json.loads(a2a_env)

        raw_session_type = os.getenv("STRANDS_SESSION_MANAGER_TYPE")
        session_type: StrandsSessionManagerType | None = None
        if raw_session_type is not None:
            session_type = StrandsSessionManagerType(str(raw_session_type).lower())

        agent_state_initial_values: dict[str, Any] = {}
        if state_env := os.getenv("STRANDS_AGENT_STATE_INITIAL_VALUES"):
            agent_state_initial_values = json.loads(state_env)

        return cls(
            model=model,
            agent_name=os.getenv("STRANDS_AGENT_NAME", "strands-base-agent"),
            agent_description=os.getenv(
                "STRANDS_AGENT_DESCRIPTION",
                "A general-purpose AI agent powered by AWS Strands Agent framework",
            ),
            agent_version=os.getenv("STRANDS_AGENT_VERSION", "1.0"),
            agent_port=int(v) if (v := os.getenv("STRANDS_AGENT_PORT")) else None,
            system_prompt=os.getenv(
                "STRANDS_SYSTEM_PROMPT",
                (
                    "You are a helpful AI assistant powered by the AWS Strands Agent framework. "
                    "You assist users by leveraging available tools and capabilities to provide "
                    "accurate, helpful responses to their queries and tasks."
                ),
            ),
            tools_modules=[t.strip() for t in tools_modules_env.split(",") if t.strip()],
            tools_files=[t.strip() for t in tools_files_env.split(",") if t.strip()],
            max_conversation_length=int(os.getenv("STRANDS_MAX_CONVERSATION_LENGTH", "10")),
            enable_memory=os.getenv("STRANDS_ENABLE_MEMORY", "false").lower() == "true",
            knowledge_base_id=os.getenv("STRANDS_KNOWLEDGE_BASE_ID"),
            mcp_servers=mcp_servers,
            a2a_servers=a2a_servers,
            session_id=os.getenv("STRANDS_SESSION_ID"),
            session_type=session_type,
            session_storage_dir=os.getenv("STRANDS_SESSION_STORAGE_DIR"),
            session_s3_bucket=os.getenv("STRANDS_SESSION_S3_BUCKET"),
            session_s3_prefix=os.getenv("STRANDS_SESSION_S3_PREFIX"),
            conversation_window_size=int(os.getenv("STRANDS_CONVERSATION_WINDOW_SIZE", "100")),
            conversation_truncate_results=os.getenv("STRANDS_CONVERSATION_TRUNCATE_RESULTS", "false").lower() == "true",
            agent_state_initial_values=agent_state_initial_values,
            log_level=os.getenv("STRANDS_LOG_LEVEL", "INFO").upper(),
            max_query_length=int(os.getenv("STRANDS_MAX_QUERY_LENGTH", "2000")),
            default_similarity_threshold=float(os.getenv("STRANDS_DEFAULT_SIMILARITY_THRESHOLD", "0.7")),
            max_response_time_ms=int(os.getenv("STRANDS_MAX_RESPONSE_TIME_MS", "30000")),
            observability_enabled=os.getenv("STRANDS_O11Y_ENABLED", "false").lower() == "true",
        )

    @classmethod
    def from_yaml(cls, yaml_path: Path, env_prefix: str = "STRANDS") -> Self:
        """Load config from YAML file with environment variable overrides.

        This is the recommended loading path. Uses `load_config` from
        `foundry-agent-config` under the hood.

        Args:
            yaml_path: Path to YAML configuration file
            env_prefix: Environment variable prefix (default: "STRANDS")

        Returns:
            Validated StrandsAgentConfig instance

        Raises:
            foundry_agent_config.ConfigurationError: If loading or validation fails
        """
        return load_config(cls, yaml_path, env_prefix)


AgentConfig = StrandsAgentConfig
