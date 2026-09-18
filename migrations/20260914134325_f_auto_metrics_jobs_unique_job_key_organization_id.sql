-- Treat a (job_key, organization_id) pair as the duplicate key for
-- f_auto_metrics_jobs. The previous UNIQUE (job_key) is replaced rather than
-- kept alongside: leaving it in place would reject the same job_key under a
-- different organization with a constraint error instead of letting the
-- ON CONFLICT ... DO NOTHING path skip it as a duplicate.
ALTER TABLE public.f_auto_metrics_jobs
    DROP CONSTRAINT IF EXISTS auto_metrics_jobs_job_key_key;

ALTER TABLE public.f_auto_metrics_jobs
    ADD CONSTRAINT f_auto_metrics_jobs_job_key_organization_id_key
    UNIQUE (job_key, organization_id);
