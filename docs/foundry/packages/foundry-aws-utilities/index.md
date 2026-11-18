# foundry-aws-utilities

![Status: Available](https://img.shields.io/badge/status-available-brightgreen)
![Version](https://img.shields.io/badge/version-2.1.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

AWS service integrations for Foundry agents: DynamoDB, S3, and Bedrock
Knowledge Base MCP (Model Context Protocol) servers. No runtime
dependencies on other packages in this repo.

## Install

Install a released wheel from this repo's
[GitHub Releases](https://github.com/boozallen/foundry-agent-packages/releases).
See [Adopting these packages](../../releases/adopting.md) for
the full flow - pinning a release URL directly for evaluation, or
hosting the wheel in your own index for production, plus verifying the
SBOM/scan assets.

## Quickstart

```python
from foundry_aws_utilities import create_dynamodb_mcp_server

# Create server with default configuration
server = create_dynamodb_mcp_server()

# Run the server
server.run(transport="streamable-http")
```

Or run one of the three MCP servers as a standalone process via its
console entry point: `foundry-dynamodb-mcp-server`,
`foundry-s3-mcp-server`, or `foundry-bedrock-kb-mcp-server`.

## What's in the box

| Surface | Highlights |
|---------|------------|
| DynamoDB MCP server | `create_dynamodb_mcp_server`, `DynamoDBMCPServer` - store/retrieve/list/update/delete content, table management |
| S3 MCP server | `create_s3_mcp_server` - store/retrieve/list/delete objects, bucket management |
| Bedrock Knowledge Base MCP server | `create_bedrock_kb_mcp_server` - query a Bedrock Knowledge Base |
| Health endpoint | Every server exposes `GET /health` for liveness/readiness probes |

Each server works with LocalStack for local development and real AWS
for production; see the [Docker Compose example](../../../../packages/foundry-aws-utilities/examples/docker/README.md)
for a runnable stack.

## Security

- **HTTP transport requires a bearer token**: when a server is run over
  `streamable-http`, `BearerTokenMiddleware` rejects any request to `/mcp`
  without a matching `Authorization: Bearer <token>` header; only
  `GET /health` is exempt.
- **Input length limits** (STIG V-222612 overflow bounds) are configurable
  via environment variable - content payload, DynamoDB key/table name, S3
  key/bucket/prefix, Knowledge Base ID, and query string all have a
  bounded maximum length. See
  [Input Length Limits](../../../../packages/foundry-aws-utilities/README.md#input-length-limits)
  in the package README for the full variable list and defaults.

## Reference

- [README](../../../../packages/foundry-aws-utilities/README.md)
- [Changelog](../../../../packages/foundry-aws-utilities/CHANGELOG.md)
- [Source](../../../../packages/foundry-aws-utilities/)
- [License (Apache-2.0)](../../../../LICENSE)
