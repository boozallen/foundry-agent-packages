# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for tool_loader.py — security analysis and tool loading scenarios."""

from pathlib import Path

import pytest

from foundry_agent_core import ToolLoadingError
from foundry_strands_agent.tool_loader import (
    TOOLS_DIR,
    ModuleSecurityAnalyzer,
    _resolve_tools_dir,
    analyze_dangerous_calls,
    analyze_imports,
    detect_and_validate_tool,
    load_tool_from_file,
    load_tool_from_module,
    validate_imports,
)

TOOL_SPEC_SOURCE = '''
TOOL_SPEC = {
    "name": "greet",
    "description": "Greet someone by name.",
    "inputSchema": {"json": {"type": "object", "properties": {"name": {"type": "string"}}}},
}


def greet(name: str) -> str:
    """Greet someone by name."""
    return "hello " + name
'''

DECORATED_TOOL_SOURCE = '''
from strands import tool


@tool
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b
'''


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
        # detect_obfuscation no longer flags exec/eval strings itself - real exec/eval
        # calls are caught end-to-end by analyze_dangerous_calls, which
        # runs first, unconditionally, in analyze_module_file. See
        # TestSecurityAnalyzerDangerousCalls.test_exec_call_detected.
        analyzer = ModuleSecurityAnalyzer()
        source = 'x = "print(1)"\nexec(x)'
        assert analyzer.detect_obfuscation(source) is False

    def test_eval_detected(self):
        # Same rationale as test_exec_detected above - see
        # TestSecurityAnalyzerDangerousCalls.test_eval_call_detected for the real
        # end-to-end guarantee.
        analyzer = ModuleSecurityAnalyzer()
        source = 'eval("1+1")'
        assert analyzer.detect_obfuscation(source) is False

    def test_base64_payload_detected(self):
        # Real, independently-decodable base64 payloads (not synthetic repeated-letter
        # strings) — the validity check requires actual base64 characteristics, not
        # just character-class matching.
        analyzer = ModuleSecurityAnalyzer()
        source = (
            'a = "pt0SWwd5EoeF7vKOcloPo0TjA662C4KG"\n'
            'b = "+gE5uSH6hzqmOwjMwtOS6fJOMfiGDxu9"\n'
            'c = "zZe/Xjd9EG//1uwelJ2kb19Yk6c+wTvp"\n'
            'd = "aeXqd08Hmp5v3ssmft427qvyE/UiOBCq"'
        )
        assert analyzer.detect_obfuscation(source) is True

    def test_base64_false_positive_avoided_for_real_api_parameter_names(self):
        # Live repro: a tool module wrapping boto3's Bedrock retrieve() API tripped
        # the old character-class-only regex purely from AWS's own required
        # parameter names, with no actual obfuscated payload present anywhere in
        # the file.
        analyzer = ModuleSecurityAnalyzer()
        source = (
            "search_config = {\n"
            '    "rerankingConfiguration": {\n'
            '        "bedrockRerankingConfiguration": {"modelConfiguration": {}},\n'
            "    },\n"
            "}\n"
            'key = "managedSearchConfiguration" if managed else "vectorSearchConfiguration"\n'
            "response = client.retrieve(retrievalConfiguration={key: search_config})\n"
        )
        assert analyzer.detect_obfuscation(source) is False

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

    def test_subscript_callee_rejected(self):
        # Regression for f005: Subscript callee on a whitelisted module fell
        # through the Name/Attribute checks and reached exec_module unchecked.
        source = "import json\njson.__builtins__['ex' + 'ec']('1')"
        with pytest.raises(ToolLoadingError):
            analyze_dangerous_calls(source)

    def test_retrieval_class_not_flagged_as_dangerous_call(self):
        # Live repro: a class name/instantiation ending in "eval(" (Retrieval()
        # contains "eval(" as a substring) must not be mistaken for a real
        # eval/exec call by the AST-based check either.
        source = "class Retrieval:\n    def __init__(self, config):\n        self.config = config\nr = Retrieval(config={})\n"
        analyze_dangerous_calls(source)  # should not raise


class TestObfuscationRetrievalFalsePositive:
    """Spec: strands-tool-loading — Identifiers ending in exec/eval-like letters."""

    def test_retrieval_class_loads_successfully(self, tmp_path: Path):
        # Exact repro end-to-end through the full analyze_module_file pipeline, not
        # just detect_obfuscation in isolation.
        source = (
            "class Retrieval:\n"
            "    def __init__(self, config):\n"
            "        self.config = config\n"
            "\n"
            "r = Retrieval(config={})\n"
        )
        tool_file = tmp_path / "retrieval_tool.py"
        tool_file.write_text(source)
        analyzer = ModuleSecurityAnalyzer()
        assert analyzer.analyze_module_file(tool_file) is True


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


class TestDefaultToolsRoot:
    """Spec: strands-tool-loading — No override configured."""

    def test_default_root_is_the_container_path(self):
        assert TOOLS_DIR == Path("/app/strands_base_agent/tools").resolve()

    def test_no_override_resolves_to_default(self):
        assert _resolve_tools_dir(None) == TOOLS_DIR

    def test_empty_override_resolves_to_default(self):
        assert _resolve_tools_dir("") == TOOLS_DIR

    def test_override_is_resolved_absolute(self, tmp_path: Path):
        nested = tmp_path / "tools" / "sub"
        nested.mkdir(parents=True)

        assert _resolve_tools_dir(str(nested / ".." / "sub")) == nested.resolve()


class TestConfiguredToolsRootFileLoading:
    """Spec: strands-tool-loading — Load a tool file from a temporary directory."""

    @pytest.mark.asyncio
    async def test_load_tool_spec_file_from_configured_root(self, tmp_path: Path):
        tool_file = tmp_path / "greet.py"
        tool_file.write_text(TOOL_SPEC_SOURCE)

        tool = await load_tool_from_file(str(tool_file), tools_dir=str(tmp_path))

        assert tool.TOOL_SPEC["name"] == "greet"
        assert tool.greet("world") == "hello world"

    @pytest.mark.asyncio
    async def test_load_decorated_tool_file_from_configured_root(self, tmp_path: Path):
        tool_file = tmp_path / "add_numbers.py"
        tool_file.write_text(DECORATED_TOOL_SOURCE)

        tool = await load_tool_from_file(str(tool_file), tools_dir=str(tmp_path))

        assert tool is not None

    @pytest.mark.asyncio
    async def test_load_tool_file_from_nested_configured_root(self, tmp_path: Path):
        nested = tmp_path / "pkg" / "tools"
        nested.mkdir(parents=True)
        tool_file = nested / "greet.py"
        tool_file.write_text(TOOL_SPEC_SOURCE)

        tool = await load_tool_from_file(str(tool_file), tools_dir=str(tmp_path))

        assert tool.TOOL_SPEC["name"] == "greet"

    @pytest.mark.asyncio
    async def test_reject_file_outside_configured_root(self, tmp_path: Path):
        root = tmp_path / "tools"
        root.mkdir()
        outside_file = tmp_path / "evil.py"
        outside_file.write_text(TOOL_SPEC_SOURCE)

        with pytest.raises(ToolLoadingError, match="outside allowed tools directory"):
            await load_tool_from_file(str(outside_file), tools_dir=str(root))

    @pytest.mark.asyncio
    async def test_reject_dot_dot_escape_from_configured_root(self, tmp_path: Path):
        root = tmp_path / "tools"
        root.mkdir()
        outside_file = tmp_path / "evil.py"
        outside_file.write_text(TOOL_SPEC_SOURCE)

        with pytest.raises(ToolLoadingError, match="outside allowed tools directory"):
            await load_tool_from_file(str(root / ".." / "evil.py"), tools_dir=str(root))

    @pytest.mark.asyncio
    async def test_reject_symlink_escape_from_configured_root(self, tmp_path: Path):
        root = tmp_path / "tools"
        root.mkdir()
        outside_file = tmp_path / "evil.py"
        outside_file.write_text(TOOL_SPEC_SOURCE)
        link = root / "innocent.py"
        try:
            link.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not permitted on this platform")

        with pytest.raises(ToolLoadingError, match="outside allowed tools directory"):
            await load_tool_from_file(str(link), tools_dir=str(root))

    @pytest.mark.asyncio
    async def test_dangerous_import_rejected_inside_configured_root(self, tmp_path: Path):
        tool_file = tmp_path / "dangerous.py"
        tool_file.write_text("import os\n\n\ndef run():\n    return os.getcwd()\n")

        with pytest.raises(ToolLoadingError, match="Dangerous import detected: os"):
            await load_tool_from_file(str(tool_file), tools_dir=str(tmp_path))


class TestConfiguredToolsRootModuleLoading:
    """Spec: strands-tool-loading — Load module from a configured root."""

    @pytest.mark.asyncio
    async def test_load_module_from_configured_root(self, tmp_path: Path, monkeypatch):
        import importlib

        module_file = tmp_path / "greet_from_root.py"
        module_file.write_text(TOOL_SPEC_SOURCE)
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()

        tool = await load_tool_from_module("greet_from_root", tools_dir=str(tmp_path))

        assert tool.TOOL_SPEC["name"] == "greet"

    @pytest.mark.asyncio
    async def test_reject_module_outside_configured_root(self, tmp_path: Path):
        with pytest.raises(ToolLoadingError, match="outside allowed tools directory"):
            await load_tool_from_module("json", tools_dir=str(tmp_path))


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
