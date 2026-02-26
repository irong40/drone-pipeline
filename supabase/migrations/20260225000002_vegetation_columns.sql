-- Migration: vegetation_columns
-- Phase 7 Plan 02 Task 2 — Environment and Foundation
-- Adds vegetation columns to drone_jobs and processing_templates.
-- Extends processing_steps to accept Path E step names.
--
-- NOTE: The Sentinel pipeline refers to jobs as "missions". The underlying
-- table is public.drone_jobs.
--
-- NOTE: processing_steps.step_name is free text (TEXT NOT NULL) with no
-- ENUM type and no CHECK constraint on values. The 4 new step names are
-- therefore accepted without any schema change to processing_steps itself.
-- This migration documents that fact and verifies the current constraint
-- state so future maintainers have clarity.

-- ============================================================
-- 1. drone_jobs — vegetation routing columns
-- ============================================================
-- vegetation_analysis: flag set by n8n when Path E should run for this mission
-- vegetation_status:   tracks Path E progress through E1-E4 steps
ALTER TABLE public.drone_jobs
  ADD COLUMN IF NOT EXISTS vegetation_analysis BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS vegetation_status   TEXT    DEFAULT NULL;

-- vegetation_status accepted values (enforced by application/n8n, not DB constraint):
-- 'pending', 'detecting', 'classifying', 'assessing',
-- 'generating_report', 'review', 'complete', 'failed'
-- Using free text (same pattern as processing_steps.step_name) allows n8n
-- to set transitional states without a migration.
COMMENT ON COLUMN public.drone_jobs.vegetation_analysis IS
  'TRUE when Path E vegetation analysis should run for this mission. Set during job intake or template routing.';

COMMENT ON COLUMN public.drone_jobs.vegetation_status IS
  'Path E processing state. Values: pending | detecting | classifying | assessing | generating_report | review | complete | failed';

-- Index for n8n query: find missions ready for Path E
CREATE INDEX IF NOT EXISTS idx_drone_jobs_vegetation_analysis
  ON public.drone_jobs (vegetation_analysis)
  WHERE vegetation_analysis = TRUE;

-- ============================================================
-- 2. processing_templates — vegetation configuration columns
-- ============================================================
-- vegetation_enabled: whether this template activates Path E by default
-- vegetation_config:  JSONB blob holding E1-E3 tunable parameters
ALTER TABLE public.processing_templates
  ADD COLUMN IF NOT EXISTS vegetation_enabled BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS vegetation_config  JSONB   DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.processing_templates.vegetation_enabled IS
  'When TRUE, n8n activates Path E for missions using this template.';

COMMENT ON COLUMN public.processing_templates.vegetation_config IS
  'Path E parameters. Keys: tile_size, score_threshold, iou_threshold, max_canopies, skip_plantnet, vision_sample_pct, skip_vision.';

-- ============================================================
-- 3. processing_steps — Path E step name support
-- ============================================================
-- The processing_steps.step_name column is plain TEXT with no ENUM type
-- and no CHECK constraint on values (confirmed in migration
-- 20260211120000_sentinel_pipeline_schema.sql). The 4 new Path E step
-- names are therefore valid inserts without any DDL change.
--
-- New step names (used by E1-E4 scripts when writing processing_steps rows):
--   veg_canopy_detection       (E1 — DeepForest canopy polygon detection)
--   veg_species_classification (E2 — OpenAI Vision + PlantNet classification)
--   veg_health_assessment      (E3 — VARI/ExG health scoring)
--   veg_report_generation      (E4 — PDF, map, and GeoJSON report output)
--
-- No DDL required. This comment block serves as authoritative documentation.

-- ============================================================
-- 4. Seed default vegetation_config
-- ============================================================
-- NOTE: processing_templates uses preset_name (not path_code) as identifier.
-- Seeding deferred to application layer — operators enable vegetation_enabled
-- per-template via the admin UI or a future migration once template naming
-- conventions are finalized for Path E workflows.
