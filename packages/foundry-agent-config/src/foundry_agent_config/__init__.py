# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""foundry-agent-config — YAML config loader with env var overrides."""

from foundry_agent_config.exceptions import ConfigurationError
from foundry_agent_config.loader import load_config

__all__ = ["load_config", "ConfigurationError"]
