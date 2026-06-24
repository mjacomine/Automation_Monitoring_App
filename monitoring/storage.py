"""Persistence: store raw Orchestrator payloads and per-job rows in Postgres.

This is the *storage backend* for the monitoring data, intended to run against
a free Supabase (managed Postgres) project during development and the same
schema in production. Like the reporting backends, it reads the raw payload and
the analytics model; nothing upstream knows it exists.

Two tables are written each run:

* ``job_snapshots`` — one row per monitoring cycle: the verbatim JSON envelope
  plus run metadata (when, which ``$filter``, how many jobs). This is the
  source of truth and lets any later schema be rebuilt from raw data.
* ``jobs`` — one typed, queryable row per job, keyed on the job ``Key`` (UUID)
  and upserted so re-runs update existing rows instead of duplicating. Every
  job also keeps its verbatim object in a ``raw`` JSONB column, so fields not
  promoted to typed columns are still queryable via ``raw->>'FieldName'``.

The :data:`FIELD_TYPES` map is the canonical list of fields returned by the
Orchestrator Jobs endpoint (observed from a live response). It drives both the
generated DDL and the insert, so adding/removing a field is a one-line change.
Run ``python -m monitoring.storage --print-schema`` to dump the DDL.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import timezone
from typing import Any, Iterable

try:  # psycopg is only needed when persistence is actually used.
    import psycopg
    from psycopg.types.json import Json
except ImportError:  # pragma: no cover - import guard
    psycopg = None  # type: ignore[assignment]
    Json = None  # type: ignore[assignment]

from .config import ClientConfig, Settings

# --- Canonical Orchestrator Jobs field -> Postgres type --------------------
# Derived from a live Get Jobs response. Fields that were entirely null in the
# sample have their type inferred from UiPath's documented schema and are
# marked "(inferred)"; widen them to ``text`` if a value ever fails to cast.
FIELD_TYPES: dict[str, str] = {
    "Id": "bigint",
    "Key": "uuid",
    "State": "text",
    "SubState": "text",                       # (inferred) all-null in sample
    "ReleaseName": "text",
    "Source": "text",
    "SourceType": "text",
    "ProcessType": "text",
    "Type": "text",
    "RuntimeType": "text",
    "JobPriority": "text",
    "SpecificPriorityValue": "integer",
    "StartTime": "timestamptz",
    "EndTime": "timestamptz",
    "CreationTime": "timestamptz",
    "LastModificationTime": "timestamptz",
    "ResumeTime": "timestamptz",              # (inferred) all-null in sample
    "Info": "text",
    "EntryPointPath": "text",
    "HostMachineName": "text",
    "LocalSystemAccount": "text",
    "Reference": "text",
    "BatchExecutionKey": "uuid",
    "ProjectKey": "uuid",
    "FolderKey": "text",                      # (inferred) all-null in sample
    "CreatorUserKey": "text",                 # (inferred) all-null in sample
    "ParentJobKey": "text",                   # (inferred) all-null in sample
    "ReleaseVersionId": "bigint",
    "OrganizationUnitId": "bigint",
    "OrganizationUnitFullyQualifiedName": "text",
    "StartingScheduleId": "bigint",
    "StartingTriggerId": "text",              # (inferred) all-null in sample
    "MaxExpectedRunningTimeSeconds": "integer",  # (inferred) all-null in sample
    "EnableAutopilotHealing": "boolean",
    "AutopilotForRobots": "text",             # (inferred) all-null in sample
    "AutoHealStatus": "text",                 # (inferred) all-null in sample
    "HasMediaRecorded": "boolean",
    "HasVideoRecorded": "boolean",
    "RequiresUserInteraction": "boolean",
    "ResumeOnSameContext": "boolean",
    "RemoteControlAccess": "text",
    "StopStrategy": "text",
    "ErrorCode": "text",                      # (inferred) all-null in sample
    "JobError": "text",                       # (inferred) all-null in sample
    "InputArguments": "text",                 # JSON string when present
    "OutputArguments": "text",                # JSON string when present
    "InputFile": "text",                      # (inferred) all-null in sample
    "OutputFile": "text",                     # (inferred) all-null in sample
    "EnvironmentVariables": "text",
    "ResourceOverwrites": "text",             # (inferred) all-null in sample
    "PersistenceId": "text",                  # (inferred) all-null in sample
    "ResumeVersion": "text",                  # (inferred) all-null in sample
    "ServerlessJobType": "text",              # (inferred) all-null in sample
    "TargetRuntime": "text",                  # (inferred) all-null in sample
    "ProfilingOptions": "text",               # (inferred) all-null in sample
    "OrchestratorUserIdentity": "text",       # (inferred) all-null in sample
    "FpsContext": "text",                     # (inferred) all-null in sample
    "FpsProperties": "text",                  # (inferred) all-null in sample
    "ParentContext": "text",                  # (inferred) all-null in sample
    "ParentOperationId": "text",              # (inferred) all-null in sample
    "ParentSpanId": "text",                   # (inferred) all-null in sample
    "RootSpanId": "text",                     # (inferred) all-null in sample
    "TraceId": "text",                        # (inferred) all-null in sample
}

# Types whose empty string ("") must become NULL or the cast will fail.
_NON_TEXT = {"bigint", "integer", "boolean", "timestamptz", "uuid"}


def _snake(name: str) -> str:
    """Convert an API field name (PascalCase) to a snake_case column name."""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


COLUMNS: dict[str, str] = {field: _snake(field) for field in FIELD_TYPES}


def _coerce(value: Any, sql_type: str) -> Any:
    """Normalise a raw JSON value for its target Postgres type."""
    if value is None:
        return None
    # Some fields (e.g. ParentContext, FpsContext, *Arguments) arrive as a
    # nested JSON object/array on some Orchestrators and a JSON string on
    # others. Their column is text, and psycopg can't adapt a dict/list, so
    # serialise back to a JSON string for a consistent text representation.
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, str) and value == "" and sql_type in _NON_TEXT:
        return None
    if sql_type in ("bigint", "integer") and isinstance(value, str):
        return int(value)
    return value


# --- Schema ----------------------------------------------------------------
def schema_sql() -> str:
    """Return the full ``CREATE TABLE`` DDL for the monitoring schema."""
    job_cols = ",\n".join(
        f'    {COLUMNS[field]:38} {sql_type}' for field, sql_type in FIELD_TYPES.items()
    )
    return f"""\
-- Raw payload, one row per monitoring run -------------------------------
CREATE TABLE IF NOT EXISTS job_snapshots (
    id           bigserial PRIMARY KEY,
    fetched_at   timestamptz NOT NULL DEFAULT now(),
    filter_desc  text,
    total_jobs   integer,
    raw_payload  jsonb NOT NULL
);

-- One typed, queryable row per job (upserted on the job Key) -------------
CREATE TABLE IF NOT EXISTS jobs (
{job_cols},
    raw            jsonb NOT NULL,
    snapshot_id    bigint REFERENCES job_snapshots(id),
    first_seen_at  timestamptz NOT NULL DEFAULT now(),
    last_seen_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (key)
);

CREATE INDEX IF NOT EXISTS jobs_release_name_idx ON jobs (release_name);
CREATE INDEX IF NOT EXISTS jobs_state_idx        ON jobs (state);
CREATE INDEX IF NOT EXISTS jobs_creation_time_idx ON jobs (creation_time);
"""


def initialize_schema(conn: "psycopg.Connection") -> None:
    """Create the monitoring tables and indexes if they do not yet exist."""
    with conn.cursor() as cur:
        cur.execute(schema_sql())


# --- Write path ------------------------------------------------------------
def _insert_snapshot(
    conn: "psycopg.Connection", payload: dict, filter_desc: str, total_jobs: int
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO job_snapshots (filter_desc, total_jobs, raw_payload) "
            "VALUES (%s, %s, %s) RETURNING id",
            (filter_desc, total_jobs, Json(payload)),
        )
        return cur.fetchone()[0]


def _upsert_jobs(
    conn: "psycopg.Connection", jobs: Iterable[dict], snapshot_id: int
) -> int:
    fields = list(FIELD_TYPES)
    cols = [COLUMNS[f] for f in fields] + ["raw", "snapshot_id"]
    placeholders = ", ".join(["%s"] * len(cols))
    # On conflict, refresh every typed column + raw + snapshot, bump last_seen.
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in cols if c != "key"
    )
    sql = (
        f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT (key) DO UPDATE SET {updates}, last_seen_at = now()"
    )

    count = 0
    with conn.cursor() as cur:
        for job in jobs:
            row = [_coerce(job.get(f), FIELD_TYPES[f]) for f in fields]
            row.append(Json(job))
            row.append(snapshot_id)
            cur.execute(sql, row)
            count += 1
    return count


def persist_snapshot(
    settings: Settings, payload: dict, filter_desc: str
) -> tuple[int, int] | None:
    """Persist one monitoring cycle to Postgres.

    Stores the raw envelope in ``job_snapshots`` and upserts each job into
    ``jobs``. No-ops (returning ``None``) when no ``DATABASE_URL`` is configured
    so local development needs no database.

    Returns:
        ``(snapshot_id, job_count)`` on success, or ``None`` if persistence was
        skipped because no database is configured.

    Raises:
        RuntimeError: if a ``DATABASE_URL`` is set but ``psycopg`` is missing.
    """
    if not settings.database_url:
        return None
    if psycopg is None:
        raise RuntimeError(
            "DATABASE_URL is set but psycopg is not installed. "
            "Run: pip install -r requirements.txt"
        )

    jobs = payload.get("value", [])
    with psycopg.connect(settings.database_url) as conn:
        initialize_schema(conn)
        snapshot_id = _insert_snapshot(conn, payload, filter_desc, len(jobs))
        job_count = _upsert_jobs(conn, jobs, snapshot_id)
        conn.commit()
    return snapshot_id, job_count


# --- f_auto_metrics_jobs: select-field mirror for metrics dashboards ---------
# A compact, hand-maintained Supabase table holding only the few fields the
# metrics views need. Maps Orchestrator JSON field -> table column. Rows are
# upserted on the unique ``job_key`` so re-runs refresh existing rows instead
# of failing the unique constraint. The table itself is created in Supabase
# (it is not part of :func:`schema_sql`).
#
# ``organization_id`` is NOT taken from the job JSON: it is set to the
# configured client's ``client_code`` (see :func:`persist_metrics_jobs`), so
# every row is attributed to the Orchestrator client it came from.
METRICS_FIELD_MAP: dict[str, str] = {
    "Key": "job_key",
    "ReleaseName": "job_name",
    "State": "job_state",
    "CreationTime": "error_datetime",
}

# Target column type per mapped field, used to normalise values before insert.
_METRICS_FIELD_TYPES: dict[str, str] = {
    "Key": "text",
    "ReleaseName": "text",
    "State": "text",
    "CreationTime": "timestamptz",
}


def persist_metrics_jobs(
    settings: Settings, client: ClientConfig, payload: dict
) -> tuple[int, int] | None:
    """Upsert select job fields into the ``f_auto_metrics_jobs`` table.

    Iterates every job in the Orchestrator payload and writes one compact row
    (organization id, job key, job name, job state) per job, upserted on the
    unique ``job_key``. ``organization_id`` is set to ``client.client_code``
    (not the job's ``OrganizationUnitId``), so every row is attributed to the
    Orchestrator client it was fetched from. Jobs with no ``ReleaseName``
    (e.g. Studio debug runs) are skipped: they can't be attributed to a process
    and ``job_name`` is ``NOT NULL``. No-ops (returning ``None``) when no
    ``DATABASE_URL`` is configured, so local development needs no database.

    Returns:
        ``(upserted, skipped)`` — the number of jobs written and the number
        skipped for having no ``ReleaseName`` — or ``None`` if persistence was
        skipped entirely (no database configured).

    Raises:
        RuntimeError: if a ``DATABASE_URL`` is set but ``psycopg`` is missing.
    """
    if not settings.database_url:
        return None
    if psycopg is None:
        raise RuntimeError(
            "DATABASE_URL is set but psycopg is not installed. "
            "Run: pip install -r requirements.txt"
        )

    fields = list(METRICS_FIELD_MAP)
    # organization_id leads the column list and is filled from client_code, not
    # from a job field; the rest are mapped per-job from the payload.
    cols = ["organization_id"] + [METRICS_FIELD_MAP[f] for f in fields]
    placeholders = ", ".join(["%s"] * len(cols))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "job_key")
    sql = (
        f"INSERT INTO f_auto_metrics_jobs ({', '.join(cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (job_key) DO UPDATE SET {updates}"
    )

    jobs = payload.get("value", [])
    count = 0
    skipped = 0
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            for job in jobs:
                name = job.get("ReleaseName")
                if name is None or str(name).strip() == "":
                    skipped += 1
                    continue
                row = [client.client_code] + [
                    _coerce(job.get(f), _METRICS_FIELD_TYPES[f]) for f in fields
                ]
                cur.execute(sql, row)
                count += 1
        conn.commit()
    return count, skipped


def load_metrics_jobs(settings: Settings) -> dict | None:
    """Read all stored rows from ``f_auto_metrics_jobs`` as an Orchestrator-shaped payload.

    Returns a dict with a ``value`` list of job-like records carrying
    ``ReleaseName`` / ``State`` (mapped back from ``job_name`` / ``job_state``)
    so it can be fed straight into :func:`~monitoring.analytics.analyze_jobs`,
    plus ``Organization`` and ``ErrorDate`` (the date portion of
    ``error_datetime``) which power the dashboard's interactive filters.

    ``f_auto_metrics_jobs`` is the fact table; ``Organization`` is resolved to
    the formal ``organization_name`` from the ``d_organizations`` dimension via
    an inner join on ``organization_id``, so the filter shows friendly names.
    This lets the report reflect exactly what is stored — the accumulated,
    deduplicated set across runs — rather than only the latest live API call.

    Returns ``None`` when no ``DATABASE_URL`` is configured, so callers can fall
    back to the live payload during local development.

    Raises:
        RuntimeError: if a ``DATABASE_URL`` is set but ``psycopg`` is missing.
    """
    if not settings.database_url:
        return None
    if psycopg is None:
        raise RuntimeError(
            "DATABASE_URL is set but psycopg is not installed. "
            "Run: pip install -r requirements.txt"
        )

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT o.organization_name, amj.job_name, amj.job_state, "
                "amj.error_datetime "
                "FROM f_auto_metrics_jobs amj "
                "INNER JOIN d_organizations o "
                "ON amj.organization_id = o.organization_id"
            )
            rows = cur.fetchall()

    value = [
        {
            "Organization": org_name,
            "ReleaseName": name,
            "State": state,
            # Date portion only — the filter groups by calendar day, not time.
            "ErrorDate": err_dt.date().isoformat() if err_dt else None,
        }
        for org_name, name, state, err_dt in rows
    ]
    return {"value": value}


def load_last_poll(settings: Settings) -> tuple[str, str] | None:
    """Read the ``last_poll`` cursor that drives incremental polling.

    Returns ``(id, creation_time)`` for the stored row, where ``creation_time``
    is the previous run's ``last_poll_datetime`` formatted as an OData-ready
    ISO-8601 UTC string (``YYYY-MM-DDTHH:MM:SS.000Z``). That value becomes this
    run's ``CreationTime`` filter lower bound, so the API only returns jobs
    created since the last poll; ``id`` is kept so the same row can be advanced
    at the end of the run.

    Returns ``None`` when no ``DATABASE_URL`` is configured or the table is
    empty. The ``last_poll`` table is the only source of ``creation_time``, so
    callers treat ``None`` as a hard error rather than falling back to a seed.

    Raises:
        RuntimeError: if a ``DATABASE_URL`` is set but ``psycopg`` is missing.
    """
    if not settings.database_url:
        return None
    if psycopg is None:
        raise RuntimeError(
            "DATABASE_URL is set but psycopg is not installed. "
            "Run: pip install -r requirements.txt"
        )

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, last_poll_datetime FROM last_poll "
                "ORDER BY last_poll_datetime DESC NULLS LAST LIMIT 1"
            )
            row = cur.fetchone()

    if row is None:
        return None
    poll_id, last_dt = row
    creation_time = last_dt.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    return str(poll_id), creation_time


def update_last_poll(
    settings: Settings, poll_id: str, creation_time_temp: str
) -> None:
    """Advance the ``last_poll`` cursor to this run's start time.

    ``creation_time_temp`` is a ``YYYY-MM-DD HH:MM:SS`` UTC timestamp captured
    at the *start* of the run (so jobs created while the run is in flight are
    still picked up next time). It is written to the row identified by
    ``poll_id`` and becomes the next run's filter lower bound. The ``+00`` is
    appended so the value is stored as UTC regardless of the database session
    timezone.

    Does nothing when no ``DATABASE_URL`` is configured.

    Raises:
        RuntimeError: if a ``DATABASE_URL`` is set but ``psycopg`` is missing.
    """
    if not settings.database_url:
        return
    if psycopg is None:
        raise RuntimeError(
            "DATABASE_URL is set but psycopg is not installed. "
            "Run: pip install -r requirements.txt"
        )

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE last_poll SET last_poll_datetime = (%s || '+00')::timestamptz "
                "WHERE id = %s",
                (creation_time_temp, poll_id),
            )
        conn.commit()


if __name__ == "__main__":
    # Utility: `python -m monitoring.storage --print-schema` dumps the DDL so
    # the database can be configured by hand (e.g. in the Supabase SQL editor).
    if "--print-schema" in sys.argv:
        print(schema_sql())
    elif "--print-fields" in sys.argv:
        print(json.dumps(FIELD_TYPES, indent=2))
    else:
        print("usage: python -m monitoring.storage [--print-schema|--print-fields]")
