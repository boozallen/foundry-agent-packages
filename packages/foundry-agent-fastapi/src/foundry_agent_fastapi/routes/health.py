# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Health check endpoint for service liveness."""

from fastapi import APIRouter, status

router = APIRouter()


@router.get("/api/v1/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, str]:
    """Basic liveness probe."""
    return {"status": "healthy"}
