---
phase: 16-package-router-core-path-a
verified: 2026-03-05T17:00:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 16: Package Router Core + Path A Verification Report

**Phase Goal:** Missions arriving via webhook are automatically routed by package type, and real estate photo missions complete end-to-end without operator intervention
**Verified:** 2026-03-05T17:00:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | POSTing an ingest_sorter payload to /webhook/package-router creates a processing_jobs row with correct steps | VERIFIED | package_router.json: Webhook node (POST, path "package-router") -> Normalize -> Build Steps (STEP_MAP with all 8 types) -> Create Processing Job (POST to /rest/v1/processing_jobs with Prefer: return=representation) |
| 2 | POSTing a folder_watcher payload normalizes to the same internal format before routing | VERIFIED | Normalize Payload Code node contains full package_router_normalizer.js (detects folder_watcher via folder_name field, parses SAI_MXXXX_type_YYYYMMDD regex, sets needs_mission_lookup=true) |
| 3 | Package Router fetches template defaults from processing_templates and merges with mission overrides | VERIFIED | Fetch Template node GETs /rest/v1/processing_templates?package_type=eq.{type}&select=*; Build Steps node reads template config and passes through |
| 4 | Switch node routes re_standard/real_estate to Path A, mapping types to Path C, video to Path V, construction/adiat to manual path | VERIFIED | Route by Package Type switch v3: output 0 (re_standard OR real_estate) -> Execute Path A, output 1 (mapping OR site_survey OR environmental_survey) -> Path C stub, output 2 (video) -> Path V stub, fallback "extra" -> Execute Manual Path |
| 5 | Duplicate missions (already in processing_jobs) are stopped before re-processing | VERIFIED | Check Duplicate Job queries /rest/v1/processing_jobs?mission_id=eq.{id}; IF Duplicate Exists true branch -> empty array (stops), false branch -> continues to Fetch Template |
| 6 | Path A sub-workflow executes color grading script on mission photos | VERIFIED | Execute Color Grade node runs video_color_grade.py with --platform and --processing-job-id; Parse Color Grade Result handles stdout JSON |
| 7 | Path A sub-workflow executes delivery_packaging.py to create client delivery ZIP | VERIFIED | Execute Delivery Packaging node runs delivery_packaging.py with --address, --city, --photos-only, --processing-job-id |
| 8 | Each processing step updates Supabase status to running/complete/failed as it progresses | VERIFIED | delivery_packaging.py lines 337-362: PipelineStatusReporter created with step_name="delivery_packaging", reporter.start() before logic, reporter.complete(output=result_data) on success, reporter.fail(error=str(e)) on exception; video_color_grade.py already had PipelineStatusReporter |
| 9 | delivery_packaging.py accepts --processing-job-id and reports step status via PipelineStatusReporter | VERIFIED | Line 35: imports PipelineStatusReporter, add_pipeline_args; Line 331: add_pipeline_args(parser); Line 337-340: reporter creation; Line 350-352: dry-run guard skips reporter.start(); Lines 354-364: start/complete/fail lifecycle |

**Score:** 9/9 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `n8n/package_router.json` | Main Package Router n8n workflow | VERIFIED | 18 nodes (plan said 16, includes 2 extra merge/lookup nodes for dual-branch design), 428 lines, valid JSON, all validation tests pass |
| `n8n/path_a_workflow.json` | Path A sub-workflow for real estate photo processing | VERIFIED | 7 nodes, workflow ID "sentinel-path-a", executeWorkflowTrigger entry point, valid JSON, all validation tests pass |
| `delivery_packaging.py` | Enhanced delivery packaging with pipeline status reporting | VERIFIED | PipelineStatusReporter import (line 35), add_pipeline_args (line 331), reporter lifecycle (lines 337-364), _run_packaging() extraction for clean try/except |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| package_router.json (Webhook) | Normalize Payload Code node | connection in connections{} | WIRED | "Package Router Webhook" -> "Normalize Payload" in connections |
| package_router.json (Switch) | Execute Sub Workflow nodes | switch output routes | WIRED | Route by Package Type main[0] -> Execute Path A, main[1] -> Path C Stub, main[2] -> Path V Stub, main[3] -> Execute Manual Path |
| package_router.json (HTTP Request) | Supabase processing_jobs | POST to /rest/v1/processing_jobs | WIRED | Create Processing Job node: POST method, body with mission_id/package_type/status/steps/source, Prefer: return=representation |
| path_a_workflow.json (Execute Command) | video_color_grade.py | command with --processing-job-id | WIRED | Command: python SENTINEL_SCRIPTS\video_color_grade.py folder_path --platform --processing-job-id |
| path_a_workflow.json (Execute Command) | delivery_packaging.py | command with --processing-job-id --address --city | WIRED | Command: python SENTINEL_SCRIPTS\delivery_packaging.py folder_path --address --city --photos-only --processing-job-id |
| delivery_packaging.py | Supabase processing_jobs | PipelineStatusReporter start/complete/fail | WIRED | Import confirmed (line 35), reporter created (line 337-340), lifecycle called (lines 354-362) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| RTR-01 | 16-01 | n8n webhook receives POST from ingest_sorter.py with mission_id, package_type, and inventory payload | SATISFIED | Webhook node POST at /package-router; normalizer detects ingest_sorter fields (mission_id && !folder_name) |
| RTR-02 | 16-01 | n8n Switch node routes missions to Path A/B/C/D/V sub-workflows based on package_type | SATISFIED | Switch v3 with 3 rules + fallback covering all 8 package types to 4 outputs |
| RTR-03 | 16-01 | Package Router fetches processing_templates config from Supabase and merges with mission-specific overrides | SATISFIED | Fetch Template HTTP Request node; Build Steps Code node reads template config |
| RTR-04 | 16-01 | Package Router creates a processing_jobs row in Supabase with all active steps before dispatching | SATISFIED | Build Steps generates STEP_MAP, Create Processing Job POSTs to Supabase, Prepare Dispatch extracts job ID before routing |
| RTR-05 | 16-01 | Package Router normalizes both folder_watcher and ingest_sorter payloads into a common format | SATISFIED | Normalize Payload Code node with full package_router_normalizer.js embedded |
| PHA-01 | 16-02 | n8n Path A sub-workflow executes photo color grading script on mission photos | SATISFIED | Execute Color Grade node calls video_color_grade.py with --processing-job-id |
| PHA-02 | 16-02 | n8n Path A sub-workflow executes delivery_packaging.py to create client delivery ZIP | SATISFIED | Execute Delivery Packaging node calls delivery_packaging.py with --photos-only --address --city --processing-job-id |
| PHA-03 | 16-02 | Path A sub-workflow updates Supabase processing_steps status at each stage | SATISFIED | Both scripts use PipelineStatusReporter (self-report); no double-update from n8n |

No orphaned requirements found -- all 8 requirement IDs from REQUIREMENTS.md Phase 16 mapping are covered by plans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | - | - | - | No TODO/FIXME/placeholder/stub patterns found in modified files |

Path C and Path V stub nodes (noOp) are intentional design -- documented as Phase 17/18 replacement targets, not forgotten placeholders.

### Human Verification Required

### 1. End-to-End Webhook Test

**Test:** Import package_router.json and path_a_workflow.json into n8n. POST an ingest_sorter payload to http://localhost:5678/webhook/package-router with a real_estate package_type.
**Expected:** Processing job created in Supabase, Path A sub-workflow triggers, color grade runs (skips gracefully for photos), delivery ZIP created.
**Why human:** Requires running n8n instance, Supabase connection, and actual mission folder on disk.

### 2. Folder Watcher Payload Normalization

**Test:** POST a folder_watcher payload (with folder_name like SAI_M1234_real_estate_20260305) to the webhook.
**Expected:** Mission ID looked up from drone_jobs, payload normalized, same routing as ingest_sorter.
**Why human:** Requires live Supabase with drone_jobs data and n8n running.

### 3. Duplicate Mission Rejection

**Test:** POST the same mission_id payload twice to the webhook.
**Expected:** First creates processing_job, second is stopped by deduplication check (IF Duplicate Exists true branch).
**Why human:** Requires live Supabase to verify the dedup query returns existing row.

### 4. Delivery Packaging Backward Compatibility

**Test:** Run delivery_packaging.py without --processing-job-id on a test mission folder.
**Expected:** ZIP created successfully with no Supabase errors (PipelineStatusReporter is no-op when processing_job_id is None).
**Why human:** Requires test mission folder with photo files.

### Gaps Summary

No gaps found. All 9 observable truths verified, all 3 artifacts substantive and wired, all 6 key links confirmed, all 8 requirements satisfied. Automated validation tests pass (16 passed, 2 skipped for config files).

The phase goal is achieved at the workflow definition level. The workflows are n8n JSON files that must be imported into n8n to execute -- the human verification items above confirm live execution behavior that cannot be verified statically.

---

_Verified: 2026-03-05T17:00:00Z_
_Verifier: Claude (gsd-verifier)_
