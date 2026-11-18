# DynamoDB MCP Server Docker Setup

This directory provides Docker configuration for running the DynamoDB MCP Server with LocalStack for local development, using the uv package manager. The `foundry-aws-utilities` package supplies the DynamoDB MCP server functionality and resolves from the package index pinned in `pyproject.toml`; see [Package Resolution](#package-resolution).

## Prerequisites

1. **Docker and Docker Compose**: Latest versions recommended
2. **Environment Configuration**: Copy and customize env.template (optional)

## Quick Start

1. **Set up environment (optional customization):**
   ```bash
   cp env.template .env
   # Customize .env if needed
   ```

2. **Start the stack:**
   ```bash
   docker compose up -d
   ```

3. **Check health:**
   ```bash
   # LocalStack DynamoDB
   curl http://localhost:4566/health

   # MCP Server
   curl http://localhost:9003/health
   ```

4. **Test MCP operations:**
   ```bash
   # List tables
   curl -X POST http://localhost:9003/mcp \
     -H "Content-Type: application/json" \
     -d '{"method": "tools/call", "params": {"name": "list_tables"}}'
   ```

## Services

### LocalStack DynamoDB
- **Purpose**: Local DynamoDB for development
- **Ports**:
  - `4566` - LocalStack main endpoint
  - `8001` - DynamoDB endpoint (for direct access)
- **Data**: Persisted in `./localstack-data/`

### MCP Server
- **Purpose**: DynamoDB MCP Server for agent integration
- **Port**: `9003` - MCP HTTP endpoint
- **Endpoints**:
  - `/health` - Health check
  - `/mcp` - MCP operations

## Environment Configuration

All settings have working defaults. Customize only if you need to:

```bash
cp env.template .env
# Edit .env as needed
```

### Key Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `UV_EXTRA_INDEX_URL` | Additional package index, if resolving from one you host | `https://pypi.internal.example.com/simple` |
| `AWS_ENDPOINT_URL` | LocalStack endpoint | `http://localhost:4566` |
| `DYNAMODB_TABLE_NAME` | Default table name | `strands-storage` |
| `MCP_SERVER_PORT` | MCP server port | `9003` |

### Package Resolution

`pyproject.toml` resolves `foundry-aws-utilities` from a hosted package index via
`[[tool.uv.index]]` / `[tool.uv.sources]`, following the adopter flow in
[Adopting these packages](../../../../docs/foundry/releases/adopting.md):
download the wheel from a `foundry-agent-packages` GitHub Release, host it in your
own index (Artifactory, CodeArtifact, `devpi`, etc.), and replace the placeholder
`https://<your-index>/simple` URL with your actual index, adding whatever
authentication it requires.

## Available MCP Tools

The DynamoDB MCP Server provides these tools:

### Table Management
- `create_table` - Create DynamoDB table
- `list_tables` - List all tables
- `describe_table` - Get table schema

### Data Operations
- `store_content` - Store data in table
- `retrieve_content` - Get data by key
- `query_items` - Query items with conditions
- `scan_table` - Scan entire table

### Example Usage

```bash
# Create a table
curl -X POST http://localhost:9003/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "method": "tools/call",
    "params": {
      "name": "create_table",
      "arguments": {
        "table_name": "my-table",
        "key_schema": "simple"
      }
    }
  }'

# Store content
curl -X POST http://localhost:9003/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "method": "tools/call",
    "params": {
      "name": "store_content",
      "arguments": {
        "content": "Hello, DynamoDB!",
        "table_name": "my-table",
        "content_type": "text"
      }
    }
  }'
```

## Development Commands

```bash
# Start services
docker compose up -d

# View logs
docker compose logs -f foundry-aws-utilities-mcp-server
docker compose logs -f dynamodb-local

# Rebuild MCP server (after foundry package changes)
docker compose up -d --build foundry-aws-utilities-mcp-server

# Stop services
docker compose down

# Clean up (removes data and volumes)
docker compose down -v

# Build without starting
docker compose build
```

## Building Against a Local Wheel

To test uncommitted changes to `foundry-aws-utilities` rather than the pinned git tag:

1. **Build the wheel** from the repository root:
   ```bash
   just build foundry-aws-utilities
   ```

2. **Point the example at it** by replacing the `[tool.uv.sources]` entry in
   `pyproject.toml` with a path source:
   ```toml
   [tool.uv.sources]
   foundry-aws-utilities = { path = "../../dist/foundry_aws_utilities-2.1.0-py3-none-any.whl" }
   ```

3. **Rebuild**:
   ```bash
   docker compose up -d --build foundry-aws-utilities-mcp-server
   ```

Alternatively, set `UV_EXTRA_INDEX_URL` to a local PyPI server hosting the wheel:

```bash
UV_EXTRA_INDEX_URL=http://localhost:8080/simple
docker compose up -d --build foundry-aws-utilities-mcp-server
```

## Troubleshooting

### Build Fails Resolving Dependencies
- **Error**: `No solution found when resolving dependencies`
- **Cause**: the build fetches `foundry-aws-utilities` from the index configured in
  `[[tool.uv.index]]`, so this usually means no network access to that index, a
  wrong URL, or missing authentication.
- **Check**:
  ```bash
  # Confirm the index is reachable and serves the package
  curl -f https://<your-index>/simple/foundry-aws-utilities/

  # Rebuild without the layer cache
  docker compose build --no-cache foundry-aws-utilities-mcp-server
  ```

### MCP Server Won't Start
- Check LocalStack is healthy: `docker compose ps`
- View MCP server logs: `docker compose logs foundry-aws-utilities-mcp-server`
- Verify AWS credentials in environment
- Check if foundry-aws-utilities installed correctly:
  ```bash
  docker compose exec foundry-aws-utilities-mcp-server python -c "import foundry_aws_utilities; print('OK')"
  ```

### Can't Connect to DynamoDB
- Ensure LocalStack is running: `curl http://localhost:4566/health`
- Check network connectivity between containers
- Verify `AWS_ENDPOINT_URL` points to `dynamodb-local:4566`

### Tables Not Creating
- Check LocalStack DynamoDB service status
- Verify AWS credentials (`test`/`test` for LocalStack)
- Check MCP server logs for error details

### Local Development Issues
- **UV_EXTRA_INDEX_URL not working**: use an absolute URL and confirm the index serves a `/simple` endpoint
- **Package not found**: verify the wheel path in `[tool.uv.sources]` resolves relative to `pyproject.toml`
- **Permission errors**: check file permissions on the directory holding the wheel

## Integration with Agents

Configure your Strands agent to use this MCP server:

```json
{
  "mcpServers": {
    "dynamodb": {
      "command": "http",
      "args": ["http://localhost:9003/mcp"]
    }
  }
}
```

## Production Usage

For production deployment:

1. **Replace LocalStack** with real AWS DynamoDB
2. **Configure real AWS credentials** via IAM roles
3. **Use HTTPS endpoints** with proper certificates
4. **Set up monitoring** and alerting
5. **Configure backup** and disaster recovery
