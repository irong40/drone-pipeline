-- Applied live 2026-07-27 (MCP: sync_delivery_state_trigger).
-- delivery_status is the source of truth; status/delivered_at follow.
-- 'zz_' prefix fires last among BEFORE UPDATE triggers (alphabetical).
-- portfolio_complete must NOT stamp delivered_at.
CREATE OR REPLACE FUNCTION sync_delivery_state() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.delivery_status IS DISTINCT FROM OLD.delivery_status
     AND NEW.delivery_status IN ('sent','delivery_confirmed') THEN
    NEW.status := 'delivered';
    NEW.delivered_at := coalesce(NEW.delivered_at, OLD.delivered_at, now());
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS zz_sync_delivery_state ON drone_jobs;
CREATE TRIGGER zz_sync_delivery_state BEFORE UPDATE ON drone_jobs
  FOR EACH ROW EXECUTE FUNCTION sync_delivery_state();
