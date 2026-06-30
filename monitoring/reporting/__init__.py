"""Reporting backends: render a JobAnalysis to various output targets.

Each backend depends only on the analytics domain model, so new targets
(CSV, Slack, e-mail, ...) can be added here without touching upstream layers.
"""

from __future__ import annotations

from .console import render_console
from .dashboard import render_dashboard
from .trends import render_trends

__all__ = ["render_console", "render_dashboard", "render_trends"]
