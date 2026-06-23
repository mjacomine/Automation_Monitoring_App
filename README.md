# UiPath Orchestrator – Get Jobs

A small Python utility that authenticates against the UiPath Cloud Identity
server (Orchestrator) using the **client_credentials** grant and calls the Orchestrator
**Get Jobs** (OData) endpoint.

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
python get_jobs.py
```

The script prints the OData `$filter` it sends, the number of jobs returned,
and the full JSON response for review.

## Changing the filter

Edit the variables at the top of `get_jobs.py`:

| Variable        | Purpose                                                         |
| --------------- | --------------------------------------------------------------- |
| `CREATION_TIME` | Lower bound for `CreationTime` (ISO-8601 UTC). Easy to switch.   |
| `SOURCE_TYPE`   | Filter by job source (`"Schedule"`, `"Manual"`, …). `None` = all. |

For example, to pull jobs created since a different date, just change:

```python
CREATION_TIME = "2026-05-01T00:00:00.000Z"
```
