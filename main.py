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
    ClientConfig,
    OrchestratorClient,
    Settings,
    analyze_jobs,
    authenticate,
    load_metrics_jobs,
    persist_metrics_jobs,
    persist_snapshot,
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


def _process_client(settings: Settings, client: ClientConfig) -> dict | None:
    """Monitor one Orchestrator client: authenticate, fetch, and persist.

    Returns the client's raw Get Jobs payload, or ``None`` if the client could
    not be processed (so a single bad client never aborts the whole run).
    """
    label = f"{client.name} ({client.client_code}/{client.environment})"
    print(f"--- {label} ---")
    try:
        token = authenticate(settings, client)
        orch = OrchestratorClient(settings, client, token)
        filter_desc = orch.build_filter()
        print(f"  Calling Get Jobs with $filter: {filter_desc}")
        payload = orch.get_jobs()
    except requests.RequestException as exc:
        print(f"  ERROR: request failed for {label}: {exc}", file=sys.stderr)
        response = getattr(exc, "response", None)
        if response is not None and response.text:
            print(f"  Orchestrator said: {response.text}", file=sys.stderr)
        return None

    result = persist_snapshot(settings, payload, f"{client.name}: {filter_desc}")
    if result is None:
        print("  Persistence skipped (no DATABASE_URL set).")
    else:
        snapshot_id, job_count = result
        print(f"  Persisted snapshot #{snapshot_id} ({job_count} job(s) upserted).")

    metrics_count = persist_metrics_jobs(settings, payload)
    if metrics_count is not None:
        print(f"  Upserted {metrics_count} row(s) into auto_metrics_jobs.")
    print()
    return payload


def run(settings: Settings) -> int:
    """Execute one monitoring cycle across all clients. Returns an exit code."""
    # 1-3. Fetch + persist each configured client --------------------------
    print(f"Monitoring {len(settings.clients)} client(s).\n")
    payloads: list[dict] = []
    failures = 0
    for client in settings.clients:
        payload = _process_client(settings, client)
        if payload is None:
            failures += 1
        else:
            payloads.append(payload)

    if not payloads:
        print("No client returned data; nothing to report.", file=sys.stderr)
        return 1

    # 4. Choose the analysis source ---------------------------------------
    # When persistence is active, report off the stored auto_metrics_jobs
    # table (the accumulated, deduplicated set across all clients and runs) so
    # the dashboard always matches what is in the database. Otherwise fall back
    # to the combined live payloads from this run.
    metrics_payload = load_metrics_jobs(settings)
    if metrics_payload is not None:
        analysis_source = metrics_payload
        report_desc = "all jobs stored in auto_metrics_jobs"
        print("Building report from the auto_metrics_jobs table.")
    else:
        analysis_source = {"value": [j for p in payloads for j in p.get("value", [])]}
        report_desc = f"live jobs from {len(payloads)} client(s)"

    # 5. Analyze (pure) ----------------------------------------------------
    analysis = analyze_jobs(analysis_source, settings.success_threshold)
    print(f"Analyzed {analysis.total_jobs} job(s).")
    print(f"Unique ReleaseName count: {analysis.unique_automations}\n")

    # 6. Report — console --------------------------------------------------
    print("Job counts per ReleaseName by State:")
    print(render_console(analysis))

    # 7. Report — HTML dashboard ------------------------------------------
    html = render_dashboard(analysis, report_desc)
    output_path = _write_dashboard(settings, html)
    print(f"\nDashboard written to: {output_path}")
    if settings.open_dashboard:
        try:
            webbrowser.open(f"file://{output_path}")
        except Exception:
            pass

    # A partial run (some clients failed) is still a failure exit code so the
    # condition is visible to schedulers, but the dashboard already reflects
    # the clients that did succeed.
    if failures:
        print(
            f"\nWARNING: {failures} client(s) failed to process.", file=sys.stderr
        )
        return 1
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
