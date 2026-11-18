# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Shared input-length bounds for the AWS MCP servers.

STIG V-222612 (SRG-APP-000450): user-supplied string arguments on the MCP tools
must be bounded to prevent overflow-style abuse. Limits are aligned with AWS
service maxima where applicable so legitimate calls are never blocked by this
check (AWS would reject anything larger regardless).
"""

import os

# AWS service maxima
MAX_S3_KEY_LENGTH = int(os.getenv("FOUNDRY_AWS_UTILITIES_MAX_S3_KEY_LEN", "1024"))
MAX_S3_BUCKET_LENGTH = int(os.getenv("FOUNDRY_AWS_UTILITIES_MAX_S3_BUCKET_LEN", "63"))
MAX_DDB_TABLE_NAME_LENGTH = int(os.getenv("FOUNDRY_AWS_UTILITIES_MAX_TABLE_LEN", "255"))

# Identifier / general string caps
MAX_DDB_KEY_LENGTH = int(os.getenv("FOUNDRY_AWS_UTILITIES_MAX_KEY_LEN", "1024"))
MAX_PREFIX_LENGTH = int(os.getenv("FOUNDRY_AWS_UTILITIES_MAX_PREFIX_LEN", "1024"))
MAX_KB_ID_LENGTH = int(os.getenv("FOUNDRY_AWS_UTILITIES_MAX_KB_ID_LEN", "128"))

# Free-text payload caps
MAX_CONTENT_LENGTH = int(os.getenv("FOUNDRY_AWS_UTILITIES_MAX_CONTENT_LEN", "1048576"))
MAX_QUERY_LENGTH = int(os.getenv("FOUNDRY_AWS_UTILITIES_MAX_QUERY_LEN", "10000"))


def enforce_str_bounds(*fields: tuple[str, str | None, int]) -> None:
    """Raise ``ValueError`` if any ``(name, value, max_len)`` string exceeds its limit.

    ``None`` values are ignored (optional arguments). Intended to be called at the
    start of an MCP tool body so the tool's existing ``except`` returns the standard
    structured error result.
    """
    for name, value, max_len in fields:
        if value is not None and len(value) > max_len:
            raise ValueError(f"{name} exceeds maximum length of {max_len} characters (got {len(value)})")
