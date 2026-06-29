# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Configuration exceptions for foundry-agent-config.

Independently owned — no dependency on foundry-agent-core.
"""

from typing import Any


class ConfigurationError(Exception):
    """Raised when configuration loading or validation fails."""

    def __init__(self, message: str, *, cause: Exception | None = None, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}
        if cause:
            self.__cause__ = cause
