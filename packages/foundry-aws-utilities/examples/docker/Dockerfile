# DynamoDB MCP Server Dockerfile
# Multi-stage build. foundry-aws-utilities resolves from a hosted package index
# via [tool.uv.sources] in pyproject.toml.

FROM python:3.13-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r mcpuser \
    && useradd -r -g mcpuser mcpuser \
    && mkdir -p /app/logs /app/data

###

FROM base AS builder

# Copy uv from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=true \
    UV_LINK_MODE=copy \
    UV_NO_INSTALLER_METADATA=true \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies. foundry-aws-utilities resolves from the hosted package
# index pinned in pyproject.toml's [tool.uv.sources].
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-dev --no-editable --no-install-project --no-install-workspace

###

FROM base AS production

# Copy built application from builder
COPY --from=builder --chown=mcpuser:mcpuser /app /app

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    AWS_DEFAULT_REGION=us-east-1 \
    AWS_ENDPOINT_URL=http://dynamodb-local:8000 \
    DYNAMODB_TABLE_NAME=strands-storage \
    LOG_LEVEL=INFO \
    ENVIRONMENT=production

# Set ownership and switch to non-root user
RUN chown -R mcpuser:mcpuser /app /app/logs /app/data
USER mcpuser

WORKDIR /app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Container metadata
LABEL \
    org.opencontainers.image.title="DynamoDB MCP Server" \
    org.opencontainers.image.description="MCP Server for DynamoDB operations with foundry-aws-utilities" \
    org.opencontainers.image.version="1.0.0" \
    org.opencontainers.image.source="https://github.com/boozallen/foundry-agent-packages" \
    org.opencontainers.image.licenses="Apache-2.0" \
    server.type="dynamodb-mcp-server"

# Expose MCP server port
EXPOSE 8000

# Note: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY should be set via
# docker run -e or docker-compose environment for security

# Start the MCP server
CMD ["python", "-m", "foundry_aws_utilities.mcp_server"]
