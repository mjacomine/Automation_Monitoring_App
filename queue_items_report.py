"""Ad-hoc QueueItems fetcher — dumps raw results to a text file for review.

Unlike ``main.py``, this does *no* persistence. It authenticates each
configured Orchestrator client with its Client ID / Secret, calls the
``odata/QueueItems`` endpoint (currently with a ``$top=10`` cap for testing),
and writes the returned items to a plain-text file so they can be eyeballed.

Run with:  python queue_items_report.py
"""

from __future__ import annotations

import json
import os
import sys

import requests

from monitoring import OrchestratorClient, Settings, authenticate

# Query options for this run. Testing with $top=10 for now; swap in a
# {"$filter": "CreationTime gt ..."} once the endpoint shape is confirmed.
QUEUE_ITEMS_PARAMS = {"$top": 10}
OUTPUT_FILENAME = "queue_items.txt"


def _report_error(lines: list[str], context: str, exc: Exception) -> None:
    """Print an API error to stderr and record it in the report lines."""
    print(f"  ERROR: request failed while {context}: {exc}", file=sys.stderr)
    response = getattr(exc, "response", None)
    if response is not None and response.text:
        print(f"  Orchestrator said: {response.text}", file=sys.stderr)
    lines.append(f"ERROR while {context}: {exc}")
    lines.append("")


def fetch_queue_items(settings: Settings) -> str:
    """Fetch QueueItems for every client and write them to a text file.

    Returns the path of the written file.
    """
    lines: list[str] = []
    lines.append("UiPath Orchestrator QueueItems report")
    lines.append(f"Query: {QUEUE_ITEMS_PARAMS}")
    lines.append("=" * 70)
    lines.append("")

    for client in settings.clients:
        label = f"{client.name} ({client.client_code}/{client.environment})"
        print(f"--- {label} ---")
        lines.append(f"### {label}")
        try:
            token = authenticate(settings, client)
            orch = OrchestratorClient(settings, client, token)
            payload = orch.get_queue_items(QUEUE_ITEMS_PARAMS)
        except requests.RequestException as exc:
            _report_error(lines, f"fetching QueueItems for {label}", exc)
            continue

        items = payload.get("value", [])
        print(f"  Retrieved {len(items)} queue item(s).")
        lines.append(f"Retrieved {len(items)} queue item(s).")
        lines.append(json.dumps(items, indent=2, ensure_ascii=False))
        lines.append("")

    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), OUTPUT_FILENAME
    )
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return output_path


def main() -> int:
    try:
        settings = Settings.load()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output_path = fetch_queue_items(settings)
    print(f"\nQueueItems written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
