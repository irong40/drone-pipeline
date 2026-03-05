-- Migration: processing_jobs
-- Phase 15 Plan 01 Task 1 — Foundation Scripts & Schema
-- Creates processing_jobs table with RLS policies and indexes.
--
-- NOTE: The Sentinel pipeline refers to jobs as "missions". The underlying
-- table is public.drone_jobs. All foreign keys reference public.drone_jobs(id).
--
-- NOTE: The set_updated_at() trigger function already exists from
-- 20260225000001_vegetation_tables.sql — do NOT recreate it here.

-- ============================================================
-- processing_jobs
-- One row per pipeline processing job. PipelineStatusReporter
-- queries this table to track step-by-step progress.
--
-- steps JSONB structure (array of objects):
--   [
--     {
--       "name":         "step_name",
--       "status":       "pending" | "running" | "complete" | "failed" | "skipped",
--       "started_at":   "ISO 8601 timestamp or null",
--       "completed_at": "ISO 8601 timestamp or null",
--       "error":        "error message or null",
--       "output":       {} (step-specific output data)
--     }
--   ]
--
-- status values: pending, running, awaiting_manual_edit, complete, failed
-- ============================================================
CREATE TABLE public.processing_jobs (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  mission_id      UUID          NOT NULL REFERENCES public.drone_jobs(id) ON DELETE CASCADE,
  package_type    TEXT          NOT NULL,
  status          TEXT          NOT NULL DEFAULT 'pending',
  current_step    TEXT,
  steps           JSONB         NOT NULL DEFAULT '[]'::jsonb,
  error_message   TEXT,
  created_at      TIMESTAMPTZ   DEFAULT now(),
  updated_at      TIMESTAMPTZ   DEFAULT now(),
  completed_at    TIMESTAMPTZ,
  UNIQUE (mission_id)
);

COMMENT ON COLUMN public.processing_jobs.status IS
  'Job status. Values: pending | running | awaiting_manual_edit | complete | failed';

COMMENT ON COLUMN public.processing_jobs.current_step IS
  'Name of the currently executing step. Set by PipelineStatusReporter when status=running.';

COMMENT ON COLUMN public.processing_jobs.steps IS
  'JSONB array of step objects: [{name, status, started_at, completed_at, error, output}]. Updated in-place by PipelineStatusReporter._update_step().';

COMMENT ON COLUMN public.processing_jobs.error_message IS
  'Top-level error message. Set by PipelineStatusReporter when a step fails.';

-- Indexes for common query patterns
CREATE INDEX idx_processing_jobs_mission
  ON public.processing_jobs (mission_id);

CREATE INDEX idx_processing_jobs_status
  ON public.processing_jobs (status);

-- Auto-update updated_at (reuses existing set_updated_at function)
CREATE TRIGGER processing_jobs_updated_at
  BEFORE UPDATE ON public.processing_jobs
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ============================================================
-- RLS — processing_jobs
-- Service role: full access (Python scripts + n8n use service key)
-- Authenticated (admin UI): SELECT only
-- Anon: no access (blocks unauthenticated writes)
-- ============================================================
ALTER TABLE public.processing_jobs ENABLE ROW LEVEL SECURITY;

-- Service role full access (pipeline scripts write via service key)
CREATE POLICY "Service role full access on processing_jobs"
  ON public.processing_jobs FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- Authenticated users (admin portal) can read
CREATE POLICY "Authenticated users can read processing_jobs"
  ON public.processing_jobs FOR SELECT
  TO authenticated
  USING (true);
