#!/usr/bin/env python3
# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""
DynamoDB MCP Server - Provides DynamoDB storage operations

This MCP server provides tools for:
- Storing content in DynamoDB tables
- Retrieving content from DynamoDB items
- Creating DynamoDB tables
- Listing DynamoDB tables
- Operating with AWS DynamoDB (or LocalStack when configured)
"""

import logging
import os
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError
from fastmcp import FastMCP  # type: ignore
from starlette.requests import Request
from starlette.responses import JSONResponse

from ._auth import BearerTokenMiddleware, require_auth_token
from ._validation import MAX_CONTENT_LENGTH, MAX_DDB_KEY_LENGTH, MAX_DDB_TABLE_NAME_LENGTH, enforce_str_bounds

logger = logging.getLogger(__name__)


class DynamoDBMCPServer:
    """DynamoDB MCP Server class for managing DynamoDB operations."""

    def __init__(
        self,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        default_table: str = "strands-storage",
        allowed_tables: list[str] | None = None,
    ):
        """
        Initialize DynamoDB MCP Server.

        Args:
            aws_access_key_id: AWS access key ID (defaults to env var or 'test')
            aws_secret_access_key: AWS secret access key (defaults to env var or 'test')
            region_name: AWS region (defaults to env var or 'us-east-1')
            endpoint_url: AWS endpoint URL override (defaults to None for real AWS DynamoDB)
            default_table: Default DynamoDB table name
            allowed_tables: Table names tools may access (defaults to env DYNAMODB_ALLOWED_TABLES
                comma-separated, else just default_table). Tools reject any table outside this set.
        """
        # Initialize boto3 session - use explicit credentials only if provided, otherwise use credential chain
        session_kwargs = {"region_name": region_name or os.getenv("AWS_DEFAULT_REGION", "us-east-1")}

        # Only add credentials if explicitly provided - don't use "test" fallback that breaks Pod Identity
        access_key = aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = aws_secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key

        self.session = boto3.Session(**session_kwargs)

        endpoint = endpoint_url or os.getenv("AWS_ENDPOINT_URL")

        # Initialize DynamoDB clients using explicit session
        self.dynamodb = self.session.resource("dynamodb", endpoint_url=endpoint)  # type: ignore
        self.dynamodb_client = self.session.client("dynamodb", endpoint_url=endpoint)  # type: ignore
        self.default_table = default_table

        env_allowed = os.getenv("DYNAMODB_ALLOWED_TABLES", "")
        if allowed_tables is None and env_allowed:
            allowed_tables = [t.strip() for t in env_allowed.split(",") if t.strip()]
        self.allowed_tables: set[str] = set(allowed_tables or []) | {default_table}

        # Initialize FastMCP; host/port/path passed to run() by caller
        self.server = FastMCP("DynamoDB MCP Server")  # type: ignore

        # Register routes and tools
        self._register_routes()
        self._register_tools()

    def _register_routes(self) -> None:
        """Register custom HTTP routes."""

        # Add health endpoint
        @self.server.custom_route("/health", methods=["GET"])
        async def health_check(_request: Request) -> JSONResponse:
            return JSONResponse(
                {
                    "status": "healthy",
                    "server": "DynamoDB MCP Server",
                    "timestamp": datetime.now().isoformat(),
                    "mcp_port": 8000,
                    "dynamodb_endpoint": os.getenv("AWS_ENDPOINT_URL") or "AWS DynamoDB",
                }
            )

    def _check_table_allowed(self, table_name: str) -> None:
        """Raise if table_name is not in the operator-configured allowlist."""
        if table_name not in self.allowed_tables:
            raise PermissionError(f"Table '{table_name}' is not in the allowed set")

    def _register_tools(self) -> None:
        """Register MCP tools."""

        @self.server.tool()  # type: ignore
        def dynamodb_store_content(
            content: str, item_id: str | None = None, table: str | None = None
        ) -> dict[str, Any]:
            """Store content in DynamoDB and return storage URL."""
            table_name = table or self.default_table
            try:
                enforce_str_bounds(
                    ("content", content, MAX_CONTENT_LENGTH),
                    ("item_id", item_id, MAX_DDB_KEY_LENGTH),
                    ("table", table, MAX_DDB_TABLE_NAME_LENGTH),
                )
                self._check_table_allowed(table_name)
                # Generate ID if not provided
                if not item_id:
                    item_id = str(uuid.uuid4())

                # Ensure table exists
                if not self.ensure_table_exists(table_name):
                    return {
                        "success": False,
                        "error": f"Cannot access or create table {table_name}",
                        "table": table_name,
                        "id": item_id,
                    }

                # Store content with metadata
                table_resource = self.dynamodb.Table(table_name)  # type: ignore
                timestamp = datetime.now().isoformat()

                # Calculate size
                size_bytes = len(content.encode("utf-8"))
                size_kb = Decimal(str(round(size_bytes / 1024, 2)))

                item = {
                    "id": item_id,
                    "content": content,
                    "timestamp": timestamp,
                    "size_bytes": size_bytes,
                    "size_kb": size_kb,
                }

                table_resource.put_item(Item=item)

                # Generate storage URL
                storage_url = f"dynamodb://{table_name}/{item_id}"

                return {
                    "success": True,
                    "storage_url": storage_url,
                    "table": table_name,
                    "id": item_id,
                    "size_bytes": size_bytes,
                    "size_kb": size_kb,
                    "timestamp": timestamp,
                    "message": f"Successfully stored content at {storage_url}",
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error storing content: {str(e)}",
                    "table": table_name,
                    "id": item_id,
                }

        @self.server.tool()  # type: ignore
        def dynamodb_retrieve_content(item_id: str, table: str | None = None) -> dict[str, Any]:
            """Retrieve content from DynamoDB."""
            table_name = table or self.default_table
            try:
                enforce_str_bounds(
                    ("item_id", item_id, MAX_DDB_KEY_LENGTH),
                    ("table", table, MAX_DDB_TABLE_NAME_LENGTH),
                )
                self._check_table_allowed(table_name)
                table_resource = self.dynamodb.Table(table_name)  # type: ignore

                response = table_resource.get_item(Key={"id": item_id})

                if "Item" not in response:
                    return {
                        "success": False,
                        "error": f"Item {item_id} not found in table {table_name}",
                        "table": table_name,
                        "id": item_id,
                    }

                item = response["Item"]
                storage_url = f"dynamodb://{table_name}/{item_id}"

                return {
                    "success": True,
                    "storage_url": storage_url,
                    "content": item.get("content", ""),
                    "table": table_name,
                    "id": item_id,
                    "size_bytes": item.get("size_bytes", 0),
                    "size_kb": item.get("size_kb", 0),
                    "timestamp": item.get("timestamp", ""),
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error retrieving content: {str(e)}",
                    "table": table_name,
                    "id": item_id,
                }

        @self.server.tool()  # type: ignore
        def list_items(table: str | None = None, limit: int = 20) -> dict[str, Any]:
            """List items in DynamoDB table."""
            table_name = table or self.default_table
            try:
                self._check_table_allowed(table_name)
                table_resource = self.dynamodb.Table(table_name)  # type: ignore

                response = table_resource.scan(Limit=limit)

                items = []
                for item in response.get("Items", []):
                    items.append(
                        {
                            "id": item.get("id", ""),
                            "size_bytes": item.get("size_bytes", 0),
                            "size_kb": item.get("size_kb", 0),
                            "timestamp": item.get("timestamp", ""),
                            "storage_url": f"dynamodb://{table_name}/{item.get('id', '')}",
                        }
                    )

                return {
                    "success": True,
                    "table": table_name,
                    "items": items,
                    "count": len(items),
                    "scanned_count": response.get("ScannedCount", 0),
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error listing items: {str(e)}",
                    "table": table_name,
                }

        @self.server.tool()  # type: ignore
        def create_table(table_name: str) -> dict[str, Any]:
            """Create a new DynamoDB table."""
            try:
                enforce_str_bounds(("table_name", table_name, MAX_DDB_TABLE_NAME_LENGTH))
                self._check_table_allowed(table_name)
                table = self.dynamodb.create_table(  # type: ignore
                    TableName=table_name,
                    KeySchema=[
                        {
                            "AttributeName": "id",
                            "KeyType": "HASH",  # Partition key
                        }
                    ],
                    AttributeDefinitions=[
                        {
                            "AttributeName": "id",
                            "AttributeType": "S",
                        }
                    ],
                    BillingMode="PAY_PER_REQUEST",
                )

                # Wait for table to be created
                table.wait_until_exists()

                return {
                    "success": True,
                    "table": table_name,
                    "message": f"Successfully created table {table_name}",
                }

            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceInUseException":
                    return {
                        "success": False,
                        "error": f"Table {table_name} already exists",
                        "table": table_name,
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Error creating table: {str(e)}",
                        "table": table_name,
                    }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error creating table: {str(e)}",
                    "table": table_name,
                }

        @self.server.tool()  # type: ignore
        def list_tables() -> dict[str, Any]:
            """List all DynamoDB tables."""
            try:
                response = self.dynamodb_client.list_tables()

                tables = []
                for table_name in response["TableNames"]:
                    tables.append({"name": table_name})

                return {
                    "success": True,
                    "tables": tables,
                    "count": len(tables),
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error listing tables: {str(e)}",
                }

        @self.server.tool()  # type: ignore
        def delete_item(item_id: str, table: str | None = None) -> dict[str, Any]:
            """Delete an item from DynamoDB."""
            table_name = table or self.default_table
            try:
                self._check_table_allowed(table_name)
                table_resource = self.dynamodb.Table(table_name)  # type: ignore

                table_resource.delete_item(Key={"id": item_id})

                return {
                    "success": True,
                    "table": table_name,
                    "id": item_id,
                    "message": f"Successfully deleted dynamodb://{table_name}/{item_id}",
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error deleting item: {str(e)}",
                    "table": table_name,
                    "id": item_id,
                }

        @self.server.tool()  # type: ignore
        def update_content(item_id: str, content: str, table: str | None = None) -> dict[str, Any]:
            """Update content of an existing item in DynamoDB."""
            table_name = table or self.default_table
            try:
                self._check_table_allowed(table_name)
                table_resource = self.dynamodb.Table(table_name)  # type: ignore
                timestamp = datetime.now().isoformat()

                # Calculate size
                size_bytes = len(content.encode("utf-8"))
                size_kb = Decimal(str(round(size_bytes / 1024, 2)))

                table_resource.update_item(
                    Key={"id": item_id},
                    UpdateExpression=(
                        "SET content = :content, #ts = :timestamp, size_bytes = :size_bytes, size_kb = :size_kb"
                    ),
                    ExpressionAttributeNames={
                        "#ts": "timestamp"  # Escape reserved keyword
                    },
                    ExpressionAttributeValues={
                        ":content": content,
                        ":timestamp": timestamp,
                        ":size_bytes": size_bytes,
                        ":size_kb": size_kb,
                    },
                )

                storage_url = f"dynamodb://{table_name}/{item_id}"

                return {
                    "success": True,
                    "storage_url": storage_url,
                    "table": table_name,
                    "id": item_id,
                    "size_bytes": size_bytes,
                    "size_kb": size_kb,
                    "timestamp": timestamp,
                    "message": f"Successfully updated content at {storage_url}",
                }

            except Exception as e:
                return {
                    "success": False,
                    "error": f"Error updating content: {str(e)}",
                    "table": table_name,
                    "id": item_id,
                }

    def ensure_table_exists(self, table_name: str, table_schema: str = "default") -> bool:
        """
        Ensure DynamoDB table exists, create if not.

        Args:
            table_name: Name of the table
            table_schema: Schema type ('default' or 'research')

        Returns:
            True if table exists or was created successfully, False otherwise
        """
        try:
            table = self.dynamodb.Table(table_name)  # type: ignore
            table.load()  # This will raise an exception if table doesn't exist
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                # Table doesn't exist, create it
                try:
                    if table_schema == "research":
                        # Research documents table schema
                        table = self.dynamodb.create_table(  # type: ignore
                            TableName=table_name,
                            KeySchema=[
                                {
                                    "AttributeName": "workflow_id",
                                    "KeyType": "HASH",  # Partition key
                                },
                                {
                                    "AttributeName": "document_key",
                                    "KeyType": "RANGE",  # Sort key
                                },
                            ],
                            AttributeDefinitions=[
                                {
                                    "AttributeName": "workflow_id",
                                    "AttributeType": "S",
                                },
                                {
                                    "AttributeName": "document_key",
                                    "AttributeType": "S",
                                },
                            ],
                            BillingMode="PAY_PER_REQUEST",
                        )
                    else:
                        # Default simple table schema
                        table = self.dynamodb.create_table(  # type: ignore
                            TableName=table_name,
                            KeySchema=[
                                {
                                    "AttributeName": "id",
                                    "KeyType": "HASH",  # Partition key
                                }
                            ],
                            AttributeDefinitions=[
                                {
                                    "AttributeName": "id",
                                    "AttributeType": "S",
                                }
                            ],
                            BillingMode="PAY_PER_REQUEST",
                        )

                    # Wait for table to be created (for LocalStack this should be quick)
                    table.wait_until_exists()
                    logger.info("Created DynamoDB table: %s", table_name)
                    return True
                except Exception:
                    logger.exception("Error creating table %s", table_name)
                    return False
            else:
                logger.exception("Error checking table %s", table_name)
                return False

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


def create_dynamodb_mcp_server(
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    region_name: str | None = None,
    endpoint_url: str | None = None,
    default_table: str = "strands-storage",
    allowed_tables: list[str] | None = None,
) -> DynamoDBMCPServer:
    """
    Create and configure a DynamoDB MCP Server instance.

    Args:
        aws_access_key_id: AWS access key ID (defaults to env var or 'test')
        aws_secret_access_key: AWS secret access key (defaults to env var or 'test')
        region_name: AWS region (defaults to env var or 'us-east-1')
        endpoint_url: AWS endpoint URL override (defaults to None for real AWS DynamoDB)
        default_table: Default DynamoDB table name
        allowed_tables: Table names tools may access (defaults to DYNAMODB_ALLOWED_TABLES env or default table)

    Returns:
        Configured DynamoDBMCPServer instance
    """
    return DynamoDBMCPServer(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region_name,
        endpoint_url=endpoint_url,
        default_table=default_table,
        allowed_tables=allowed_tables,
    )


def main() -> None:
    """Main entry point for CLI usage."""
    import signal
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def signal_handler(_sig, _frame):
        logger.info("Shutting down DynamoDB MCP Server...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Starting DynamoDB MCP Server on port 8000...")
    logger.info("DynamoDB endpoint: %s", os.getenv("AWS_ENDPOINT_URL") or "AWS DynamoDB")
    logger.info("Health endpoint available at /health")
    logger.info("MCP endpoint available at /mcp")
    logger.info("Press Ctrl+C to stop the server")

    # Create server instance
    server = create_dynamodb_mcp_server()

    # Ensure default table exists on startup
    logger.info("Ensuring default table '%s' exists...", server.default_table)
    server.ensure_table_exists(server.default_table)

    # Ensure research documents table exists on startup
    research_table = os.getenv("DYNAMODB_TABLE_NAME", "strands-storage")
    logger.info("Ensuring research table '%s' exists...", research_table)
    server.ensure_table_exists(research_table, "research")

    try:
        server.run(transport="streamable-http")
    except KeyboardInterrupt:
        logger.info("Server stopped by user")


# Main entry point for running as a script
if __name__ == "__main__":
    main()
