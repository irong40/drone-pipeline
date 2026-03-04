-- Migration: vegetation_tables
-- Phase 7 Plan 02 Task 1 — Environment and Foundation
-- Creates vegetation_detections and vegetation_analysis_summary tables with RLS policies
--
-- NOTE: The Sentinel pipeline refers to jobs as "missions". The underlying table is
-- public.drone_jobs. All foreign keys reference public.drone_jobs(id).

-- ============================================================
-- updated_at trigger function (shared across vegetation tables)
-- Reuses existing pattern from processing_templates trigger.
-- ============================================================
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ============================================================
-- vegetation_detections
-- One row per detected canopy polygon, populated across E1-E3.
-- E1: geometry + canopy dimensions + confidence
-- E2: species_tag + classification_details
-- E3: health_score + health_status + health_details
-- ============================================================
CREATE TABLE public.vegetation_detections (
  id                     UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  mission_id             UUID          NOT NULL REFERENCES public.drone_jobs(id) ON DELETE CASCADE,
  detection_index        INTEGER       NOT NULL,
  geometry_wkt           TEXT          NOT NULL,
  centroid_lat           DOUBLE PRECISION NOT NULL,
  centroid_lon           DOUBLE PRECISION NOT NULL,
  canopy_area_sqm        DOUBLE PRECISION,
  canopy_width_m         DOUBLE PRECISION,
  canopy_height_m        DOUBLE PRECISION,
  detection_confidence   DOUBLE PRECISION,
  -- Species classification (E2)
  species_tag            TEXT,
  species_confidence     DOUBLE PRECISION,
  vegetation_type        TEXT,
  cross_validated        BOOLEAN       DEFAULT FALSE,
  classification_details JSONB,
  -- Health assessment (E3)
  health_score           DOUBLE PRECISION,
  health_status          TEXT,
  health_details         JSONB,
  -- Operator review
  review_status          TEXT          DEFAULT 'pending',
  review_notes           TEXT,
  -- Timestamps
  created_at             TIMESTAMPTZ   DEFAULT now(),
  updated_at             TIMESTAMPTZ   DEFAULT now(),
  UNIQUE (mission_id, detection_index)
);

-- Indexes for common query patterns
CREATE INDEX idx_vegetation_detections_mission
  ON public.vegetation_detections (mission_id);

CREATE INDEX idx_vegetation_detections_health_status
  ON public.vegetation_detections (health_status);

CREATE INDEX idx_vegetation_detections_species_tag
  ON public.vegetation_detections (species_tag);

CREATE INDEX idx_vegetation_detections_mission_index
  ON public.vegetation_detections (mission_id, detection_index);

-- Auto-update updated_at
CREATE TRIGGER vegetation_detections_updated_at
  BEFORE UPDATE ON public.vegetation_detections
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ============================================================
-- vegetation_analysis_summary
-- One row per mission (written by E4 — report generation).
-- UNIQUE constraint enforces single summary per mission.
-- ============================================================
CREATE TABLE public.vegetation_analysis_summary (
  id                      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  mission_id              UUID          NOT NULL REFERENCES public.drone_jobs(id) ON DELETE CASCADE UNIQUE,
  -- Site geometry
  site_area_sqm           DOUBLE PRECISION,
  site_area_acres         DOUBLE PRECISION,
  -- Canopy aggregate stats
  total_canopy_count      INTEGER,
  canopy_coverage_pct     DOUBLE PRECISION,
  -- Species stats
  unique_species_count    INTEGER,
  species_distribution    JSONB,
  -- Health stats
  avg_health_score        DOUBLE PRECISION,
  health_distribution     JSONB,
  needs_attention_count   INTEGER,
  -- Processing stats
  api_calls_total         INTEGER,
  processing_time_seconds DOUBLE PRECISION,
  -- Output file paths (relative to mission output dir or Drive URL)
  pdf_report_path         TEXT,
  species_map_path        TEXT,
  health_map_path         TEXT,
  geojson_path            TEXT,
  interactive_map_path    TEXT,
  -- Timestamps
  created_at              TIMESTAMPTZ   DEFAULT now(),
  updated_at              TIMESTAMPTZ   DEFAULT now()
);

-- Auto-update updated_at
CREATE TRIGGER vegetation_analysis_summary_updated_at
  BEFORE UPDATE ON public.vegetation_analysis_summary
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ============================================================
-- RLS — vegetation_detections
-- Service role: full access (Python E scripts use service key)
-- Authenticated (admin UI): SELECT only
-- Anon: no access (blocks unauthenticated writes)
-- ============================================================
ALTER TABLE public.vegetation_detections ENABLE ROW LEVEL SECURITY;

-- Service role full access (E1-E3 write via service key)
CREATE POLICY "Service role full access on vegetation_detections"
  ON public.vegetation_detections FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- Authenticated users (admin portal) can read
CREATE POLICY "Authenticated users can read vegetation_detections"
  ON public.vegetation_detections FOR SELECT
  TO authenticated
  USING (true);

-- ============================================================
-- RLS — vegetation_analysis_summary
-- Service role: full access (E4 writes summary via service key)
-- Authenticated (admin UI): SELECT only
-- Anon: no access (blocks unauthenticated writes)
-- ============================================================
ALTER TABLE public.vegetation_analysis_summary ENABLE ROW LEVEL SECURITY;

-- Service role full access (E4 writes via service key)
CREATE POLICY "Service role full access on vegetation_analysis_summary"
  ON public.vegetation_analysis_summary FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- Authenticated users (admin portal) can read
CREATE POLICY "Authenticated users can read vegetation_analysis_summary"
  ON public.vegetation_analysis_summary FOR SELECT
  TO authenticated
  USING (true);
