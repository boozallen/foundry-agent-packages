# Foundry AWS Utilities

AWS service integrations for Foundry agents, providing DynamoDB, S3, and [Bedrock Knowledge Base](https://aws.amazon.com/bedrock/knowledge-bases/) MCP servers.

## Overview

This package provides reusable AWS service integrations, with a focus on DynamoDB operations via an MCP (Model Context Protocol) server. It is designed to work seamlessly with LocalStack for local development and AWS for production.

## Features

- **[DynamoDB MCP Server](./src/foundry_aws_utilities/mcp_server.py)**: FastMCP-based server providing DynamoDB storage operations
- **LocalStack Support**: Works with LocalStack for local development
- **Production Ready**: Supports both local and production AWS environments
- **Table Management**: Automatic table creation with configurable schemas
- **Content Operations**: Store, retrieve, update, and delete content in DynamoDB

## Installation

The package is not published to public PyPI. Host a released wheel from this
repo's [GitHub Releases](https://github.com/boozallen/foundry-agent-packages/releases) in your own package index, and pin the package to that
index so it is never looked up on PyPI. See
[Adopting these packages](../../docs/foundry/releases/adopting.md) for the full
flow.

```toml
# pyproject.toml in your project
[[tool.uv.index]]
name = "my-index"
url = "https://<your-index>/simple"
explicit = true

[tool.uv.sources]
foundry-aws-utilities = { index = "my-index" }
```

```bash
uv add foundry-aws-utilities
```

Or install a downloaded wheel file directly:

```bash
pip install ./foundry_aws_utilities-<version>-py3-none-any.whl
```

Or from the monorepo:

```bash
cd foundry-agent-packages
uv pip install -e packages/foundry-aws-utilities
```

## Quick Start

### Running the MCP Server

```python
from foundry_aws_utilities import create_dynamodb_mcp_server

# Create server with default configuration
server = create_dynamodb_mcp_server()

# Run the server
server.run(transport="streamable-http")
```

### Command Line Usage

```bash
# Run as a standalone server
python -m foundry_aws_utilities.mcp_server

# Or use the entry point (if installed)
foundry-dynamodb-mcp-server
```

### Programmatic Usage

```python
from foundry_aws_utilities import DynamoDBMCPServer

# Create server with custom configuration
server = DynamoDBMCPServer(
    aws_access_key_id="your-key",
    aws_secret_access_key="your-secret",
    region_name="us-east-1",
    endpoint_url="http://localhost:4566",  # LocalStack
    default_table="my-table",
)

# Ensure table exists
server.ensure_table_exists("my-table")

# Run server
server.run()
```

## Configuration

The server can be configured via environment variables or constructor parameters:

### Environment Variables

- `AWS_ACCESS_KEY_ID`: AWS access key (defaults to 'test' for LocalStack)
- `AWS_SECRET_ACCESS_KEY`: AWS secret key (defaults to 'test' for LocalStack)
- `AWS_DEFAULT_REGION`: AWS region (defaults to 'us-east-1')
- `AWS_ENDPOINT_URL`: AWS endpoint URL (defaults to `http://localhost:4566` for LocalStack)
- `DYNAMODB_TABLE_NAME`: Default table name (defaults to 'strands-storage')

### Input Length Limits

STIG V-222612 overflow bounds — each limit is configurable via environment variable:

| Variable | Default | Description |
|---|---|---|
| `FOUNDRY_AWS_UTILITIES_MAX_CONTENT_LEN` | `1048576` | Maximum content payload length (bytes) |
| `FOUNDRY_AWS_UTILITIES_MAX_KEY_LEN` | `1024` | Maximum DynamoDB item key length |
| `FOUNDRY_AWS_UTILITIES_MAX_TABLE_LEN` | `255` | Maximum DynamoDB table name length |
| `FOUNDRY_AWS_UTILITIES_MAX_S3_KEY_LEN` | `1024` | Maximum S3 object key length |
| `FOUNDRY_AWS_UTILITIES_MAX_S3_BUCKET_LEN` | `63` | Maximum S3 bucket name length |
| `FOUNDRY_AWS_UTILITIES_MAX_PREFIX_LEN` | `1024` | Maximum S3 prefix length |
| `FOUNDRY_AWS_UTILITIES_MAX_KB_ID_LEN` | `128` | Maximum Knowledge Base ID length |
| `FOUNDRY_AWS_UTILITIES_MAX_QUERY_LEN` | `10000` | Maximum query string length |

### Constructor Parameters

All environment variables can be overridden via constructor parameters when creating the server programmatically.

## MCP Tools

The server provides the following MCP tools:

- `dynamodb_store_content`: Store content in DynamoDB
- `dynamodb_retrieve_content`: Retrieve content from DynamoDB
- `list_items`: List items in a DynamoDB table
- `create_table`: Create a new DynamoDB table
- `list_tables`: List all DynamoDB tables
- `delete_item`: Delete an item from DynamoDB
- `update_content`: Update content of an existing item

## Health Endpoint

The server exposes a health check endpoint at `/health`:

```bash
curl http://localhost:8000/health
```

## Docker Integration

The package can be used in Docker containers. Example Dockerfile:

```dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install the wheel downloaded from this repo's GitHub Releases
COPY foundry_aws_utilities-*.whl /tmp/
RUN pip install /tmp/foundry_aws_utilities-*.whl

# Run the server
CMD ["python", "-m", "foundry_aws_utilities.mcp_server"]
```

## Development

### Setup

```bash
# Install in development mode
uv pip install -e .

# Install test dependencies
uv pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing
```

### Code Quality

```bash
# Lint
ruff check src tests

# Format
ruff format src tests

# Type check
pyright src
```

## Architecture

The package is structured as follows:

```
foundry-aws-utilities/
├── src/
│   └── foundry_aws_utilities/
│       ├── __init__.py
│       └── mcp_server.py      # Main MCP server implementation
├── tests/
│   └── test_mcp_server.py      # Test suite
├── pyproject.toml              # Package configuration
└── README.md                   # This file
```

## License

Copyright (c) 2024 Foundry Team. All rights reserved.

## Contributing

This package is part of the Foundry ecosystem. For issues or feature requests, please contact the Foundry team.
