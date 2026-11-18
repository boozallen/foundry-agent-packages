#!/usr/bin/env python3
# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""
Bedrock Knowledge Base MCP Server - Query Amazon Bedrock Knowledge Bases

This MCP server provides tools for:
- Querying a Bedrock Knowledge Base and retrieving relevant chunks
- Listing knowledge bases in the account
- Operating with Amazon Bedrock Knowledge Bases (RAG retrieval)
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
from ._validation import MAX_KB_ID_LENGTH, MAX_QUERY_LENGTH, enforce_str_bounds

logger = logging.getLogger(__name__)


class BedrockKBMCPServer:
    """Bedrock Knowledge Base MCP Server for RAG retrieval operations."""

    def __init__(
        self,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        region_name: str | None = None,
        knowledge_base_id: str | None = None,
        allowed_knowledge_base_ids: list[str] | None = None,
    ):
        """
        Initialize Bedrock Knowledge Base MCP Server.

        Args:
            aws_access_key_id: AWS access key ID (defaults to env var)
            aws_secret_access_key: AWS secret access key (defaults to env var)
            region_name: AWS region (defaults to env var or 'us-east-1')
            knowledge_base_id: Default knowledge base ID (defaults to env BEDROCK_KNOWLEDGE_BASE_ID)
            allowed_knowledge_base_ids: KB IDs tools may query (defaults to env BEDROCK_KB_ALLOWED_IDS
                comma-separated, else just knowledge_base_id). Tools reject any KB ID outside this set.
        """
        session_kwargs = {"region_name": region_name or os.getenv("AWS_DEFAULT_REGION", "us-east-1")}
        access_key = aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = aws_secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        if access_key and secret_key:
            session_kwargs["aws_access_key_id"] = access_key
            session_kwargs["aws_secret_access_key"] = secret_key

        self.session = boto3.Session(**session_kwargs)
        self.runtime_client = self.session.client("bedrock-agent-runtime")  # type: ignore
        self.agent_client = self.session.client("bedrock-agent")  # type: ignore
        self.knowledge_base_id = knowledge_base_id or os.getenv("BEDROCK_KNOWLEDGE_BASE_ID") or ""

        env_allowed = os.getenv("BEDROCK_KB_ALLOWED_IDS", "")
        if allowed_knowledge_base_ids is None and env_allowed:
            allowed_knowledge_base_ids = [k.strip() for k in env_allowed.split(",") if k.strip()]
        self.allowed_knowledge_base_ids: set[str] = set(allowed_knowledge_base_ids or [])
        if self.knowledge_base_id:
            self.allowed_knowledge_base_ids.add(self.knowledge_base_id)

        self.server = FastMCP("Bedrock Knowledge Base MCP Server")  # type: ignore

        self._register_routes()
        self._register_tools()

    def _register_routes(self) -> None:
        """Register custom HTTP routes."""

        @self.server.custom_route("/health", methods=["GET"])
        async def health_check(_request: Request) -> JSONResponse:
            return JSONResponse(
                {
                    "status": "healthy",
                    "server": "Bedrock Knowledge Base MCP Server",
                    "timestamp": datetime.now().isoformat(),
                    "mcp_port": 8000,
                    "region": self.session.region_name,
                    "default_knowledge_base_id": self.knowledge_base_id or "(not set)",
                }
            )

    def _check_kb_allowed(self, kb_id: str) -> None:
        """Raise if kb_id is not in the operator-configured allowlist."""
        if kb_id not in self.allowed_knowledge_base_ids:
            raise PermissionError(f"Knowledge base '{kb_id}' is not in the allowed set")

    def _register_tools(self) -> None:
        """Register MCP tools."""

        @self.server.tool()  # type: ignore
        def bedrock_kb_retrieve(
            query: str,
            knowledge_base_id: str | None = None,
            number_of_results: int = 5,
        ) -> dict[str, Any]:
            """Query a Bedrock Knowledge Base and retrieve relevant text chunks (RAG retrieval)."""
            kb_id = knowledge_base_id or self.knowledge_base_id
            if not kb_id:
                return {
                    "success": False,
                    "error": "knowledge_base_id is required (set BEDROCK_KNOWLEDGE_BASE_ID or pass knowledge_base_id)",
                    "results": [],
                }
            if not query or not query.strip():
                return {
                    "success": False,
                    "error": "query must be non-empty",
                    "results": [],
                }
            try:
                enforce_str_bounds(
                    ("query", query, MAX_QUERY_LENGTH),
                    ("knowledge_base_id", knowledge_base_id, MAX_KB_ID_LENGTH),
                )
                self._check_kb_allowed(kb_id)
                retrieval_config: dict[str, Any] = {}
                if number_of_results > 0:
                    retrieval_config["vectorSearchConfiguration"] = {
                        "numberOfResults": min(max(1, number_of_results), 25)
                    }
                response = self.runtime_client.retrieve(
                    knowledgeBaseId=kb_id,
                    retrievalQuery={"text": query.strip()},
                    retrievalConfiguration=retrieval_config if retrieval_config else None,
                )
                results = []
                for item in response.get("retrievalResults", []):
                    content = item.get("content", {})
                    text = content.get("text", "")
                    location = item.get("location", {})
                    score = item.get("score")
                    results.append(
                        {
                            "text": text,
                            "score": score,
                            "location": location,
                        }
                    )
                return {
                    "success": True,
                    "knowledge_base_id": kb_id,
                    "query": query.strip(),
                    "results": results,
                    "count": len(results),
                    "next_token": response.get("nextToken"),
                }
            except ClientError as e:
                return {
                    "success": False,
                    "error": e.response.get("Error", {}).get("Message", str(e)),
                    "knowledge_base_id": kb_id,
                    "results": [],
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "knowledge_base_id": kb_id,
                    "results": [],
                }

        @self.server.tool()  # type: ignore
        def list_knowledge_bases(
            max_results: int = 10,
        ) -> dict[str, Any]:
            """List Bedrock Knowledge Bases in the account (IDs and names)."""
            try:
                response = self.agent_client.list_knowledge_bases(maxResults=max_results)
                kb_list = [
                    {
                        "knowledge_base_id": kb["knowledgeBaseId"],
                        "name": kb.get("name", ""),
                        "description": kb.get("description", ""),
                        "status": kb.get("status", ""),
                        "updated_at": (kb["updatedAt"].isoformat() if kb.get("updatedAt") else None),
                    }
                    for kb in response.get("knowledgeBaseSummaries", [])
                ]
                return {
                    "success": True,
                    "knowledge_bases": kb_list,
                    "count": len(kb_list),
                    "next_token": response.get("nextToken"),
                }
            except ClientError as e:
                return {
                    "success": False,
                    "error": e.response.get("Error", {}).get("Message", str(e)),
                    "knowledge_bases": [],
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": str(e),
                    "knowledge_bases": [],
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


def create_bedrock_kb_mcp_server(
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    region_name: str | None = None,
    knowledge_base_id: str | None = None,
    allowed_knowledge_base_ids: list[str] | None = None,
) -> BedrockKBMCPServer:
    """
    Create and configure a Bedrock Knowledge Base MCP Server instance.

    Args:
        aws_access_key_id: AWS access key ID (defaults to env var)
        aws_secret_access_key: AWS secret access key (defaults to env var)
        region_name: AWS region (defaults to env var or 'us-east-1')
        knowledge_base_id: Default knowledge base ID (defaults to BEDROCK_KNOWLEDGE_BASE_ID)
        allowed_knowledge_base_ids: KB IDs tools may query (defaults to BEDROCK_KB_ALLOWED_IDS env or default KB)

    Returns:
        Configured BedrockKBMCPServer instance
    """
    return BedrockKBMCPServer(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region_name,
        knowledge_base_id=knowledge_base_id,
        allowed_knowledge_base_ids=allowed_knowledge_base_ids,
    )


def main() -> None:
    """Main entry point for CLI usage."""
    import signal
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def signal_handler(_sig: int, _frame: object) -> None:
        logger.info("Shutting down Bedrock Knowledge Base MCP Server...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Starting Bedrock Knowledge Base MCP Server on port 8000...")
    logger.info("Region: %s", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    kb_id = os.getenv("BEDROCK_KNOWLEDGE_BASE_ID") or "(set BEDROCK_KNOWLEDGE_BASE_ID for default)"
    logger.info("Default knowledge base ID: %s", kb_id)
    logger.info("Health endpoint available at /health")
    logger.info("MCP endpoint available at /mcp")
    logger.info("Press Ctrl+C to stop the server")

    server = create_bedrock_kb_mcp_server()
    try:
        server.run(transport="streamable-http")
    except KeyboardInterrupt:
        logger.info("Server stopped by user")


if __name__ == "__main__":
    main()
