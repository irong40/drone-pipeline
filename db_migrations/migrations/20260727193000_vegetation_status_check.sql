-- Applied live 2026-07-27 (MCP: vegetation_status_check).
-- Values = exactly what the live Path E n8n workflow writes (verified
-- against the 2026-07-26 export) + 'pending' reserved. All rows NULL today.
ALTER TABLE drone_jobs ADD CONSTRAINT drone_jobs_vegetation_status_check
  CHECK (vegetation_status IS NULL OR vegetation_status IN
    ('pending','detecting','classifying','assessing','generating_report','review','complete','failed'));
