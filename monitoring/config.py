"""Centralised configuration for the Automation Monitoring App.

All tunable values live here behind a single immutable ``Settings`` object,
loaded once at startup from environment variables (and ``.env``) with sensible
defaults. Every other component receives the settings it needs by dependency
injection rather than reaching for globals, which keeps each module independent
and easy to test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Immutable application configuration.

    Construct via :meth:`Settings.load` so values resolve from the environment.
    """

    # --- Credentials (required, sourced from the environment) ---------------
    client_id: str
    client_secret: str

    # --- Authentication -----------------------------------------------------
    token_url: str = "https://cloud.uipath.com/identity_/connect/token"
    scope: str = "OR.Default"

    # --- Orchestrator endpoint ---------------------------------------------
    jobs_url: str = (
        "https://cloud.uipath.com/geisingerhs/Test/orchestrator_/odata/Jobs"
    )

    # --- Query filter -------------------------------------------------------
    # Lower bound for the CreationTime filter (ISO-8601 UTC).
    creation_time: str = "2026-03-22T00:00:00.000Z"
    # Restrict to a single SourceType ("Schedule", "Manual", ...) or None for all.
    source_type: str | None = "Schedule"

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
            ValueError: if the required credential variables are missing.
        """
        load_dotenv()

        client_id = os.getenv("ORCHESTRATOR_CLIENT_ID")
        client_secret = os.getenv("ORCHESTRATOR_API_KEY")
        if not client_id or not client_secret:
            raise ValueError(
                "ORCHESTRATOR_CLIENT_ID and/or ORCHESTRATOR_API_KEY are not set. "
                "Create a .env file (see .env.example) with your credentials."
            )

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            creation_time=os.getenv("MONITOR_CREATION_TIME", cls.creation_time),
            source_type=os.getenv("MONITOR_SOURCE_TYPE", cls.source_type),
            database_url=os.getenv("DATABASE_URL") or None,
        )
