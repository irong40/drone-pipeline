---
phase: 07-environment-and-foundation
plan: 02
subsystem: database
tags: [supabase, postgresql, rls, migrations, vegetation-analysis]

requires:
  - phase: 07-01
    provides: Python venv with DeepForest + CUDA confirmed working

provides:
  - vegetation_detections table with RLS (service_role write, authenticated read, anon blocked)
  - vegetation_analysis_summary table with RLS (service_role write, authenticated read, anon blocked)
  - drone_jobs.vegetation_analysis (BOOLEAN) and drone_jobs.vegetation_status (TEXT) columns
  - processing_templates.vegetation_enabled (BOOLEAN) and vegetation_config (JSONB) columns
  - Path E template seeded in processing_templates (path_code='E', all 4 step names in default_steps)
  - Default vegetation_config seeded for Path C and B+C templates

affects: [08-canopy-detection, 09-species-classification, 10-health-assessment, 11-report-generation, 12-integration-and-delivery]

tech-stack:
  added: []
  patterns:
    - "Shared set_updated_at() trigger function reused across vegetation tables"
    - "service_role policy grants full access; authenticated policy grants SELECT-only"
    - "step_name is free text (no ENUM/CHECK) — new step names valid without DDL"
    - "processing_templates seeded with INSERT...WHERE NOT EXISTS for idempotent deploys"

key-files:
  created:
    - supabase/migrations/20260225000001_vegetation_tables.sql
    - supabase/migrations/20260225000002_vegetation_columns.sql
  modified: []

key-decisions:
  - "Used drone_jobs (not missions) as FK target — missions is a conceptual alias in the codebase, drone_jobs is the actual table"
  - "processing_steps.step_name is free TEXT with no ENUM or CHECK constraint — confirmed in 20260211120000 migration; no DDL needed for 4 new step names"
  - "UPDATE for site_survey/environmental_survey templates adapted to path_code IN ('C', 'B+C') since package_type column does not exist in processing_templates; Path E template also seeded"
  - "RLS uses TO service_role / TO authenticated role targeting (not has_role() function) to match n8n/Python script usage pattern with service key"
  - "set_updated_at() function created as shared function (CREATE OR REPLACE) rather than per-table functions"

patterns-established:
  - "All vegetation tables reference public.drone_jobs(id) ON DELETE CASCADE"
  - "RLS: service_role FOR ALL, authenticated FOR SELECT TO authenticated"
  - "JSONB columns for extensible config/details (vegetation_config, classification_details, health_details)"

requirements-completed: [ENV-02, ENV-03, ENV-04, ENV-05]

duration: 2min
completed: 2026-02-25
---

# Phase 7 Plan 02: Vegetation Schema Migration Summary

**Two Supabase migrations creating vegetation_detections and vegetation_analysis_summary tables, adding vegetation columns to drone_jobs and processing_templates, and seeding Path E processing template with all 4 E-script step names**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-25T14:00:18Z
- **Completed:** 2026-02-25T14:02:04Z
- **Tasks:** 2
- **Files modified:** 2 (both new migration files)

## Accomplishments

- Created `vegetation_detections` table (24 columns covering geometry, species, health, review) with 4 indexes and RLS blocking anon writes
- Created `vegetation_analysis_summary` table (19 columns covering site stats, species/health distribution, output paths) with UNIQUE constraint per mission and RLS
- Added `vegetation_analysis` and `vegetation_status` columns to `drone_jobs` for n8n Path E routing
- Added `vegetation_enabled` and `vegetation_config` columns to `processing_templates`
- Seeded Path E template (path_code='E') with all 4 veg step names in default_steps
- Confirmed processing_steps.step_name is free TEXT — no DDL needed for new step names

## Task Commits

Each task was committed atomically:

1. **Task 1: Create vegetation tables migration** - `0568a72` (feat)
2. **Task 2: Add vegetation columns and extend processing_steps** - `7d96bdc` (feat)

**Plan metadata:** (docs commit — pending)

## Files Created/Modified

- `supabase/migrations/20260225000001_vegetation_tables.sql` - Creates vegetation_detections and vegetation_analysis_summary tables with RLS policies and updated_at triggers
- `supabase/migrations/20260225000002_vegetation_columns.sql` - Adds vegetation columns to drone_jobs and processing_templates; seeds Path C, B+C, and new Path E templates

## Decisions Made

1. **drone_jobs not missions** — The plan used `missions` as the FK target, but the actual table is `public.drone_jobs`. All FKs corrected to `REFERENCES public.drone_jobs(id)`.

2. **processing_steps.step_name is free TEXT** — Confirmed by reviewing `20260211120000_sentinel_pipeline_schema.sql`. The column is defined as `TEXT NOT NULL` with no ENUM type and no CHECK constraint on values. The 4 new Path E step names (`veg_canopy_detection`, `veg_species_classification`, `veg_health_assessment`, `veg_report_generation`) are valid inserts without any DDL change. Documented with a comment block in the migration.

3. **UPDATE target adapted from package_type to path_code** — The plan's `UPDATE processing_templates WHERE package_type IN ('site_survey', 'environmental_survey')` does not match the schema: `processing_templates` has no `package_type` column (confirmed in all migrations). Updated to `WHERE path_code IN ('C', 'B+C')` (the paths that produce orthomosaics). Also added Path E template seed via INSERT...WHERE NOT EXISTS.

4. **RLS uses role targeting (TO service_role)** — Used `TO service_role` / `TO authenticated` role targeting instead of `has_role(auth.uid(), 'admin'::app_role)` pattern, because Python E scripts use the service key directly (not admin role) and need programmatic write access without admin privileges.

5. **Shared set_updated_at() trigger function** — Created as `CREATE OR REPLACE FUNCTION public.set_updated_at()` shared across both tables rather than per-table functions. Follows PostgreSQL best practice for reusable trigger functions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected FK target from `missions` to `drone_jobs`**
- **Found during:** Task 1 (Create vegetation tables migration)
- **Issue:** Plan specified `REFERENCES missions(id)` but the actual Supabase table is `public.drone_jobs`. No `missions` table exists.
- **Fix:** Changed all FK references to `REFERENCES public.drone_jobs(id) ON DELETE CASCADE`
- **Files modified:** supabase/migrations/20260225000001_vegetation_tables.sql
- **Verification:** Reviewed 20260211120000_sentinel_pipeline_schema.sql and 20260224140000_processing_jobs.sql — both use `drone_jobs`
- **Committed in:** 0568a72 (Task 1 commit)

**2. [Rule 1 - Bug] Fixed UPDATE target from non-existent package_type to path_code**
- **Found during:** Task 2 (Add vegetation columns)
- **Issue:** Plan's `UPDATE processing_templates WHERE package_type IN ('site_survey', 'environmental_survey')` would fail silently (0 rows updated) or error — no `package_type` column exists; `site_survey`/`environmental_survey` are not seeded path codes
- **Fix:** Changed UPDATE to `WHERE path_code IN ('C', 'B+C')` and added Path E template seed with all correct column names
- **Files modified:** supabase/migrations/20260225000002_vegetation_columns.sql
- **Verification:** Reviewed processing_templates schema across all migrations; confirmed `path_code` is the routing key
- **Committed in:** 7d96bdc (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - Bug corrections)
**Impact on plan:** Both fixes required for migrations to apply correctly. No scope creep — all plan requirements still met (ENV-02 through ENV-05).

## Issues Encountered

- `supabase/migrations/` directory did not exist in the drone-pipeline project. Created it as part of Task 1 (migration files define the structure; no Supabase CLI config files needed for this plan).

## User Setup Required

Apply migrations to the Supabase project after this plan completes:

```bash
cd C:/Users/redle/drone-pipeline
supabase link --project-ref qjpujskwqaehxnqypxzu
supabase db push
```

Verify after push:
- `SELECT * FROM vegetation_detections LIMIT 1;` — table exists
- `SELECT vegetation_analysis, vegetation_status FROM drone_jobs LIMIT 1;` — columns exist
- `SELECT vegetation_enabled, vegetation_config FROM processing_templates WHERE path_code = 'E';` — Path E row seeded
- `INSERT INTO processing_steps (mission_id, step_name, step_order, status) VALUES ('<uuid>', 'veg_canopy_detection', 100, 'waiting');` — step name accepted

## Next Phase Readiness

- Schema ready for Phase 8 (Canopy Detection — E1 script) to write rows to `vegetation_detections`
- Path E template seeded; n8n can reference `path_code = 'E'` for routing
- Blocker noted: `supabase db push` must be run before any E script can write to the database

## Self-Check: PASSED

- FOUND: supabase/migrations/20260225000001_vegetation_tables.sql
- FOUND: supabase/migrations/20260225000002_vegetation_columns.sql
- FOUND: .planning/phases/07-environment-and-foundation/07-02-SUMMARY.md
- FOUND commit 0568a72: feat(07-02): create vegetation_detections and vegetation_analysis_summary tables
- FOUND commit 7d96bdc: feat(07-02): add vegetation columns and seed Path E processing template

---
*Phase: 07-environment-and-foundation*
*Completed: 2026-02-25*
