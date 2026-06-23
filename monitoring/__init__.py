"""Automation Monitoring App — composable core components.

Each module owns one concern and data flows one way through them:

    config       -> Settings (configuration)
    auth         -> authenticate() (OAuth token)
    orchestrator -> OrchestratorClient (Orchestrator API access)
    analytics    -> analyze_jobs() / JobAnalysis (pure aggregation)
    storage      -> persist_snapshot() (Postgres/Supabase persistence)
    reporting    -> render_console() / render_dashboard() (output)

``main.py`` wires these together; nothing here imports ``main``.
"""

from __future__ import annotations

from .analytics import JobAnalysis, ReleaseStats, analyze_jobs
from .auth import authenticate
from .config import Settings
from .orchestrator import OrchestratorClient
from .storage import persist_metrics_jobs, persist_snapshot

__all__ = [
    "Settings",
    "authenticate",
    "OrchestratorClient",
    "analyze_jobs",
    "JobAnalysis",
    "ReleaseStats",
    "persist_snapshot",
    "persist_metrics_jobs",
]
