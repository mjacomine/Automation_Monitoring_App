-- EndProcessing is stored as the UTC instant UiPath returned; this view is
-- where it is normalized to the organization's timezone. Converting on read
-- rather than shifting the stored value keeps the true instant intact (a
-- shifted timestamp loses it, and DST makes some local times ambiguous or
-- nonexistent), while every consumer still sees local time and local dates.
--
-- security_invoker is required: without it the view would run as its owner and
-- bypass the RLS policy on f_queue_item_metrics, exposing every organization.
CREATE OR REPLACE VIEW public.v_queue_item_metrics
WITH (security_invoker = true) AS
SELECT q.id,
       q.organization_id,
       o.organization_name,
       o.timezone                                            AS organization_timezone,
       q."QueueKey"                                          AS queue_key,
       q."Status"                                            AS status,
       q."EndProcessing"                                     AS end_processing_utc,
       q."EndProcessing" AT TIME ZONE o.timezone             AS end_processing_local,
      (q."EndProcessing" AT TIME ZONE o.timezone)::date      AS end_processing_date_local
FROM public.f_queue_item_metrics q
JOIN public.d_organizations o ON q.organization_id = o.organization_id;
