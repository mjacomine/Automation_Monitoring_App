-- 1. organization_id must hold the client code used for the API request
--    (e.g. 'deaconesshealth'), matching f_auto_metrics_jobs. It was a bigint
--    referencing the surrogate d_organizations.id, which cannot store a code.
--    The table is empty, so the retype is lossless.
ALTER TABLE public.f_queue_item_metrics
    DROP CONSTRAINT IF EXISTS f_queue_item_metrics_organization_id_fkey;

ALTER TABLE public.f_queue_item_metrics
    ALTER COLUMN organization_id TYPE character varying
    USING organization_id::character varying;

ALTER TABLE public.f_queue_item_metrics
    ADD CONSTRAINT f_queue_item_metrics_organization_id_fkey
    FOREIGN KEY (organization_id) REFERENCES public.d_organizations(organization_id);

-- 2. Per-organization timezone, needed to present EndProcessing in local time.
--    IANA zone names (not "CST") so daylight saving is handled by the database.
--    A CHECK cannot contain a subquery, so validity is checked via a function.
CREATE OR REPLACE FUNCTION public.is_valid_timezone(tz text)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = tz);
$$;

ALTER TABLE public.d_organizations
    ADD COLUMN IF NOT EXISTS timezone text NOT NULL DEFAULT 'UTC';

ALTER TABLE public.d_organizations
    DROP CONSTRAINT IF EXISTS d_organizations_timezone_valid;
ALTER TABLE public.d_organizations
    ADD CONSTRAINT d_organizations_timezone_valid
    CHECK (public.is_valid_timezone(timezone));

UPDATE public.d_organizations
   SET timezone = 'America/Chicago'
 WHERE organization_id = 'deaconesshealth';

-- 3. RLS was enabled with no policy at all, so the table was unreadable by
--    every signed-in user. Mirror the fact-table policy on f_auto_metrics_jobs.
DROP POLICY IF EXISTS queue_fact_read_assigned ON public.f_queue_item_metrics;
CREATE POLICY queue_fact_read_assigned ON public.f_queue_item_metrics
    FOR SELECT TO authenticated
    USING (
        is_admin()
        OR (organization_id)::text IN (SELECT current_user_org_ids())
    );
