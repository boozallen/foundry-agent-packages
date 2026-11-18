# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for S3 MCP Server."""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from foundry_aws_utilities import create_s3_mcp_server
from foundry_aws_utilities._validation import (
    MAX_CONTENT_LENGTH,
    MAX_PREFIX_LENGTH,
    MAX_S3_BUCKET_LENGTH,
    MAX_S3_KEY_LENGTH,
)

FASTMCP_FORBIDDEN_KWARGS = {"host", "port", "streamable_http_path", "stateless_http", "json_response"}


def _fastmcp_mock_reject_deprecated(*args, **kwargs):
    bad = FASTMCP_FORBIDDEN_KWARGS & set(kwargs)
    if bad:
        raise TypeError(f"FastMCP() no longer accepts `{next(iter(bad))}`. Pass it to run() or set env.")
    return MagicMock()


def _call_tool_text(server, tool_name: str, arguments: dict) -> str:
    result = asyncio.run(server.server.call_tool(tool_name, arguments))
    return result.content[0].text


class TestS3MCPServer:
    def test_create_server_with_defaults(self):
        with patch("foundry_aws_utilities.s3_mcp_server.boto3"):
            server = create_s3_mcp_server()
        assert server is not None
        assert server.default_bucket == "strands-storage"

    def test_bucket_allowlist_rejects_non_default(self):
        """Allowlist defaults to {default_bucket}; non-listed bucket is rejected without disclosing the allowlist."""
        with patch("foundry_aws_utilities.s3_mcp_server.boto3"):
            with patch.dict("os.environ", {"S3_ALLOWED_BUCKETS": ""}, clear=False):
                server = create_s3_mcp_server(default_bucket="allowed-bucket")
        assert server.allowed_buckets == {"allowed-bucket"}
        server._check_bucket_allowed("allowed-bucket")
        with pytest.raises(PermissionError) as exc_info:
            server._check_bucket_allowed("attacker-bucket")
        # Rejection message must NOT enumerate the allowed set (info disclosure to unauthorized caller)
        assert "allowed-bucket" not in str(exc_info.value)

    def test_fastmcp_called_without_deprecated_kwargs(self):
        with patch("foundry_aws_utilities.s3_mcp_server.boto3"):
            with patch("foundry_aws_utilities.s3_mcp_server.FastMCP", side_effect=_fastmcp_mock_reject_deprecated):
                server = create_s3_mcp_server()
        assert server is not None

    def test_create_server_with_custom_config(self):
        with patch("foundry_aws_utilities.s3_mcp_server.boto3"):
            server = create_s3_mcp_server(
                aws_access_key_id="test-key",
                aws_secret_access_key="test-secret",  # noqa: S106
                region_name="us-west-2",
                endpoint_url="http://localhost:4566",
                default_bucket="custom-bucket",
            )
        assert server is not None
        assert server.default_bucket == "custom-bucket"

    @patch("foundry_aws_utilities.s3_mcp_server.boto3")
    def test_server_initialization(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_session.client.return_value = MagicMock()

        server = create_s3_mcp_server()
        assert server is not None
        mock_boto3.Session.assert_called_once()
        mock_session.client.assert_called()

    @patch("foundry_aws_utilities.s3_mcp_server.boto3")
    def test_ensure_bucket_exists_bucket_exists(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.head_bucket.return_value = {}

        server = create_s3_mcp_server()
        result = server.ensure_bucket_exists("test-bucket")
        assert result is True
        mock_client.head_bucket.assert_called_once_with(Bucket="test-bucket")
        mock_client.create_bucket.assert_not_called()

    @patch("foundry_aws_utilities.s3_mcp_server.boto3")
    def test_ensure_bucket_exists_404_creates_bucket(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.head_bucket.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadBucket")
        mock_client.create_bucket.return_value = {}

        server = create_s3_mcp_server()
        result = server.ensure_bucket_exists("new-bucket")
        assert result is True
        mock_client.create_bucket.assert_called_once_with(Bucket="new-bucket")

    @patch("foundry_aws_utilities.s3_mcp_server.boto3")
    def test_ensure_bucket_exists_404_create_fails(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.head_bucket.side_effect = ClientError({"Error": {"Code": "NoSuchBucket"}}, "HeadBucket")
        mock_client.create_bucket.side_effect = Exception("Permission denied")

        server = create_s3_mcp_server()
        result = server.ensure_bucket_exists("new-bucket")
        assert result is False

    @patch("foundry_aws_utilities.s3_mcp_server.boto3")
    def test_ensure_bucket_exists_other_client_error(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.head_bucket.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "HeadBucket")

        server = create_s3_mcp_server()
        result = server.ensure_bucket_exists("test-bucket")
        assert result is False
        mock_client.create_bucket.assert_not_called()

    @patch("foundry_aws_utilities.s3_mcp_server.boto3")
    def test_create_server_with_endpoint_url_from_env(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_session.client.return_value = MagicMock()

        with patch.dict("os.environ", {"AWS_ENDPOINT_URL": "http://local:4566"}, clear=False):
            server = create_s3_mcp_server()
        assert server is not None
        mock_session.client.assert_called_once()
        call_kw = mock_session.client.call_args[1]
        assert call_kw.get("endpoint_url") == "http://local:4566"

    def test_run_method_exists(self):
        with patch("foundry_aws_utilities.s3_mcp_server.boto3"):
            server = create_s3_mcp_server()
        assert hasattr(server, "run")
        assert callable(server.run)

    @patch("foundry_aws_utilities.s3_mcp_server.boto3")
    def test_health_route_returns_healthy(self, mock_boto3):
        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_session.client.return_value = MagicMock()

        server = create_s3_mcp_server()
        app = server.server.http_app()
        from starlette.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "S3 MCP Server" in data["server"]

    @patch("foundry_aws_utilities.s3_mcp_server.boto3")
    def test_http_transport_requires_bearer_token(self, mock_boto3):
        """Regression for f003 (unauthenticated destructive AWS tools over HTTP).

        http_app() must refuse to build without MCP_AUTH_TOKEN, must reject
        requests to /mcp lacking a valid bearer token, and must leave /health
        unauthenticated for liveness probes.
        """
        from starlette.testclient import TestClient

        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session
        mock_session.client.return_value = MagicMock()
        server = create_s3_mcp_server()

        with patch.dict("os.environ", {"MCP_AUTH_TOKEN": ""}, clear=False):
            with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
                server.http_app()

        with patch.dict("os.environ", {"MCP_AUTH_TOKEN": "test-secret-token"}, clear=False):
            app = server.http_app()
            with TestClient(app) as client:
                assert client.get("/health").status_code == 200
                assert client.post("/mcp").status_code == 401
                assert client.post("/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 401
                ok = client.post("/mcp", headers={"Authorization": "Bearer test-secret-token"})
                assert ok.status_code != 401


class TestS3MCPTools:
    @pytest.fixture
    def server_with_mocks(self):
        with patch("foundry_aws_utilities.s3_mcp_server.boto3") as mock_boto3:
            mock_session = MagicMock()
            mock_boto3.Session.return_value = mock_session
            mock_client = MagicMock()
            mock_session.client.return_value = mock_client
            # Tools are allowlist-gated: cover every bucket name this suite
            # exercises so the guard admits them (default_bucket is implicit).
            server = create_s3_mcp_server(
                default_bucket="test-bucket",
                allowed_buckets=["new-bucket", "existing", "x"],
            )
        return server, mock_client

    def test_store_content_success(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.head_bucket.return_value = {}
        mock_client.put_object.return_value = {}

        text = _call_tool_text(server, "s3_store_content", {"content": "hello", "key": "docs/file.txt"})
        assert "s3://test-bucket/docs/file.txt" in text

    def test_store_content_bucket_not_accessible(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.head_bucket.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadBucket")
        mock_client.create_bucket.side_effect = Exception("Permission denied")

        text = _call_tool_text(server, "s3_store_content", {"content": "hello", "key": "k"})
        assert "Cannot access" in text

    def test_store_content_put_exception(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.head_bucket.return_value = {}
        mock_client.put_object.side_effect = RuntimeError("network error")

        text = _call_tool_text(server, "s3_store_content", {"content": "data", "key": "k"})
        assert "network error" in text

    def test_retrieve_content_success(self, server_with_mocks):
        server, mock_client = server_with_mocks
        body_mock = MagicMock()
        body_mock.read.return_value = b"file content"
        mock_client.get_object.return_value = {
            "Body": body_mock,
            "ContentLength": 12,
            "LastModified": datetime(2024, 1, 1),
        }

        text = _call_tool_text(server, "s3_retrieve_content", {"key": "docs/file.txt"})
        assert "file content" in text

    def test_retrieve_content_no_such_key(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

        text = _call_tool_text(server, "s3_retrieve_content", {"key": "missing.txt"})
        assert "not found" in text.lower()

    def test_retrieve_content_generic_exception(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.get_object.side_effect = RuntimeError("timeout")

        text = _call_tool_text(server, "s3_retrieve_content", {"key": "k"})
        assert "timeout" in text

    def test_list_objects_success(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "a.txt", "Size": 100, "LastModified": datetime(2024, 1, 1)},
                {"Key": "b.txt", "Size": 200, "LastModified": datetime(2024, 1, 2)},
            ]
        }

        text = _call_tool_text(server, "list_objects", {"prefix": ""})
        assert "a.txt" in text

    def test_list_objects_exception(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.list_objects_v2.side_effect = RuntimeError("denied")

        text = _call_tool_text(server, "list_objects", {})
        assert "denied" in text

    def test_create_bucket_success(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.create_bucket.return_value = {}

        text = _call_tool_text(server, "create_bucket", {"bucket_name": "new-bucket"})
        assert "new-bucket" in text

    def test_create_bucket_already_exists(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.create_bucket.side_effect = ClientError({"Error": {"Code": "BucketAlreadyExists"}}, "CreateBucket")

        text = _call_tool_text(server, "create_bucket", {"bucket_name": "existing"})
        assert "already exists" in text.lower()

    def test_create_bucket_generic_exception(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.create_bucket.side_effect = RuntimeError("network")

        text = _call_tool_text(server, "create_bucket", {"bucket_name": "x"})
        assert "network" in text

    def test_list_buckets_success(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.list_buckets.return_value = {
            "Buckets": [
                {"Name": "bucket-a", "CreationDate": datetime(2024, 1, 1)},
                {"Name": "bucket-b", "CreationDate": datetime(2024, 2, 1)},
            ]
        }

        text = _call_tool_text(server, "list_buckets", {})
        assert "bucket-a" in text

    def test_list_buckets_exception(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.list_buckets.side_effect = RuntimeError("error")

        text = _call_tool_text(server, "list_buckets", {})
        assert "error" in text.lower()

    def test_delete_object_success(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.delete_object.return_value = {}

        text = _call_tool_text(server, "delete_object", {"key": "docs/old.txt"})
        assert "deleted" in text.lower() or "success" in text.lower()

    def test_delete_object_exception(self, server_with_mocks):
        server, mock_client = server_with_mocks
        mock_client.delete_object.side_effect = RuntimeError("forbidden")

        text = _call_tool_text(server, "delete_object", {"key": "k"})
        assert "forbidden" in text

    # STIG V-222612: string-length bounds

    def test_store_content_oversized_content_rejected(self, server_with_mocks):
        server, mock_client = server_with_mocks
        oversized = "x" * (MAX_CONTENT_LENGTH + 1)

        text = _call_tool_text(server, "s3_store_content", {"content": oversized, "key": "k"})
        assert "exceeds maximum length" in text
        mock_client.put_object.assert_not_called()

    def test_store_content_oversized_key_rejected(self, server_with_mocks):
        server, mock_client = server_with_mocks
        oversized_key = "k" * (MAX_S3_KEY_LENGTH + 1)

        text = _call_tool_text(server, "s3_store_content", {"content": "hi", "key": oversized_key})
        assert "exceeds maximum length" in text
        mock_client.put_object.assert_not_called()

    def test_retrieve_content_oversized_bucket_rejected(self, server_with_mocks):
        server, mock_client = server_with_mocks
        oversized_bucket = "b" * (MAX_S3_BUCKET_LENGTH + 1)

        text = _call_tool_text(server, "s3_retrieve_content", {"key": "k", "bucket": oversized_bucket})
        assert "exceeds maximum length" in text
        mock_client.get_object.assert_not_called()

    def test_list_objects_oversized_prefix_rejected(self, server_with_mocks):
        server, mock_client = server_with_mocks
        oversized_prefix = "p" * (MAX_PREFIX_LENGTH + 1)

        text = _call_tool_text(server, "list_objects", {"prefix": oversized_prefix})
        assert "exceeds maximum length" in text
        mock_client.list_objects_v2.assert_not_called()


class TestS3MainFunction:
    @patch("foundry_aws_utilities.s3_mcp_server.create_s3_mcp_server")
    @patch("signal.signal")
    @patch("builtins.print")
    def test_main_function(self, mock_print, mock_signal, mock_create_server):
        from foundry_aws_utilities.s3_mcp_server import main

        mock_server_instance = MagicMock()
        mock_server_instance.default_bucket = "strands-storage"
        mock_server_instance.ensure_bucket_exists = MagicMock(return_value=True)
        mock_server_instance.run = MagicMock(side_effect=KeyboardInterrupt())
        mock_create_server.return_value = mock_server_instance

        main()

        mock_create_server.assert_called_once()
        mock_server_instance.ensure_bucket_exists.assert_called_once_with("strands-storage")
        mock_server_instance.run.assert_called_with(transport="streamable-http")
        assert mock_signal.call_count >= 2
