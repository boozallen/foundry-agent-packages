# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
"""Agent configuration data models.

This module provides data model classes for agent configuration.
Config loading is powered by `foundry-agent-config`'s `load_config`,
which supports YAML files with environment variable overrides.
"""

import json
import logging
import os
import re
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo, field_validator, model_validator

from foundry_agent_config import load_config
from foundry_agent_core import _MAX_QUERY_LEN, InvalidConfigurationError, validate_bounded_dict

logger = logging.getLogger(__name__)

# Common credential-bearing HTTP header names (lower-cased for case-insensitive
# matching). This is a heuristic safety net, not an exhaustive credential
# classifier - it covers the header the finding names (Authorization), the other
# standard credential headers (Proxy-Authorization, Cookie), and the most common
# API-key conventions. Extending this set only makes the guard stricter, so it is
# safe to add names later without a breaking change.
_CREDENTIAL_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "x-api-key",
        "x-api-token",
        "api-key",
        "x-auth-token",
    }
)

_MAX_NAME_LEN = 128
_MAX_DESCRIPTION_LEN = 1024
_MAX_VERSION_LEN = 32
_MAX_PROVIDER_LEN = 32
_MAX_MODEL_ID_LEN = 256
_MAX_URL_LEN = 512
_MAX_API_KEY_LEN = 256
_MAX_REGION_LEN = 64
_MAX_PROMPT_LEN = 16384
_MAX_MODULES = 64
_MAX_PATHS = 64
_MAX_ENTRY_LEN = 512
_MAX_KB_ID_LEN = 128
_MAX_SESSION_ID_LEN = 128
_MAX_BUCKET_LEN = 128
_MAX_PREFIX_LEN = 256
_MAX_SERVERS = 32
_MAX_LOG_LEVEL_LEN = 16
_MAX_PORT = 65535
_MAX_CONVERSATION_LENGTH = 1000
_MAX_CONVERSATION_WINDOW_SIZE = 1000
_MAX_QUERY_LENGTH = _MAX_QUERY_LEN
_MAX_RESPONSE_TIME_MS = 86_400_000  # 24h
_MAX_AGENT_STATE_KEYS = 128
_MAX_AGENT_STATE_KEY_LEN = 128
_MAX_AGENT_STATE_BYTES = 1_048_576

# RFC 3986 scheme grammar (section 3.1), anchored at the start: a scheme is
# exactly one letter followed by letters/digits/"+"/"-"/".", then ":". Used
# instead of urlsplit().scheme for the credential guard below because
# urlsplit() is lenient about what precedes the "://" - a space, tab, or
# control character embedded before the colon makes it silently return an
# empty (or, for some characters, a still-"http") scheme rather than raising,
# which would let a crafted url bypass a same-string scheme comparison. This
# regex either matches a real, well-formed scheme or doesn't match at all -
# no separate control-character blocklist to maintain.
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")

# Matches the "/", "?" or "#" that ends a URL's authority component (no match
# means it runs to end of string). Used by `_split_url_authority` to find the
# userinfo/host boundary without depending on a well-formed, `_SCHEME_RE`-matching
# scheme or a literal "://" being present - see `_redact_url`'s docstring.
_AUTHORITY_END_RE = re.compile(r"[/?#]")


def _split_url_authority(url: str) -> tuple[str, str, str] | None:
    """Split `url` into (scheme-and-slashes prefix, authority, remainder), or `None` if unparseable.

    Finds the first ":" (the scheme delimiter, whether or not `_SCHEME_RE` would consider the
    scheme well-formed), skips an optional "//", and takes everything up to the next "/", "?",
    "#" (or end of string) as the authority. This does NOT require a literal "://" or a
    well-formed scheme - see `_redact_url`'s docstring for why neither is required.
    Used by `_url_has_userinfo` to detect a credential in the authority's userinfo, and by
    `_redact_url` only for the scheme prefix (its redaction is deliberately broader).
    """
    colon = url.find(":")
    if colon == -1:
        return None
    rest = url[colon + 1 :]
    has_slashes = rest.startswith("//")
    authority_and_beyond = rest[2:] if has_slashes else rest
    sep_match = _AUTHORITY_END_RE.search(authority_and_beyond)
    end = sep_match.start() if sep_match else len(authority_and_beyond)
    authority = authority_and_beyond[:end]
    remainder = authority_and_beyond[end:]
    prefix = url[: colon + 1] + ("//" if has_slashes else "")
    return prefix, authority, remainder


def _url_has_userinfo(url: str) -> bool:
    """Whether `url` embeds a credential in its authority's userinfo (`user:pass@host`).

    Checked independent of any header: httpx derives HTTP Basic-Auth from a url's userinfo by
    default whenever no explicit `auth=` is set (`httpx.Client._build_request_auth`), so a
    plaintext url carrying its own embedded credential sends that credential unencrypted
    exactly like one paired with an `Authorization` header - even when the entry has no
    `headers` key at all.
    """
    split = _split_url_authority(url)
    return split is not None and "@" in split[1]


def _redact_url(url: str) -> str:
    r"""Redact a URL's userinfo, query and fragment, keeping scheme, host and path.

    A credential embedded in a URL (`http://user:token@host/path`, or a query parameter such  # trufflehog:ignore
    as `?token=...`) is exactly as sensitive as one in a header and must never appear
    verbatim in output this guard produces. The query and fragment are replaced wholesale
    (their contents can't be classified), and the scheme, host and path are kept so the
    message still identifies the endpoint. For the userinfo, this does
    NOT use a regex anchored on a literal "user:pass@" or "://...@" shape, and does NOT
    require the url to have a well-formed, `_SCHEME_RE`-matching scheme - each of those
    approaches leaks a real credential in a concrete shape:

    - `://[^/@]*@` (stops at the FIRST "@") under-redacts when the userinfo itself contains a
      literal "@" (e.g. a password like `p@ssw0rd`) - httpx (following WHATWG URL parsing)
      takes the LAST "@" as the host boundary, not the first.
    - Requiring a literal "://" misses the RFC-3986-valid `scheme:opaque` form with no
      authority marker at all (e.g. a dropped-slash typo, `"http:user:pass@host/path"`) -
      the credential passed through completely unredacted.
    - Anchoring on `_SCHEME_RE` matching first misses malformed-scheme urls (which
      `_validate_server_credentials` rejects unconditionally for that exact reason) - a
      malformed scheme must not also get a pass on credential redaction.
    - Stopping at the authority's end (the first "/", "?" or "#") misses an unencoded "/", "?"
      or "#" inside the password itself (`http://user:SEC/RET@host/`): the "@" is never seen.

    Instead, redaction is deliberately broader than `_url_has_userinfo`'s detection: everything
    after the scheme prefix up to the LAST "@" anywhere in the url is redacted (the host
    boundary httpx/WHATWG parsing uses), then the query and fragment. If a "?" or "#" comes
    before that "@", it can't be told whether the "?" sits in the password or the "@" sits in
    the query, so everything after the scheme prefix is redacted. The prefix is kept only when
    it is followed by "//" or is `http:`/`https:`, since in `user:pass@host` the text before
    the first ":" is a username, not a scheme. Over-redacting a url with a literal "@" in its
    path costs only readability; under-redacting would leak a credential.
    """
    at = url.rfind("@")
    if at == -1:
        return _redact_query_and_fragment(url)
    split = _split_url_authority(url)
    prefix = split[0] if split is not None and len(split[0]) <= at else ""
    if not prefix.endswith("//") and prefix[:-1].lower() not in ("http", "https"):
        prefix = ""
    query_start = _query_or_fragment_start(url)
    if query_start != -1 and query_start < at:
        return f"{prefix}<redacted>"
    return _redact_query_and_fragment(f"{prefix}<redacted>@{url[at + 1 :]}")


def _query_or_fragment_start(url: str) -> int:
    """Index of the first "?" or "#" in `url`, or -1 if it has neither."""
    return min((i for i in (url.find("?"), url.find("#")) if i != -1), default=-1)


def _redact_query_and_fragment(url: str) -> str:
    """Replace everything after the first "?" or "#" with `<redacted>` (its contents can't be classified)."""
    cut = _query_or_fragment_start(url)
    return url if cut == -1 else f"{url[: cut + 1]}<redacted>"


_BoundedName = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_NAME_LEN, strip_whitespace=True)]
_BoundedDescription = Annotated[
    str, StringConstraints(min_length=1, max_length=_MAX_DESCRIPTION_LEN, strip_whitespace=True)
]
_BoundedVersion = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_VERSION_LEN, strip_whitespace=True)]
_BoundedUrl = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_URL_LEN, strip_whitespace=True)]
_BoundedOptionalUrl = _BoundedUrl | None


def _is_credential_header(key: object) -> bool:
    """Whether a header key names a credential-bearing header (case- and whitespace-insensitive).

    httpx also accepts `bytes` header names, so those are decoded rather than passed through
    `str()`, which would render `b'Authorization'` and never match.
    """
    name = key.decode("latin-1") if isinstance(key, bytes) else str(key)
    return name.strip().lower() in _CREDENTIAL_HEADER_NAMES


def _redact_server_for_error(server: dict[str, Any]) -> dict[str, Any]:
    """Build a safe-to-log/raise representation of a server entry.

    `InvalidConfigurationError` renders its `config_value` argument straight into the
    exception's `str()` (`f"... (got: {config_value!r})"`), and that message can propagate
    into logs or error responses. The entire point of this module's credential guard is to
    stop a credential from reaching such a sink, so the guard must never hand the raw
    server dict - headers and all - to the exception it raises.

    This follows the same principle as `foundry_agent_core.masking.mask_session_id`/
    `redact_session_ids` (never let the raw sensitive value reach a log or exception), but
    uses a fixed `<redacted>` marker rather than that module's per-value hash token, since
    nothing needs to correlate one credential occurrence with another. A credential can sit
    in any header or any extra field, not only the ones `_CREDENTIAL_HEADER_NAMES` knows, so
    only what identifies the entry is kept: the url via `_redact_url` (userinfo, query and
    fragment redacted), a string `name`, the header names, and `None` values. Every header
    value, a non-mapping `headers` value, and every other field's value becomes `<redacted>`.
    """
    redacted: dict[str, Any] = {}
    for key, value in server.items():
        if key == "url" and isinstance(value, str):
            redacted[key] = _redact_url(value)
        elif key == "headers" and isinstance(value, Mapping):
            redacted[key] = dict.fromkeys(cast("Mapping[Any, Any]", value), "<redacted>")
        elif (key == "name" and isinstance(value, str)) or value is None:
            redacted[key] = value
        else:
            redacted[key] = "<redacted>"
    return redacted


def _validate_server_credentials(
    servers: list[dict[str, Any]], field_name: str, *, allow_insecure: bool
) -> list[dict[str, Any]]:
    r"""Reject (or warn about) MCP/A2A server entries that send credentials over insecure HTTP.

    An entry is "credentialed" if either its `headers` carry a credential-bearing header
    (`Authorization`, `X-Api-Key`, etc., matched case- and whitespace-insensitively) or its
    `url` embeds a credential in its own userinfo (`http://user:token@host/path`) - httpx  # trufflehog:ignore
    derives HTTP Basic-Auth from url userinfo by default even with no `headers` at all, so
    that case is exactly as unsafe and is checked independently of headers, not only when a
    header also happens to be present (see `_url_has_userinfo`).

    A non-credentialed entry is always allowed regardless of scheme - this guard is scoped to
    the specific unsafe combination the finding describes, not plaintext in general. A
    credentialed entry's scheme falls into one of three buckets:

    - Well-formed `https` - always safe, always allowed.
    - Well-formed `http` (exactly) - treated as a deployer's deliberate (if risky) choice: by
      default raises `InvalidConfigurationError`, or when `allow_insecure` is True (an
      explicit, deployer-controlled opt-in), downgrades to a logged warning so the entry
      still loads.
    - Anything else - unparseable, missing/non-string, or some other scheme entirely - raises
      unconditionally, never downgradable via `allow_insecure`. This doesn't look like a
      deployer's informed choice of plaintext http; it looks like malformed or
      adversarially-crafted input, and `allow_insecure` exists for the former, not the latter.

    A non-empty `headers` value that isn't a mapping (e.g. a list of `[name, value]` pairs)
    also raises unconditionally, whatever the scheme: its header names can't be checked, so
    the entry can't be proven non-credentialed.

    The scheme is checked via `_SCHEME_RE`, an RFC 3986-anchored regex, not
    `urlsplit(url).scheme`: `urlsplit` is lenient about what precedes the `://` - a NUL byte
    or a literal space embedded before the colon (e.g. `"ht\x00tp://..."`, `"ht p://..."`)
    makes it silently return an empty scheme rather than raising, and trusting that would let
    a crafted url bypass a same-string `scheme == "http"` comparison with its credential
    intact.

    The exception's `config_value` comes from `_redact_server_for_error`, and the `reason`
    strings and warning below carry only the url via `_redact_url` and header names, so no
    header value, url userinfo, query or fragment reaches the exception message or a log line.
    """
    for server in servers:
        headers = server.get("headers") or {}
        if not isinstance(headers, Mapping):
            reason = (
                f"server entry has a non-mapping 'headers' value ({type(headers).__name__}) - its "
                "header names can't be checked for credentials, so this is rejected unconditionally"
            )
            raise InvalidConfigurationError(field_name, _redact_server_for_error(server), reason)
        offending_headers = [key for key in cast("Mapping[Any, Any]", headers) if _is_credential_header(key)]

        url = server.get("url")
        url_is_str = isinstance(url, str)
        url_has_credential = url_is_str and _url_has_userinfo(url)

        if not offending_headers and not url_has_credential:
            # Not credentialed by either route - out of this guard's scope regardless of
            # what the rest of the url looks like (or whether there even is one).
            continue

        if not url_is_str:
            # A missing or non-string url can't be proven to use https. The only way to
            # reach here with one is via offending_headers (url_has_credential requires
            # url_is_str) - reject unconditionally rather than silently letting it through.
            reason = (
                "server entry has a missing or non-string url and carries credential-bearing "
                f"header(s) {offending_headers} - cannot verify the transport is https, so "
                "this is rejected unconditionally"
            )
            raise InvalidConfigurationError(field_name, _redact_server_for_error(server), reason)

        if offending_headers and url_has_credential:
            credential_source = f"header(s) {offending_headers} and a credential embedded in the url's own userinfo"
        elif offending_headers:
            credential_source = f"header(s) {offending_headers}"
        else:
            credential_source = "a credential embedded in the url's own userinfo"

        match = _SCHEME_RE.match(url)
        scheme = match.group(1).lower() if match else None
        if scheme == "https":
            continue

        if scheme != "http":
            # Not a well-formed http/https scheme at all (unparseable, or some other
            # scheme entirely) - this doesn't look like a deployer's deliberate choice of
            # plaintext http, it looks like malformed or adversarially-crafted input. Never
            # downgradable via allow_insecure, unlike the well-formed-http case below: that
            # opt-in exists for a deployer knowingly choosing http, not for input the guard
            # couldn't even parse as a normal scheme.
            reason = (
                f"server url '{_redact_url(url)}' has an unparseable or non-http(s) scheme "
                f"and carries {credential_source} - the scheme could not be safely "
                "determined, so this is rejected unconditionally"
            )
            raise InvalidConfigurationError(field_name, _redact_server_for_error(server), reason)

        reason = (
            f"server url '{_redact_url(url)}' uses plaintext http and carries "
            f"{credential_source} - credentials would be sent unencrypted"
        )
        if not allow_insecure:
            raise InvalidConfigurationError(field_name, _redact_server_for_error(server), reason)

        logger.warning(
            "Allowing insecure credentialed endpoint in %s: %s (allow_insecure_credentialed_endpoints=True)",
            field_name,
            reason,
        )

    return servers


class StrandsSessionManagerType(StrEnum):
    FILE = "file"
    S3 = "s3"


def _config_model_config() -> ConfigDict:
    """Build the config models' settings.

    Config can hold secrets (agent state, API keys, MCP/A2A headers), so validation errors omit
    input values. Each model gets its own dict, so no settings are shared module state.
    """
    return ConfigDict(frozen=True, hide_input_in_errors=True)


class ModelGuardrailConfig(BaseModel):
    """Configuration for model guardrail settings."""

    model_config = _config_model_config()

    guardrail_id: Annotated[str, StringConstraints(min_length=1, max_length=128, strip_whitespace=True)]
    guardrail_version: Annotated[str, StringConstraints(min_length=1, max_length=64, strip_whitespace=True)]
    guardrail_trace: Annotated[str, StringConstraints(min_length=1, max_length=32, strip_whitespace=True)] | None = (
        "enabled"
    )


class AgentModelConfig(BaseModel):
    """Configuration for Strands Agent model settings."""

    model_config = _config_model_config()

    provider: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_PROVIDER_LEN, strip_whitespace=True)] = (
        "bedrock"
    )
    model_id: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_MODEL_ID_LEN, strip_whitespace=True)] = (
        "us.anthropic.claude-haiku-5-5"
    )
    ollama_url: _BoundedOptionalUrl = None
    llamacpp_url: _BoundedOptionalUrl = None
    nims_base_url: _BoundedOptionalUrl = None
    nims_api_key: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_API_KEY_LEN, strip_whitespace=True)] | None
    ) = None
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=131_072)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    # Extends (does not replace) the built-in reject set in factory.py's
    # _BEDROCK_TEMPERATURE_REJECTING_MODEL_SUBSTRINGS - lets an operator add a
    # newly-discovered temperature-rejecting model_id (or a custom import) without
    # a package upgrade.
    bedrock_temperature_rejecting_models: list[
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_MODEL_ID_LEN, strip_whitespace=True)]
    ] = Field(default_factory=list, max_length=_MAX_MODULES)
    streaming: bool = True
    region_name: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_REGION_LEN, strip_whitespace=True)] | None
    ) = None
    guardrails: ModelGuardrailConfig | None = None


class StrandsAgentConfig(BaseModel):
    """Complete configuration for Strands Agent instances.

    Contains model settings, system prompt, tool configuration, and
    environment-specific settings for agent query processing.

    Load via `load_config(StrandsAgentConfig, yaml_path, "STRANDS")` for
    YAML+env configuration, or `StrandsAgentConfig.from_env()` for
    environment-only backward compatibility.
    """

    model_config = _config_model_config()

    model: AgentModelConfig = Field(default_factory=AgentModelConfig)

    agent_name: _BoundedName = "strands-base-agent"
    agent_description: _BoundedDescription = "A general-purpose AI agent powered by AWS Strands Agent framework"
    agent_version: _BoundedVersion = "1.0"
    agent_port: int | None = Field(default=None, ge=1, le=_MAX_PORT)

    system_prompt: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_PROMPT_LEN)] = (
        "You are a helpful AI assistant powered by the AWS Strands Agent framework. "
        "You assist users by leveraging available tools and capabilities to provide "
        "accurate, helpful responses to their queries and tasks."
    )
    tools_modules: list[
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_ENTRY_LEN, strip_whitespace=True)]
    ] = Field(default_factory=list, max_length=_MAX_MODULES)
    tools_files: list[
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_ENTRY_LEN, strip_whitespace=True)]
    ] = Field(default_factory=list, max_length=_MAX_PATHS)
    tools_dir: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_ENTRY_LEN, strip_whitespace=True)] | None
    ) = None
    max_conversation_length: int = Field(default=10, ge=1, le=_MAX_CONVERSATION_LENGTH)
    enable_memory: bool = False
    knowledge_base_id: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_KB_ID_LEN, strip_whitespace=True)] | None
    ) = None

    session_id: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_SESSION_ID_LEN, strip_whitespace=True)] | None
    ) = None
    session_type: StrandsSessionManagerType | None = None
    session_storage_dir: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_ENTRY_LEN, strip_whitespace=True)] | None
    ) = None
    session_s3_bucket: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_BUCKET_LEN, strip_whitespace=True)] | None
    ) = None
    session_s3_prefix: (
        Annotated[str, StringConstraints(min_length=1, max_length=_MAX_PREFIX_LEN, strip_whitespace=True)] | None
    ) = None
    session_restore_dangling_tool_use: Literal["sanitize", "reject"] = "sanitize"

    conversation_window_size: int = Field(default=100, ge=1, le=_MAX_CONVERSATION_WINDOW_SIZE)
    conversation_truncate_results: bool = False
    agent_state_initial_values: dict[str, Any] = Field(default_factory=dict)

    # Deployer-controlled, template-repo-agnostic opt-in. This repo ships to many adopters
    # with different network topologies - some legitimately terminate TLS upstream (e.g. a
    # service mesh sidecar) or run local dev/test MCP/A2A endpoints without credentials, so
    # the guard below cannot hardcode one company's posture. When False (the default), an
    # http MCP/A2A endpoint that carries a credential (a credential-bearing header or url
    # userinfo) fails config load. When explicitly set True, that same combination is allowed
    # and a warning is logged instead - the deployer is asserting they have accepted or
    # otherwise mitigated the risk.
    allow_insecure_credentialed_endpoints: bool = False

    mcp_servers: list[dict[str, Any]] = Field(default_factory=list, max_length=_MAX_SERVERS)
    a2a_servers: list[dict[str, Any]] = Field(default_factory=list, max_length=_MAX_SERVERS)

    log_level: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_LOG_LEVEL_LEN, strip_whitespace=True)] = (
        "INFO"
    )
    max_query_length: int = Field(default=2000, ge=1, le=_MAX_QUERY_LENGTH)
    default_similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    max_response_time_ms: int = Field(default=30000, ge=1, le=_MAX_RESPONSE_TIME_MS)
    observability_enabled: bool = False

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str | None) -> str | None:
        if v is not None and v.strip() == "":
            raise InvalidConfigurationError("session_id", v, "cannot be empty or whitespace")
        return v

    @field_validator("mcp_servers", "a2a_servers")
    @classmethod
    def validate_servers_credentials(cls, v: list[dict[str, Any]], info: ValidationInfo) -> list[dict[str, Any]]:
        allow_insecure = bool(info.data.get("allow_insecure_credentialed_endpoints", False))
        field_name = info.field_name
        assert field_name is not None  # always set for a field_validator, per pydantic v2
        return _validate_server_credentials(v, field_name, allow_insecure=allow_insecure)

    def check_mcp_server_credentials(self, servers: list[dict[str, Any]]) -> None:
        """Apply the plaintext-credential guard to an MCP server list, honoring this config's opt-in.

        Used where MCP connections are opened, so servers that didn't come from this config's own
        validated `mcp_servers` are covered too.

        Raises:
            InvalidConfigurationError: If a server entry would send a credential over plaintext http
        """
        _validate_server_credentials(servers, "mcp_servers", allow_insecure=self.allow_insecure_credentialed_endpoints)

    @field_validator("session_type", mode="before")
    @classmethod
    def coerce_session_type(cls, v: Any) -> StrandsSessionManagerType | None:
        if v is None:
            return None
        if isinstance(v, StrandsSessionManagerType):
            return v
        try:
            return StrandsSessionManagerType(str(v).lower())
        except ValueError as e:
            raise InvalidConfigurationError("session_type", v, "must be one of: 'file', 's3'") from e

    @field_validator("session_restore_dangling_tool_use", mode="before")
    @classmethod
    def coerce_session_restore_dangling_tool_use(cls, v: Any) -> str:
        if isinstance(v, str):
            lowered = v.lower()
            if lowered in ("sanitize", "reject"):
                return lowered
        raise InvalidConfigurationError("session_restore_dangling_tool_use", v, "must be one of: 'sanitize', 'reject'")

    @field_validator("conversation_window_size")
    @classmethod
    def validate_conversation_window_size(cls, v: int) -> int:
        if v <= 0:
            raise InvalidConfigurationError(
                "conversation_window_size", v, "conversation_window_size must be a positive integer"
            )
        return v

    @field_validator("agent_state_initial_values")
    @classmethod
    def validate_agent_state_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        # InvalidConfigurationError renders its value into the message, and agent state can
        # hold secrets, so only the state's shape is passed (see _redact_server_for_error).
        try:
            validate_bounded_dict(
                v,
                max_keys=_MAX_AGENT_STATE_KEYS,
                max_key_len=_MAX_AGENT_STATE_KEY_LEN,
                max_bytes=_MAX_AGENT_STATE_BYTES,
                label="agent_state_initial_values",
            )
        except ValueError as e:
            raise InvalidConfigurationError(
                "agent_state_initial_values", f"<redacted: {len(v)} top-level keys>", str(e)
            ) from e
        return v

    @model_validator(mode="after")
    def validate_cross_field_constraints(self) -> Self:
        if self.enable_memory and not self.knowledge_base_id:
            raise InvalidConfigurationError(
                "knowledge_base_id", None, "knowledge_base_id is required when enable_memory is True"
            )
        if self.session_type is StrandsSessionManagerType.S3:
            if not self.session_s3_bucket or self.session_s3_bucket.strip() == "":
                raise InvalidConfigurationError(
                    "session_s3_bucket",
                    self.session_s3_bucket,
                    "session_s3_bucket is required when session_type is 's3'",
                )
        return self

    @classmethod
    def from_env(cls) -> Self:
        """Create config from environment variables (backward compatibility).

        Constructs a StrandsAgentConfig using STRANDS_* environment variables
        with sensible defaults. No YAML file required.
        """
        model = AgentModelConfig(
            provider=os.getenv("STRANDS_MODEL_PROVIDER", "bedrock").lower(),
            model_id=os.getenv("STRANDS_MODEL_ID", "us.anthropic.claude-haiku-5-5"),
            ollama_url=os.getenv("OLLAMA_URL", "http://host.docker.internal:11434"),
            llamacpp_url=os.getenv("LLAMACPP_URL", "http://localhost:8080"),
            nims_base_url=os.getenv("NIMS_BASE_URL"),
            nims_api_key=os.getenv("NIMS_API_KEY"),
            temperature=float(os.getenv("STRANDS_TEMPERATURE", "0.3")),
            max_tokens=int(v) if (v := os.getenv("STRANDS_MAX_TOKENS")) else None,
            top_p=float(v) if (v := os.getenv("STRANDS_TOP_P")) else None,
            bedrock_temperature_rejecting_models=[
                m.strip() for m in os.getenv("STRANDS_BEDROCK_TEMPERATURE_REJECTING_MODELS", "").split(",") if m.strip()
            ],
            streaming=os.getenv("STRANDS_STREAMING", "true").lower() == "true",
            region_name=os.getenv("AWS_DEFAULT_REGION"),
            guardrails=ModelGuardrailConfig(
                guardrail_id=os.getenv("STRANDS_GUARDRAIL_ID", ""),
                guardrail_version=os.getenv("STRANDS_GUARDRAIL_VERSION", ""),
                guardrail_trace=os.getenv("STRANDS_GUARDRAIL_TRACE"),
            )
            if os.getenv("STRANDS_GUARDRAIL_ID")
            else None,
        )

        tools_modules_env = os.getenv("STRANDS_TOOLS_MODULES", "")
        tools_files_env = os.getenv("STRANDS_TOOLS_FILES", "")

        mcp_servers: list[dict[str, Any]] = []
        if mcp_env := os.getenv("STRANDS_MCP_SERVERS"):
            mcp_servers = json.loads(mcp_env)

        a2a_servers: list[dict[str, Any]] = []
        if a2a_env := os.getenv("STRANDS_A2A_AGENTS"):
            a2a_servers = json.loads(a2a_env)

        raw_session_type = os.getenv("STRANDS_SESSION_MANAGER_TYPE")
        session_type: StrandsSessionManagerType | None = None
        if raw_session_type is not None:
            session_type = StrandsSessionManagerType(str(raw_session_type).lower())

        agent_state_initial_values: dict[str, Any] = {}
        if state_env := os.getenv("STRANDS_AGENT_STATE_INITIAL_VALUES"):
            agent_state_initial_values = json.loads(state_env)

        return cls(
            model=model,
            agent_name=os.getenv("STRANDS_AGENT_NAME", "strands-base-agent"),
            agent_description=os.getenv(
                "STRANDS_AGENT_DESCRIPTION",
                "A general-purpose AI agent powered by AWS Strands Agent framework",
            ),
            agent_version=os.getenv("STRANDS_AGENT_VERSION", "1.0"),
            agent_port=int(v) if (v := os.getenv("STRANDS_AGENT_PORT")) else None,
            system_prompt=os.getenv(
                "STRANDS_SYSTEM_PROMPT",
                (
                    "You are a helpful AI assistant powered by the AWS Strands Agent framework. "
                    "You assist users by leveraging available tools and capabilities to provide "
                    "accurate, helpful responses to their queries and tasks."
                ),
            ),
            tools_modules=[t.strip() for t in tools_modules_env.split(",") if t.strip()],
            tools_files=[t.strip() for t in tools_files_env.split(",") if t.strip()],
            tools_dir=os.getenv("STRANDS_TOOLS_DIR") or None,
            max_conversation_length=int(os.getenv("STRANDS_MAX_CONVERSATION_LENGTH", "10")),
            enable_memory=os.getenv("STRANDS_ENABLE_MEMORY", "false").lower() == "true",
            knowledge_base_id=os.getenv("STRANDS_KNOWLEDGE_BASE_ID"),
            allow_insecure_credentialed_endpoints=os.getenv(
                "STRANDS_ALLOW_INSECURE_CREDENTIALED_ENDPOINTS", "false"
            ).lower()
            == "true",
            mcp_servers=mcp_servers,
            a2a_servers=a2a_servers,
            session_id=os.getenv("STRANDS_SESSION_ID"),
            session_type=session_type,
            session_storage_dir=os.getenv("STRANDS_SESSION_STORAGE_DIR"),
            session_s3_bucket=os.getenv("STRANDS_SESSION_S3_BUCKET"),
            session_s3_prefix=os.getenv("STRANDS_SESSION_S3_PREFIX"),
            session_restore_dangling_tool_use=cast(
                "Literal['sanitize', 'reject']",
                os.getenv("STRANDS_SESSION_RESTORE_DANGLING_TOOL_USE", "sanitize"),
            ),
            conversation_window_size=int(os.getenv("STRANDS_CONVERSATION_WINDOW_SIZE", "100")),
            conversation_truncate_results=os.getenv("STRANDS_CONVERSATION_TRUNCATE_RESULTS", "false").lower() == "true",
            agent_state_initial_values=agent_state_initial_values,
            log_level=os.getenv("STRANDS_LOG_LEVEL", "INFO").upper(),
            max_query_length=int(os.getenv("STRANDS_MAX_QUERY_LENGTH", "2000")),
            default_similarity_threshold=float(os.getenv("STRANDS_DEFAULT_SIMILARITY_THRESHOLD", "0.7")),
            max_response_time_ms=int(os.getenv("STRANDS_MAX_RESPONSE_TIME_MS", "30000")),
            observability_enabled=os.getenv("STRANDS_O11Y_ENABLED", "false").lower() == "true",
        )

    @classmethod
    def from_yaml(cls, yaml_path: Path, env_prefix: str = "STRANDS") -> Self:
        """Load config from YAML file with environment variable overrides.

        This is the recommended loading path. Uses `load_config` from
        `foundry-agent-config` under the hood.

        Args:
            yaml_path: Path to YAML configuration file
            env_prefix: Environment variable prefix (default: "STRANDS")

        Returns:
            Validated StrandsAgentConfig instance

        Raises:
            foundry_agent_config.ConfigurationError: If loading or validation fails
        """
        return load_config(cls, yaml_path, env_prefix)


AgentConfig = StrandsAgentConfig
