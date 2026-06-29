# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for error translator."""

from foundry_agent_core.errors.translator import InfrastructureErrorTranslator, create_error_translator
from foundry_agent_core.exceptions import (
    DomainError,
    QueryProcessingError,
)


class TestInfrastructureErrorTranslator:
    def test_translate_domain_error_passthrough(self) -> None:
        translator = InfrastructureErrorTranslator()
        err = QueryProcessingError("pipeline failed")
        result = translator.translate_error(err)
        assert isinstance(result, DomainError)

    def test_translate_timeout_error(self) -> None:
        translator = InfrastructureErrorTranslator()
        err = TimeoutError("timed out")
        result = translator.translate_error(err)
        assert isinstance(result, DomainError)

    def test_translate_connection_error(self) -> None:
        translator = InfrastructureErrorTranslator()
        err = ConnectionError("refused")
        result = translator.translate_error(err)
        assert isinstance(result, DomainError)

    def test_translate_generic_exception(self) -> None:
        translator = InfrastructureErrorTranslator()
        err = RuntimeError("unexpected")
        result = translator.translate_error(err)
        assert isinstance(result, DomainError)

    def test_classify_timeout_as_transient(self) -> None:
        translator = InfrastructureErrorTranslator()
        err = TimeoutError("timed out")
        assert translator.classify_error(err) == "transient"

    def test_classify_value_error_as_permanent(self) -> None:
        translator = InfrastructureErrorTranslator()
        err = ValueError("bad value")
        assert translator.classify_error(err) == "permanent"

    def test_classify_unknown(self) -> None:
        translator = InfrastructureErrorTranslator()
        err = RuntimeError("something happened")
        classification = translator.classify_error(err)
        assert classification in ("transient", "permanent", "unknown")

    def test_preserve_error_context(self) -> None:
        translator = InfrastructureErrorTranslator()
        err = RuntimeError("test")
        ctx = translator.preserve_error_context(err, {"op": "query"})
        assert "op" in ctx
        assert ctx["op"] == "query"

    def test_create_error_translator(self) -> None:
        translator = create_error_translator()
        assert isinstance(translator, InfrastructureErrorTranslator)
