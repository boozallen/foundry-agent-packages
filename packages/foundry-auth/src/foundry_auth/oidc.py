# Copyright 2026 Booz Allen Hamilton Inc.
# SPDX-License-Identifier: Apache-2.0
import httpx


async def get_metadata(discovery_url: str) -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.get(discovery_url, timeout=10)
        r.raise_for_status()
        return r.json()


async def refresh_oauth_tokens(
    refresh_token: str, client_id: str, metadata: dict, client_secret: str = ""
) -> tuple[str, str | None, int, str | None]:
    """Refresh OAuth tokens using a refresh token.

    Args:
        refresh_token: The refresh token to use
        client_id: OAuth client ID
        metadata: OIDC metadata dictionary containing token_endpoint
        client_secret: OAuth client secret (required for confidential clients)

    Returns:
        Tuple of (access_token, refresh_token, expires_in, id_token). id_token is
        None unless the IdP rotated one on this refresh - most IdPs don't.

    Raises:
        httpx.HTTPStatusError: If the refresh request fails (401, etc.)
        httpx.RequestError: If network error occurs
    """
    token_endpoint = metadata["token_endpoint"]
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret

    async with httpx.AsyncClient() as client:
        response = await client.post(token_endpoint, data=data, timeout=10)
        response.raise_for_status()
        token_data = response.json()

        return (
            token_data["access_token"],
            token_data.get("refresh_token"),
            token_data["expires_in"],
            token_data.get("id_token"),
        )
