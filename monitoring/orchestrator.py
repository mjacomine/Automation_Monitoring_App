"""Client for the UiPath Orchestrator OData API.

Encapsulates everything about *talking to Orchestrator*: building the OData
``$filter`` and issuing the authenticated request. Callers get back the raw
decoded JSON; turning that into insight is the analytics layer's job, not this
one's. This separation means the API shape can change here without rippling
into reporting.
"""

from __future__ import annotations

import requests

from .config import ClientConfig, Settings


class OrchestratorClient:
    """Thin, authenticated wrapper over one client's Orchestrator Jobs endpoint."""

    def __init__(
        self, settings: Settings, client: ClientConfig, access_token: str
    ) -> None:
        self._settings = settings
        self._client = client
        self._access_token = access_token

    def build_filter(self) -> str:
        """Build the OData ``$filter`` expression from configuration."""
        clauses = [f"CreationTime gt {self._settings.creation_time}"]
        if self._settings.source_type:
            clauses.append(f"Type eq '{self._settings.source_type}'")
        return "(" + " and ".join(clauses) + ")"

    def get_jobs(self) -> dict:
        """Call the Get Jobs endpoint and return the decoded OData payload.

        Raises:
            requests.HTTPError: on a non-2xx response.
        """
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        params = {"$filter": self.build_filter()}

        response = requests.get(
            self._client.jobs_url(self._settings.base_url),
            headers=headers,
            params=params,
            timeout=self._settings.request_timeout,
        )
        response.raise_for_status()
        return response.json()
