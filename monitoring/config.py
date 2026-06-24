"""Centralised configuration for the Automation Monitoring App.

All tunable values live here behind a single immutable ``Settings`` object,
loaded once at startup from environment variables (and ``.env``) with sensible
defaults. Every other component receives the settings it needs by dependency
injection rather than reaching for globals, which keeps each module independent
and easy to test.

The app monitors *multiple* Orchestrator environments. The per-client values
(client code, environment name, and OAuth credentials) live in a list of
:class:`ClientConfig` objects, while everything shared (base URL, token
endpoint, query filter, persistence, thresholds) stays on ``Settings``. The
client list is sourced from a single ``ORCHESTRATOR_CLIENTS`` JSON environment
variable, so the same code path works whether that value comes from a local
``.env`` file or is injected from a secret manager in production.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class ClientConfig:
    """Credentials and addressing for a single Orchestrator environment."""

    name: str
    client_code: str
    environment: str
    client_id: str
    client_secret: str

    def _odata_base(self, base_url: str) -> str:
        """Build this client's ``/orchestrator_/odata`` root URL."""
        return (
            f"{base_url.rstrip('/')}/{self.client_code}/{self.environment}"
            "/orchestrator_/odata"
        )

    def jobs_url(self, base_url: str) -> str:
        """Build this client's fully-qualified Get Jobs OData URL."""
        return f"{self._odata_base(base_url)}/Jobs"


@dataclass(frozen=True)
class Settings:
    """Immutable application configuration.

    Construct via :meth:`Settings.load` so values resolve from the environment.
    """

    # --- Clients (one entry per Orchestrator environment to monitor) --------
    clients: tuple[ClientConfig, ...] = ()

    # --- Orchestrator addressing -------------------------------------------
    # Common base; each client's Jobs URL is derived as
    #   {base_url}/{client_code}/{environment}/orchestrator_/odata/Jobs
    base_url: str = "https://cloud.uipath.com"

    # --- Authentication -----------------------------------------------------
    token_url: str = "https://cloud.uipath.com/identity_/connect/token"
    scope: str = "OR.Default"

    # --- Query filter -------------------------------------------------------
    # Lower bound for the CreationTime filter (ISO-8601 UTC). There is no
    # static default: the value is populated at runtime from the last_poll
    # table (see ``main.run``), which is the single source of truth.
    creation_time: str | None = None
    # Restrict to a single SourceType ("Schedule", "Manual", ...) or None for all.
    source_type: str | None = "Unattended"

    # --- Persistence --------------------------------------------------------
    # Supabase/Postgres connection string. When unset, persistence is skipped
    # (the app still runs and reports), so local dev needs no database.
    database_url: str | None = None

    # --- Behaviour ----------------------------------------------------------
    request_timeout: int = 30
    # Success-rate threshold (percent) at or above which a process is "healthy".
    success_threshold: float = 90.0
    # Where the generated HTML dashboard is written.
    dashboard_filename: str = "dashboard.html"
    # Open the dashboard in a browser after generating it.
    open_dashboard: bool = True

    @classmethod
    def load(cls) -> "Settings":
        """Build a ``Settings`` instance from environment variables / ``.env``.

        Raises:
            ValueError: if no clients are configured, or the
                ``ORCHESTRATOR_CLIENTS`` JSON is malformed/incomplete.
        """
        load_dotenv()

        clients = cls._load_clients()
        if not clients:
            raise ValueError(
                "No Orchestrator clients configured. Set ORCHESTRATOR_CLIENTS to a "
                "JSON array of client objects (see .env.example), or provide the "
                "legacy ORCHESTRATOR_CLIENT_ID / ORCHESTRATOR_API_KEY for a single "
                "client."
            )

        return cls(
            clients=clients,
            base_url=os.getenv("ORCHESTRATOR_BASE_URL", cls.base_url),
            source_type=os.getenv("MONITOR_SOURCE_TYPE", cls.source_type),
            database_url=os.getenv("DATABASE_URL") or None,
        )

    @staticmethod
    def _load_clients() -> tuple[ClientConfig, ...]:
        """Resolve the client list from the environment.

        Prefers the ``ORCHESTRATOR_CLIENTS`` JSON array; falls back to the
        legacy single-client variables so existing ``.env`` files keep working.
        """
        raw = os.getenv("ORCHESTRATOR_CLIENTS")
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"ORCHESTRATOR_CLIENTS is not valid JSON: {exc}"
                ) from exc
            if not isinstance(data, list) or not data:
                raise ValueError(
                    "ORCHESTRATOR_CLIENTS must be a non-empty JSON array of "
                    "client objects."
                )

            required = ("client_code", "environment", "client_id", "api_key")
            clients = []
            for i, entry in enumerate(data):
                if not isinstance(entry, dict):
                    raise ValueError(
                        f"ORCHESTRATOR_CLIENTS[{i}] must be a JSON object."
                    )
                missing = [k for k in required if not entry.get(k)]
                if missing:
                    raise ValueError(
                        f"ORCHESTRATOR_CLIENTS[{i}] is missing required "
                        f"field(s): {', '.join(missing)}"
                    )
                clients.append(
                    ClientConfig(
                        name=entry.get("name") or entry["client_code"],
                        client_code=entry["client_code"],
                        environment=entry["environment"],
                        client_id=entry["client_id"],
                        client_secret=entry["api_key"],
                    )
                )
            return tuple(clients)

        # Backward compatibility: a single client from the original env vars.
        client_id = os.getenv("ORCHESTRATOR_CLIENT_ID")
        client_secret = os.getenv("ORCHESTRATOR_API_KEY")
        if client_id and client_secret:
            client_code = os.getenv("MONITOR_CLIENT_CODE", "geisingerhs")
            return (
                ClientConfig(
                    name=client_code,
                    client_code=client_code,
                    environment=os.getenv("MONITOR_ENVIRONMENT", "Test"),
                    client_id=client_id,
                    client_secret=client_secret,
                ),
            )

        return ()
