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
from dataclasses import replace
from datetime import datetime, timezone

import requests

from monitoring import (
    ClientConfig,
    OrchestratorClient,
    Settings,
    analyze_jobs,
    authenticate,
    load_last_poll,
    load_metrics_jobs,
    persist_metrics_jobs,
    persist_snapshot,
    update_last_poll,
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

    metrics = persist_metrics_jobs(settings, client, payload)
    if metrics is not None:
        upserted, skipped = metrics
        msg = f"  Upserted {upserted} row(s) into f_auto_metrics_jobs."
        if skipped:
            msg += f" Skipped {skipped} with no ReleaseName."
        print(msg)
    print()
    return payload


def run(settings: Settings) -> int:
    """Execute one monitoring cycle across all clients. Returns an exit code."""
    # 0. Incremental poll window -------------------------------------------
    # Capture this run's start time (UTC) up front: it becomes the lower bound
    # for the *next* run, so jobs created while this run is in flight are still
    # picked up next time. Load the previous run's timestamp from the last_poll
    # table and use it as this run's CreationTime filter, so the API only
    # returns jobs created since we last polled.
    creation_time_temp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    last_poll = load_last_poll(settings)
    if last_poll is None:
        print(
            "ERROR: incremental polling requires the last_poll cursor in the "
            "database, but none was found. Set DATABASE_URL and ensure the "
            "last_poll table has a row.",
            file=sys.stderr,
        )
        return 1
    last_poll_id, creation_time = last_poll
    settings = replace(settings, creation_time=creation_time)
    print(
        f"Incremental poll: jobs created after {creation_time} "
        f"(cursor advances to {creation_time_temp} UTC at end).\n"
    )

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
    # When persistence is active, report off the stored f_auto_metrics_jobs
    # table (the accumulated, deduplicated set across all clients and runs) so
    # the dashboard always matches what is in the database. Otherwise fall back
    # to the combined live payloads from this run.
    metrics_payload = load_metrics_jobs(settings)
    if metrics_payload is not None:
        analysis_source = metrics_payload
        report_desc = "all jobs stored in f_auto_metrics_jobs"
        print("Building report from the f_auto_metrics_jobs table.")
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

    # 8. Advance the incremental-poll cursor -------------------------------
    # Now that this run has fetched (and persisted) jobs, move the last_poll
    # cursor to this run's start time so the next run is incremental. Never
    # reached on a total fetch failure (handled by the early return above), so
    # we never advance past jobs we failed to retrieve.
    update_last_poll(settings, last_poll_id, creation_time_temp)
    print(f"\nAdvanced last_poll cursor to {creation_time_temp} (UTC).")

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
