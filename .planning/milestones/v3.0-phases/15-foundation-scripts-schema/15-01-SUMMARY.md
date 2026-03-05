---
phase: 15-foundation-scripts-schema
plan: 01
subsystem: database
tags: [supabase, postgres, migrations, jsonb, rls, processing-jobs]

requires:
  - phase: 07-vegetation-analysis
    provides: set_updated_at() trigger function, RLS pattern, vegetation_tables migration pattern
provides:
  - processing_jobs table for pipeline step tracking
  - mipmap_workspace JSONB column on drone_jobs
  - video_formats and mipmap_config columns on processing_templates
affects: [15-02, 15-03, 16-n8n-workflows, pipeline_status.py, mipmap_launcher.py]

tech-stack:
  added: []
  patterns: [processing_jobs step-tracking via JSONB array, one-job-per-mission uniqueness]

key-files:
  created:
    - db_migrations/migrations/20260305000001_processing_jobs.sql
    - db_migrations/migrations/20260305000002_mipmap_workspace_and_templates.sql
  modified: []

key-decisions:
  - "UNIQUE(mission_id) on processing_jobs enforces one active job per mission"
  - "Reused existing set_updated_at() function instead of recreating it"
  - "Steps stored as JSONB array for flexible in-place updates by PipelineStatusReporter"

patterns-established:
  - "Processing job tracking: steps JSONB array with {name, status, started_at, completed_at, error, output} objects"
  - "ALTER TABLE ADD COLUMN IF NOT EXISTS for extending existing tables with new path configs"

requirements-completed: [SCH-01, SCH-02, SCH-03]

duration: 1min
completed: 2026-03-05
---

# Phase 15 Plan 01: Schema Migrations Summary

**processing_jobs table with JSONB step tracking, mipmap_workspace on drone_jobs, and video_formats/mipmap_config on processing_templates**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-05T15:25:10Z
- **Completed:** 2026-03-05T15:26:16Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- processing_jobs table with all columns matching PipelineStatusReporter query patterns
- RLS policies (service_role full access, authenticated read-only) and indexes on mission_id/status
- mipmap_workspace JSONB column on drone_jobs for MipMap launcher metadata
- video_formats and mipmap_config JSONB columns on processing_templates for Path V and Path C config

## Task Commits

Each task was committed atomically:

1. **Task 1: Create processing_jobs table migration** - `8e4dff9` (feat)
2. **Task 2: Create mipmap_workspace and templates config migration** - `c751b3f` (feat)

## Files Created/Modified
- `db_migrations/migrations/20260305000001_processing_jobs.sql` - processing_jobs table with RLS, indexes, updated_at trigger
- `db_migrations/migrations/20260305000002_mipmap_workspace_and_templates.sql` - mipmap_workspace, video_formats, mipmap_config columns

## Decisions Made
- UNIQUE(mission_id) constraint on processing_jobs enforces one active processing job per mission
- Reused existing set_updated_at() trigger function from vegetation_tables migration
- Steps column uses JSONB array for flexible in-place patching by PipelineStatusReporter

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required. Migrations are ready to apply via Supabase dashboard or CLI.

## Next Phase Readiness
- Schema is ready for pipeline_status.py (15-02) and mipmap_launcher.py (15-03) implementation
- processing_jobs table matches all PipelineStatusReporter query patterns
- processing_templates columns ready for n8n workflow configuration

## Self-Check: PASSED

All files verified present. All commits verified in git log.

---
*Phase: 15-foundation-scripts-schema*
*Completed: 2026-03-05*
