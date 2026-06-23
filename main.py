"""Entry point — orchestrates the Automation Monitoring data flow.

This is the *composition root*: the only place that knows the end-to-end
sequence. It wires the independent core components together and owns
process-level concerns (argument-free CLI run, exit codes, error reporting,
side effects like writing files and opening a browser). All real work lives in
the ``monitoring`` package.

    load config -> authenticate -> fetch jobs -> analyze -> report

Run with:  python main.py
"""

from __future__ import annotations

import os
import sys
import webbrowser

import requests

from monitoring import (
    OrchestratorClient,
    Settings,
    analyze_jobs,
    authenticate,
)
from monitoring.reporting import render_console, render_dashboard


def _write_dashboard(settings: Settings, html: str) -> str:
    """Write the dashboard HTML next to this script and return its path."""
    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), settings.dashboard_filename
    )
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return output_path


def run(settings: Settings) -> int:
    """Execute one monitoring cycle. Returns a process exit code."""
    # 1. Authenticate ------------------------------------------------------
    print("Requesting access token...")
    token = authenticate(settings)
    print("Access token acquired.\n")

    # 2. Fetch -------------------------------------------------------------
    client = OrchestratorClient(settings, token)
    filter_desc = client.build_filter()
    print(f"Calling Get Jobs with $filter: {filter_desc}\n")
    payload = client.get_jobs()

    # 3. Analyze (pure) ----------------------------------------------------
    analysis = analyze_jobs(payload, settings.success_threshold)
    print(f"Returned {analysis.total_jobs} job(s).")
    print(f"Unique ReleaseName count: {analysis.unique_automations}\n")

    # 4. Report — console --------------------------------------------------
    print("Job counts per ReleaseName by State:")
    print(render_console(analysis))

    # 5. Report — HTML dashboard ------------------------------------------
    html = render_dashboard(analysis, filter_desc)
    output_path = _write_dashboard(settings, html)
    print(f"\nDashboard written to: {output_path}")
    if settings.open_dashboard:
        try:
            webbrowser.open(f"file://{output_path}")
        except Exception:
            pass

    return 0


def main() -> int:
    """Build settings, run a cycle, and translate failures into exit codes."""
    try:
        settings = Settings.load()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        return run(settings)
    except requests.HTTPError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        if exc.response is not None:
            print(exc.response.text, file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
