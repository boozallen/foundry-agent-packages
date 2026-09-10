# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for foundry-agent-config load_config."""

from pathlib import Path

import pytest
from pydantic import BaseModel

import foundry_agent_config
from foundry_agent_config import ConfigurationError, load_config


def test_import():
    assert foundry_agent_config is not None


# --- Test fixtures ---


class SimpleConfig(BaseModel):
    name: str = "default"
    port: int = 8000
    debug: bool = False


class NestedConfig(BaseModel):
    class ModelConfig(BaseModel):
        provider: str = "bedrock"
        model_id: str = "claude"

    model: ModelConfig = ModelConfig()
    name: str = "agent"


class ListConfig(BaseModel):
    tools: list[str] = []
    name: str = "agent"


class AmbiguousConfig(BaseModel):
    """Config with both flat underscored field and nested path."""

    session_manager_type: str = "none"

    class Session(BaseModel):
        manager_type: str = "none"

    session: Session = Session()


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(content)
    return p


# --- AC1: Env var overrides YAML value ---


def test_ac1_env_var_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = _write_yaml(tmp_path, "name: from_yaml\nport: 3000\n")
    monkeypatch.setenv("TEST__NAME", "from_env")

    config = load_config(SimpleConfig, yaml_path, "TEST")

    assert config.name == "from_env"
    assert config.port == 3000


def test_ac1_nested_env_var_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = _write_yaml(tmp_path, "model:\n  provider: bedrock\n  model_id: claude\nname: agent\n")
    monkeypatch.setenv("TEST__MODEL__PROVIDER", "ollama")

    config = load_config(NestedConfig, yaml_path, "TEST")

    assert config.model.provider == "ollama"
    assert config.model.model_id == "claude"


# --- AC2: YAML-only loading ---


def test_ac2_yaml_only(tmp_path: Path) -> None:
    yaml_path = _write_yaml(tmp_path, "name: my_agent\nport: 9090\ndebug: true\n")

    config = load_config(SimpleConfig, yaml_path, "TEST")

    assert config.name == "my_agent"
    assert config.port == 9090
    assert config.debug is True


# --- AC3: JSON-encoded list override ---


def test_ac3_json_list_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = _write_yaml(tmp_path, 'tools:\n  - "a"\n  - "b"\nname: agent\n')
    monkeypatch.setenv("TEST__TOOLS", '["c", "d"]')

    config = load_config(ListConfig, yaml_path, "TEST")

    assert config.tools == ["c", "d"]


# --- AC4: Invalid YAML / invalid Pydantic ---


def test_ac4_invalid_yaml(tmp_path: Path) -> None:
    yaml_path = _write_yaml(tmp_path, ":\n  bad: yaml: [invalid\n")

    with pytest.raises(ConfigurationError, match="Invalid YAML"):
        load_config(SimpleConfig, yaml_path, "TEST")


def test_ac4_invalid_pydantic_value(tmp_path: Path) -> None:
    yaml_path = _write_yaml(tmp_path, "name: valid\nport: not_a_number\n")

    with pytest.raises(ConfigurationError, match="validation failed"):
        load_config(SimpleConfig, yaml_path, "TEST")


def test_ac4_file_not_found() -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_config(SimpleConfig, Path("/nonexistent/config.yaml"), "TEST")


# --- AC6: Double-underscore disambiguation ---


def test_ac6_flat_vs_nested_disambiguation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = _write_yaml(tmp_path, "session_manager_type: none\nsession:\n  manager_type: none\n")
    monkeypatch.setenv("TEST__SESSION_MANAGER_TYPE", "file")
    monkeypatch.setenv("TEST__SESSION__MANAGER_TYPE", "s3")

    config = load_config(AmbiguousConfig, yaml_path, "TEST")

    assert config.session_manager_type == "file"
    assert config.session.manager_type == "s3"


# --- Edge cases ---


def test_bool_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = _write_yaml(tmp_path, "name: agent\nport: 8000\ndebug: false\n")
    monkeypatch.setenv("TEST__DEBUG", "true")

    config = load_config(SimpleConfig, yaml_path, "TEST")

    assert config.debug is True


def test_empty_yaml(tmp_path: Path) -> None:
    yaml_path = _write_yaml(tmp_path, "")

    config = load_config(SimpleConfig, yaml_path, "TEST")

    assert config.name == "default"
    assert config.port == 8000


def test_empty_prefix_ignores_env_vars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = _write_yaml(tmp_path, "name: from_yaml\nport: 3000\n")
    monkeypatch.setenv("TEST__NAME", "from_env")

    config = load_config(SimpleConfig, yaml_path, "")

    assert config.name == "from_yaml"
    assert config.port == 3000


# --- Type-aware coercion ---


def test_comma_separated_list_coercion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """list[str] fields are split on commas from env vars."""
    yaml_path = _write_yaml(tmp_path, "tools: []\nname: agent\n")
    monkeypatch.setenv("TEST__TOOLS", "tool_a, tool_b, tool_c")

    config = load_config(ListConfig, yaml_path, "TEST")

    assert config.tools == ["tool_a", "tool_b", "tool_c"]


def test_int_coercion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Int fields are coerced from string env vars."""
    yaml_path = _write_yaml(tmp_path, "name: agent\nport: 3000\n")
    monkeypatch.setenv("TEST__PORT", "9090")

    config = load_config(SimpleConfig, yaml_path, "TEST")

    assert config.port == 9090


def test_float_coercion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Float fields are coerced from string env vars."""

    class FloatConfig(BaseModel):
        temperature: float = 0.3

    yaml_path = _write_yaml(tmp_path, "temperature: 0.3\n")
    monkeypatch.setenv("TEST__TEMPERATURE", "0.9")

    config = load_config(FloatConfig, yaml_path, "TEST")

    assert config.temperature == 0.9


def test_bool_coercion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bool fields are coerced from string env vars."""
    yaml_path = _write_yaml(tmp_path, "name: agent\nport: 8000\ndebug: false\n")
    monkeypatch.setenv("TEST__DEBUG", "yes")

    config = load_config(SimpleConfig, yaml_path, "TEST")

    assert config.debug is True
