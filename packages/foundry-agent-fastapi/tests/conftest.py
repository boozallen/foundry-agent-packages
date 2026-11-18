# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Shared test fixtures for foundry-agent-fastapi."""

from collections.abc import Callable

import pytest


@pytest.fixture
def utf8_sized_dict() -> Callable[[str, int], dict[str, str]]:
    """Build ``{"k": ...}``, about half ``char``, whose UTF-8 JSON encoding is exactly ``size`` bytes."""

    def build(char: str, size: int) -> dict[str, str]:
        char_bytes = len(char.encode("utf-8"))
        count = size // (2 * char_bytes)
        return {"k": char * count + "x" * (size - len('{"k": ""}') - count * char_bytes)}

    return build
