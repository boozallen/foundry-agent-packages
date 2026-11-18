# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for Bedrock Knowledge Base MCP Server."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from foundry_aws_utilities import create_bedrock_kb_mcp_server
from foundry_aws_utilities._validation import MAX_KB_ID_LENGTH, MAX_QUERY_LENGTH

FASTMCP_FORBIDDEN_KWARGS = {"host", "port", "streamable_http_path", "stateless_http", "json_response"}


def _fastmcp_mock_reject_deprecated(*args, **kwargs):
    bad = FASTMCP_FORBIDDEN_KWARGS & set(kwargs)
    if bad:
        raise TypeError(f"FastMCP() no longer accepts `{next(iter(bad))}`. Pass it to run() or set env.")
    return MagicMock()


def _call_tool_text(server, tool_name: str, arguments: dict) -> str:
    result = asyncio.run(server.server.call_tool(tool_name, arguments))
    return result.content[0].text


class TestBedrockKBMCPServer:
    def test_create_server_with_defaults(self):
        with patch("foundry_aws_utilities.bedrock_kb_mcp_server.boto3"):
            server = create_bedrock_kb_mcp_server()
        assert server is not None
        assert server.knowledge_base_id == ""

    def test_fastmcp_called_without_deprecated_kwargs(self):
        with patch("foundry_aws_utilities.bedrock_kb_mcp_server.boto3"):
            with patch(
                "foundry_aws_utilities.bedrock_kb_mcp_server.FastMCP",
                side_effect=_fastmcp_mock_reject_deprecated,
            ):
                server = create_bedrock_kb_mcp_server()
        assert server is not None

    def test_create_server_with_custom_config(self):
        with patch("foundry_aws_utilities.bedrock_kb_mcp_server.boto3"):
            server = create_bedrock_kb_mcp_server(
                aws_access_key_id="test-key",
                aws_secret_access_key="test-secret",  # noqa: S106
                region_name="us-west-2",
                knowledge_base_id="test-kb-id",
            )
        assert server is not None
        assert server.knowledge_base_id == "test-kb-id"

    @patch("foundry_aws_utilities.bedrock_kb_mcp_server.boto3")
    def test_server_initialization(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_session.client.return_value = MagicMock()

        server = create_bedrock_kb_mcp_server()
        assert server is not None
        mock_boto3.Session.assert_called_once()
        assert mock_session.client.call_count >= 2

    def test_run_method_exists(self):
        with patch("foundry_aws_utilities.bedrock_kb_mcp_server.boto3"):
            server = create_bedrock_kb_mcp_server()
        assert hasattr(server, "run")
        assert callable(server.run)

    @patch("foundry_aws_utilities.bedrock_kb_mcp_server.boto3")
    def test_knowledge_base_id_from_env(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_session.client.return_value = MagicMock()

        with patch.dict("os.environ", {"BEDROCK_KNOWLEDGE_BASE_ID": "kb-123"}, clear=False):
            server = create_bedrock_kb_mcp_server()
        assert server.knowledge_base_id == "kb-123"

    @patch("foundry_aws_utilities.bedrock_kb_mcp_server.boto3")
    def test_health_route_returns_healthy(self, mock_boto3):
        mock_session = MagicMock()
        mock_session.region_name = "us-east-1"
        mock_boto3.Session.return_value = mock_session
        mock_session.client.return_value = MagicMock()

        server = create_bedrock_kb_mcp_server()
        app = server.server.http_app()
        from starlette.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "Bedrock" in data["server"]


class TestBedrockKBTools:
    @pytest.fixture
    def server_with_mocks(self):
        with patch("foundry_aws_utilities.bedrock_kb_mcp_server.boto3") as mock_boto3:
            mock_session = MagicMock()
            mock_session.region_name = "us-east-1"
            mock_boto3.Session.return_value = mock_session
            mock_runtime = MagicMock()
            mock_agent = MagicMock()
            mock_session.client.side_effect = [mock_runtime, mock_agent]
            server = create_bedrock_kb_mcp_server(knowledge_base_id="kb-test-123")
        return server, mock_runtime, mock_agent

    def test_retrieve_no_kb_id_returns_error(self):
        with patch("foundry_aws_utilities.bedrock_kb_mcp_server.boto3") as mock_boto3:
            mock_session = MagicMock()
            mock_boto3.Session.return_value = mock_session
            mock_session.client.return_value = MagicMock()
            server = create_bedrock_kb_mcp_server(knowledge_base_id="")

        text = _call_tool_text(server, "bedrock_kb_retrieve", {"query": "test query"})
        assert "knowledge_base_id is required" in text

    def test_retrieve_empty_query_returns_error(self, server_with_mocks):
        server, _, _ = server_with_mocks
        text = _call_tool_text(server, "bedrock_kb_retrieve", {"query": "   "})
        assert "must be non-empty" in text

    def test_retrieve_success(self, server_with_mocks):
        server, mock_runtime, _ = server_with_mocks
        mock_runtime.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "sample chunk"},
                    "location": {"type": "S3", "s3Location": {"uri": "s3://bucket/key"}},
                    "score": 0.95,
                }
            ]
        }
        text = _call_tool_text(server, "bedrock_kb_retrieve", {"query": "find something"})
        assert "sample chunk" in text

    def test_retrieve_client_error(self, server_with_mocks):
        server, mock_runtime, _ = server_with_mocks
        mock_runtime.retrieve.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Not authorized"}},
            "Retrieve",
        )
        text = _call_tool_text(server, "bedrock_kb_retrieve", {"query": "test"})
        assert "Not authorized" in text

    def test_retrieve_generic_exception(self, server_with_mocks):
        server, mock_runtime, _ = server_with_mocks
        mock_runtime.retrieve.side_effect = RuntimeError("connection timeout")
        text = _call_tool_text(server, "bedrock_kb_retrieve", {"query": "test"})
        assert "connection timeout" in text

    # STIG V-222612: string-length bounds

    def test_retrieve_oversized_query_rejected(self, server_with_mocks):
        server, mock_runtime, _ = server_with_mocks
        oversized_query = "q" * (MAX_QUERY_LENGTH + 1)

        text = _call_tool_text(server, "bedrock_kb_retrieve", {"query": oversized_query})
        assert "exceeds maximum length" in text
        mock_runtime.retrieve.assert_not_called()

    def test_retrieve_oversized_kb_id_rejected(self, server_with_mocks):
        server, mock_runtime, _ = server_with_mocks
        oversized_kb_id = "k" * (MAX_KB_ID_LENGTH + 1)

        text = _call_tool_text(server, "bedrock_kb_retrieve", {"query": "test", "knowledge_base_id": oversized_kb_id})
        assert "exceeds maximum length" in text
        mock_runtime.retrieve.assert_not_called()

    def test_list_knowledge_bases_success(self, server_with_mocks):
        server, _, mock_agent = server_with_mocks
        mock_agent.list_knowledge_bases.return_value = {
            "knowledgeBaseSummaries": [
                {
                    "knowledgeBaseId": "kb-001",
                    "name": "My KB",
                    "description": "Test",
                    "status": "ACTIVE",
                }
            ]
        }
        text = _call_tool_text(server, "list_knowledge_bases", {"max_results": 5})
        assert "kb-001" in text

    def test_list_knowledge_bases_client_error(self, server_with_mocks):
        server, _, mock_agent = server_with_mocks
        mock_agent.list_knowledge_bases.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Forbidden"}},
            "ListKnowledgeBases",
        )
        text = _call_tool_text(server, "list_knowledge_bases", {"max_results": 5})
        assert "Forbidden" in text

    def test_list_knowledge_bases_generic_exception(self, server_with_mocks):
        server, _, mock_agent = server_with_mocks
        mock_agent.list_knowledge_bases.side_effect = RuntimeError("network issue")
        text = _call_tool_text(server, "list_knowledge_bases", {"max_results": 5})
        assert "network issue" in text

    @patch("foundry_aws_utilities.bedrock_kb_mcp_server.create_bedrock_kb_mcp_server")
    @patch("signal.signal")
    @patch("builtins.print")
    def test_main_function(self, mock_print, mock_signal, mock_create_server):
        from foundry_aws_utilities.bedrock_kb_mcp_server import main

        mock_server_instance = MagicMock()
        mock_server_instance.run = MagicMock(side_effect=KeyboardInterrupt())
        mock_create_server.return_value = mock_server_instance

        main()

        mock_create_server.assert_called_once()
        mock_server_instance.run.assert_called_with(transport="streamable-http")
        assert mock_signal.call_count >= 2
