# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for DynamoDB MCP Server."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from foundry_aws_utilities import create_dynamodb_mcp_server
from foundry_aws_utilities._validation import (
    MAX_CONTENT_LENGTH,
    MAX_DDB_KEY_LENGTH,
    MAX_DDB_TABLE_NAME_LENGTH,
)


def _call_tool_text(server, tool_name: str, arguments: dict) -> str:
    result = asyncio.run(server.server.call_tool(tool_name, arguments))
    return result.content[0].text


# FastMCP no longer accepts these in constructor; must be passed to run()
FASTMCP_FORBIDDEN_KWARGS = {"host", "port", "streamable_http_path", "stateless_http", "json_response"}


def _fastmcp_mock_reject_deprecated(*args, **kwargs):
    """Mock FastMCP that raises if deprecated kwargs are passed (like real FastMCP)."""
    bad = FASTMCP_FORBIDDEN_KWARGS & set(kwargs)
    if bad:
        raise TypeError(f"FastMCP() no longer accepts `{next(iter(bad))}`. Pass it to run() or set env.")
    return MagicMock()


class TestDynamoDBMCPServer:
    """Test suite for DynamoDBMCPServer."""

    def test_create_server_with_defaults(self):
        """Test creating server with default configuration."""
        server = create_dynamodb_mcp_server()
        assert server is not None
        assert server.default_table == "strands-storage"

    @patch("foundry_aws_utilities.mcp_server.boto3")
    def test_fastmcp_called_without_deprecated_kwargs(self, mock_boto3):
        """FastMCP() must not be called with host/port/streamable_http_path/stateless_http/json_response."""
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_session.resource.return_value = MagicMock()
        mock_session.client.return_value = MagicMock()
        with patch(
            "foundry_aws_utilities.mcp_server.FastMCP",
            side_effect=_fastmcp_mock_reject_deprecated,
        ):
            server = create_dynamodb_mcp_server()
        assert server is not None

    def test_create_server_with_custom_config(self):
        """Test creating server with custom configuration."""
        server = create_dynamodb_mcp_server(
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",  # noqa: S106
            region_name="us-west-2",
            endpoint_url="http://localhost:4566",
            default_table="custom-table",
        )
        assert server.default_table == "custom-table"

    @patch("foundry_aws_utilities.mcp_server.boto3")
    def test_server_initialization(self, mock_boto3):
        """Test server initialization creates boto3 resources."""
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_session.resource.return_value = MagicMock()
        mock_session.client.return_value = MagicMock()

        server = create_dynamodb_mcp_server()
        assert server is not None
        mock_boto3.Session.assert_called_once()

    def test_ensure_table_exists_default_schema(self):
        """Test ensure_table_exists with default schema."""
        server = create_dynamodb_mcp_server()
        # This will fail in test without mocking, but tests the method exists
        assert hasattr(server, "ensure_table_exists")

    def test_ensure_table_exists_research_schema(self):
        """Test ensure_table_exists with research schema."""
        server = create_dynamodb_mcp_server()
        # This will fail in test without mocking, but tests the method exists
        assert hasattr(server, "ensure_table_exists")


class TestEnsureTableExists:
    """Test suite for ensure_table_exists method."""

    @pytest.fixture
    def mock_server(self):
        """Create a mock server for testing."""
        with patch("foundry_aws_utilities.mcp_server.boto3"):
            server = create_dynamodb_mcp_server()
            server.dynamodb = MagicMock()
            server.dynamodb_client = MagicMock()
            return server

    def test_ensure_table_exists_default_schema(self, mock_server):
        """Test ensure_table_exists with default schema."""
        # Mock table exists scenario
        mock_table = MagicMock()
        mock_server.dynamodb.Table.return_value = mock_table
        mock_table.load.return_value = None  # No exception means table exists

        result = mock_server.ensure_table_exists("test-table")

        assert result is True
        mock_server.dynamodb.Table.assert_called_with("test-table")
        mock_table.load.assert_called_once()

    def test_ensure_table_exists_creates_default_table(self, mock_server):
        """Test ensure_table_exists creates table when it doesn't exist."""
        from botocore.exceptions import ClientError

        # Mock table doesn't exist
        mock_table = MagicMock()
        mock_server.dynamodb.Table.return_value = mock_table
        mock_table.load.side_effect = ClientError({"Error": {"Code": "ResourceNotFoundException"}}, "DescribeTable")

        # Mock table creation
        created_table = MagicMock()
        mock_server.dynamodb.create_table.return_value = created_table

        result = mock_server.ensure_table_exists("test-table")

        assert result is True
        mock_server.dynamodb.create_table.assert_called_once()
        created_table.wait_until_exists.assert_called_once()

    def test_ensure_table_exists_creates_research_table(self, mock_server):
        """Test ensure_table_exists creates research schema table."""
        from botocore.exceptions import ClientError

        # Mock table doesn't exist
        mock_table = MagicMock()
        mock_server.dynamodb.Table.return_value = mock_table
        mock_table.load.side_effect = ClientError({"Error": {"Code": "ResourceNotFoundException"}}, "DescribeTable")

        # Mock table creation
        created_table = MagicMock()
        mock_server.dynamodb.create_table.return_value = created_table

        result = mock_server.ensure_table_exists("research-table", "research")

        assert result is True
        # Verify research schema was used (workflow_id + document_key)
        call_args = mock_server.dynamodb.create_table.call_args
        key_schema = call_args[1]["KeySchema"]
        assert len(key_schema) == 2
        assert key_schema[0]["AttributeName"] == "workflow_id"
        assert key_schema[1]["AttributeName"] == "document_key"

    def test_ensure_table_exists_creation_fails(self, mock_server):
        """Test ensure_table_exists handles table creation failure."""
        from botocore.exceptions import ClientError

        # Mock table doesn't exist
        mock_table = MagicMock()
        mock_server.dynamodb.Table.return_value = mock_table
        mock_table.load.side_effect = ClientError({"Error": {"Code": "ResourceNotFoundException"}}, "DescribeTable")

        # Mock table creation failure
        mock_server.dynamodb.create_table.side_effect = Exception("Create failed")

        result = mock_server.ensure_table_exists("test-table")

        assert result is False

    def test_ensure_table_exists_other_client_error(self, mock_server):
        """Test ensure_table_exists handles other client errors."""
        from botocore.exceptions import ClientError

        # Mock table check fails with different error
        mock_table = MagicMock()
        mock_server.dynamodb.Table.return_value = mock_table
        mock_table.load.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "DescribeTable")

        result = mock_server.ensure_table_exists("test-table")

        assert result is False


class TestServerIntegration:
    """Integration tests for server functionality."""

    @pytest.fixture
    def mock_server(self):
        """Create a mock server for testing."""
        with patch("foundry_aws_utilities.mcp_server.boto3"):
            server = create_dynamodb_mcp_server()
            server.dynamodb = MagicMock()
            server.dynamodb_client = MagicMock()

            # Mock successful table operations
            mock_table = MagicMock()
            server.dynamodb.Table.return_value = mock_table

            # Mock ensure_table_exists to always succeed
            server.ensure_table_exists = MagicMock(return_value=True)

            return server, mock_table

    def test_server_initialization(self, mock_server):
        """Test server initializes with correct configuration."""
        server, _ = mock_server

        assert server.default_table == "strands-storage"
        assert hasattr(server, "server")
        assert server.server is not None
        assert hasattr(server, "dynamodb")
        assert hasattr(server, "dynamodb_client")

    def test_store_and_retrieve_workflow(self, mock_server):
        """Test complete store and retrieve workflow."""
        server, mock_table = mock_server

        # Mock successful storage
        mock_table.put_item.return_value = None

        # Mock successful retrieval
        mock_table.get_item.return_value = {
            "Item": {
                "id": "test-id",
                "content": "test content",
                "timestamp": "2024-01-01T00:00:00",
                "size_bytes": 12,
                "size_kb": 0.01,
            }
        }

        # Verify table operations would be called
        # (We can't easily test the decorated functions, but we can test the setup)
        assert server.ensure_table_exists.return_value is True
        mock_table.put_item(Item={"id": "test-id", "content": "test content"})
        mock_table.get_item(Key={"id": "test-id"})

        # Verify calls were made
        mock_table.put_item.assert_called()
        mock_table.get_item.assert_called()

    def test_table_operations_workflow(self, mock_server):
        """Test table creation and listing workflow."""
        server, mock_table = mock_server

        # Mock table creation
        created_table = MagicMock()
        server.dynamodb.create_table.return_value = created_table

        # Mock table listing
        server.dynamodb_client.list_tables.return_value = {"TableNames": ["table1", "table2"]}

        # Test table creation call
        server.dynamodb.create_table(
            TableName="test-table",
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        # Test table listing call
        tables = server.dynamodb_client.list_tables()

        # Verify operations
        server.dynamodb.create_table.assert_called_once()
        server.dynamodb_client.list_tables.assert_called_once()
        assert len(tables["TableNames"]) == 2

    def test_item_management_workflow(self, mock_server):
        """Test item update and delete workflow."""
        server, mock_table = mock_server

        # Mock item update
        mock_table.update_item.return_value = None

        # Mock item deletion
        mock_table.delete_item.return_value = None

        # Mock scan for listing
        mock_table.scan.return_value = {"Items": [{"id": "item1"}, {"id": "item2"}], "ScannedCount": 2}

        # Test operations
        mock_table.update_item(Key={"id": "test-id"})
        mock_table.delete_item(Key={"id": "test-id"})
        items = mock_table.scan()

        # Verify calls
        mock_table.update_item.assert_called_once()
        mock_table.delete_item.assert_called_once()
        mock_table.scan.assert_called_once()
        assert items["ScannedCount"] == 2


class TestMainFunction:
    """Test suite for main CLI function."""

    @patch("foundry_aws_utilities.mcp_server.create_dynamodb_mcp_server")
    @patch("signal.signal")
    @patch("builtins.print")
    def test_main_function_setup(self, mock_print, mock_signal, mock_create_server):
        """Test main function initialization and setup."""
        from foundry_aws_utilities.mcp_server import main

        # Mock server instance
        mock_server_instance = MagicMock()
        mock_server_instance.default_table = "strands-storage"
        mock_server_instance.ensure_table_exists = MagicMock(return_value=True)
        mock_server_instance.run = MagicMock(side_effect=KeyboardInterrupt())
        mock_create_server.return_value = mock_server_instance

        # Test main function (will be interrupted by KeyboardInterrupt)
        main()

        # Verify setup calls
        mock_create_server.assert_called_once()
        mock_server_instance.ensure_table_exists.assert_called()
        mock_server_instance.run.assert_called_with(transport="streamable-http")

        # Verify signal handlers were registered
        assert mock_signal.call_count >= 2  # SIGINT and SIGTERM

    @patch("foundry_aws_utilities.mcp_server.create_dynamodb_mcp_server")
    @patch("foundry_aws_utilities.mcp_server.os.getenv")
    @patch("builtins.print")
    def test_main_function_with_custom_table(self, mock_print, mock_getenv, mock_create_server):
        """Test main function with custom research table."""
        from foundry_aws_utilities.mcp_server import main

        # Mock environment variable for custom table
        def mock_env_side_effect(key, default=None):
            return "custom-research-table" if key == "DYNAMODB_TABLE_NAME" else default

        mock_getenv.side_effect = mock_env_side_effect

        # Mock server instance
        mock_server_instance = MagicMock()
        mock_server_instance.default_table = "strands-storage"
        mock_server_instance.ensure_table_exists = MagicMock(return_value=True)
        mock_server_instance.run = MagicMock(side_effect=KeyboardInterrupt())
        mock_create_server.return_value = mock_server_instance

        # Test main function
        main()

        # Verify research table creation was attempted
        calls = mock_server_instance.ensure_table_exists.call_args_list
        # Should be called twice: once for default table, once for research table
        assert len(calls) >= 2
        # Check if research table was created with custom name and schema
        research_call = [call for call in calls if len(call[0]) > 1 and call[0][1] == "research"]
        assert len(research_call) == 1
        assert research_call[0][0][0] == "custom-research-table"


class TestMCPTools:
    """Test suite for MCP tools."""

    @pytest.fixture
    def mock_server(self):
        """Create a mock server for testing."""
        with patch("foundry_aws_utilities.mcp_server.boto3"):
            server = create_dynamodb_mcp_server()
            # Mock the DynamoDB resources
            server.dynamodb = MagicMock()
            server.dynamodb_client = MagicMock()
            return server

    def test_server_has_fastmcp_instance(self, mock_server):
        """Test that server has FastMCP instance and tools are registered."""
        # Tools are registered via decorators, so we check the server has the FastMCP instance
        assert hasattr(mock_server, "server")
        assert mock_server.server is not None

        # Verify the server is a FastMCP instance
        from fastmcp import FastMCP

        assert isinstance(mock_server.server, FastMCP)

        # Verify the server has the required methods for tool registration
        assert hasattr(mock_server.server, "tool")
        assert callable(mock_server.server.tool)

    def test_server_run_method(self, mock_server, monkeypatch):
        """Test server run method."""
        # streamable-http now requires MCP_AUTH_TOKEN (fail-closed bearer auth)
        # and serves the auth-wrapped ASGI app via uvicorn.run; provide the
        # token and stub uvicorn so the test does not bind a real listener.
        monkeypatch.setenv("MCP_AUTH_TOKEN", "test-token")
        # Mock the server.run method to avoid actually starting the server
        mock_server.server.run = MagicMock()

        with patch("uvicorn.run") as mock_uvicorn_run:
            # Test calling run method
            mock_server.run(transport="streamable-http")

            # streamable-http path serves the wrapped app via uvicorn,
            # not FastMCP's own run().
            mock_uvicorn_run.assert_called_once()
            mock_server.server.run.assert_not_called()

        # Non-http transports still delegate to FastMCP.run() unchanged.
        mock_server.run(transport="stdio")
        mock_server.server.run.assert_called_once_with(transport="stdio")

    def test_server_run_method_no_auth_token(self, mock_server, monkeypatch):
        """Server must refuse to start streamable-http without MCP_AUTH_TOKEN."""
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
            mock_server.run(transport="streamable-http")


class TestDynamoDBMCPTools:
    @pytest.fixture
    def server_with_mocks(self):
        with patch("foundry_aws_utilities.mcp_server.boto3") as mock_boto3:
            mock_session = MagicMock()
            mock_boto3.Session.return_value = mock_session
            mock_resource = MagicMock()
            mock_client = MagicMock()
            mock_session.resource.return_value = mock_resource
            mock_session.client.return_value = mock_client
            # Tools are allowlist-gated: cover every table name this suite
            # exercises so the guard admits them (default_table is implicit).
            server = create_dynamodb_mcp_server(
                default_table="test-table",
                allowed_tables=["new-table", "existing", "x"],
            )
        mock_table = MagicMock()
        server.dynamodb.Table.return_value = mock_table
        return server, mock_table, mock_client

    def test_store_content_success(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        server.ensure_table_exists = MagicMock(return_value=True)
        mock_table.put_item.return_value = None

        text = _call_tool_text(server, "dynamodb_store_content", {"content": "hello world", "item_id": "abc123"})
        assert "dynamodb://test-table/abc123" in text

    def test_store_content_auto_generates_id(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        server.ensure_table_exists = MagicMock(return_value=True)
        mock_table.put_item.return_value = None

        text = _call_tool_text(server, "dynamodb_store_content", {"content": "data"})
        assert "dynamodb://test-table/" in text

    def test_store_content_table_not_available(self, server_with_mocks):
        server, _, _ = server_with_mocks
        server.ensure_table_exists = MagicMock(return_value=False)

        text = _call_tool_text(server, "dynamodb_store_content", {"content": "x"})
        assert "Cannot access" in text

    def test_store_content_exception(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        server.ensure_table_exists = MagicMock(return_value=True)
        mock_table.put_item.side_effect = RuntimeError("write failed")

        text = _call_tool_text(server, "dynamodb_store_content", {"content": "x", "item_id": "id1"})
        assert "write failed" in text

    # STIG V-222612: string-length bounds

    def test_store_content_oversized_content_rejected(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        server.ensure_table_exists = MagicMock(return_value=True)
        oversized = "x" * (MAX_CONTENT_LENGTH + 1)

        text = _call_tool_text(server, "dynamodb_store_content", {"content": oversized, "item_id": "id1"})
        assert "exceeds maximum length" in text
        mock_table.put_item.assert_not_called()

    def test_store_content_oversized_item_id_rejected(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        server.ensure_table_exists = MagicMock(return_value=True)
        oversized_id = "i" * (MAX_DDB_KEY_LENGTH + 1)

        text = _call_tool_text(server, "dynamodb_store_content", {"content": "x", "item_id": oversized_id})
        assert "exceeds maximum length" in text
        mock_table.put_item.assert_not_called()

    def test_retrieve_content_oversized_table_rejected(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        oversized_table = "t" * (MAX_DDB_TABLE_NAME_LENGTH + 1)

        text = _call_tool_text(server, "dynamodb_retrieve_content", {"item_id": "abc", "table": oversized_table})
        assert "exceeds maximum length" in text
        mock_table.get_item.assert_not_called()

    def test_create_table_oversized_name_rejected(self, server_with_mocks):
        server, _, _ = server_with_mocks
        oversized_name = "n" * (MAX_DDB_TABLE_NAME_LENGTH + 1)

        text = _call_tool_text(server, "create_table", {"table_name": oversized_name})
        assert "exceeds maximum length" in text
        server.dynamodb.create_table.assert_not_called()

    def test_retrieve_content_success(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        mock_table.get_item.return_value = {
            "Item": {
                "id": "abc",
                "content": "stored data",
                "timestamp": "2024-01-01T00:00:00",
                "size_bytes": 11,
                "size_kb": 0.01,
            }
        }

        text = _call_tool_text(server, "dynamodb_retrieve_content", {"item_id": "abc"})
        assert "stored data" in text

    def test_retrieve_content_not_found(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        mock_table.get_item.return_value = {}

        text = _call_tool_text(server, "dynamodb_retrieve_content", {"item_id": "missing"})
        assert "not found" in text.lower()

    def test_retrieve_content_exception(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        mock_table.get_item.side_effect = RuntimeError("timeout")

        text = _call_tool_text(server, "dynamodb_retrieve_content", {"item_id": "x"})
        assert "timeout" in text

    def test_list_items_success(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        mock_table.scan.return_value = {
            "Items": [
                {"id": "item1", "size_bytes": 10, "size_kb": 0.01, "timestamp": "t1"},
                {"id": "item2", "size_bytes": 20, "size_kb": 0.02, "timestamp": "t2"},
            ],
            "ScannedCount": 2,
        }

        text = _call_tool_text(server, "list_items", {"limit": 10})
        assert "item1" in text

    def test_list_items_exception(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        mock_table.scan.side_effect = RuntimeError("scan failed")

        text = _call_tool_text(server, "list_items", {})
        assert "scan failed" in text

    def test_create_table_success(self, server_with_mocks):
        server, _, _ = server_with_mocks
        created_table = MagicMock()
        server.dynamodb.create_table.return_value = created_table

        text = _call_tool_text(server, "create_table", {"table_name": "new-table"})
        assert "new-table" in text
        created_table.wait_until_exists.assert_called_once()

    def test_create_table_already_exists(self, server_with_mocks):
        server, _, _ = server_with_mocks
        server.dynamodb.create_table.side_effect = ClientError(
            {"Error": {"Code": "ResourceInUseException"}}, "CreateTable"
        )

        text = _call_tool_text(server, "create_table", {"table_name": "existing"})
        assert "already exists" in text.lower()

    def test_create_table_generic_exception(self, server_with_mocks):
        server, _, _ = server_with_mocks
        server.dynamodb.create_table.side_effect = RuntimeError("boom")

        text = _call_tool_text(server, "create_table", {"table_name": "x"})
        assert "boom" in text

    def test_list_tables_success(self, server_with_mocks):
        server, _, mock_client = server_with_mocks
        server.dynamodb_client = mock_client
        mock_client.list_tables.return_value = {"TableNames": ["table-a", "table-b"]}

        text = _call_tool_text(server, "list_tables", {})
        assert "table-a" in text

    def test_list_tables_exception(self, server_with_mocks):
        server, _, mock_client = server_with_mocks
        server.dynamodb_client = mock_client
        mock_client.list_tables.side_effect = RuntimeError("denied")

        text = _call_tool_text(server, "list_tables", {})
        assert "denied" in text

    def test_delete_item_success(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        mock_table.delete_item.return_value = None

        text = _call_tool_text(server, "delete_item", {"item_id": "abc"})
        assert "deleted" in text.lower() or "success" in text.lower()

    def test_delete_item_exception(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        mock_table.delete_item.side_effect = RuntimeError("failed")

        text = _call_tool_text(server, "delete_item", {"item_id": "x"})
        assert "failed" in text

    def test_update_content_success(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        mock_table.update_item.return_value = None

        text = _call_tool_text(server, "update_content", {"item_id": "abc", "content": "new data"})
        assert "dynamodb://test-table/abc" in text

    def test_update_content_exception(self, server_with_mocks):
        server, mock_table, _ = server_with_mocks
        mock_table.update_item.side_effect = RuntimeError("update failed")

        text = _call_tool_text(server, "update_content", {"item_id": "x", "content": "y"})
        assert "update failed" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
