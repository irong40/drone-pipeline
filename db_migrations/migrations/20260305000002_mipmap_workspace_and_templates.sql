-- Migration: mipmap_workspace_and_templates
-- Phase 15 Plan 01 Task 2 — Foundation Scripts & Schema
-- Adds mipmap_workspace JSONB column to drone_jobs and
-- video_formats / mipmap_config columns to processing_templates.
--
-- NOTE: The Sentinel pipeline refers to jobs as "missions". The underlying
-- table is public.drone_jobs.
--
-- NOTE: processing_templates already has vegetation_enabled and vegetation_config
-- columns from 20260225000002_vegetation_columns.sql — do NOT re-add them.

-- ============================================================
-- 1. drone_jobs — mipmap_workspace column
-- ============================================================
-- mipmap_workspace: stores MipMap workspace metadata per mission,
-- set by mipmap_launcher.py after launching a reconstruction task.
ALTER TABLE public.drone_jobs
  ADD COLUMN IF NOT EXISTS mipmap_workspace JSONB DEFAULT NULL;

COMMENT ON COLUMN public.drone_jobs.mipmap_workspace IS
  'MipMap workspace metadata. Keys: workspace_path, project_file, task_id, started_at, completed_at. Set by mipmap_launcher.py.';

-- ============================================================
-- 2. processing_templates — path-specific config columns
-- ============================================================
-- video_formats: Path V video export parameters
-- mipmap_config: Path C MipMap reconstruction parameters
ALTER TABLE public.processing_templates
  ADD COLUMN IF NOT EXISTS video_formats JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS mipmap_config JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.processing_templates.video_formats IS
  'Path V parameters. Keys: export_formats, proxy_resolution, codec_preferences.';

COMMENT ON COLUMN public.processing_templates.mipmap_config IS
  'Path C parameters. Keys: reconstruction_quality, output_format, workspace_template.';
