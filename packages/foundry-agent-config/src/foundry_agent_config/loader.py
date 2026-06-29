# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""YAML configuration loader with environment variable overrides."""

import json
import os
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import yaml
from pydantic import BaseModel, ValidationError

from foundry_agent_config.exceptions import ConfigurationError

_MAX_YAML_FILE_BYTES = 1_048_576  # 1 MiB
_MAX_ENV_OVERRIDES = 512
_MAX_ENV_PATH_DEPTH = 8
_MAX_ENV_SEGMENT_LEN = 128
_MAX_ENV_VALUE_LEN = 16_384
_MAX_JSON_LIST_ITEMS = 256
_MAX_JSON_DICT_KEYS = 256


def load_config[T: BaseModel](
    config_class: type[T],
    yaml_path: Path,
    env_prefix: str = "",
) -> T:
    """Load configuration from YAML with environment variable overrides.

    YAML is the primary source. Environment variables override YAML values
    using double-underscore nesting: {PREFIX}__{KEY__PATH}.

    Args:
        config_class: Pydantic BaseModel class to validate against
        yaml_path: Path to YAML configuration file
        env_prefix: Environment variable prefix (e.g., "STRANDS")

    Returns:
        Validated configuration instance

    Raises:
        ConfigurationError: If YAML is invalid, file not found, or validation fails
    """
    base_dict = _load_yaml(yaml_path)
    env_overrides = _collect_env_overrides(env_prefix)
    merged = _merge_overrides(base_dict, env_overrides, config_class)

    try:
        return config_class(**merged)
    except ValidationError as e:
        raise ConfigurationError(
            f"Configuration validation failed: {e}",
            cause=e,
            context={"config_class": config_class.__name__, "yaml_path": str(yaml_path)},
        ) from e


def _load_yaml(yaml_path: Path) -> dict[str, Any]:
    try:
        if yaml_path.stat().st_size > _MAX_YAML_FILE_BYTES:
            raise ConfigurationError(
                f"Configuration YAML exceeds {_MAX_YAML_FILE_BYTES} bytes",
                context={
                    "yaml_path": str(yaml_path),
                    "max_yaml_bytes": _MAX_YAML_FILE_BYTES,
                },
            )
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise ConfigurationError(
            f"Configuration file not found: {yaml_path}",
            cause=e,
            context={"yaml_path": str(yaml_path)},
        ) from e
    except yaml.YAMLError as e:
        raise ConfigurationError(
            f"Invalid YAML in configuration file: {e}",
            cause=e,
            context={"yaml_path": str(yaml_path)},
        ) from e

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"YAML root must be a mapping, got {type(data).__name__}",
            context={"yaml_path": str(yaml_path)},
        )
    return data


def _collect_env_overrides(prefix: str) -> dict[tuple[str, ...], str]:
    if not prefix:
        return {}

    overrides: dict[tuple[str, ...], str] = {}
    prefix_with_sep = f"{prefix}__"

    for key, value in os.environ.items():
        if not key.startswith(prefix_with_sep):
            continue
        if len(overrides) >= _MAX_ENV_OVERRIDES:
            raise ConfigurationError(
                f"Environment override count exceeds {_MAX_ENV_OVERRIDES}",
                context={
                    "env_prefix": prefix,
                    "max_env_overrides": _MAX_ENV_OVERRIDES,
                },
            )
        remainder = key[len(prefix_with_sep) :]
        path_parts = remainder.split("__")
        if len(path_parts) > _MAX_ENV_PATH_DEPTH:
            raise ConfigurationError(
                f"Environment override path depth exceeds {_MAX_ENV_PATH_DEPTH}",
                context={
                    "env_key": key,
                    "path_depth": len(path_parts),
                    "max_path_depth": _MAX_ENV_PATH_DEPTH,
                },
            )
        for segment in path_parts:
            if not segment:
                raise ConfigurationError(
                    "Environment override path contains empty segment",
                    context={"env_key": key},
                )
            if len(segment) > _MAX_ENV_SEGMENT_LEN:
                raise ConfigurationError(
                    f"Environment override path segment exceeds {_MAX_ENV_SEGMENT_LEN} characters",
                    context={
                        "env_key": key,
                        "segment": segment,
                        "max_segment_len": _MAX_ENV_SEGMENT_LEN,
                    },
                )
        if len(value) > _MAX_ENV_VALUE_LEN:
            raise ConfigurationError(
                f"Environment override value exceeds {_MAX_ENV_VALUE_LEN} characters",
                context={
                    "env_key": key,
                    "value_length": len(value),
                    "max_value_len": _MAX_ENV_VALUE_LEN,
                },
            )
        # Lowercased to match Pydantic field names (always snake_case).
        # Mixed-case YAML keys won't match — by design, all config fields are lowercase.
        path_segments = tuple(seg.lower() for seg in path_parts)
        overrides[path_segments] = value

    return overrides


def _merge_overrides(
    base: dict[str, Any],
    overrides: dict[tuple[str, ...], str],
    config_class: type[BaseModel] | None = None,
) -> dict[str, Any]:
    result = _deep_copy_dict(base)

    for path, raw_value in overrides.items():
        field_type = _resolve_field_type(config_class, path) if config_class else None
        value = _parse_env_value(raw_value, field_type, path)
        _set_nested(result, path, value)

    return result


def _resolve_field_type(model_class: type[BaseModel] | None, path: tuple[str, ...]) -> type | None:
    """Walk the model's type annotations to find the field type at the given path."""
    if model_class is None:
        return None

    current_class = model_class
    for i, segment in enumerate(path):
        try:
            hints = get_type_hints(current_class)
        except Exception:
            return None

        if segment not in hints:
            return None

        field_type = hints[segment]

        # If this is the last segment, return the type
        if i == len(path) - 1:
            return field_type

        # If there are more segments, the field must be a nested BaseModel
        origin = get_origin(field_type)
        if origin is None and isinstance(field_type, type) and issubclass(field_type, BaseModel):
            current_class = field_type
        else:
            return None

    return None


def _deep_copy_dict(d: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            result[k] = _deep_copy_dict(v)
        elif isinstance(v, list):
            result[k] = list(v)
        else:
            result[k] = v
    return result


def _set_nested(d: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    for segment in path[:-1]:
        if segment not in d or not isinstance(d[segment], dict):
            d[segment] = {}
        d = d[segment]
    d[path[-1]] = value


def _parse_env_value(raw: str, field_type: type | None = None, path: tuple[str, ...] | None = None) -> Any:
    """Parse an environment variable value, coercing to the target field type if known."""
    stripped = raw.strip()

    # If we know the target type, do type-aware coercion
    if field_type is not None:
        return _coerce_to_type(stripped, field_type, path)

    # Fallback: generic parsing without type info
    if stripped.startswith(("[", "{")):
        try:
            parsed = json.loads(stripped)
            _enforce_json_structure_bounds(parsed, path)
            return parsed
        except json.JSONDecodeError:
            return raw

    if stripped.startswith('"') and stripped.endswith('"'):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return raw

    lower = stripped.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower == "null":
        return None

    return raw


def _coerce_to_type(value: str, field_type: type, path: tuple[str, ...] | None = None) -> Any:
    """Coerce a string value to the expected field type."""
    origin = get_origin(field_type)
    args = get_args(field_type)

    # Handle Optional[X] (Union[X, None])
    if origin is type(int | str):  # UnionType
        # Filter out NoneType
        non_none_args = [a for a in args if a is not type(None)]
        if non_none_args:
            return _coerce_to_type(value, non_none_args[0], path)

    # list[str] → split on commas
    if origin is list:
        # Try JSON first (handles list[dict] and complex lists)
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                _enforce_json_structure_bounds(parsed, path)
                return parsed
            except json.JSONDecodeError:
                pass
        # Fall back to comma-split for list[str]
        if args and args[0] is str:
            return [item.strip() for item in value.split(",") if item.strip()]
        # For other list types, try JSON
        try:
            parsed = json.loads(value)
            _enforce_json_structure_bounds(parsed, path)
            return parsed
        except json.JSONDecodeError:
            return [item.strip() for item in value.split(",") if item.strip()]

    # dict → parse as JSON
    if origin is dict or field_type is dict:
        try:
            parsed = json.loads(value)
            _enforce_json_structure_bounds(parsed, path)
            return parsed
        except json.JSONDecodeError:
            return value

    # int
    if field_type is int:
        try:
            return int(value)
        except ValueError:
            return value

    # float
    if field_type is float:
        try:
            return float(value)
        except ValueError:
            return value

    # bool
    if field_type is bool:
        return value.lower() in ("true", "1", "yes")

    # str or unknown — return as-is
    return value


def _enforce_json_structure_bounds(value: Any, path: tuple[str, ...] | None) -> None:
    path_label = "__".join(path) if path else "<unknown>"
    if isinstance(value, list) and len(value) > _MAX_JSON_LIST_ITEMS:
        raise ConfigurationError(
            f"JSON list override exceeds {_MAX_JSON_LIST_ITEMS} items",
            context={
                "override_path": path_label,
                "item_count": len(value),
                "max_items": _MAX_JSON_LIST_ITEMS,
            },
        )
    if isinstance(value, dict) and len(value) > _MAX_JSON_DICT_KEYS:
        raise ConfigurationError(
            f"JSON object override exceeds {_MAX_JSON_DICT_KEYS} keys",
            context={
                "override_path": path_label,
                "key_count": len(value),
                "max_keys": _MAX_JSON_DICT_KEYS,
            },
        )
