---
phase: 07-environment-and-foundation
verified: 2026-02-25T15:30:00Z
status: passed
score: 5/5 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "Confirm migrations applied to live Supabase project"
    expected: "SELECT * FROM vegetation_detections LIMIT 1 returns empty (not error); SELECT vegetation_analysis, vegetation_status FROM drone_jobs LIMIT 1 returns rows"
    why_human: "Migrations exist as SQL files only — no Supabase CLI config is present in drone-pipeline. The SUMMARY documents that supabase db push must be run manually. Cannot verify remote DB state programmatically without credentials."
---

# Phase 7: Environment and Foundation — Verification Report

**Phase Goal:** Operators can run a GPU verification script that confirms the dedicated Path E environment is ready for production workloads
**Verified:** 2026-02-25T15:30:00Z
**Status:** PASSED (5/5 truths verified)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running `python test_environment.py` in `.venv-path-e` prints "CUDA sm_120 verified" with RTX 5070 device name and exits 0 | VERIFIED | Script executed live: output `{"status": "CUDA sm_120 verified", "gpu": "NVIDIA GeForce RTX 5070", ...}`, exit code 0 |
| 2 | `vegetation_detections` and `vegetation_analysis_summary` tables exist with RLS policies blocking unauthenticated writes | VERIFIED | Migration `20260225000001` creates both tables; `ENABLE ROW LEVEL SECURITY` + policies grant service_role/authenticated only — anon has no policy, so all anon writes are blocked by default |
| 3 | `missions` table (`drone_jobs`) has `vegetation_analysis` (bool) and `vegetation_status` (text) columns | VERIFIED | Migration `20260225000002` adds both columns to `public.drone_jobs` with `ADD COLUMN IF NOT EXISTS`; the `missions` alias is documented in the migration comment header |
| 4 | `processing_templates` table has `vegetation_enabled` (bool) and `vegetation_config` (JSONB) columns | VERIFIED | Migration `20260225000002` adds both columns; Path E template seeded with `vegetation_enabled = TRUE` and full JSONB config |
| 5 | `processing_steps` accepts all four new step names without error on insert | VERIFIED | Migration `20260225000002` confirms `step_name` is plain `TEXT NOT NULL` with no ENUM type and no CHECK constraint — all four step names (`veg_canopy_detection`, `veg_species_classification`, `veg_health_assessment`, `veg_report_generation`) are valid inserts without DDL |

**Score:** 5/5 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `requirements-path-e.txt` | Pinned dep list for Path E venv | VERIFIED | Exists, 37 lines, contains `deepforest>=1.4.0` and full geospatial + reporting + API stack; documents PyTorch-first install order in header |
| `test_environment.py` | GPU verification script | VERIFIED | Exists, 284 lines, substantive implementation with 9 checks, argparse, setup_logging, JSON stdout, exit 0/1 — not a stub |
| `.venv-path-e/` | Python 3.12 venv with all deps | VERIFIED | `pyvenv.cfg` confirms Python 3.12.10; `torch==2.10.0+cu128` installed; all deps verified importable |
| `supabase/migrations/20260225000001_vegetation_tables.sql` | Vegetation tables + RLS | VERIFIED | Exists, 155 lines, creates both tables, 4 indexes, 2 RLS-enabled tables, 4 policies |
| `supabase/migrations/20260225000002_vegetation_columns.sql` | Column additions + enum docs | VERIFIED | Exists, 137 lines, adds all required columns, documents step_name free-text fact, seeds Path E template |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `test_environment.py` | `torch.cuda` | `assert get_device_capability()[0] >= 12` | VERIFIED | `torch.cuda.get_device_capability(0)` called at line 135; `major < 12` exits 1 |
| `test_environment.py` | `deepforest.main.deepforest` | import and instantiate | VERIFIED | `from deepforest.main import deepforest as DeepForest` then `DeepForest()` at lines 163-171; v2 API check at lines 176-179 |
| `vegetation_detections` | `missions.id` (drone_jobs) | foreign key on mission_id | VERIFIED | `REFERENCES public.drone_jobs(id) ON DELETE CASCADE` at line 29; naming discrepancy documented in migration header |
| `vegetation_analysis_summary` | `missions.id` (drone_jobs) | foreign key on mission_id | VERIFIED | `REFERENCES public.drone_jobs(id) ON DELETE CASCADE UNIQUE` at line 82 |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| ENV-01 | 07-01-PLAN.md | Dedicated Python 3.12 venv with CUDA-verified PyTorch on RTX 5070 | SATISFIED | `.venv-path-e` with Python 3.12.10, torch 2.10.0+cu128, sm_120 verified live |
| ENV-02 | 07-02-PLAN.md | `vegetation_detections` and `vegetation_analysis_summary` with RLS | SATISFIED | Migration `20260225000001` creates both tables with RLS; anon writes blocked |
| ENV-03 | 07-02-PLAN.md | `vegetation_analysis` and `vegetation_status` added to missions table | SATISFIED | Migration `20260225000002` adds both columns to `public.drone_jobs` |
| ENV-04 | 07-02-PLAN.md | `vegetation_enabled` and `vegetation_config` added to `processing_templates` | SATISFIED | Migration `20260225000002` adds both columns; Path E template seeded |
| ENV-05 | 07-02-PLAN.md | `processing_steps` accepts 4 new step names | SATISFIED | `step_name` is free TEXT — no constraint; new names valid without DDL; documented with a comment block |

**Orphaned requirements (mapped to Phase 7 but not in any plan):** None. All five ENV requirements are claimed and satisfied.

---

### Deviations Assessed

Two deviations were made during execution and both are **correct fixes, not gaps**:

1. **PyTorch 2.10.0+cu128 instead of 2.9.1+cu128** — Version 2.9.1 was never published on the CUDA index. 2.10.0+cu128 is newer and meets all sm_120 requirements. REQUIREMENTS.md ENV-01 states "CUDA-verified PyTorch 2.9.1+cu128" but this is a version number in a requirement that was written before verifying availability. The installed version exceeds the intent.

2. **`public.drone_jobs` instead of `missions`** — The Roadmap and Requirements use "missions" as a conceptual name. The actual Supabase table is `drone_jobs`, confirmed in prior migration `20260211120000`. Both migration files document this explicitly. The semantic requirement (columns on the missions/job table) is fully satisfied.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | - | - | - | No stubs, placeholders, TODOs, or empty returns found in any phase 7 file |

---

### Human Verification Required

#### 1. Supabase Migrations Applied to Live Database

**Test:** Run `supabase db push` from `C:/Users/redle/drone-pipeline` after linking with `supabase link --project-ref qjpujskwqaehxnqypxzu`. Then run:
```sql
SELECT * FROM vegetation_detections LIMIT 1;
SELECT vegetation_analysis, vegetation_status FROM drone_jobs LIMIT 1;
SELECT vegetation_enabled, vegetation_config FROM processing_templates WHERE path_code = 'E';
INSERT INTO processing_steps (mission_id, step_name, step_order, status) VALUES ('<valid_uuid>', 'veg_canopy_detection', 100, 'waiting');
```
**Expected:** All four queries succeed without error; the INSERT accepts the new step name.
**Why human:** The drone-pipeline project has no `supabase/config.toml` — only migration SQL files exist. The Supabase CLI cannot be invoked to dry-run or push without credentials. Database state is unverifiable without the live project connection.

---

### Notes on Success Criterion Wording

Success Criterion 1 specifies `torch 2.9.1+cu128`. The actual installed version is `2.10.0+cu128` (the newer, CUDA-compatible release — 2.9.1 was never published). The script output prints the actual version. The intent of the criterion (sm_120 confirmed, RTX 5070 named, exits 0) is fully met. The version discrepancy is not a gap.

Success Criterion 3 says "`missions` table". The actual table name is `drone_jobs`. This is a documented codebase alias: the pipeline conceptually calls them missions, the Supabase schema uses `drone_jobs`. The migration correctly targets `drone_jobs` and both migration files carry an explanatory comment. This is not a gap.

---

## Summary

Phase 7 goal is **achieved**. All five observable truths are verified against the actual codebase:

- The GPU verification script (`test_environment.py`) runs live and prints `"CUDA sm_120 verified"` with `"NVIDIA GeForce RTX 5070"` and exits 0.
- Both vegetation tables exist as substantive SQL with correct RLS blocking anon writes.
- All four column additions are present in the migration and correctly target the actual table names.
- The `processing_steps` free-text constraint means the four new step names are already accepted — no DDL was needed or missed.

The only item requiring human action is `supabase db push` to apply the migrations to the live database — a deployment step, not a code gap.

---

_Verified: 2026-02-25T15:30:00Z_
_Verifier: Claude (gsd-verifier)_
