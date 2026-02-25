# Roadmap: Sentinel Drone Pipeline

## Milestones

- [x] **v1.0 Hardening and Testing** - Phases 1-6 (shipped 2026-02-24)
- [ ] **v2.0 Vegetation Analysis Pipeline** - Phases 7-13 (in progress)

## Phases

<details>
<summary>v1.0 Hardening and Testing (Phases 1-6) - SHIPPED 2026-02-24</summary>

### Phase 1: Code Hardening
**Goal**: All 14 production scripts meet the reliability contract (logging, exit codes, checkpoint resume, datetime fixes)
**Plans**: 4 plans

Plans:
- [x] 01-01: Logging + exit codes for ingest layer
- [x] 01-02: Logging + exit codes for video pipeline
- [x] 01-03: Logging + exit codes for delivery layer
- [x] 01-04: checkpoint.py utility + GAP-10 graded_path + GAP-11 resume

### Phase 2: Test Infrastructure
**Goal**: pytest framework with fixtures and stubs that can mock Supabase, Drive, and FFmpeg
**Plans**: 2 plans

Plans:
- [x] 02-01: conftest.py, fixtures, sys.modules stubs
- [x] 02-02: Test runner config, coverage setup

### Phase 3: Ingest Layer Tests
**Goal**: Unit tests for ingest_sorter, folder_watcher, platform_detect, folder_watcher_service
**Plans**: 3 plans

Plans:
- [x] 03-01: ingest_sorter tests
- [x] 03-02: folder_watcher tests
- [x] 03-03: platform_detect + folder_watcher_service tests

### Phase 4: Video Pipeline Tests
**Goal**: Unit tests for all 7 video pipeline scripts
**Plans**: 3 plans

Plans:
- [x] 04-01: video_color_grade + video_metadata tests
- [x] 04-02: srt_telemetry_parser + video_qa tests
- [x] 04-03: video_proxy_gen + video_format_export tests

### Phase 5: Delivery Layer Tests
**Goal**: Unit tests for delivery_packaging and gdrive_upload
**Plans**: 2 plans

Plans:
- [x] 05-01: delivery_packaging tests
- [x] 05-02: gdrive_upload + archive_sync tests

### Phase 6: Integration Tests
**Goal**: End-to-end integration tests verifying full pipeline flows
**Plans**: 3 plans

Plans:
- [x] 06-01: Ingest flow integration
- [x] 06-02: Video pipeline integration
- [x] 06-03: Delivery + checkpoint resume integration

</details>

---

### v2.0 Vegetation Analysis Pipeline (In Progress)

**Milestone Goal:** Add Path E — automated vegetation identification, species classification, and health assessment as a new service offering that extracts additional revenue from existing orthomosaic imagery.

## Phase Details

### Phase 7: Environment and Foundation
**Goal**: Operators can run a GPU verification script that confirms the dedicated Path E environment is ready for production workloads
**Depends on**: Phase 6 (v1.0 complete)
**Requirements**: ENV-01, ENV-02, ENV-03, ENV-04, ENV-05
**Success Criteria** (what must be TRUE):
  1. Running `python test_environment.py` in `.venv-path-e` prints "CUDA sm_120 verified" with the RTX 5070 device name and exits 0
  2. The Supabase `vegetation_detections` and `vegetation_analysis_summary` tables exist with RLS policies applied and reject unauthenticated writes
  3. The `missions` table has `vegetation_analysis` (bool) and `vegetation_status` (text) columns
  4. The `processing_templates` table has `vegetation_enabled` (bool) and `vegetation_config` (JSONB) columns
  5. The `processing_steps` enum accepts all four new step names without error on insert
**Plans**: TBD

### Phase 8: Canopy Detection (E1)
**Goal**: Operators can run canopy_detection.py on a real orthomosaic and receive a GeoPackage with individual tree polygons and a Supabase row per detection
**Depends on**: Phase 7
**Requirements**: DET-01, DET-02, DET-03, DET-04, DET-05, DET-06, DET-07
**Success Criteria** (what must be TRUE):
  1. Running `canopy_detection.py` on a 500MB test orthomosaic completes in under 5 minutes with CUDA and produces a GeoPackage with at least one polygon
  2. Canopy count from the GeoPackage is within 30% of manual visual inspection count (no gross duplicate inflation from tile overlap)
  3. Each detection row in `vegetation_detections` has area_sqm, width_m, height_m, centroid lat/lon, and confidence populated
  4. Killing the script mid-run and restarting picks up from the last completed tile without re-processing earlier tiles
  5. Running on a 1GB orthomosaic stays under 2GB peak RSS and does not raise an OOM error
**Plans**: TBD

### Phase 9: Species Classification (E2)
**Goal**: Operators can run species_classification.py and receive a species tag with confidence score for each detected canopy, with API cost capped before any call is made
**Depends on**: Phase 8
**Requirements**: SPE-01, SPE-02, SPE-03, SPE-04, SPE-05, SPE-06, SPE-07, SPE-08
**Success Criteria** (what must be TRUE):
  1. The script logs an estimated API cost and aborts if estimated spend exceeds the configured threshold before making any call
  2. Each canopy detection receives a species_tag, confidence, vegetation_type, and classification source written to `vegetation_detections`
  3. Killing the script mid-run and restarting does not re-call the API for canopies already classified (checkpoint + species_tag IS NULL double protection)
  4. Running with `--skip-plantnet` completes without PlantNet calls; running without that flag triggers cross-validation and confidence adjustment per reconciliation rules
  5. A 200-canopy site run stays within 0.5 seconds between calls and logs a warning when PlantNet remaining requests drop below 10
**Plans**: TBD

### Phase 10: Health Assessment (E3)
**Goal**: Operators can run health_assessment.py and receive a health status category for every detected canopy based on VARI/ExG index computation
**Depends on**: Phase 8
**Requirements**: HLT-01, HLT-02, HLT-03, HLT-04, HLT-05, HLT-06
**Success Criteria** (what must be TRUE):
  1. VARI and ExG values computed for a test canopy match hand-calculated values from known pixel data within 1% tolerance
  2. Every detection in `vegetation_detections` receives a health_status value from the five defined categories (healthy, moderate_stress, stressed, severe_decline, dead)
  3. Running with `--skip-vision` produces health scores using index-only weighting with no OpenAI calls made
  4. Killing the script mid-run and restarting does not re-call the Vision API for already-assessed canopies
**Plans**: TBD

### Phase 11: Report Generation (E4)
**Goal**: Operators can run vegetation_report.py and receive a branded PDF report, annotated map PNGs, delivery GeoJSON, and optional interactive HTML map that together constitute the client vegetation deliverable
**Depends on**: Phase 9, Phase 10
**Requirements**: RPT-01, RPT-02, RPT-03, RPT-04, RPT-05, RPT-06, RPT-07, RPT-08, RPT-09
**Success Criteria** (what must be TRUE):
  1. The generated PDF opens without error, shows Sentinel branding with forest green headers, FAA Part 107 statement, veteran-owned designation, and the methodology disclaimer on every report
  2. The PDF contains a species distribution table, health overview, and at least one annotated orthomosaic map with color-coded canopy polygons
  3. The generated Folium HTML map opens in Chrome, shows clickable canopy popups with species and health data, and the file size is under 10MB for a 200-canopy site
  4. A `vegetation_analysis_summary` row is written to Supabase with canopy count, coverage percentage, species distribution JSON, health distribution JSON, API costs, and output file paths
  5. A delivery GeoJSON containing all canopy attributes is written and can be opened in QGIS without CRS errors
**Plans**: TBD

### Phase 12: Integration and Delivery
**Goal**: The full Path E workflow runs end-to-end in n8n, pauses for operator review after E4, and adds a vegetation subfolder to the client delivery ZIP without blocking delivery when Path E is absent or incomplete
**Depends on**: Phase 11
**Requirements**: INT-01, INT-02, INT-03, INT-04, INT-05, INT-06, INT-07
**Success Criteria** (what must be TRUE):
  1. An n8n workflow fires when `mission.vegetation_analysis=true` and a Path C orthomosaic exists, runs E1 through E4 in sequence, and pauses at a webhook wait node with the operator review PDF available
  2. The operator can approve, exclude individual detections, or flag for arborist via the review gate; posting to the resume webhook triggers report regeneration and delivery packaging
  3. Running `delivery_packaging.py --include-vegetation` on a complete mission adds a `vegetation/` subfolder to the client ZIP containing PDF, species map, health map, and GeoJSON
  4. Running `delivery_packaging.py` without `--include-vegetation` (or when `vegetation_status` is not 'complete') produces an identical client ZIP to v1.0 with no vegetation folder and no error
  5. All four E scripts produce JSON stdout, set exit codes 0/1/2, call `setup_logging()`, and update `processing_steps` rows matching v1.0 contract verified by a smoke test
**Plans**: TBD

### Phase 13: Test Suite and Acceptance
**Goal**: The full Path E test suite passes at target coverage and at least one real orthomosaic has been processed through E1-E4 producing a PDF report reviewed by the operator
**Depends on**: Phase 12
**Requirements**: TST-01, TST-02, TST-03, TST-04, TST-05, TST-06
**Success Criteria** (what must be TRUE):
  1. `pytest tests/` passes with all existing 282 tests still green and all new Path E unit tests passing
  2. The E1-E4 integration test runs end-to-end on a sample orthomosaic with mocked APIs and produces a PDF, maps, and GeoJSON without error
  3. The delivery packaging integration test confirms the vegetation subfolder appears when `--include-vegetation` is set and is absent otherwise
  4. A full run on one real mission orthomosaic (unmocked) produces a PDF that the operator has reviewed and approved for correctness
**Plans**: TBD

---

## Progress

**Execution Order:** 7 → 8 → 9 → 10 → 11 → 12 → 13

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Code Hardening | v1.0 | 4/4 | Complete | 2026-02-24 |
| 2. Test Infrastructure | v1.0 | 2/2 | Complete | 2026-02-24 |
| 3. Ingest Layer Tests | v1.0 | 3/3 | Complete | 2026-02-24 |
| 4. Video Pipeline Tests | v1.0 | 3/3 | Complete | 2026-02-24 |
| 5. Delivery Layer Tests | v1.0 | 2/2 | Complete | 2026-02-24 |
| 6. Integration Tests | v1.0 | 3/3 | Complete | 2026-02-24 |
| 7. Environment and Foundation | 2/2 | Complete    | 2026-02-25 | - |
| 8. Canopy Detection | 2/2 | Complete    | 2026-02-25 | - |
| 9. Species Classification | 1/2 | In Progress|  | - |
| 10. Health Assessment | v2.0 | Complete    | 2026-02-25 | 2026-02-25 |
| 11. Report Generation | v2.0 | 0/TBD | Not started | - |
| 12. Integration and Delivery | v2.0 | 0/TBD | Not started | - |
| 13. Test Suite and Acceptance | v2.0 | 0/TBD | Not started | - |
