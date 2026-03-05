# Milestones
## v3.0 Package Router & End-to-End Automation (Shipped: 2026-03-05)

**Phases completed:** 6 phases, 12 plans
**Test suite:** 494 tests (+92 v3.0 tests: workflow validation, integration, mipmap, ortho)
**Timeline:** 2026-03-05 (46 commits, 69 files, 11,185 LOC added)
**Requirements:** 34/34 complete

**Key accomplishments:**
1. Central Package Router n8n workflow: webhook entry point normalizes both folder_watcher and ingest_sorter payloads, deduplicates, creates processing_jobs row, and dispatches to 5 path sub-workflows via Switch node
2. Path A (real estate photos): automated color grade + delivery packaging with PipelineStatusReporter tracking each step in Supabase
3. Path C (MipMap mapping): fire-and-forget MipMap launch with PID-based orphan detection, polling-based ortho harvest with rasterio integrity verification, and automatic Path E vegetation trigger
4. Path V (video pipeline): 30-node sub-workflow executing V1-V4 automatically, V5 Wait node for DaVinci Resolve manual gate, V6 + delivery on resume — all 6 V scripts report status to Supabase
5. Path B/D (construction/ADIAT): shared manual sub-workflow sets status to "manual" and sends operator email notification via SMTP
6. Foundation: mipmap_launcher.py, ortho_harvester.py, payload_normalizer.py, pipeline_status.py PipelineStatusReporter with --step-name override, Supabase processing_jobs/processing_templates schema

**Archives:**
- `milestones/v3.0-ROADMAP.md`
- `milestones/v3.0-REQUIREMENTS.md`

---


## v1.0 Hardening & Testing (Shipped: 2026-02-24)

**Phases completed:** 6 phases, 17 plans
**Test suite:** 282 tests, 0 failures (0.92s)
**Timeline:** 2026-02-23 → 2026-02-24 (50 commits, 86 files, 9,011 LOC Python)

**Key accomplishments:**
1. Hardened all 14 scripts with file logging, consistent exit codes, and datetime deprecation fixes
2. Created checkpoint.py utility for atomic JSON-based resume across all pipeline scripts
3. Added graded_path Supabase upsert to video_color_grade.py (GAP-10 closed)
4. Built pytest framework with conftest.py providing mock_supabase_client, mock_drive_client, mock_ffmpeg fixtures
5. 266 unit tests covering all 14 scripts (ingest, platform detect, video pipeline, delivery, Drive upload, archive sync)
6. 16 integration tests verifying end-to-end flows (ingest, video pipeline, delivery packaging, checkpoint resume)

**Archives:**
- `milestones/v1.0-ROADMAP.md`
- `milestones/v1.0-REQUIREMENTS.md`

---

## v2.0 Vegetation Analysis Pipeline (Shipped: 2026-02-25)

**Phases completed:** 7 phases, 14 plans
**Test suite:** 402 tests, 0 failures (+120 Path E tests)
**Timeline:** 2026-02-24 → 2026-02-25 (18 feat commits, 18,489 LOC Python)
**Requirements:** 48/48 complete

**Key accomplishments:**
1. DeepForest GPU-accelerated canopy detection with 1024px tiling, cross-tile NMS, GeoPackage/GeoJSON export, and per-tile checkpoint resume (E1)
2. Dual-API species classification (OpenAI Vision gpt-4o + PlantNet) with genus-level confidence reconciliation, cost gate, and PlantNet quota exhaustion handling (E2)
3. VARI/ExG vegetation health indices with optional Vision API qualitative assessment for bottom-30% canopies (E3)
4. Branded PDF report with species pie chart, health overview, annotated map PNGs, delivery GeoJSON, and Folium interactive HTML map with satellite basemap (E4)
5. 35-node n8n workflow with ortho polling, E1→E4 orchestration, operator review gate (webhook wait), and zero-canopy bypass
6. Delivery packaging with `--include-vegetation` flag gated on vegetation/.status sentinel file — Path E failure never blocks main delivery
7. 120 new tests (50 E1/E2 unit + 63 E3/E4 unit + 7 integration) with full module-level stub injection for GPU/API dependencies

**Known gaps:**
- TST-06 real-ortho acceptance test deferred — no processed orthomosaic available yet from WebODM Path C

**Archives:**
- `milestones/v2.0-ROADMAP.md`
- `milestones/v2.0-REQUIREMENTS.md`

---

