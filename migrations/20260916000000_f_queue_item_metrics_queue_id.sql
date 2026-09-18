-- ============================================================================
-- f_queue_item_metrics."Queue_ID" — the queue a item belongs to.
--
-- Populated from the QueueItems API field QueueDefinitionId, and joined to
-- d_queues("Organization_ID", "Queue_ID") for the queue name. Required by
-- 20260917202640, which exposes it through v_queue_item_metrics.
--
-- This column was added by hand in the Supabase UI rather than through a
-- migration, so it is absent from the supabase_migrations ledger. Recorded
-- here so the folder reproduces the full schema; written idempotently, so
-- applying it to the live project is a no-op.
-- ============================================================================

alter table public.f_queue_item_metrics
  add column if not exists "Queue_ID" integer;
