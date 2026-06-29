# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Additional edge case tests to increase coverage for foundry-agent-config."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from foundry_agent_config import ConfigurationError, load_config


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(content)
    return p


class SimpleConfig(BaseModel):
    name: str = "default"
    value: str = "default"


class ComplexConfig(BaseModel):
    """Config with nested models and various types."""

    class Database(BaseModel):
        host: str = "localhost"
        port: int = 5432
        settings: dict[str, str] = {}

    database: Database = Database()
    timeout: float = 30.0
    enabled: bool = True


def test_yaml_root_not_dict(tmp_path: Path) -> None:
    """Test error when YAML root is a list instead of dict."""
    yaml_path = _write_yaml(tmp_path, "- item1\n- item2\n")

    with pytest.raises(ConfigurationError, match="YAML root must be a mapping"):
        load_config(SimpleConfig, yaml_path, "TEST")


def test_env_override_with_json_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test dict field override with JSON-encoded environment variable."""
    yaml_path = _write_yaml(tmp_path, "database:\n  host: localhost\n  port: 5432\n")
    monkeypatch.setenv("TEST__DATABASE__SETTINGS", '{"key1": "value1", "key2": "value2"}')

    config = load_config(ComplexConfig, yaml_path, "TEST")

    assert config.database.settings == {"key1": "value1", "key2": "value2"}


def test_env_override_invalid_json_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test dict field override with invalid JSON falls back to string."""
    yaml_path = _write_yaml(tmp_path, "database:\n  host: localhost\n  port: 5432\n  settings: {}\n")
    monkeypatch.setenv("TEST__DATABASE__SETTINGS", "{invalid json}")

    # Should not raise - Pydantic will handle validation
    with pytest.raises(ConfigurationError, match="validation failed"):
        load_config(ComplexConfig, yaml_path, "TEST")


def test_env_override_float_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test float field with invalid string falls back gracefully."""
    yaml_path = _write_yaml(tmp_path, "timeout: 30.0\n")
    monkeypatch.setenv("TEST__TIMEOUT", "not_a_float")

    # Pydantic should reject it
    with pytest.raises(ConfigurationError, match="validation failed"):
        load_config(ComplexConfig, yaml_path, "TEST")


def test_env_override_int_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test int field with invalid string falls back gracefully."""
    yaml_path = _write_yaml(tmp_path, "database:\n  host: localhost\n  port: 5432\n")
    monkeypatch.setenv("TEST__DATABASE__PORT", "not_an_int")

    # Pydantic should reject it
    with pytest.raises(ConfigurationError, match="validation failed"):
        load_config(ComplexConfig, yaml_path, "TEST")


def test_env_override_quoted_string_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test JSON-quoted string environment variable without type info (no coercion without BaseModel hint)."""
    yaml_path = _write_yaml(tmp_path, "name: default\n")
    monkeypatch.setenv("TEST__NAME", '"quoted_value"')

    config = load_config(SimpleConfig, yaml_path, "TEST")

    # Without type info path, quoted strings are returned as-is for str fields
    assert config.name == '"quoted_value"'


def test_env_override_invalid_json_quoted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test invalid JSON quoted string falls back to raw."""
    yaml_path = _write_yaml(tmp_path, "name: default\n")
    monkeypatch.setenv("TEST__NAME", '"invalid')

    config = load_config(SimpleConfig, yaml_path, "TEST")

    # Falls back to raw string
    assert config.name == '"invalid'


def test_env_override_null_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 'null' environment variable - with type info, coercion uses Pydantic's handling."""

    class NullableConfig(BaseModel):
        value: str | None = "default"

    yaml_path = _write_yaml(tmp_path, "value: default\n")
    monkeypatch.setenv("TEST__VALUE", "null")

    config = load_config(NullableConfig, yaml_path, "TEST")

    # str | None with "null" string becomes literal "null" string (Pydantic behavior)
    assert config.value == "null"


def test_env_override_json_list_with_dict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test list[dict] override with JSON."""

    class ListDictConfig(BaseModel):
        items: list[dict[str, str]] = []

    yaml_path = _write_yaml(tmp_path, "items: []\n")
    monkeypatch.setenv("TEST__ITEMS", '[{"key": "value1"}, {"key": "value2"}]')

    config = load_config(ListDictConfig, yaml_path, "TEST")

    assert config.items == [{"key": "value1"}, {"key": "value2"}]


def test_env_override_list_invalid_json_fallback_comma_split(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test list override with invalid JSON falls back to comma split."""

    class ListConfig(BaseModel):
        items: list[str] = []

    yaml_path = _write_yaml(tmp_path, "items: []\n")
    monkeypatch.setenv("TEST__ITEMS", "[invalid, json")

    config = load_config(ListConfig, yaml_path, "TEST")

    # Should fall back to comma split
    assert config.items == ["[invalid", "json"]


def test_env_override_bool_various_truthy_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test various truthy boolean values."""
    yaml_path = _write_yaml(tmp_path, "enabled: false\n")

    for truthy_value in ["1", "YES", "True", "TRUE"]:
        monkeypatch.setenv("TEST__ENABLED", truthy_value)
        config = load_config(ComplexConfig, yaml_path, "TEST")
        assert config.enabled is True, f"Failed for {truthy_value}"


def test_env_override_bool_falsy_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test various falsy boolean values."""
    yaml_path = _write_yaml(tmp_path, "enabled: true\n")

    for falsy_value in ["0", "no", "False", "FALSE", "off"]:
        monkeypatch.setenv("TEST__ENABLED", falsy_value)
        config = load_config(ComplexConfig, yaml_path, "TEST")
        assert config.enabled is False, f"Failed for {falsy_value}"


def test_env_override_nested_model_missing_intermediate_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test environment override creates intermediate nested dicts as needed."""
    yaml_path = _write_yaml(tmp_path, "enabled: true\n")
    monkeypatch.setenv("TEST__DATABASE__HOST", "remote_host")

    config = load_config(ComplexConfig, yaml_path, "TEST")

    assert config.database.host == "remote_host"
    assert config.database.port == 5432  # default


def test_resolve_field_type_with_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test edge case where get_type_hints might raise an exception (gracefully handled)."""

    class WeirdConfig(BaseModel):
        """Config that might have tricky type hints."""

        value: str = "default"

    yaml_path = _write_yaml(tmp_path, "value: from_yaml\n")
    # Set an env var for a nested path that doesn't exist
    monkeypatch.setenv("TEST__NONEXISTENT__NESTED", "value")

    # Should still work - the non-matching env var is ignored
    config = load_config(WeirdConfig, yaml_path, "TEST")
    assert config.value == "from_yaml"


def test_yaml_file_too_large_raises(tmp_path: Path) -> None:
    """YAML files over bound should fail before parsing."""
    oversized = tmp_path / "config.yaml"
    oversized.write_text("x" * (1_048_576 + 1))

    with pytest.raises(ConfigurationError, match="YAML exceeds"):
        load_config(SimpleConfig, oversized, "TEST")


def test_env_override_value_too_large_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Oversized env override values should be rejected."""
    yaml_path = _write_yaml(tmp_path, "name: default\n")
    monkeypatch.setenv("TEST__NAME", "x" * (16_384 + 1))

    with pytest.raises(ConfigurationError, match="override value exceeds"):
        load_config(SimpleConfig, yaml_path, "TEST")


def test_env_override_path_too_deep_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Excessive env override nesting should be rejected."""
    yaml_path = _write_yaml(tmp_path, "name: default\n")
    monkeypatch.setenv("TEST__A__B__C__D__E__F__G__H__I", "x")

    with pytest.raises(ConfigurationError, match="path depth exceeds"):
        load_config(SimpleConfig, yaml_path, "TEST")


def test_env_override_path_segment_too_long_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Oversized env path segments should be rejected."""
    yaml_path = _write_yaml(tmp_path, "name: default\n")
    monkeypatch.setenv(f"TEST__{'A' * 129}", "x")

    with pytest.raises(ConfigurationError, match="segment exceeds"):
        load_config(SimpleConfig, yaml_path, "TEST")


def test_env_json_list_too_many_items_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON list override should enforce item count bound."""

    class BigListConfig(BaseModel):
        items: list[int] = []

    yaml_path = _write_yaml(tmp_path, "items: []\n")
    monkeypatch.setenv("TEST__ITEMS", "[" + ",".join(str(i) for i in range(257)) + "]")

    with pytest.raises(ConfigurationError, match="list override exceeds"):
        load_config(BigListConfig, yaml_path, "TEST")


def test_env_json_dict_too_many_keys_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON dict override should enforce key count bound."""
    yaml_path = _write_yaml(tmp_path, "database:\n  settings: {}\n")
    entries = ",".join(f'"k{i}":"v{i}"' for i in range(257))
    monkeypatch.setenv("TEST__DATABASE__SETTINGS", "{" + entries + "}")

    with pytest.raises(ConfigurationError, match="object override exceeds"):
        load_config(ComplexConfig, yaml_path, "TEST")
