# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the public bounded-dict validator (STIG V-222612)."""

import json
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError, field_validator

import foundry_agent_core
from foundry_agent_core import (
    _MAX_DICT_BYTES,
    _MAX_DICT_KEY_LEN,
    _MAX_DICT_KEYS,
    AgentRequest,
    validate_bounded_dict,
)
from foundry_agent_core.types import _json_utf8_size, _validate_bounded_dict


def test_exported_from_package_root():
    assert "validate_bounded_dict" in foundry_agent_core.__all__


def test_private_alias_is_the_public_validator():
    assert _validate_bounded_dict is validate_bounded_dict


def test_none_passes_through():
    assert validate_bounded_dict(None) is None


def test_returns_the_value_unchanged():
    value = {"k": "v"}
    assert validate_bounded_dict(value) is value


class TestInputShape:
    """A non-dict value or a dict JSON can't encode raises ``ValueError``, not ``TypeError``."""

    @pytest.mark.parametrize("value", ["abc", ["a", "b"]])
    def test_non_dict_raises_value_error(self, value):
        with pytest.raises(ValueError, match="^Context must be a dictionary$"):
            validate_bounded_dict(value, label="Context")

    def test_nested_key_json_cannot_encode_raises_value_error(self):
        with pytest.raises(ValueError, match="^Context is not JSON-serializable$"):
            validate_bounded_dict({"a": {(1, 2): 1}}, label="Context")

    def test_circular_reference_raises_labelled_value_error(self):
        value: dict = {}
        value["self"] = value
        with pytest.raises(ValueError, match="^Context is not JSON-serializable$"):
            validate_bounded_dict(value, label="Context")

    def test_too_deeply_nested_raises_value_error(self):
        value: dict = {}
        cursor = value
        for _ in range(10_000):
            cursor["a"] = {}
            cursor = cursor["a"]
        with pytest.raises(ValueError, match="^Context is not JSON-serializable$"):
            validate_bounded_dict(value, label="Context")

    def test_nested_key_json_cannot_encode_becomes_validation_error(self):
        with pytest.raises(ValidationError, match="dict is not JSON-serializable"):
            AgentRequest(query="q", context={"a": {(1, 2): 1}})


class TestKeyType:
    """Non-string keys are rejected with ``ValueError``, so a Pydantic validator reports a validation error."""

    @pytest.mark.parametrize("key", [1, (1, 2)])
    def test_non_string_key_raises_value_error(self, key):
        with pytest.raises(ValueError, match="^Context keys must be strings$"):
            validate_bounded_dict({key: 0}, label="Context")

    def test_non_string_key_becomes_validation_error(self):
        class Model(BaseModel):
            ctx: Any = None

            @field_validator("ctx", mode="before")
            @classmethod
            def _bound(cls, v: Any) -> Any:
                return validate_bounded_dict(v)

        with pytest.raises(ValidationError, match="dict keys must be strings"):
            Model(ctx={1: "v"})


class TestDefaultLimits:
    """The defaults are core's canonical bounds."""

    def test_key_count_at_limit_passes(self):
        validate_bounded_dict({f"k{i}": 0 for i in range(_MAX_DICT_KEYS)})

    def test_key_count_over_limit_raises(self):
        with pytest.raises(ValueError, match=f"^dict exceeds {_MAX_DICT_KEYS} top-level keys$"):
            validate_bounded_dict({f"k{i}": 0 for i in range(_MAX_DICT_KEYS + 1)})

    def test_key_length_at_limit_passes(self):
        validate_bounded_dict({"k" * _MAX_DICT_KEY_LEN: 0})

    def test_key_length_over_limit_raises(self):
        with pytest.raises(ValueError, match=f"^dict key exceeds {_MAX_DICT_KEY_LEN} characters$"):
            validate_bounded_dict({"k" * (_MAX_DICT_KEY_LEN + 1): 0})

    def test_size_at_limit_passes(self, utf8_sized_dict):
        validate_bounded_dict(utf8_sized_dict("λ", _MAX_DICT_BYTES))

    def test_size_over_limit_raises(self, utf8_sized_dict):
        with pytest.raises(ValueError, match=f"^dict serializes above {_MAX_DICT_BYTES} bytes$"):
            validate_bounded_dict(utf8_sized_dict("λ", _MAX_DICT_BYTES + 1))


class TestCustomLimits:
    """Caller-supplied limits replace the defaults, and ``label`` starts each message."""

    def test_key_count_at_and_over_limit(self):
        validate_bounded_dict({"a": 0, "b": 0}, max_keys=2)
        with pytest.raises(ValueError, match="^Context exceeds 2 top-level keys$"):
            validate_bounded_dict({"a": 0, "b": 0, "c": 0}, max_keys=2, label="Context")

    def test_key_length_at_and_over_limit(self):
        validate_bounded_dict({"abcd": 0}, max_key_len=4)
        with pytest.raises(ValueError, match="^Context key exceeds 4 characters$"):
            validate_bounded_dict({"abcde": 0}, max_key_len=4, label="Context")

    @pytest.mark.parametrize("char", ["x", "λ", "😀"])
    def test_size_at_and_over_limit(self, char, utf8_sized_dict):
        validate_bounded_dict(utf8_sized_dict(char, 64), max_bytes=64)
        with pytest.raises(ValueError, match="^Context serializes above 64 bytes$"):
            validate_bounded_dict(utf8_sized_dict(char, 65), max_bytes=64, label="Context")


class TestSizeMeasurement:
    r"""The size is UTF-8 bytes of the ``ensure_ascii=False`` JSON form, not ``\uXXXX`` escapes."""

    @pytest.mark.parametrize("char", ["λ", "😀"])
    def test_non_ascii_counts_utf8_bytes_not_escapes(self, char, utf8_sized_dict):
        value = utf8_sized_dict(char, 64)
        assert len(json.dumps(value)) > 64
        validate_bounded_dict(value, max_bytes=64)

    def test_lone_surrogate_counts_three_bytes(self):
        value = {"k": "\ud83d"}  # '{"k": "' + 3 bytes + '"}' = 12 bytes
        validate_bounded_dict(value, max_bytes=12)
        with pytest.raises(ValueError, match="serializes above 11 bytes"):
            validate_bounded_dict(value, max_bytes=11)


class TestJsonUtf8Size:
    """``_json_utf8_size`` is the size measure behind every byte cap."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("v", 10),  # '{"k": "' (7) + 1 + '"}' (2)
            ("\x7f", 10),  # DEL is 1 byte, not a 6-character escape
            ("λ", 11),  # 2 bytes
            ("😀", 13),  # 4 bytes
            ("\ud83d", 12),  # lone surrogate: 3 bytes
        ],
    )
    def test_counts_utf8_bytes(self, text, expected):
        assert _json_utf8_size({"k": text}) == expected

    def test_stringifies_values_json_cannot_encode(self):
        class Opaque:
            def __str__(self) -> str:
                return "opaque"

        assert _json_utf8_size({"k": Opaque()}) == _json_utf8_size({"k": "opaque"})
