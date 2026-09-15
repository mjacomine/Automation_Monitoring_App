"""Authentication against the UiPath Cloud Identity server.

Exchanges OAuth2 ``client_credentials`` for a short-lived bearer token. This is
the only component that knows how a token is obtained, so swapping grant types
or identity providers later touches nothing else.
"""

from __future__ import annotations

import requests

from .config import ClientConfig, Settings


def authenticate(settings: Settings, client: ClientConfig) -> str:
    """Exchange a client's credentials for an OAuth2 bearer access token.

    Args:
        settings: Application configuration carrying the shared token endpoint
            and scope.
        client: The Orchestrator client whose credentials to authenticate.

    Returns:
        The bearer access token string.

    Raises:
        requests.HTTPError: if the identity server returns a non-2xx status.
        RuntimeError: if the response omits an ``access_token``.
    """
    payload = {
        "grant_type": "client_credentials",
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "scope": settings.scope,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(
        settings.token_url,
        data=payload,
        headers=headers,
        timeout=settings.request_timeout,
    )
    response.raise_for_status()

    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("No access_token returned from the identity server.")
    return token
