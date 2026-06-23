"""Connect to UiPath Orchestrator and call the Get Jobs (OData) endpoint.

Authenticates with the Cloud Identity Server using the client_credentials
grant, then queries the Orchestrator Jobs endpoint, filtering for jobs created
after a configurable timestamp that were started by a Schedule.
"""

import json
import os
import sys
import webbrowser
from collections import Counter
from datetime import datetime
from html import escape

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Change this value to adjust the lower bound of the CreationTime filter.
# Must be an ISO-8601 UTC timestamp (e.g. "2026-03-22T00:00:00.000Z").
CREATION_TIME = "2026-03-22T00:00:00.000Z"

# Only return jobs whose SourceType matches this value (e.g. "Schedule",
# "Manual", "Agent", "Queue"). Set to None to return all source types.
SOURCE_TYPE = "Schedule"

# Authentication
TOKEN_URL = "https://cloud.uipath.com/identity_/connect/token"
SCOPE = "OR.Default"

# Orchestrator Jobs endpoint
JOBS_URL = "https://cloud.uipath.com/geisingerhs/Test/orchestrator_/odata/Jobs"

# Network timeout (seconds)
REQUEST_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

def get_access_token(client_id: str, client_secret: str) -> str:
    """Exchange client credentials for an OAuth2 bearer access token."""
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": SCOPE,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(
        TOKEN_URL, data=payload, headers=headers, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()

    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("No access_token returned from the identity server.")
    return token


def build_filter() -> str:
    """Build the OData $filter expression from the configured variables."""
    clauses = [f"CreationTime gt {CREATION_TIME}"]
    if SOURCE_TYPE:
        clauses.append(f"SourceType eq '{SOURCE_TYPE}'")
    return "(" + " and ".join(clauses) + ")"


def get_jobs(access_token: str) -> dict:
    """Call the Orchestrator Get Jobs endpoint with the configured filter."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    params = {"$filter": build_filter()}

    response = requests.get(
        JOBS_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def count_release_names(result: dict) -> Counter:
    """Count the number of jobs per unique ReleaseName.

    Iterates over the jobs in the OData ``value`` list and tallies how many
    times each ``ReleaseName`` appears. This gives the number of running
    processes grouped by process (release) name. Jobs missing a ReleaseName
    are grouped under "(unknown)".
    """
    counts: Counter = Counter()
    for job in result.get("value", []):
        release_name = job.get("ReleaseName") or "(unknown)"
        counts[release_name] += 1
    return counts


def count_states_by_release(result: dict) -> tuple[dict, list]:
    """Count jobs per State value, grouped by ReleaseName.

    Iterates over the jobs in the OData ``value`` list and builds a
    cross-tabulation: for each unique ReleaseName, a Counter of how many jobs
    fall into each unique State value. Missing values are grouped under
    "(unknown)".

    Returns a tuple of (table, states) where ``table`` maps each ReleaseName
    to a Counter keyed by State, and ``states`` is the sorted list of every
    unique State value seen (the columns).
    """
    table: dict = {}
    states: set = set()
    for job in result.get("value", []):
        release_name = job.get("ReleaseName") or "(unknown)"
        state = job.get("State") or "(unknown)"
        states.add(state)
        table.setdefault(release_name, Counter())[state] += 1
    return table, sorted(states)


def print_state_matrix(table: dict, states: list) -> None:
    """Print the ReleaseName x State counts as an aligned table."""
    name_width = max([len("ReleaseName")] + [len(name) for name in table])
    col_width = max([len("Total")] + [len(s) for s in states]) + 2

    header = "ReleaseName".ljust(name_width)
    header += "".join(s.rjust(col_width) for s in states)
    header += "Total".rjust(col_width)
    header += "Success %".rjust(col_width)
    print(header)
    print("-" * len(header))

    for release_name in sorted(table, key=lambda n: -sum(table[n].values())):
        row_counts = table[release_name]
        total = sum(row_counts.values())
        successful = row_counts.get("Successful", 0)
        success_pct = (successful / total * 100) if total else 0.0
        row = release_name.ljust(name_width)
        row += "".join(str(row_counts.get(s, 0)).rjust(col_width) for s in states)
        row += str(total).rjust(col_width)
        row += f"{success_pct:.1f}%".rjust(col_width)
        print(row)


# Color thresholds for the Success % indicator.
SUCCESS_GREEN = "#008000"  # Success % >= 90%
SUCCESS_RED = "#FF0000"    # Success % <= 89%


def build_html_dashboard(table: dict, states: list, filter_desc: str,
                         total_jobs: int) -> str:
    """Build an executive-style HTML dashboard for the ReleaseName x State data.

    Renders the cross-tab as a styled table with a color-coded Success %
    column: green (#008000) when Success % >= 90, red (#FF0000) otherwise.
    Also shows top-line KPI cards for an at-a-glance executive summary.
    """
    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    # Aggregate totals across all releases for the KPI cards.
    grand_total = sum(sum(c.values()) for c in table.values())
    grand_success = sum(c.get("Successful", 0) for c in table.values())
    overall_pct = (grand_success / grand_total * 100) if grand_total else 0.0
    healthy = sum(
        1 for c in table.values()
        if sum(c.values()) and c.get("Successful", 0) / sum(c.values()) * 100 >= 90
    )
    at_risk = len(table) - healthy
    overall_color = SUCCESS_GREEN if overall_pct >= 90 else SUCCESS_RED

    # Build the state column headers.
    state_headers = "".join(f"<th>{escape(s)}</th>" for s in states)

    # Build one table row per ReleaseName, sorted by total volume (desc).
    rows = []
    for release_name in sorted(table, key=lambda n: -sum(table[n].values())):
        counts = table[release_name]
        total = sum(counts.values())
        successful = counts.get("Successful", 0)
        pct = (successful / total * 100) if total else 0.0
        color = SUCCESS_GREEN if pct >= 90 else SUCCESS_RED
        badge = "On Target" if pct >= 90 else "Needs Attention"

        state_cells = "".join(
            f"<td class='num'>{counts.get(s, 0)}</td>" for s in states
        )
        rows.append(f"""
        <tr>
          <td class="name">{escape(release_name)}</td>
          {state_cells}
          <td class="num total">{total}</td>
          <td class="pct" style="color:{color};">
            <span class="dot" style="background:{color};"></span>{pct:.1f}%
          </td>
          <td><span class="badge" style="background:{color};">{badge}</span></td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RPA Job Success Dashboard</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: #467958;
    color: #1e293b;
    padding: 40px 24px;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  header {{ color: #f8fafc; margin-bottom: 28px; }}
  header h1 {{ font-size: 26px; font-weight: 600; letter-spacing: .3px; }}
  header .sub {{ color: #FFFFFF; font-size: 14px; margin-top: 6px; }}
  .kpis {{
    display: grid; grid-template-columns: repeat(5, 1fr);
    gap: 16px; margin-bottom: 28px;
  }}
  .kpi {{
    background: #ffffff; border-radius: 12px; padding: 20px;
    box-shadow: 0 6px 18px rgba(0,0,0,.25);
  }}
  .kpi .label {{
    font-size: 12px; text-transform: uppercase; letter-spacing: .8px;
    color: #64748b; font-weight: 600;
  }}
  .kpi .value {{ font-size: 30px; font-weight: 700; margin-top: 8px; }}
  .card {{
    background: #ffffff; border-radius: 12px; overflow: hidden;
    box-shadow: 0 6px 18px rgba(0,0,0,.25);
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    background: #82A2B1; color: #f1f5f9; text-align: right;
    padding: 14px 16px; font-size: 12px; text-transform: uppercase;
    letter-spacing: .6px; font-weight: 600;
  }}
  thead th:first-child {{ text-align: left; }}
  tbody td {{
    padding: 14px 16px; border-bottom: 1px solid #e2e8f0;
    font-size: 15px; text-align: right;
  }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:nth-child(even) {{ background: #f8fafc; }}
  td.name {{ text-align: left; font-weight: 600; color: #0f172a; }}
  td.num {{ color: #475569; font-variant-numeric: tabular-nums; }}
  td.total {{ font-weight: 700; color: #0f172a; }}
  td.pct {{ font-weight: 700; font-variant-numeric: tabular-nums; }}
  .dot {{
    display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    margin-right: 7px; vertical-align: middle;
  }}
  .badge {{
    color: #fff; font-size: 11px; font-weight: 600; padding: 4px 10px;
    border-radius: 999px; text-transform: uppercase; letter-spacing: .5px;
    white-space: nowrap;
  }}
  .legend {{
    background: #ffffff; color: #000000; margin-top: 18px;
    border-radius: 12px; padding: 18px 20px;
    box-shadow: 0 6px 18px rgba(0,0,0,.25);
  }}
  .legend .legend-title {{
    font-size: 12px; text-transform: uppercase; letter-spacing: .8px;
    font-weight: 700; color: #000000; margin-bottom: 12px;
  }}
  .legend .legend-items {{
    display: flex; gap: 24px; font-size: 13px; align-items: center;
  }}
  .legend .dot {{ width: 11px; height: 11px; }}
  footer {{ color: #64748b; font-size: 12px; margin-top: 22px; text-align: center; }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>RPA Job Success Dashboard</h1>
      <div class="sub">Generated {escape(generated_at)} &nbsp;&bull;&nbsp; Filter: {escape(filter_desc)}</div>
    </header>

    <div class="kpis">
      <div class="kpi">
        <div class="label">Unique Automations</div>
        <div class="value">{len(table)}</div>
      </div>
      <div class="kpi">
        <div class="label">Total Jobs</div>
        <div class="value">{total_jobs}</div>
      </div>
      <div class="kpi">
        <div class="label">Overall Success</div>
        <div class="value" style="color:{overall_color};">{overall_pct:.1f}%</div>
      </div>
      <div class="kpi">
        <div class="label">Processes On Target</div>
        <div class="value" style="color:{SUCCESS_GREEN};">{healthy}</div>
      </div>
      <div class="kpi">
        <div class="label">Processes At Risk</div>
        <div class="value" style="color:{SUCCESS_RED};">{at_risk}</div>
      </div>
    </div>

    <div class="card">
      <table>
        <thead>
          <tr>
            <th>Process (ReleaseName)</th>
            {state_headers}
            <th>Total</th>
            <th>Success %</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}
        </tbody>
      </table>
    </div>

    <div class="legend">
      <div class="legend-title">Legend</div>
      <div class="legend-items">
        <span><span class="dot" style="background:{SUCCESS_GREEN};"></span>Success % &ge; 90% (On Target)</span>
        <span><span class="dot" style="background:{SUCCESS_RED};"></span>Success % &le; 89% (Needs Attention)</span>
      </div>
    </div>

    <footer>UiPath Orchestrator &mdash; Automated reporting</footer>
  </div>
</body>
</html>"""


def main() -> int:
    load_dotenv()

    client_id = os.getenv("ORCHESTRATOR_CLIENT_ID")
    client_secret = os.getenv("ORCHESTRATOR_API_KEY")

    if not client_id or not client_secret:
        print(
            "ERROR: ORCHESTRATOR_CLIENT_ID and/or ORCHESTRATOR_API_KEY are not set.\n"
            "Create a .env file (see .env.example) with your credentials.",
            file=sys.stderr,
        )
        return 1

    try:
        print("Requesting access token...")
        token = get_access_token(client_id, client_secret)
        print("Access token acquired.\n")

        print(f"Calling Get Jobs with $filter: {build_filter()}\n")
        result = get_jobs(token)
    except requests.HTTPError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        if exc.response is not None:
            print(exc.response.text, file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    jobs = result.get("value", [])
    print(f"Returned {len(jobs)} job(s).\n")
    print(json.dumps(result, indent=2))

    release_counts = count_release_names(result)
    print(f"\nUnique ReleaseName count: {len(release_counts)}")
    print("Running processes per ReleaseName:")
    for release_name, count in release_counts.most_common():
        print(f"  {release_name}: {count}")

    state_table, states = count_states_by_release(result)
    print(f"\nUnique State values: {states}")
    print("Job counts per ReleaseName by State:")
    print_state_matrix(state_table, states)

    # Generate the color-coded executive HTML dashboard.
    html = build_html_dashboard(state_table, states, build_filter(), len(jobs))
    output_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"\nDashboard written to: {output_path}")
    try:
        webbrowser.open(f"file://{output_path}")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
