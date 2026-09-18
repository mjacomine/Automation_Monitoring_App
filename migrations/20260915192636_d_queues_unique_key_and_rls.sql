-- A queue is identified by its Orchestrator Id within an organization. Without
-- this, every run would append a fresh duplicate row for the same queue.
ALTER TABLE public.d_queues
    DROP CONSTRAINT IF EXISTS d_queues_organization_queue_key;
ALTER TABLE public.d_queues
    ADD CONSTRAINT d_queues_organization_queue_key
    UNIQUE ("Organization_ID", "Queue_ID");

-- RLS was enabled with no policy at all, so the table was unreadable by every
-- signed-in user. Mirror the policy used on the other organization-scoped
-- tables so a user sees only the queues of organizations they are assigned.
DROP POLICY IF EXISTS queues_read_assigned ON public.d_queues;
CREATE POLICY queues_read_assigned ON public.d_queues
    FOR SELECT TO authenticated
    USING (
        is_admin()
        OR ("Organization_ID")::text IN (SELECT current_user_org_ids())
    );
