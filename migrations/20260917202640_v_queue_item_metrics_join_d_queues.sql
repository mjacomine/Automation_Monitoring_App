-- Add the queue dimension so queue metrics can be reported per queue.
-- Dropped and recreated rather than CREATE OR REPLACE: that only permits new
-- columns appended at the end, and queue_id/queue_name belong beside the item.
DROP VIEW IF EXISTS public.v_queue_item_metrics;

CREATE VIEW public.v_queue_item_metrics
WITH (security_invoker = true) AS
SELECT q.id,
       q.organization_id,
       o.organization_name,
       o.timezone                                        AS organization_timezone,
       q."Queue_ID"                                      AS queue_id,
       -- LEFT JOIN + COALESCE: an item whose queue is absent from d_queues (a
       -- queue deleted in Orchestrator, or one not yet synced) must still be
       -- counted rather than silently dropped from the report.
       COALESCE(dq."QueueName", '(unknown queue)')       AS queue_name,
       q."QueueKey"                                      AS queue_key,
       q."Status"                                        AS status,
       q."EndProcessing"                                 AS end_processing_utc,
       q."EndProcessing" AT TIME ZONE o.timezone         AS end_processing_local,
      (q."EndProcessing" AT TIME ZONE o.timezone)::date  AS end_processing_date_local
FROM public.f_queue_item_metrics q
JOIN public.d_organizations o
  ON q.organization_id = o.organization_id
LEFT JOIN public.d_queues dq
  ON dq."Organization_ID" = q.organization_id
 AND dq."Queue_ID"        = q."Queue_ID";
