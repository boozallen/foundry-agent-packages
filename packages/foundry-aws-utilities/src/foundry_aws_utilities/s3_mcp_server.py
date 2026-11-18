#!/usr/bin/env python3
# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""
S3 MCP Server - Provides S3 storage operations

This MCP server provides tools for:
- Storing content in S3 buckets
- Retrieving content from S3 objects
- Listing S3 buckets and objects
- Creating S3 buckets
- Operating with AWS S3 (or LocalStack when configured)
"""

import logging
import os
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError
from fastmcp import FastMCP  # type: ignore
from starlette.requests import Request
from starlette.responses import JSONResponse

from ._auth import BearerTokenMiddleware, require_auth_token
from ._validation import (
    MAX_CONTENT_LENGTH,
    MAX_PREFIX_LENGTH,
    MAX_S3_BUCKET_LENGTH,
    MAX_S3_KEY_LENGTH,
    enforce_str_bounds,
)

logger = logging.getLogger(__name__)


class S3MCPServer:
    """S3 MCP Server class for managing S3 operations."""

    def __init__(
        self,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        default_bucket: str = "strands-storage",
        allowed_buckets: list[str] | None = None,
    ):
        """
        Initialize S3 MCP Server.

        Args:
            aws_access_key_id: AWS access key ID (defaults to env var)
            aws_secret_access_key: AWS secret access key (defaults to env var)
            region_name: AWS region (defaults to env var or 'us-east-1')
            endpoint_url: AWS endpoint URL override (defaults to None for real AWS S3)
            default_bucket: Default S3 bucket name
            allowed_buckets: Bucket names tools may access (defaults to env S3_ALLOWED_BUCKETS
                comma-separated, else just default_bucket). Tools reject any bucket outside this set.
        """
        session_kwargs = {"region_name": region_name or os.getenv("AWS_DEFAULT_REGION", "us-east-1")}
        access_key = aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = aws_secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key

        self.session = boto3.Session(**session_kwargs)
        endpoint = endpoint_url or os.getenv("AWS_ENDPOINT_URL")
        self.s3_client = self.session.client("s3", endpoint_url=endpoint)  # type: ignore
        self.default_bucket = default_bucket

        env_allowed = os.getenv("S3_ALLOWED_BUCKETS", "")
        if allowed_buckets is None and env_allowed:
            allowed_buckets = [b.strip() for b in env_allowed.split(",") if b.strip()]
        self.allowed_buckets: set[str] = set(allowed_buckets or []) | {default_bucket}

        self.server = FastMCP("S3 MCP Server")  # type: ignore

        self._register_routes()
        self._register_tools()

    def _register_routes(self) -> None:
        """Register custom HTTP routes."""

        @self.server.custom_route("/health", methods=["GET"])
        async def health_check(_request: Request) -> JSONResponse:
            return JSONResponse(
                {
                    "status": "healthy",
                    "server": "S3 MCP Server",
                    "timestamp": datetime.now().isoformat(),
                    "mcp_port": 8000,
                    "s3_endpoint": os.getenv("AWS_ENDPOINT_URL") or "AWS S3",
                }
            )

    def ensure_bucket_exists(self, bucket_name: str) -> bool:
        """Ensure S3 bucket exists, create if not."""
        try:
            self.s3_client.head_bucket(Bucket=bucket_name)
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchBucket"):
                try:
                    self.s3_client.create_bucket(Bucket=bucket_name)
                    return True
                except Exception:
                    logger.exception("Error creating bucket %s", bucket_name)
                    return False
            logger.exception("Error checking bucket %s", bucket_name)
            return False

    def _check_bucket_allowed(self, bucket_name: str) -> None:
        """Raise if bucket_name is not in the operator-configured allowlist."""
        if bucket_name not in self.allowed_buckets:
            raise PermissionError(f"Bucket '{bucket_name}' is not in the allowed set")

    def _register_tools(self) -> None:
        """Register MCP tools."""

        @self.server.tool()  # type: ignore
        def s3_store_content(content: str, key: str, bucket: str | None = None) -> dict[str, Any]:
            """Store content in S3 and return storage URL."""
            bucket_name = bucket or self.default_bucket
            try:
                enforce_str_bounds(
                    ("content", content, MAX_CONTENT_LENGTH),
                    ("key", key, MAX_S3_KEY_LENGTH),
                    ("bucket", bucket, MAX_S3_BUCKET_LENGTH),
                )
                self._check_bucket_allowed(bucket_name)
                if not self.ensure_bucket_exists(bucket_name):
                    return {
                        "success": False,
                        "error": f"Cannot access or create bucket {bucket_name}",
                        "bucket": bucket_name,
                        "key": key,
                    }
                self.s3_client.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=content.encode("utf-8"),
                    ContentType="text/plain",
                )
                size_bytes = len(content.encode("utf-8"))
                size_kb = round(size_bytes / 1024, 2)
                storage_url = f"s3://{bucket_name}/{key}"
                return {
                    "success": True,
                    "storage_url": storage_url,
                    "bucket": bucket_name,
                    "key": key,
                    "size_bytes": size_bytes,
                    "size_kb": size_kb,
                    "message": f"Successfully stored content at {storage_url}",
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error storing content: {str(e)}",
                    "bucket": bucket_name,
                    "key": key,
                }

        @self.server.tool()  # type: ignore
        def s3_retrieve_content(key: str, bucket: str | None = None) -> dict[str, Any]:
            """Retrieve content from S3."""
            bucket_name = bucket or self.default_bucket
            try:
                enforce_str_bounds(
                    ("key", key, MAX_S3_KEY_LENGTH),
                    ("bucket", bucket, MAX_S3_BUCKET_LENGTH),
                )
                self._check_bucket_allowed(bucket_name)
                response = self.s3_client.get_object(Bucket=bucket_name, Key=key)
                content = response["Body"].read().decode("utf-8")
                size_bytes = response["ContentLength"]
                size_kb = round(size_bytes / 1024, 2)
                storage_url = f"s3://{bucket_name}/{key}"
                return {
                    "success": True,
                    "storage_url": storage_url,
                    "content": content,
                    "bucket": bucket_name,
                    "key": key,
                    "size_bytes": size_bytes,
                    "size_kb": size_kb,
                    "last_modified": response["LastModified"].isoformat(),
                }
            except ClientError as e:
                if e.response["Error"]["Code"] == "NoSuchKey":
                    return {
                        "success": False,
                        "error": f"Object {key} not found in bucket {bucket_name}",
                        "bucket": bucket_name,
                        "key": key,
                    }
                return {
                    "success": False,
                    "error": f"Error retrieving content: {str(e)}",
                    "bucket": bucket_name,
                    "key": key,
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error retrieving content: {str(e)}",
                    "bucket": bucket_name,
                    "key": key,
                }

        @self.server.tool()  # type: ignore
        def list_objects(bucket: str | None = None, prefix: str = "") -> dict[str, Any]:
            """List objects in S3 bucket."""
            bucket_name = bucket or self.default_bucket
            try:
                enforce_str_bounds(
                    ("prefix", prefix if prefix else None, MAX_PREFIX_LENGTH),
                    ("bucket", bucket, MAX_S3_BUCKET_LENGTH),
                )
                self._check_bucket_allowed(bucket_name)
                kwargs: dict[str, Any] = {"Bucket": bucket_name}
                if prefix:
                    kwargs["Prefix"] = prefix
                response = self.s3_client.list_objects_v2(**kwargs)
                objects = []
                if "Contents" in response:
                    for obj in response["Contents"]:
                        size_kb = round(obj["Size"] / 1024, 2)
                        objects.append(
                            {
                                "key": obj["Key"],
                                "size_bytes": obj["Size"],
                                "size_kb": size_kb,
                                "last_modified": obj["LastModified"].isoformat(),
                                "storage_url": f"s3://{bucket_name}/{obj['Key']}",
                            }
                        )
                return {
                    "success": True,
                    "bucket": bucket_name,
                    "prefix": prefix,
                    "objects": objects,
                    "count": len(objects),
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error listing objects: {str(e)}",
                    "bucket": bucket_name,
                    "prefix": prefix,
                }

        @self.server.tool()  # type: ignore
        def create_bucket(bucket_name: str) -> dict[str, Any]:
            """Create a new S3 bucket."""
            try:
                self._check_bucket_allowed(bucket_name)
                self.s3_client.create_bucket(Bucket=bucket_name)
                return {
                    "success": True,
                    "bucket": bucket_name,
                    "message": f"Successfully created bucket {bucket_name}",
                }
            except ClientError as e:
                if e.response["Error"]["Code"] == "BucketAlreadyExists":
                    return {
                        "success": False,
                        "error": f"Bucket {bucket_name} already exists",
                        "bucket": bucket_name,
                    }
                return {
                    "success": False,
                    "error": f"Error creating bucket: {str(e)}",
                    "bucket": bucket_name,
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error creating bucket: {str(e)}",
                    "bucket": bucket_name,
                }

        @self.server.tool()  # type: ignore
        def list_buckets() -> dict[str, Any]:
            """List all S3 buckets."""
            try:
                response = self.s3_client.list_buckets()
                buckets = [{"name": b["Name"], "created": b["CreationDate"].isoformat()} for b in response["Buckets"]]
                return {
                    "success": True,
                    "buckets": buckets,
                    "count": len(buckets),
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error listing buckets: {str(e)}",
                }

        @self.server.tool()  # type: ignore
        def delete_object(key: str, bucket: str | None = None) -> dict[str, Any]:
            """Delete an object from S3."""
            bucket_name = bucket or self.default_bucket
            try:
                self._check_bucket_allowed(bucket_name)
                self.s3_client.delete_object(Bucket=bucket_name, Key=key)
                return {
                    "success": True,
                    "bucket": bucket_name,
                    "key": key,
                    "message": f"Successfully deleted s3://{bucket_name}/{key}",
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error deleting object: {str(e)}",
                    "bucket": bucket_name,
                    "key": key,
                }

    def http_app(self) -> Any:
        """Return the ASGI app with bearer-token auth enforced on all non-/health routes."""
        token = require_auth_token()
        return BearerTokenMiddleware(self.server.http_app(), token=token)  # type: ignore

    def run(self, transport: str = "streamable-http") -> None:
        """Run the MCP server."""
        if transport != "streamable-http":
            self.server.run(transport=transport)  # type: ignore
            return
        import uvicorn

        uvicorn.run(self.http_app(), host="0.0.0.0", port=8000)


def create_s3_mcp_server(
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    region_name: str | None = None,
    endpoint_url: str | None = None,
    default_bucket: str = "strands-storage",
    allowed_buckets: list[str] | None = None,
) -> S3MCPServer:
    """
    Create and configure an S3 MCP Server instance.

    Args:
        aws_access_key_id: AWS access key ID (defaults to env var)
        aws_secret_access_key: AWS secret access key (defaults to env var)
        region_name: AWS region (defaults to env var or 'us-east-1')
        endpoint_url: AWS endpoint URL override (e.g. LocalStack)
        default_bucket: Default S3 bucket name
        allowed_buckets: Bucket names tools may access (defaults to S3_ALLOWED_BUCKETS env or default bucket)

    Returns:
        Configured S3MCPServer instance
    """
    return S3MCPServer(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region_name,
        endpoint_url=endpoint_url,
        default_bucket=default_bucket,
        allowed_buckets=allowed_buckets,
    )


def main() -> None:
    """Main entry point for CLI usage."""
    import signal
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def signal_handler(_sig: int, _frame: object) -> None:
        logger.info("Shutting down S3 MCP Server...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Starting S3 MCP Server on port 8000...")
    logger.info("S3 endpoint: %s", os.getenv("AWS_ENDPOINT_URL") or "AWS S3")
    logger.info("Health endpoint available at /health")
    logger.info("MCP endpoint available at /mcp")
    logger.info("Press Ctrl+C to stop the server")

    server = create_s3_mcp_server()
    logger.info("Ensuring default bucket '%s' exists...", server.default_bucket)
    server.ensure_bucket_exists(server.default_bucket)

    try:
        server.run(transport="streamable-http")
    except KeyboardInterrupt:
        logger.info("Server stopped by user")


if __name__ == "__main__":
    main()
