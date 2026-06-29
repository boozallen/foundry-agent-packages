# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for tool_loader.py — security analysis and tool loading scenarios."""

from pathlib import Path

import pytest

from foundry_agent_core import ToolLoadingError
from foundry_strands_agent.tool_loader import (
    ModuleSecurityAnalyzer,
    analyze_dangerous_calls,
    analyze_imports,
    detect_and_validate_tool,
    load_tool_from_file,
    load_tool_from_module,
    validate_imports,
)


class TestSecurityAnalyzerDangerousImports:
    """Spec: strands-tool-loading — Dangerous import detected."""

    def test_dangerous_import_os(self):
        source = "import os\nprint(os.getcwd())"
        with pytest.raises(ToolLoadingError, match="Dangerous import detected: os"):
            validate_imports(source)

    def test_dangerous_import_subprocess(self):
        source = "import subprocess\nsubprocess.run(['ls'])"
        with pytest.raises(ToolLoadingError, match="Dangerous import detected: subprocess"):
            validate_imports(source)

    def test_dangerous_import_from_style(self):
        source = "from os import path"
        with pytest.raises(ToolLoadingError, match="Dangerous import detected: os"):
            validate_imports(source)

    def test_safe_import_allowed(self):
        source = "import json\nimport math"
        assert validate_imports(source) is True

    def test_non_whitelisted_import_rejected(self):
        source = "import some_unknown_package"
        with pytest.raises(ToolLoadingError, match="Non-whitelisted import"):
            validate_imports(source)


class TestSecurityAnalyzerObfuscation:
    """Spec: strands-tool-loading — Obfuscated code detected."""

    def test_exec_detected(self):
        analyzer = ModuleSecurityAnalyzer()
        source = 'x = "print(1)"\nexec(x)'
        assert analyzer.detect_obfuscation(source) is True

    def test_eval_detected(self):
        analyzer = ModuleSecurityAnalyzer()
        source = 'eval("1+1")'
        assert analyzer.detect_obfuscation(source) is True

    def test_base64_payload_detected(self):
        analyzer = ModuleSecurityAnalyzer()
        source = (
            'a = "AAAAAAAAAAAAAAAAAAAAAA=="\n'
            'b = "BBBBBBBBBBBBBBBBBBBBBB"\n'
            'c = "CCCCCCCCCCCCCCCCCCCCCC"\n'
            'd = "DDDDDDDDDDDDDDDDDDDDDD"'
        )
        assert analyzer.detect_obfuscation(source) is True

    def test_hex_encoding_detected(self):
        analyzer = ModuleSecurityAnalyzer()
        source = "".join([f"x = '\\x{i:02x}'\n" for i in range(15)])
        assert analyzer.detect_obfuscation(source) is True

    def test_clean_code_passes(self):
        analyzer = ModuleSecurityAnalyzer()
        source = 'def hello():\n    return "world"'
        assert analyzer.detect_obfuscation(source) is False


class TestSecurityAnalyzerDangerousCalls:
    """Spec: strands-tool-loading — Dangerous function calls."""

    def test_eval_call_detected(self):
        source = 'eval("1+1")'
        with pytest.raises(ToolLoadingError, match="Dangerous function call: eval"):
            analyze_dangerous_calls(source)

    def test_exec_call_detected(self):
        source = 'exec("x = 1")'
        with pytest.raises(ToolLoadingError, match="Dangerous function call: exec"):
            analyze_dangerous_calls(source)

    def test_system_method_detected(self):
        source = "os.system('ls')"
        with pytest.raises(ToolLoadingError, match="Dangerous method call: system"):
            analyze_dangerous_calls(source)


class TestModuleSecurityAnalyzerFileAnalysis:
    """Spec: strands-tool-loading — Full file security analysis."""

    def test_syntax_error_rejected(self, tmp_path: Path):
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def broken(\n")
        analyzer = ModuleSecurityAnalyzer()
        with pytest.raises(ToolLoadingError, match="Syntax error"):
            analyzer.analyze_module_file(bad_file)

    def test_oversized_file_rejected(self, tmp_path: Path):
        big_file = tmp_path / "big.py"
        big_file.write_text("x = 1\n" * 60000)
        analyzer = ModuleSecurityAnalyzer()
        with pytest.raises(ToolLoadingError, match="Module too large"):
            analyzer.analyze_module_file(big_file)

    def test_too_many_lines_rejected(self, tmp_path: Path):
        long_file = tmp_path / "long.py"
        long_file.write_text("x = 1\n" * 1001)
        analyzer = ModuleSecurityAnalyzer()
        with pytest.raises(ToolLoadingError, match="Too many lines"):
            analyzer.analyze_module_file(long_file)


class TestToolLoaderRejectOutsideDirectory:
    """Spec: strands-tool-loading — Reject module/file outside tools directory."""

    @pytest.mark.asyncio
    async def test_reject_module_outside_tools_dir(self):
        with pytest.raises(ToolLoadingError):
            await load_tool_from_module("json")

    @pytest.mark.asyncio
    async def test_reject_file_outside_tools_dir(self, tmp_path: Path):
        outside_file = tmp_path / "evil.py"
        outside_file.write_text("x = 1")
        with pytest.raises(ToolLoadingError, match="outside allowed tools directory"):
            await load_tool_from_file(str(outside_file))

    @pytest.mark.asyncio
    async def test_reject_nonexistent_file(self):
        with pytest.raises(ToolLoadingError):
            await load_tool_from_file("/app/strands_base_agent/tools/nonexistent.py")

    @pytest.mark.asyncio
    async def test_reject_non_python_file(self, tmp_path: Path):
        txt_file = tmp_path / "tool.txt"
        txt_file.write_text("not python")
        with pytest.raises(ToolLoadingError):
            await load_tool_from_file(str(txt_file))


class TestDetectAndValidateTool:
    """Spec: strands-tool-loading — Tool format detection."""

    def test_tool_spec_module_detected(self):
        import types

        module = types.ModuleType("fake_tool")
        module.TOOL_SPEC = {"name": "test_tool", "description": "A test", "inputSchema": {}}  # type: ignore[attr-defined]

        def test_tool():
            pass

        module.test_tool = test_tool  # type: ignore[attr-defined]
        result = detect_and_validate_tool(module, "fake_tool")
        assert result is module

    def test_decorated_function_detected(self):
        import types

        module = types.ModuleType("fake_decorated")

        def my_func():
            pass

        my_func.__tool__ = True  # type: ignore[attr-defined]
        module.my_func = my_func  # type: ignore[attr-defined]
        result = detect_and_validate_tool(module, "fake_decorated")
        assert result is not None

    def test_no_tool_format_raises(self):
        import types

        module = types.ModuleType("empty_module")
        with pytest.raises(ToolLoadingError, match="does not match any supported format"):
            detect_and_validate_tool(module, "empty_module")


class TestAnalyzeImports:
    """Unit tests for import extraction."""

    def test_extracts_import_names(self):
        source = "import json\nimport os"
        result = analyze_imports(source)
        assert "json" in result
        assert "os" in result

    def test_extracts_from_imports(self):
        source = "from pathlib import Path"
        result = analyze_imports(source)
        assert "pathlib" in result
