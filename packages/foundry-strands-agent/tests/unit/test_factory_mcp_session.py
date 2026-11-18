# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for factory MCP client collection and session management paths."""

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from foundry_agent_core import AgentCreationError, ExternalServiceError, InvalidConfigurationError
from foundry_strands_agent.config.models import AgentModelConfig, StrandsAgentConfig
from foundry_strands_agent.factory import StrandsAgentFactory, _destination_host, _interpolate_env_vars

# Fake, non-functional values used only to exercise destination-host redaction in logs.
FAKE_URL_CREDENTIAL = "super-secret"  # trufflehog:ignore
FAKE_URL_PASSWORD = "pass"  # trufflehog:ignore


@pytest.fixture
def factory():
    container = MagicMock()
    config = StrandsAgentConfig(model=AgentModelConfig())
    container.resolve.return_value = config
    return StrandsAgentFactory(container=container)


class TestCollectMcpClients:
    @pytest.mark.asyncio
    async def test_creates_mcp_client_per_server(self, factory):
        with patch("foundry_strands_agent.factory.ReconnectingMCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.return_value = MagicMock()
                servers = [{"url": "http://server1:8080"}, {"url": "http://server2:8080"}]
                result = await factory._collect_mcp_clients(servers)
                assert len(result) == 2

    @pytest.mark.asyncio
    async def test_raises_on_missing_url(self, factory):
        with pytest.raises(ExternalServiceError, match="Missing 'url'"):
            await factory._collect_mcp_clients([{"url": ""}])

    @pytest.mark.asyncio
    async def test_raises_on_connection_failure(self, factory):
        with patch("foundry_strands_agent.factory.ReconnectingMCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.side_effect = RuntimeError("connection refused")
                with pytest.raises(ExternalServiceError):
                    await factory._collect_mcp_clients([{"url": "http://bad:8080"}])

    @pytest.mark.asyncio
    async def test_connection_failure_never_puts_secret_in_raised_exception(self, factory, monkeypatch, caplog):
        """A real secret must never appear in the raised exception.

        It's logged under a correlation_id instead, and that same correlation_id is the only
        linkage back to it.
        """
        monkeypatch.setenv("GITHUB_PAT", "super-secret-value")
        with patch("foundry_strands_agent.factory.ReconnectingMCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.side_effect = RuntimeError("connect failed, sent super-secret-value")
                servers = [
                    {
                        "url": "https://bad:8080",
                        "headers": {"Authorization": "Bearer ${GITHUB_PAT}"},
                    }
                ]
                with caplog.at_level(logging.ERROR):
                    with pytest.raises(ExternalServiceError) as exc_info:
                        await factory._collect_mcp_clients(servers)

                # Never in the raised exception's message or context.
                assert "super-secret-value" not in str(exc_info.value)
                assert "super-secret-value" not in repr(exc_info.value.context)
                assert exc_info.value.__cause__ is None  # chain deliberately severed

                # The only linkage back to the real failure is the correlation_id.
                correlation_id = exc_info.value.context["correlation_id"]
                assert correlation_id
                assert correlation_id in caplog.text
                # Full detail (including the secret) is intentionally in the log, under that id.
                assert "super-secret-value" in caplog.text

    @pytest.mark.asyncio
    async def test_interpolates_header_env_var_before_client_creation(self, factory, monkeypatch):
        monkeypatch.setenv("GITHUB_PAT", "secret-token-value")
        with patch("foundry_strands_agent.factory.ReconnectingMCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.return_value = MagicMock()
                servers = [
                    {
                        "url": "https://server1:8080",
                        "headers": {"Authorization": "Bearer ${GITHUB_PAT}"},
                    }
                ]
                await factory._collect_mcp_clients(servers)

                transport_factory = mock_mcp.call_args.args[0]
                transport_factory()
                streamable_mock = __import__(
                    "foundry_strands_agent.factory", fromlist=["streamablehttp_client"]
                ).streamablehttp_client
                sent_headers = streamable_mock.call_args.kwargs["headers"]
                assert sent_headers == {"Authorization": "Bearer secret-token-value"}

    @pytest.mark.asyncio
    async def test_raises_on_undefined_header_env_var(self, factory, monkeypatch, caplog):
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        with patch("foundry_strands_agent.factory.ReconnectingMCPClient"):
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                servers = [
                    {
                        "url": "https://server1:8080",
                        "headers": {"Authorization": "Bearer ${GITHUB_PAT}"},
                    }
                ]
                with caplog.at_level(logging.ERROR):
                    with pytest.raises(ExternalServiceError) as exc_info:
                        await factory._collect_mcp_clients(servers)
                assert exc_info.value.context["server_name"] == "https://server1:8080"
                assert exc_info.value.context["server_url"] == "https://server1:8080"
                assert "env_var" not in exc_info.value.context
                # Detail (which env var) lives only in the log, under the correlation_id.
                assert exc_info.value.context["correlation_id"] in caplog.text
                assert "GITHUB_PAT" in caplog.text

    @pytest.mark.asyncio
    async def test_undefined_header_env_var_identifies_correct_server(self, factory, monkeypatch):
        """With multiple servers configured, the error must name the failing one."""
        monkeypatch.delenv("MISSING_TOKEN", raising=False)
        with patch("foundry_strands_agent.factory.ReconnectingMCPClient"):
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                servers = [
                    {"url": "http://server-a:8080", "name": "server-a"},
                    {
                        "url": "https://server-b:8080",
                        "name": "server-b",
                        "headers": {"Authorization": "Bearer ${MISSING_TOKEN}"},
                    },
                ]
                with pytest.raises(ExternalServiceError) as exc_info:
                    await factory._collect_mcp_clients(servers)
                assert exc_info.value.context["server_name"] == "server-b"
                assert exc_info.value.context["server_url"] == "https://server-b:8080"
                assert exc_info.value.context["correlation_id"]

    @pytest.mark.asyncio
    async def test_omitted_headers_still_create_client(self, factory):
        """Backward compatibility: servers with no 'headers' key behave exactly as before."""
        with patch("foundry_strands_agent.factory.ReconnectingMCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.return_value = MagicMock()
                result = await factory._collect_mcp_clients([{"url": "http://server1:8080"}])
                assert len(result) == 1

    @pytest.mark.asyncio
    async def test_logs_destination_host_per_server(self, factory, caplog):
        """V-222470: connecting to an MCP server logs its destination host."""
        with patch("foundry_strands_agent.factory.ReconnectingMCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.return_value = MagicMock()
                with caplog.at_level(logging.INFO):
                    await factory._collect_mcp_clients([{"url": "http://server1:8080/mcp"}])
                records = [r for r in caplog.records if r.getMessage() == "MCP client configured"]
                assert records
                assert records[0].destination_host == "http://server1:8080"

    @pytest.mark.asyncio
    async def test_destination_host_log_never_leaks_url_embedded_credential(self, factory, caplog):
        """A credential embedded in the server url's userinfo must never reach the log."""
        with patch("foundry_strands_agent.factory.ReconnectingMCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.return_value = MagicMock()
                with caplog.at_level(logging.INFO):
                    await factory._collect_mcp_clients([{"url": f"https://user:{FAKE_URL_CREDENTIAL}@server1:8080"}])
                assert FAKE_URL_CREDENTIAL not in caplog.text
                records = [r for r in caplog.records if r.getMessage() == "MCP client configured"]
                assert records[0].destination_host == "https://server1:8080"


class TestCollectMcpTools:
    @pytest.mark.asyncio
    async def test_logs_destination_host_not_raw_url(self, factory, caplog):
        """V-222470: the discovery-path log carries a destination host, not the raw server url."""
        mock_client = MagicMock()
        mock_client.list_tools_sync.return_value = []
        with patch("foundry_strands_agent.factory.MCPClient", return_value=mock_client):
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                with caplog.at_level(logging.INFO):
                    await factory._collect_mcp_tools([{"url": f"https://user:{FAKE_URL_CREDENTIAL}@server1:8080/mcp"}])
                assert FAKE_URL_CREDENTIAL not in caplog.text
                records = [
                    r for r in caplog.records if r.getMessage() == "Connected to MCP server and discovered tools"
                ]
                assert records
                assert records[0].destination_host == "https://server1:8080"
                assert not hasattr(records[0], "server_url")


class TestDestinationHost:
    def test_strips_userinfo_path_query_and_fragment(self):
        assert (
            _destination_host(f"http://user:{FAKE_URL_PASSWORD}@host.example:9000/path?q=1#frag")
            == "http://host.example:9000"
        )

    def test_no_port_omits_colon(self):
        assert _destination_host("https://host.example/mcp") == "https://host.example"

    def test_missing_hostname_is_invalid(self):
        assert _destination_host("not-a-url") == "invalid-url"

    def test_empty_string_is_invalid(self):
        assert _destination_host("") == "invalid-url"


class TestInterpolateEnvVars:
    def test_returns_none_for_none_input(self):
        assert _interpolate_env_vars(None) is None

    def test_returns_headers_unchanged_when_no_var_references(self):
        """Backward compatibility: literal header values without ${VAR} syntax pass through untouched."""
        headers = {"Authorization": "Bearer static-token", "X-Custom": "plain-value"}
        assert _interpolate_env_vars(headers) == headers

    def test_substitutes_single_env_var_reference(self, monkeypatch):
        monkeypatch.setenv("GITHUB_PAT", "abc123")
        result = _interpolate_env_vars({"Authorization": "Bearer ${GITHUB_PAT}"})
        assert result == {"Authorization": "Bearer abc123"}

    def test_substitutes_multiple_headers_independently(self, monkeypatch):
        monkeypatch.setenv("TOKEN_A", "value-a")
        monkeypatch.setenv("TOKEN_B", "value-b")
        result = _interpolate_env_vars({"X-A": "${TOKEN_A}", "X-B": "${TOKEN_B}"})
        assert result == {"X-A": "value-a", "X-B": "value-b"}

    def test_raises_external_service_error_on_undefined_var(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        with pytest.raises(ExternalServiceError, match="MISSING_VAR"):
            _interpolate_env_vars({"Authorization": "Bearer ${MISSING_VAR}"})

    def test_empty_headers_dict_returns_empty_dict(self):
        assert _interpolate_env_vars({}) == {}


class TestCreateSessionRepository:
    def test_no_session_type_returns_none(self, factory):
        factory._container.resolve.return_value = StrandsAgentConfig(model=AgentModelConfig())
        result = factory.create_session_repository()
        assert result is None

    def test_with_session_type_file(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig(), session_type="file")
        factory._container.resolve.return_value = config

        mock_sm = MagicMock()
        factory._session_manager_factories = {"file": lambda **kwargs: mock_sm}

        result = factory.create_session_repository()
        assert result is mock_sm

    def test_with_overrides(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig())
        factory._container.resolve.return_value = config

        mock_sm = MagicMock()
        factory._session_manager_factories = {"file": lambda **kwargs: mock_sm}

        result = factory.create_session_repository(config_overrides={"session_type": "file", "session_id": "session1"})
        assert result is mock_sm


class TestCreateSessionManagerInternal:
    def test_enum_type_normalized(self, factory):
        from foundry_strands_agent.config.models import StrandsSessionManagerType

        mock_sm = MagicMock()
        factory._session_manager_factories = {"file": lambda **kwargs: mock_sm}

        result = factory._create_session_manager(
            session_id="session1",
            session_type=StrandsSessionManagerType.FILE,
        )
        assert result is mock_sm

    def test_string_type_works(self, factory):
        mock_sm = MagicMock()
        factory._session_manager_factories = {"s3": lambda **kwargs: mock_sm}

        result = factory._create_session_manager(
            session_id="session1",
            session_type="s3",
            s3_bucket="bucket",
        )
        assert result is mock_sm


class TestMergeConfigOverrides:
    def test_model_deep_merge(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig(temperature=0.3))
        result = factory._merge_config_overrides(config, {"model": {"temperature": 0.9}})
        assert result["model"]["temperature"] == 0.9
        assert result["model"]["provider"] == "bedrock"

    def test_top_level_override(self, factory):
        config = StrandsAgentConfig(model=AgentModelConfig())
        result = factory._merge_config_overrides(config, {"system_prompt": "new prompt"})
        assert result["system_prompt"] == "new prompt"


async def _load_real_module(factory, tmp_path, monkeypatch, name: str, source: str) -> list:
    """Write `source` as module `name` under `tmp_path` and load it as `tools_modules` does."""
    import importlib
    import sys

    (tmp_path / f"{name}.py").write_text(source)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, name, raising=False)
    importlib.invalidate_caches()
    result = await factory._load_tools_from_modules([name], tools_dir=str(tmp_path))
    monkeypatch.delitem(sys.modules, name, raising=False)
    return result


class TestLoadToolsFromModules:
    @pytest.mark.asyncio
    async def test_tool_spec_module_is_the_tool(self, factory, tmp_path, monkeypatch):
        """A real TOOL_SPEC module (name, description, inputSchema, and its function) reaches the agent."""
        from strands.tools.registry import ToolRegistry

        result = await _load_real_module(
            factory,
            tmp_path,
            monkeypatch,
            "report_receipt",
            'TOOL_SPEC = {"name": "report_receipt", "description": "Submit a report.", '
            '"inputSchema": {"json": {"type": "object", "properties": {"content": {"type": "string"}}}}}\n\n\n'
            "def report_receipt(tool, **kwargs):\n"
            '    return {"toolUseId": tool["toolUseId"], "status": "success", "content": [{"text": "RECEIPT-1"}]}\n',
        )

        assert ToolRegistry().process_tools(result) == ["report_receipt"]

    @pytest.mark.asyncio
    async def test_decorated_tool_module_reaches_the_agent(self, factory, tmp_path, monkeypatch):
        """A real @tool module (loaded as a list of its tools) still reaches the agent."""
        from strands.tools.registry import ToolRegistry

        result = await _load_real_module(
            factory,
            tmp_path,
            monkeypatch,
            "marker_tools",
            "from strands import tool\n\n\n"
            "@tool\n"
            "def get_marker() -> str:\n"
            '    """Return the marker."""\n'
            '    return "MARKER-1"\n',
        )

        assert ToolRegistry().process_tools(result) == ["get_marker"]

    @pytest.mark.asyncio
    async def test_tool_spec_with_its_own_tools_list_still_loads_them(self, factory):
        """Backward compatible: a TOOL_SPEC that carries a "tools" list loads those tools, as before 3.2.2."""
        import types

        listed = MagicMock()
        module = types.ModuleType("multi_tools")
        module.TOOL_SPEC = {"name": "multi", "tools": [listed]}  # type: ignore[attr-defined]

        with patch("foundry_strands_agent.factory.load_tool_from_module", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = module
            result = await factory._load_tools_from_modules(["tools.multi_tools"])

        assert result == [listed]

    @pytest.mark.asyncio
    async def test_tool_spec_with_its_own_tools_tuple_still_loads_them(self, factory):
        """Backward compatible: a "tools" tuple loads its tools too, as before 3.2.2."""
        import types

        first, second = MagicMock(), MagicMock()
        module = types.ModuleType("report_bundle")
        module.TOOL_SPEC = {"name": "report_bundle", "tools": (first, second)}  # type: ignore[attr-defined]

        with patch("foundry_strands_agent.factory.load_tool_from_module", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = module
            result = await factory._load_tools_from_modules(["tools.report_bundle"])

        assert result == [first, second]

    @pytest.mark.asyncio
    async def test_handles_failed_module_gracefully(self, factory):
        with patch("foundry_strands_agent.factory.load_tool_from_module", new_callable=AsyncMock) as mock_load:
            mock_load.side_effect = ImportError("not found")
            result = await factory._load_tools_from_modules(["bad.module"])
            assert result == []


class TestDropRepeatedToolSpecModules:
    """Backward compatible: a TOOL_SPEC tool listed in both tools_modules and tools_files loads once."""

    def test_second_copy_of_the_same_file_is_skipped_with_a_warning(self, caplog, tmp_path):
        """The same file under two spellings of its path is one file: the later copy is skipped."""
        import types

        from foundry_strands_agent.factory import _drop_repeated_tool_spec_modules

        (tmp_path / "sub").mkdir()
        first, second = types.ModuleType("receipt_a"), types.ModuleType("receipt_b")
        first.TOOL_SPEC = {"name": "report_receipt"}  # type: ignore[attr-defined]
        second.TOOL_SPEC = {"name": "report_receipt"}  # type: ignore[attr-defined]
        first.__file__ = str(tmp_path / "report_receipt.py")
        second.__file__ = str(tmp_path / "sub" / ".." / "report_receipt.py")
        other = MagicMock(spec=["tool_name"])

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.factory"):
            kept = _drop_repeated_tool_spec_modules([first, other, second])

        assert kept == [first, other]
        assert "Skipping a second copy of TOOL_SPEC tool report_receipt from" in caplog.text

    def test_different_files_with_the_same_tool_name_are_both_kept(self, tmp_path):
        """Two files whose TOOL_SPECs share a name both load, as before 3.2.2."""
        import types

        from foundry_strands_agent.factory import _drop_repeated_tool_spec_modules

        first, second = types.ModuleType("receipt_a"), types.ModuleType("receipt_b")
        first.TOOL_SPEC = {"name": "report_receipt"}  # type: ignore[attr-defined]
        second.TOOL_SPEC = {"name": "report_receipt"}  # type: ignore[attr-defined]
        first.__file__ = str(tmp_path / "receipt_a.py")
        second.__file__ = str(tmp_path / "receipt_b.py")

        assert _drop_repeated_tool_spec_modules([first, second]) == [first, second]

    def test_tool_spec_modules_without_a_file_are_kept(self):
        """A module with no file to compare is never dropped."""
        import types

        from foundry_strands_agent.factory import _drop_repeated_tool_spec_modules

        first, second = types.ModuleType("receipt_a"), types.ModuleType("receipt_b")
        first.TOOL_SPEC = {"name": "report_receipt"}  # type: ignore[attr-defined]
        second.TOOL_SPEC = {"name": "report_receipt"}  # type: ignore[attr-defined]

        assert _drop_repeated_tool_spec_modules([first, second]) == [first, second]

    @pytest.mark.asyncio
    async def test_one_file_in_both_settings_registers_once(self, factory, tmp_path, monkeypatch):
        """The same real TOOL_SPEC file in tools_modules and tools_files: Strands gets one tool, not two."""
        from strands.tools.registry import ToolRegistry

        from foundry_strands_agent.factory import _drop_repeated_tool_spec_modules

        source = (
            'TOOL_SPEC = {"name": "report_receipt", "description": "Submit a report.", '
            '"inputSchema": {"json": {"type": "object", "properties": {"content": {"type": "string"}}}}}\n\n\n'
            "def report_receipt(tool, **kwargs):\n"
            '    return {"toolUseId": tool["toolUseId"], "status": "success", "content": [{"text": "RECEIPT-1"}]}\n'
        )
        from_modules = await _load_real_module(factory, tmp_path, monkeypatch, "report_receipt", source)
        from_files = await factory._load_tools_from_files(
            [str(tmp_path / "report_receipt.py")], tools_dir=str(tmp_path)
        )

        assert len(from_modules + from_files) == 2
        assert ToolRegistry().process_tools(_drop_repeated_tool_spec_modules(from_modules + from_files)) == [
            "report_receipt"
        ]

    def test_distinct_tools_are_all_kept(self, tmp_path):
        import types

        from foundry_strands_agent.factory import _drop_repeated_tool_spec_modules

        first, second = types.ModuleType("a"), types.ModuleType("b")
        first.TOOL_SPEC = {"name": "a"}  # type: ignore[attr-defined]
        second.TOOL_SPEC = {"name": "b"}  # type: ignore[attr-defined]
        first.__file__ = str(tmp_path / "a.py")
        second.__file__ = str(tmp_path / "b.py")

        assert _drop_repeated_tool_spec_modules([first, second]) == [first, second]


def _module_from_source(path, source: str):
    """Write ``source`` to ``path`` and import it under the file's stem, as tools_files does."""
    import importlib.util

    path.write_text(source)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TOOL_SPEC_SOURCE = """
TOOL_SPEC = {{
    "name": "{name}",
    "description": "Get the weather.",
    "inputSchema": {{"json": {{"type": "object", "properties": {{}}}}}},
}}


def {name}(tool, **kwargs):
    return {{"toolUseId": tool["toolUseId"], "status": "success", "content": [{{"text": "sunny"}}]}}
"""


class TestDropToolSpecModulesStrandsCannotLoad:
    """A TOOL_SPEC module Strands would reject or misname is skipped with an error, so the agent starts."""

    def test_no_function_named_after_the_file_is_skipped(self, caplog, tmp_path):
        """weather.py with only get_weather passes our loader, but Strands rejects it: skip it."""
        from strands.tools.registry import ToolRegistry

        from foundry_strands_agent.factory import _drop_tool_spec_modules_strands_cannot_load

        module = _module_from_source(tmp_path / "weather.py", _TOOL_SPEC_SOURCE.format(name="get_weather"))
        other = MagicMock(spec=["tool_name"])

        with pytest.raises(ValueError, match="missing function weather"):
            ToolRegistry().process_tools([module])  # what Strands does with it unfiltered

        with caplog.at_level(logging.ERROR, logger="foundry_strands_agent.factory"):
            kept = _drop_tool_spec_modules_strands_cannot_load([module, other])

        assert kept == [other]
        assert "Skipping tool module weather from" in caplog.text
        assert "Strands cannot load it" in caplog.text

    def test_file_name_that_differs_from_the_tool_spec_name_is_skipped(self, caplog, tmp_path):
        """With a weather alias Strands loads it, but as 'weather' while the model is told 'get_weather'."""
        from strands.tools.registry import ToolRegistry

        from foundry_strands_agent.factory import _drop_tool_spec_modules_strands_cannot_load

        source = _TOOL_SPEC_SOURCE.format(name="get_weather") + "\nweather = get_weather\n"
        module = _module_from_source(tmp_path / "weather.py", source)

        registry = ToolRegistry()
        registry.process_tools([module])  # Strands accepts it unfiltered...
        assert registry.registry["weather"].tool_spec["name"] == "get_weather"  # ...under the wrong name

        with caplog.at_level(logging.ERROR, logger="foundry_strands_agent.factory"):
            assert _drop_tool_spec_modules_strands_cannot_load([module]) == []
        assert "Skipping TOOL_SPEC tool get_weather from" in caplog.text
        assert "Rename the file to get_weather.py" in caplog.text

    def test_empty_tool_spec_is_skipped(self, caplog, tmp_path):
        """Strands rejects a falsy TOOL_SPEC, which would fail Agent() for every tool."""
        from foundry_strands_agent.factory import _drop_tool_spec_modules_strands_cannot_load

        module = _module_from_source(
            tmp_path / "weather.py", "TOOL_SPEC = {}\n\n\ndef weather(tool, **kwargs):\n    pass\n"
        )

        with caplog.at_level(logging.ERROR, logger="foundry_strands_agent.factory"):
            assert _drop_tool_spec_modules_strands_cannot_load([module]) == []
        assert "Strands cannot load it" in caplog.text

    def test_matching_names_are_kept_and_strands_loads_them(self, tmp_path):
        from strands.tools.registry import ToolRegistry

        from foundry_strands_agent.factory import _drop_tool_spec_modules_strands_cannot_load

        matching = _module_from_source(tmp_path / "weather.py", _TOOL_SPEC_SOURCE.format(name="weather"))

        kept = _drop_tool_spec_modules_strands_cannot_load([matching])

        assert kept == [matching]
        assert ToolRegistry().process_tools(kept) == ["weather"]

    def test_tool_decorated_functions_win_over_a_mismatched_tool_spec(self, tmp_path):
        """Strands loads a module's @tool functions in place of its TOOL_SPEC, so nothing is skipped."""
        from strands.tools.registry import ToolRegistry

        from foundry_strands_agent.factory import _drop_tool_spec_modules_strands_cannot_load

        source = _TOOL_SPEC_SOURCE.format(name="get_weather") + (
            "\n\nfrom strands import tool\n\n\n@tool\ndef forecast() -> str:\n"
            '    """Get the forecast."""\n    return "rain"\n'
        )
        module = _module_from_source(tmp_path / "weather.py", source)

        kept = _drop_tool_spec_modules_strands_cannot_load([module])

        assert kept == [module]
        assert ToolRegistry().process_tools(kept) == ["forecast"]

    def test_tool_spec_modules_without_a_file_are_kept(self):
        """Strands does not load a module with no file as a module tool, so there is nothing to check."""
        import types

        from foundry_strands_agent.factory import _drop_tool_spec_modules_strands_cannot_load

        module = types.ModuleType("weather")
        module.TOOL_SPEC = {"name": "get_weather"}  # type: ignore[attr-defined]

        assert _drop_tool_spec_modules_strands_cannot_load([module]) == [module]


class TestSameNamedModuleToolsFollowStrands:
    """Two different files with the same file name are both passed on, and Strands keeps the later one.

    This pins Strands 1.57.0's behavior, which the factory keeps instead of a check of its own: a
    module tool is named after its file, and a later tool with the same name replaces the earlier one
    (PythonAgentTool supports hot reload). Tools are collected tools=, then tools_modules, then
    tools_files, so a tools_files copy wins, which is the copy 3.2.1 loaded.
    """

    def test_strands_keeps_the_later_of_two_files_with_the_same_file_name(self, tmp_path):
        from strands.tools.registry import ToolRegistry

        from foundry_strands_agent.factory import _drop_repeated_tool_spec_modules

        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        source = _TOOL_SPEC_SOURCE.format(name="receipt")
        first = _module_from_source(tmp_path / "a" / "receipt.py", source)
        second = _module_from_source(
            tmp_path / "b" / "receipt.py", source.replace("Get the weather.", "The later receipt.")
        )

        kept = _drop_repeated_tool_spec_modules([first, second])
        registry = ToolRegistry()
        registry.process_tools(kept)

        assert kept == [first, second]
        assert list(registry.registry) == ["receipt"]
        assert registry.registry["receipt"].tool_spec["description"] == "The later receipt."


class TestWarnAboutToolNameOverwrites:
    """Strands keeps the later of two same-named tools; the factory keeps that and warns about it."""

    def test_two_files_with_the_same_file_name_warn(self, caplog, tmp_path):
        from foundry_strands_agent.factory import _warn_about_tool_name_overwrites

        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        first = _module_from_source(tmp_path / "a" / "receipt.py", _TOOL_SPEC_SOURCE.format(name="receipt"))
        second = _module_from_source(tmp_path / "b" / "receipt.py", _TOOL_SPEC_SOURCE.format(name="receipt"))

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.factory"):
            _warn_about_tool_name_overwrites([first, second])

        assert "Tool name 'receipt' comes from" in caplog.text
        assert "Strands keeps only the last one" in caplog.text
        assert str((tmp_path / "b" / "receipt.py").resolve()).lower() in caplog.text.lower()

    def test_a_tool_function_and_a_tool_spec_module_with_the_same_name_warn(self, caplog, tmp_path):
        """A caller's @tool weather and a TOOL_SPEC weather.py both reach Strands; the module wins."""
        from strands import tool

        from foundry_strands_agent.factory import _warn_about_tool_name_overwrites

        @tool
        def weather() -> str:
            """Get the weather."""
            return "cloudy"

        module = _module_from_source(tmp_path / "weather.py", _TOOL_SPEC_SOURCE.format(name="weather"))

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.factory"):
            _warn_about_tool_name_overwrites([weather, module])

        assert "Tool name 'weather' comes from" in caplog.text

    def test_a_tool_reached_again_after_another_is_reported_as_kept(self, caplog, tmp_path):
        """For [A, B, A] Strands keeps the last A, so the warning names A, not B."""
        from strands.tools.registry import ToolRegistry

        from foundry_strands_agent.factory import _warn_about_tool_name_overwrites

        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        source = _TOOL_SPEC_SOURCE.format(name="receipt")
        first = _module_from_source(tmp_path / "a" / "receipt.py", source)
        second = _module_from_source(tmp_path / "b" / "receipt.py", source.replace("Get the weather.", "B."))

        registry = ToolRegistry()
        registry.process_tools([first, second, first])
        assert registry.registry["receipt"].tool_spec["description"] == "Get the weather."  # Strands keeps A

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.factory"):
            _warn_about_tool_name_overwrites([first, second, first])

        kept = os.path.normcase(str((tmp_path / "a" / "receipt.py").resolve()))
        assert f"Strands keeps only the last one ({kept})" in caplog.text

    def test_the_same_tool_reached_twice_does_not_warn(self, caplog, tmp_path):
        """The registry and config can pass the same module again; that is one tool, not a clash."""
        from foundry_strands_agent.factory import _warn_about_tool_name_overwrites

        module = _module_from_source(tmp_path / "receipt.py", _TOOL_SPEC_SOURCE.format(name="receipt"))

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.factory"):
            _warn_about_tool_name_overwrites([module, module])

        assert "comes from" not in caplog.text

    def test_distinct_names_do_not_warn(self, caplog, tmp_path):
        from foundry_strands_agent.factory import _warn_about_tool_name_overwrites

        first = _module_from_source(tmp_path / "receipt.py", _TOOL_SPEC_SOURCE.format(name="receipt"))
        second = _module_from_source(tmp_path / "weather.py", _TOOL_SPEC_SOURCE.format(name="weather"))

        with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.factory"):
            _warn_about_tool_name_overwrites([first, second, MagicMock(spec=["tool_name"])])

        assert "comes from" not in caplog.text


class TestLoadToolsFromFiles:
    @pytest.mark.asyncio
    async def test_loads_file_tool(self, factory):
        mock_tool = MagicMock()
        with patch("foundry_strands_agent.factory.load_tool_from_file", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = mock_tool
            result = await factory._load_tools_from_files(["./tools/weather.py"])
            assert mock_tool in result

    @pytest.mark.asyncio
    async def test_handles_failed_file_gracefully(self, factory):
        with patch("foundry_strands_agent.factory.load_tool_from_file", new_callable=AsyncMock) as mock_load:
            mock_load.side_effect = FileNotFoundError("no such file")
            result = await factory._load_tools_from_files(["./bad.py"])
            assert result == []


_UNSAFE_MCP_SERVER = {"url": "http://evil.example.com/mcp", "headers": {"Authorization": "Bearer super-secret-token"}}
# _collect_mcp_clients builds the reconnecting client the builder shares; _collect_mcp_tools builds a plain one.
_CLIENT_CLASS_BY_COLLECTOR = {"_collect_mcp_clients": "ReconnectingMCPClient", "_collect_mcp_tools": "MCPClient"}


class TestMcpCollectorCredentialGuard:
    """The plaintext-credential guard is enforced where MCP connections are opened.

    `_collect_mcp_clients`/`_collect_mcp_tools` apply it to every server list they receive,
    so an MCP server that never passed through StrandsAgentConfig's field validators (e.g.
    `create_agent_with_mcp_clients`'s caller-supplied `mcp_servers` parameter) is covered.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("collector", ["_collect_mcp_clients", "_collect_mcp_tools"])
    async def test_collector_rejects_unsafe_server_before_connecting(self, factory, collector):
        with patch(f"foundry_strands_agent.factory.{_CLIENT_CLASS_BY_COLLECTOR[collector]}") as mock_mcp:
            with pytest.raises(InvalidConfigurationError) as exc_info:
                await getattr(factory, collector)([_UNSAFE_MCP_SERVER])

        mock_mcp.assert_not_called()
        assert "super-secret-token" not in str(exc_info.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("collector", ["_collect_mcp_clients", "_collect_mcp_tools"])
    async def test_collector_rejects_non_mapping_headers(self, factory, collector):
        server = {"url": "http://example.com/mcp", "headers": [["Authorization", "Bearer super-secret-token"]]}
        with patch(f"foundry_strands_agent.factory.{_CLIENT_CLASS_BY_COLLECTOR[collector]}") as mock_mcp:
            with pytest.raises(InvalidConfigurationError) as exc_info:
                await getattr(factory, collector)([server])

        mock_mcp.assert_not_called()
        assert "super-secret-token" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_collector_honors_deployer_opt_in(self, factory, caplog):
        factory._container.resolve.return_value = StrandsAgentConfig(allow_insecure_credentialed_endpoints=True)
        with patch("foundry_strands_agent.factory.ReconnectingMCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.return_value = MagicMock()
                with caplog.at_level(logging.WARNING, logger="foundry_strands_agent.config.models"):
                    result = await factory._collect_mcp_clients([_UNSAFE_MCP_SERVER])

        assert len(result) == 1
        assert any("insecure" in record.message.lower() for record in caplog.records)
        assert "super-secret-token" not in caplog.text

    @pytest.mark.asyncio
    async def test_unsafe_mcp_servers_parameter_raises(self, factory):
        with patch("foundry_strands_agent.factory.MCPClient") as mock_mcp:
            with pytest.raises(AgentCreationError) as exc_info:
                await factory.create_agent_with_mcp_clients(mcp_servers=[_UNSAFE_MCP_SERVER])

        mock_mcp.assert_not_called()
        assert isinstance(exc_info.value.__cause__, InvalidConfigurationError)
        assert "super-secret-token" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_safe_mcp_servers_parameter_is_unaffected(self, factory):
        with patch("foundry_strands_agent.factory.MCPClient") as mock_mcp:
            with patch("foundry_strands_agent.factory.streamablehttp_client"):
                mock_mcp.return_value = MagicMock()
                with patch.object(StrandsAgentFactory, "create_model", return_value=MagicMock()):
                    with patch("foundry_strands_agent.factory.Agent") as mock_agent:
                        mock_agent.return_value = MagicMock()
                        await factory.create_agent_with_mcp_clients(
                            mcp_servers=[{"url": "https://safe.example.com/mcp"}]
                        )

        mock_agent.assert_called_once()
