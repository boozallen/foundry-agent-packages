# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Foundry AWS Utilities - AWS utilities package for Foundry platform

This package provides AWS service integrations and utilities, including:
- DynamoDB MCP Server for document storage operations
- S3 MCP Server for object storage operations
- Bedrock Knowledge Base MCP Server for RAG retrieval
- AWS service utilities and helpers

Usage:
    from foundry_aws_utilities.mcp_server import create_dynamodb_mcp_server
    from foundry_aws_utilities.s3_mcp_server import create_s3_mcp_server

    server = create_dynamodb_mcp_server()
    server.run(transport="streamable-http")

    # or S3:
    server = create_s3_mcp_server()
    server.run(transport="streamable-http")
"""

__author__ = "Foundry Baseline Team"
__description__ = "AWS utilities package for Foundry platform"

from importlib.metadata import PackageNotFoundError, version

from .bedrock_kb_mcp_server import (
    BedrockKBMCPServer,
    create_bedrock_kb_mcp_server,
)
from .mcp_server import (
    DynamoDBMCPServer,
    create_dynamodb_mcp_server,
)
from .s3_mcp_server import (
    S3MCPServer,
    create_s3_mcp_server,
)

try:
    __version__ = version("foundry-aws-utilities")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

__all__ = [
    "__version__",
    "create_dynamodb_mcp_server",
    "DynamoDBMCPServer",
    "create_s3_mcp_server",
    "S3MCPServer",
    "create_bedrock_kb_mcp_server",
    "BedrockKBMCPServer",
]
