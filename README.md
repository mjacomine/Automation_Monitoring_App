# Automation Monitoring App

A Python utility that authenticates against the UiPath Cloud Identity server
(Orchestrator) using the **client_credentials** grant, calls the Orchestrator
**Get Jobs** (OData) endpoint, and renders job-success analytics to the console
and an executive HTML dashboard.

## Architecture

The app uses a **composable architecture**: each core concern lives in its own
module, and `main.py` is a thin *composition root* that wires them together.
Data flows one direction through the layers, so each component can be changed
or tested in isolation.

```
load config -> authenticate -> fetch jobs -> analyze -> report

monitoring/
  config.py          Settings dataclass + env loading
  auth.py            authenticate() — OAuth token acquisition
  orchestrator.py    OrchestratorClient — Orchestrator API access + OData filter
  analytics.py       analyze_jobs() / JobAnalysis — pure aggregation (no I/O)
  reporting/
    console.py       render_console() — aligned terminal table
    dashboard.py     render_dashboard() — executive HTML dashboard
main.py              orchestrates the flow; owns CLI run, exit codes, side effects
```

The **analytics** layer is pure and produces a presentation-agnostic
`JobAnalysis` model. Reporting backends read only from that model, never from
the raw API — so adding a new output (CSV, Slack, e-mail) means adding one file
under `reporting/` and one call in `main.py`, with nothing upstream changed.

## Setup

1. Create and activate a virtual environment (optional but recommended):

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Create your `.env` file from the template and fill in your credentials:

   ```powershell
   Copy-Item .env.example .env
   ```

   ```dotenv
   ORCHESTRATOR_CLIENT_ID=your-client-id
   ORCHESTRATOR_API_KEY=your-client-secret
   ```

## Usage

```powershell
python main.py
```

The app prints the OData `$filter` it sends, the number of jobs returned, a
ReleaseName-by-State table, and writes (and opens) `dashboard.html`.

## Configuration

All settings live in `monitoring/config.py` (`Settings`). Credentials and the
two most commonly changed filter values can also be set via the environment
(`.env`) without editing code:

| Variable / Setting        | Purpose                                                          |
| ------------------------- | ---------------------------------------------------------------- |
| `ORCHESTRATOR_CLIENT_ID`  | External Application client id (required).                       |
| `ORCHESTRATOR_API_KEY`    | External Application client secret (required).                   |
| `MONITOR_CREATION_TIME`   | Lower bound for `CreationTime` (ISO-8601 UTC).                   |
| `MONITOR_SOURCE_TYPE`     | Filter by job source (`Schedule`, `Manual`, …).                  |
| `success_threshold`       | Percent at/above which a process is "On Target" (default 90).    |
| `jobs_url` / `token_url`  | Orchestrator + identity endpoints.                               |

For example, to pull jobs created since a different date, set in `.env`:

```dotenv
MONITOR_CREATION_TIME=2026-05-01T00:00:00.000Z
```
