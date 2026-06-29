# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""CORS middleware configuration for web client integration.

Provides environment-configurable CORS settings following established
configuration patterns with production-safe defaults and development overrides.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def get_cors_origins() -> list[str]:
    """Get CORS allowed origins from environment configuration.

    Follows established STRANDS_ prefix convention for environment variables
    with production-safe defaults and development-friendly overrides.

    Returns:
        List of allowed CORS origins

    Environment Variables:
        STRANDS_CORS_ORIGINS: Comma-separated list of allowed origins
                             Defaults to localhost for development
    """
    origins_env = os.getenv("STRANDS_CORS_ORIGINS", "")

    if origins_env:
        # Parse comma-separated origins from environment
        origins = [origin.strip() for origin in origins_env.split(",") if origin.strip()]
        return origins

    # Development defaults - localhost variants for local testing
    return [
        "http://localhost:3000",  # React development server
        "http://localhost:8000",  # FastAPI development server
        "http://localhost:8080",  # Alternative frontend port
        "http://127.0.0.1:3000",  # IPv4 localhost alternative
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
    ]


def get_cors_allow_credentials() -> bool:
    """Get CORS allow credentials setting from environment.

    Returns:
        Boolean indicating whether to allow credentials in CORS requests

    Environment Variables:
        STRANDS_CORS_ALLOW_CREDENTIALS: Boolean flag (true/false, 1/0)
                                       Defaults to False for security
    """
    credentials_env = os.getenv("STRANDS_CORS_ALLOW_CREDENTIALS", "false").lower()
    return credentials_env in ("true", "1", "yes", "on")


def get_cors_allow_methods() -> list[str]:
    """Get CORS allowed methods from environment configuration.

    Returns:
        List of allowed HTTP methods for CORS

    Environment Variables:
        STRANDS_CORS_ALLOW_METHODS: Comma-separated list of HTTP methods
                                   Defaults to standard API methods
    """
    methods_env = os.getenv("STRANDS_CORS_ALLOW_METHODS", "")

    if methods_env:
        methods = [method.strip().upper() for method in methods_env.split(",") if method.strip()]
        return methods

    # Standard API methods for query processing
    return ["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"]


def get_cors_allow_headers() -> list[str]:
    """Get CORS allowed headers from environment configuration.

    Returns:
        List of allowed headers for CORS preflight requests

    Environment Variables:
        STRANDS_CORS_ALLOW_HEADERS: Comma-separated list of header names
                                   Defaults to common API headers
    """
    headers_env = os.getenv("STRANDS_CORS_ALLOW_HEADERS", "")

    if headers_env:
        headers = [header.strip() for header in headers_env.split(",") if header.strip()]
        return headers

    # Standard headers for API requests including correlation IDs
    return [
        "Accept",
        "Accept-Language",
        "Content-Language",
        "Content-Type",
        "Authorization",
        "X-Requested-With",
        "X-Correlation-ID",
        "X-Request-ID",
    ]


def add_cors_middleware(app: FastAPI) -> None:
    """Add CORS middleware to FastAPI application with environment configuration.

    Configures CORS middleware with environment-driven settings following
    established patterns for production deployment and development workflow.

    Args:
        app: FastAPI application instance to configure

    Environment Variables:
        STRANDS_CORS_ORIGINS: Allowed origins (comma-separated)
        STRANDS_CORS_ALLOW_CREDENTIALS: Allow credentials (true/false)
        STRANDS_CORS_ALLOW_METHODS: Allowed methods (comma-separated)
        STRANDS_CORS_ALLOW_HEADERS: Allowed headers (comma-separated)
    """
    origins = get_cors_origins()
    allow_credentials = get_cors_allow_credentials()
    allow_methods = get_cors_allow_methods()
    allow_headers = get_cors_allow_headers()

    app.add_middleware(
        CORSMiddleware,  # ty:ignore[invalid-argument-type]
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
        expose_headers=[
            "X-Correlation-ID",
            "X-Request-ID",
            "X-Response-Time-MS",
        ],
        max_age=600,  # Cache preflight requests for 10 minutes
    )
