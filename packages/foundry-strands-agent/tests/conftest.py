# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Shared test fixtures for foundry-strands-agent."""

import secrets

import pytest


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Provide SESSION_ENCRYPTION_KEY for all tests that use file session managers."""
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", secrets.token_hex(32))
