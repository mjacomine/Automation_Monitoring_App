# Database migrations

The SQL behind the Supabase schema this app reads and writes. Apply the files
in filename order — each one assumes every earlier file has run.

| File | What it does |
| ---- | ------------ |
| `00000000000000_baseline_schema.sql` | Creates the tables originally made by hand in the Supabase UI: `d_organizations`, `last_poll`, `f_auto_metrics_jobs`, `f_queue_item_metrics`, `d_queues`. Enables RLS on all of them. |
| `20260624195643_security_model_users_orgs_rls.sql` | The access-control model: `d_app_users`, `d_user_organizations`, the `is_admin()` / `current_user_org_ids()` helpers, and the read policies on `d_organizations` and `f_auto_metrics_jobs`. |
| `20260914134325_f_auto_metrics_jobs_unique_job_key_organization_id.sql` | Makes `(job_key, organization_id)` the duplicate key, replacing `UNIQUE (job_key)`. |
| `20260915174412_queue_item_metrics_client_code_timezone_and_rls.sql` | Retypes `f_queue_item_metrics.organization_id` to the client code, adds `d_organizations.timezone` (+ validator), adds the queue-fact read policy. |
| `20260915174422_v_queue_item_metrics_local_time.sql` | Creates `v_queue_item_metrics`, normalizing `EndProcessing` to each organization's timezone. |
| `20260915192636_d_queues_unique_key_and_rls.sql` | Adds `UNIQUE ("Organization_ID", "Queue_ID")` and the read policy on `d_queues`. |
| `20260916000000_f_queue_item_metrics_queue_id.sql` | Adds `f_queue_item_metrics."Queue_ID"`. |
| `20260917202640_v_queue_item_metrics_join_d_queues.sql` | Rebuilds the view to join `d_queues`, exposing `queue_id` and `queue_name`. |

## Not covered here

`jobs` and `job_snapshots` are created at runtime by
`monitoring.storage.initialize_schema()`, which runs on every persisted cycle.
Run `python -m monitoring.storage --print-schema` to dump that DDL.

Those two tables currently have **RLS disabled** while holding the verbatim
Orchestrator payloads, so they are readable by anyone with the publishable key
in `app-config.js`. Nothing in the front end reads them; enabling RLS with no
`anon` policy would close the exposure without affecting ingestion, which
connects as the owner via `DATABASE_URL` and bypasses RLS.

## Provenance

The numbered files are the SQL as actually applied, exported from
`supabase_migrations.schema_migrations`. Two files are reconstructions, because
the changes they describe were made through the Supabase UI and never entered
the ledger: `00000000000000_baseline_schema.sql` and
`20260916000000_f_queue_item_metrics_queue_id.sql`. Both are written
idempotently (`if not exists`), so applying them to the existing project is a
no-op; they exist so a fresh project can be built from this folder alone.

The baseline deliberately reflects the schema *before* the numbered migrations
— `f_auto_metrics_jobs` still keyed on `job_key` alone, `f_queue_item_metrics`
still referencing the surrogate key, no `timezone` column — so replaying the
folder in order reproduces the real history rather than a shortcut to the
current state.

## Applying to a fresh project

```bash
for f in migrations/*.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

Then seed `d_organizations` with one row per Orchestrator client code, seed
`last_poll` with a single row (its `last_poll_datetime` is the first poll's
lower bound), and set each organization's `timezone` to an IANA zone name —
`America/Chicago`, not `CST`, so daylight saving is handled by the database.
