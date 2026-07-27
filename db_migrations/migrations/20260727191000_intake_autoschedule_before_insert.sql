-- Applied live 2026-07-27 (MCP: intake_autoschedule_before_insert).
-- intake->scheduled could never fire for jobs created WITH a date
-- (auto_advance is BEFORE UPDATE + requires OLD.scheduled_date IS NULL,
-- but both creation paths insert status='intake' with a date set).
CREATE OR REPLACE FUNCTION drone_job_intake_autoschedule() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'intake' AND NEW.scheduled_date IS NOT NULL THEN
    NEW.status := 'scheduled';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS aa_intake_autoschedule ON drone_jobs;
CREATE TRIGGER aa_intake_autoschedule BEFORE INSERT ON drone_jobs
  FOR EACH ROW EXECUTE FUNCTION drone_job_intake_autoschedule();
