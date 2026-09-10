# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for AgentToolRegistryManager — spec: strands-tool-registry."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from foundry_agent_core import ToolLoadingError, ToolRegistrationError
from foundry_strands_agent._tool_factory import DependencyInjectedToolRegistry

GREET_TOOL_SOURCE = '''
TOOL_SPEC = {
    "name": "greet",
    "description": "Greet someone by name.",
    "inputSchema": {"json": {"type": "object", "properties": {"name": {"type": "string"}}}},
}


def greet(name: str) -> str:
    """Greet someone by name."""
    return "hello " + name
'''

FAREWELL_TOOL_SOURCE = '''
TOOL_SPEC = {
    "name": "farewell",
    "description": "Say goodbye to someone.",
    "inputSchema": {"json": {"type": "object", "properties": {"name": {"type": "string"}}}},
}


def farewell(name: str) -> str:
    """Say goodbye to someone."""
    return "bye " + name
'''

DANGEROUS_TOOL_SOURCE = '''
import os

TOOL_SPEC = {
    "name": "cwd",
    "description": "Report the working directory.",
    "inputSchema": {"json": {"type": "object", "properties": {}}},
}


def cwd() -> str:
    """Report the working directory."""
    return os.getcwd()
'''


@pytest.fixture
def container():
    c = MagicMock()
    c.get_registered_types.return_value = []
    return c


@pytest.fixture
def registry(container):
    return DependencyInjectedToolRegistry(container)


class TestRegisterAndRetrieveTool:
    """Scenario: Register and retrieve tool."""

    def test_register_tool_spec_module(self, registry):
        import types

        module = types.ModuleType("calc_tool")
        module.TOOL_SPEC = {"name": "calculator", "description": "A calculator", "inputSchema": {}}  # type: ignore[attr-defined]

        def calculator():
            pass

        module.calculator = calculator  # type: ignore[attr-defined]

        registry.register_tool(module)
        tools = registry.get_available_tools()
        assert len(tools) == 1
        assert tools[0] is module

    def test_register_decorated_function(self, registry):
        def my_tool():
            pass

        my_tool.__tool__ = True  # type: ignore[attr-defined]
        my_tool.__name__ = "my_tool"

        registry.register_tool(my_tool)
        tools = registry.get_available_tools()
        assert len(tools) == 1

    def test_get_available_tools_empty(self, registry):
        assert registry.get_available_tools() == []


class TestRegisterToolWithDependencies:
    """Scenario: Register tool with dependencies."""

    def test_register_with_deps(self, registry):
        def tool_fn():
            pass

        registry.register_tool_with_dependencies(
            tool_fn,
            dependencies=[str],
            metadata={"name": "dep_tool"},
        )
        tools = registry.get_available_tools()
        assert len(tools) == 1

    def test_duplicate_registration_raises(self, registry):
        def tool_fn():
            pass

        registry.register_tool_with_dependencies(tool_fn, dependencies=[], metadata={"name": "dup"})
        with pytest.raises(ToolRegistrationError):
            registry.register_tool_with_dependencies(tool_fn, dependencies=[], metadata={"name": "dup"})


class TestValidateToolDependencies:
    """Scenario: Validate tool dependencies."""

    def test_validation_passes_empty_registry(self, registry):
        result = registry.validate_tool_dependencies()
        assert result["valid"] is True

    def test_validation_fails_missing_dep(self, registry, container):
        container.get_registered_types.return_value = []

        def tool_fn():
            pass

        registry.register_tool_with_dependencies(tool_fn, dependencies=[int], metadata={"name": "needs_int"})
        result = registry.validate_tool_dependencies()
        assert result["valid"] is False
        assert len(result["issues"]) > 0


class TestUnregisterTool:
    """Scenario: Unregister tool."""

    def test_unregister_removes_tool(self, registry):
        def my_tool():
            pass

        my_tool.__tool__ = True  # type: ignore[attr-defined]
        my_tool.__name__ = "removable"

        registry.register_tool(my_tool)
        assert len(registry.get_available_tools()) == 1

        registry.unregister_tool("removable")
        assert len(registry.get_available_tools()) == 0

    def test_unregister_nonexistent_raises(self, registry):
        with pytest.raises(ToolRegistrationError):
            registry.unregister_tool("does_not_exist")


class TestRegistryStatistics:
    """Scenario: Registry statistics — tested via AgentToolRegistryManager."""

    def test_get_tool_metadata(self, registry):
        import types

        module = types.ModuleType("stat_tool")
        module.TOOL_SPEC = {"name": "stat_tool", "description": "Stats", "inputSchema": {}}  # type: ignore[attr-defined]

        def stat_tool():
            pass

        module.stat_tool = stat_tool  # type: ignore[attr-defined]

        registry.register_tool(module, metadata={"source": "test"})
        meta = registry.get_tool_metadata("stat_tool")
        assert "original_name" in meta

    def test_get_tool_dependencies(self, registry):
        def dep_tool():
            pass

        registry.register_tool_with_dependencies(dep_tool, dependencies=[str, int], metadata={"name": "dep_tool"})
        deps = registry.get_tool_dependencies("dep_tool")
        assert str in deps
        assert int in deps


class TestLoadToolsFromDirectory:
    """Scenario: Directory tool loading delegates to the audited loader."""

    @pytest.mark.asyncio
    async def test_clean_directory_registers_every_tool(self, container, tmp_path: Path):
        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        (tools_root / "greet.py").write_text(GREET_TOOL_SOURCE)
        (tools_root / "farewell.py").write_text(FAREWELL_TOOL_SOURCE)
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        await registry.load_tools_from_directory(str(tools_root))

        registered = [t.TOOL_SPEC["name"] for t in registry.get_available_tools()]
        assert len(registered) == 2
        assert any(name.endswith("greet") for name in registered)
        assert any(name.endswith("farewell") for name in registered)

    @pytest.mark.asyncio
    async def test_rejected_file_is_excluded_and_the_rest_still_load(self, container, tmp_path: Path):
        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        (tools_root / "greet.py").write_text(GREET_TOOL_SOURCE)
        (tools_root / "cwd.py").write_text(DANGEROUS_TOOL_SOURCE)
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        await registry.load_tools_from_directory(str(tools_root))

        registered = [t.TOOL_SPEC["name"] for t in registry.get_available_tools()]
        assert any(name.endswith("greet") for name in registered)
        assert not any(name.endswith("cwd") for name in registered)

    @pytest.mark.asyncio
    async def test_rejected_file_is_logged_with_its_reason(self, container, tmp_path: Path, caplog):
        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        (tools_root / "greet.py").write_text(GREET_TOOL_SOURCE)
        (tools_root / "cwd.py").write_text(DANGEROUS_TOOL_SOURCE)
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        with caplog.at_level(logging.ERROR, logger="foundry_strands_agent._tool_factory"):
            await registry.load_tools_from_directory(str(tools_root))

        per_file = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(per_file) == 1
        assert "cwd.py" in per_file[0].getMessage()
        assert "Dangerous import detected: os" in per_file[0].getMessage()

    @pytest.mark.asyncio
    async def test_summary_warning_names_every_rejected_file(self, container, tmp_path: Path, caplog):
        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        (tools_root / "greet.py").write_text(GREET_TOOL_SOURCE)
        (tools_root / "cwd.py").write_text(DANGEROUS_TOOL_SOURCE)
        (tools_root / "shell.py").write_text(DANGEROUS_TOOL_SOURCE.replace("import os", "import subprocess"))
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent._tool_factory"):
            await registry.load_tools_from_directory(str(tools_root))

        summaries = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(summaries) == 1
        summary = summaries[0].getMessage()
        assert "cwd.py" in summary
        assert "shell.py" in summary
        assert "2 rejected" in summary

    @pytest.mark.asyncio
    async def test_no_summary_warning_when_nothing_is_rejected(self, container, tmp_path: Path, caplog):
        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        (tools_root / "greet.py").write_text(GREET_TOOL_SOURCE)
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent._tool_factory"):
            await registry.load_tools_from_directory(str(tools_root))

        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    @pytest.mark.asyncio
    async def test_directory_where_nothing_loads_raises_with_every_reason(self, container, tmp_path: Path):
        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        (tools_root / "cwd.py").write_text(DANGEROUS_TOOL_SOURCE)
        (tools_root / "shell.py").write_text(DANGEROUS_TOOL_SOURCE.replace("import os", "import subprocess"))
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        with pytest.raises(ToolLoadingError, match="No tools loaded from directory") as excinfo:
            await registry.load_tools_from_directory(str(tools_root))

        rejected = excinfo.value.context["rejected"]
        assert len(rejected) == 2
        assert any("Dangerous import detected: os" in reason for reason in rejected.values())
        assert any("Dangerous import detected: subprocess" in reason for reason in rejected.values())
        assert registry.get_available_tools() == []

    @pytest.mark.asyncio
    async def test_directory_outside_configured_root_rejected(self, container, tmp_path: Path, monkeypatch):
        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "greet.py").write_text(GREET_TOOL_SOURCE)
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        loader = AsyncMock()
        monkeypatch.setattr("foundry_strands_agent._tool_factory.load_tool_from_file", loader)

        with pytest.raises(ToolLoadingError, match="outside allowed tools directory"):
            await registry.load_tools_from_directory(str(outside))

        # Rejected before any file in the directory was read.
        loader.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dot_dot_escape_from_configured_root_rejected(self, container, tmp_path: Path):
        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        with pytest.raises(ToolLoadingError, match="outside allowed tools directory"):
            await registry.load_tools_from_directory(str(tools_root / ".." / "elsewhere"))

    @pytest.mark.asyncio
    async def test_audited_loader_is_the_code_path(self, container, tmp_path: Path, monkeypatch):
        """A future reintroduction of a bare import would fail this test."""
        import types

        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        tool_file = tools_root / "greet.py"
        tool_file.write_text(GREET_TOOL_SOURCE)
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        module = types.ModuleType("greet")
        module.TOOL_SPEC = {"name": "greet", "description": "Greet", "inputSchema": {}}  # type: ignore[attr-defined]
        module.greet = lambda name: "hello " + name  # type: ignore[attr-defined]
        loader = AsyncMock(return_value=module)
        monkeypatch.setattr("foundry_strands_agent._tool_factory.load_tool_from_file", loader)

        await registry.load_tools_from_directory(str(tools_root))

        loader.assert_awaited_once_with(tool_file, tools_dir=tools_root.resolve())

    @pytest.mark.asyncio
    async def test_underscore_prefixed_files_are_skipped(self, container, tmp_path: Path):
        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        (tools_root / "greet.py").write_text(GREET_TOOL_SOURCE)
        (tools_root / "_private.py").write_text(DANGEROUS_TOOL_SOURCE)
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        await registry.load_tools_from_directory(str(tools_root))

        assert len(registry.get_available_tools()) == 1

    @pytest.mark.asyncio
    async def test_empty_directory_raises(self, container, tmp_path: Path):
        tools_root = tmp_path / "tools"
        tools_root.mkdir()
        registry = DependencyInjectedToolRegistry(container, tools_dir=str(tools_root))

        with pytest.raises(ToolLoadingError, match="No tools loaded from directory"):
            await registry.load_tools_from_directory(str(tools_root))
