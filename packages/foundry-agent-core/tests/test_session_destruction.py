# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for SessionDestruction protocol (STIG V-222578)."""

import inspect

from foundry_agent_core import SessionDestruction


class TestSessionDestructionProtocol:
    def test_protocol_importable(self):
        assert SessionDestruction is not None

    def test_has_destroy_session_method(self):
        assert hasattr(SessionDestruction, "destroy_session")

    def test_destroy_session_signature(self):
        sig = inspect.signature(SessionDestruction.destroy_session)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "session_id" in params
